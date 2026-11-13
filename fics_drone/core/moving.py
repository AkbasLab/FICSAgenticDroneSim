"""Vehicles and pedestrians: things the simulator moves that an aircraft must keep clear of.

Trees and zones stand still, so a scenario file can list them. A car or a person is somewhere else a second later, so
they come from a feed that is read when needed: `ScriptedMovers` (straight-line walkers on a clock, for the mock and the
tests) or `CarlaMovers` (every vehicle and pedestrian actor in the running simulator).

Each object is a circle that covers its body, with the speed it is moving at. `columns` turns a list of them into the same
full-height keep-out columns the guardian and the leg planner already use for trees and teammates, padded, and swept
along where the object will be over the next few seconds, so a leg across a road is refused while a car is about to
cross it.
"""

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from .obstacles import TreeObstacle

COLUMN_HALF_HEIGHT_M = 1000.0      # the column's bottom: nothing is ever flown below a person or a car
MAX_SWEEP_COLUMNS = 12
STILL_MPS = 0.3          # slower than this counts as standing still: one column, no sweep


@dataclass(frozen=True)
class MovingObject:
    name: str
    kind: str               # "vehicle" or "pedestrian"
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius: float = 0.5     # a circle that covers the whole body, metres
    height: float = 2.0     # how tall it stands above the ground, metres
    # A car is long and thin, not round: with its half width and half length and the direction it points (radians), it is a
    # capsule (a line along its length, thickened by half the width) and `radius` stays the circle that covers all of it.
    half_width: Optional[float] = None
    half_length: Optional[float] = None
    yaw: float = 0.0

    def reach(self, px: float, py: float) -> float:
        """How far the body reaches from its centre toward the point (px, py): the circle's radius, or for a car the half width
        when the point is beside it and up to the half length when it is ahead or behind."""
        if self.half_width is None or self.half_length is None:
            return self.radius
        dx, dy = px - self.x, py - self.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return self.radius
        along = abs(dx * math.cos(self.yaw) + dy * math.sin(self.yaw)) / d
        return self.half_width + max(0.0, self.half_length - self.half_width) * along

    def at(self, dt_s: float) -> "MovingObject":
        """Where it is dt seconds on, going straight at its present velocity."""
        return MovingObject(self.name, self.kind, self.x + self.vx * dt_s, self.y + self.vy * dt_s, self.vx, self.vy, self.radius, self.height,
                            self.half_width, self.half_length, self.yaw)

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


def columns(objects: Sequence[MovingObject], pad_m: float, lookahead_s: float, vertical_pad_m: float = 4.0) -> List[TreeObstacle]:
    """Keep-out columns for these objects: their body radius plus pad_m, at the place they are and, if they are moving, at
    enough points along the next lookahead_s seconds that no gap is wider than the column. Each column reaches up to the
    object's height plus vertical_pad_m, so an aircraft cruising well above a person or a car is not steered round it, and one
    that is low (taking off, landing, at the altitude floor) is."""
    out = []
    for obj in objects:
        capsule = obj.half_width is not None and obj.half_length is not None and obj.half_length - obj.half_width > 0.25
        r = (obj.half_width if capsule else obj.radius) + pad_m
        offsets = (-(obj.half_length - obj.half_width), 0.0, obj.half_length - obj.half_width) if capsule else (0.0,)
        steps = 0
        if obj.speed > STILL_MPS and lookahead_s > 0.0:
            steps = min(MAX_SWEEP_COLUMNS, max(1, math.ceil(obj.speed * lookahead_s / max(r, 0.5))))
        for i in range(steps + 1):
            p = obj.at(lookahead_s * i / steps) if steps else obj
            for off in offsets:      # a car: three columns along its length, so its ends are covered and its sides are not padded by its length
                out.append(TreeObstacle(x=p.x + off * math.cos(obj.yaw), y=p.y + off * math.sin(obj.yaw), z_bottom=-COLUMN_HALF_HEIGHT_M,
                                        z_top=obj.height + vertical_pad_m, trunk_r=r, crown_r=r, crown_from_frac=1.0))
    return out


def low_enough(objects: Sequence[MovingObject], z: float, vertical_pad_m: float = 4.0) -> List[MovingObject]:
    """The objects an aircraft at height z has to keep clear of: those whose top plus vertical_pad_m is above it."""
    return [o for o in objects if z < o.height + vertical_pad_m]


class ScriptedMovers:
    """Objects that move in straight lines on a clock: the mock world's pedestrians and cars, and the tests'."""

    def __init__(self, objects: Sequence[MovingObject], clock: Callable[[], float] = time.monotonic):
        self._objects, self._clock = list(objects), clock
        self._t0 = clock()

    def snapshot(self, now: Optional[float] = None) -> List[MovingObject]:
        dt = (self._clock() if now is None else now) - self._t0
        return [o.at(dt) for o in self._objects]


class CarlaMovers:
    """Every vehicle and pedestrian in the running CARLA world, in mission world metres (the drone's frame: CARLA x, y minus
    `origin`), read at most every `refresh_s`. The aircraft themselves are not listed, so a drone never keeps clear of
    its own body. Read-only: it never touches an actor."""

    def __init__(self, world, origin=(-172.2, 183.86), refresh_s: float = 0.2):
        self._world, self._origin, self._refresh_s = world, origin, refresh_s
        self._lock = threading.Lock()
        self._last = -1e9
        self._cache: List[MovingObject] = []
        self._sizes = {}      # actor id -> (half length, half width, half height): a body's size never changes, and reading it is a round trip
        #                       to the simulator (about 18 ms an actor), so it is read once; the rest of an actor's state is read locally

    def snapshot(self) -> List[MovingObject]:
        with self._lock:
            now = time.monotonic()
            if now - self._last < self._refresh_s:
                return list(self._cache)
            self._last = now
            found = []
            try:
                for actor in self._world.get_actors():
                    kind = "vehicle" if actor.type_id.startswith("vehicle.") else "pedestrian" if actor.type_id.startswith("walker.") else None
                    if kind is None:
                        continue
                    loc, vel = actor.get_location(), actor.get_velocity()
                    key = getattr(actor, "id", id(actor))
                    size = self._sizes.get(key)
                    if size is None:
                        ext = actor.bounding_box.extent
                        size = self._sizes[key] = (ext.x, ext.y, ext.z)
                    ext = type("Extent", (), {"x": size[0], "y": size[1], "z": size[2]})
                    car = kind == "vehicle"
                    found.append(MovingObject(name=f"{kind}{actor.id}", kind=kind, x=loc.x - self._origin[0], y=loc.y - self._origin[1],
                                              vx=vel.x, vy=vel.y, radius=math.hypot(ext.x, ext.y), height=2.0 * ext.z,
                                              half_width=ext.y if car else None, half_length=ext.x if car else None,
                                              yaw=math.radians(actor.get_transform().rotation.yaw) if car else 0.0))
            except Exception:
                return list(self._cache)      # a failed read keeps the last good picture
            self._cache = found
            return list(found)
