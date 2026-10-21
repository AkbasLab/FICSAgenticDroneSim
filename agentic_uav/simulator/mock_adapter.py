"""A lightweight simulator behind the same protocols as AirSim (AUV-04, 3.4).

    world = MockWorld(declared=["Drone1", "Drone2"])
    adapter = MockVehicleAdapter(world)        # one per thread, like AirSim's

For unit tests, communication and task-allocation testing, rapid debugging
and CI. NOT a replacement for AirSim experiments: AUV-04 is explicit, and
AUV-19 recommends the factorial run here with a confirmation subset in
AirSim. Most of this project's research questions are coordination
questions, which this answers thousands of times in the time AirSim takes to
load a map.

THE MODEL, deliberately small (decided 2026-10-20):

* A drone is a point that moves in straight lines at the commanded speed,
  with no acceleration, no wind and no drift. Turning is at a fixed yaw rate.
* Time is a `SimClock`. Every motion takes simulated time -- distance over
  speed -- so a skill's timeout, a hold's duration and a team's timing all
  mean something, and four drones flying a minute take milliseconds.
* Motion is stored as SEGMENTS (from, to, start, end), not as positions
  updated each tick. Where a drone is at the current simulated instant is
  computed exactly, whichever thread asks first. That is what makes
  separation and contact figures deterministic across runs.
* Two drones closer than `contact_distance_m` touch: both record a
  collision with the other, by name, as AirSim reports drone contacts. The
  minimum separation of every pair is kept.

WHERE IT COPIES AIRSIM, ON PURPOSE, because code above depends on it:

* NED, with the ground at z = +29.25 by default (Town10HD's measured ground),
  so a skill that forgets the ground offset fails here as it would there.
* `add_vehicle` IGNORES its pose and spawns at the player start, as
  `simAddVehicle` does; `place_vehicle` then sets x, y and the drone comes to
  rest on the ground. `scenario_manager.ensure_vehicles` relies on both.
* `reset` returns every drone to its spawn point; it removes none.
* Releasing control of an airborne drone cuts its motors: it falls to the
  ground and records a ground contact. The skill layer must never do this.
* Landing contact is reported as a collision with an object whose name
  contains "ground" (`MockGround`), which `control.contacts` classifies as
  ground.

WHERE IT DIFFERS, on purpose: the ground is solid. CarlaAir has no terrain
collision and a drone passes through it; here a move below the ground stops
at it and records a ground contact, so a sign error shows up as a contact
rather than as a drone underground.

THE TRACE. Every change of motion is recorded as a knot -- (time, position,
airborne) -- so `trace(name)` is the drone's exact path:
straight lines between knots, a jump where two share an instant. The mission
world judges a flight by it (`simulator/observer.py`), with nothing sampled.

FAULTS can be injected per drone (`world.faults`): a landing that does not
descend (the 2026-10-06 and 2026-10-19 failure), moves that make no
progress, a primitive that raises, a slower drone.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any

from ..core.clock import Clock, SimClock
from ..core.models import (
    CollisionInfo,
    Position,
    PrimitiveCommand,
    PrimitiveKind,
    PrimitiveResult,
    VehicleState,
)

MOCK_GROUND_Z = 29.25            # Town10HD's ground in NED, Phase 1
MOCK_SPACING_M = 4.0             # declared drones along +x, as settings.json lays them out
TAKEOFF_HEIGHT_M = 3.0           # AirSim's takeoff lifts about this far
TAKEOFF_SPEED_MPS = 1.5
LAND_SPEED_MPS = 1.0
YAW_RATE_DEG_S = 90.0
DEFAULT_TICK_S = 0.1             # how often a moving drone looks for contacts and cancels
DEFAULT_CONTACT_M = 0.8          # closer than this, two drones touch
MAX_PRIMITIVE_S = 3600.0         # a move with no timeout that cannot finish stops here
GROUND_OBJECT = "MockGround"     # contains "ground": classified as ground


@dataclass(frozen=True)
class _Segment:
    """Straight-line motion from `a` at `t0` to `b` at `t1`; static if t1 <= t0."""

    a: Position
    b: Position
    t0: float
    t1: float

    def at(self, t: float) -> Position:
        if self.t1 <= self.t0 or t >= self.t1:
            return self.b
        if t <= self.t0:
            return self.a
        f = (t - self.t0) / (self.t1 - self.t0)
        return Position(self.a.x + (self.b.x - self.a.x) * f,
                        self.a.y + (self.b.y - self.a.y) * f,
                        self.a.z + (self.b.z - self.a.z) * f)


def _static(p: Position) -> _Segment:
    return _Segment(p, p, 0.0, 0.0)


@dataclass
class _Vehicle:
    name: str
    spawn: Position
    segment: _Segment
    yaw: float = 0.0
    landed: bool = True
    api: bool = False
    armed: bool = False
    moving: bool = False
    cancel_requested: bool = False
    collision: CollisionInfo = field(default_factory=lambda: CollisionInfo(False))
    contact_stamp: int = 0


@dataclass
class MockFaults:
    """Per-drone faults. Names in a set, or keyed by drone name."""

    stuck_land: set[str] = field(default_factory=set)      # land and descents do nothing
    stalled: set[str] = field(default_factory=set)         # moves make no progress
    raise_on: dict[tuple[str, PrimitiveKind], str] = field(default_factory=dict)
    speed_factor: dict[str, float] = field(default_factory=dict)


class MockWorld:
    """The shared state behind every MockVehicleAdapter of one simulated scene."""

    def __init__(self, declared: list[str] | tuple[str, ...] = ("Drone1",),
                 clock: Clock | None = None, ground_z: float = MOCK_GROUND_Z,
                 spacing_m: float = MOCK_SPACING_M, tick_s: float = DEFAULT_TICK_S,
                 contact_distance_m: float = DEFAULT_CONTACT_M) -> None:
        if tick_s <= 0:
            raise ValueError("tick must be positive")
        self.clock = clock if clock is not None else SimClock()
        self.ground_z = ground_z
        self.tick_s = tick_s
        self.contact_distance_m = contact_distance_m
        self.faults = MockFaults()
        self.lock = threading.RLock()
        self.vehicles: dict[str, _Vehicle] = {}
        self._trace: dict[str, list[tuple[float, Position, bool]]] = {}
        for i, name in enumerate(declared):
            spawn = Position(i * spacing_m, 0.0, ground_z)
            self.vehicles[name] = _Vehicle(name, spawn, _static(spawn))
            self._knot(self.vehicles[name])
        # Per unordered pair: (minimum distance, simulated time it happened).
        self.min_separation: dict[tuple[str, str], tuple[float, float]] = {}
        # Every contact, one row per (pair or drone-and-ground, instant).
        self._contacts: dict[tuple[Any, ...], dict[str, Any]] = {}

    # -------------------------------------------------------------- reading

    def position(self, name: str) -> Position:
        with self.lock:
            return self.vehicles[name].segment.at(self.clock.now())

    def contacts(self) -> list[dict[str, Any]]:
        """Every contact so far, in time order, deterministically."""
        with self.lock:
            return sorted(self._contacts.values(), key=lambda c: (c["at_s"], c["drone"], c["object"]))

    def trace(self, name: str) -> list[tuple[float, Position, bool]]:
        """`name`'s knots so far: (simulated time, position, airborne), in time order."""
        with self.lock:
            return list(self._trace[name])

    def separation(self) -> dict[str, dict[str, float]]:
        with self.lock:
            return {f"{a}-{b}": {"min_m": round(d, 3), "at_s": round(t, 3)}
                    for (a, b), (d, t) in sorted(self.min_separation.items())}

    # ------------------------------------------------------------- internal

    def _vehicle(self, name: str) -> _Vehicle:
        try:
            return self.vehicles[name]
        except KeyError:
            raise KeyError(f"no vehicle named {name!r} in the mock") from None

    def _knot(self, v: _Vehicle) -> None:
        # Caller holds the lock. Called before and after every change of motion.
        now = self.clock.now()
        knot = (now, v.segment.at(now), not v.landed)
        trace = self._trace.setdefault(v.name, [])
        if not trace or trace[-1] != knot:
            trace.append(knot)

    def _touch(self, v: _Vehicle, obj: str, at: float, depth: float = 0.0) -> None:
        # Caller holds the lock.
        key = (v.name, obj, round(at, 6))
        if key in self._contacts:
            return
        v.contact_stamp += 1
        v.collision = CollisionInfo(True, v.contact_stamp, obj, depth,
                                    v.segment.at(at))
        self._contacts[key] = {"drone": v.name, "object": obj, "at_s": round(at, 6),
                               "penetration_m": round(depth, 4)}

    def _check_contacts(self, v: _Vehicle) -> None:
        # Caller holds the lock. Compares v with every other drone, at now.
        now = self.clock.now()
        here = v.segment.at(now)
        for other in self.vehicles.values():
            if other is v:
                continue
            there = other.segment.at(now)
            d = math.dist((here.x, here.y, here.z), (there.x, there.y, there.z))
            pair = tuple(sorted((v.name, other.name)))
            best = self.min_separation.get(pair)
            if not (v.landed and other.landed) and (best is None or d < best[0]):
                self.min_separation[pair] = (d, now)
            if d < self.contact_distance_m and not (v.landed and other.landed):
                depth = self.contact_distance_m - d
                self._touch(v, other.name, now, depth)
                self._touch(other, v.name, now, depth)


class MockVehicleAdapter:
    """`VehicleAdapter` and `SceneAdapter` over a `MockWorld`.

    Thread-safe; still, give each flying thread its own, as with AirSim, so
    code moves between the two unchanged. Threads that fly at the same time
    must `participate()` in the world's clock.
    """

    def __init__(self, world: MockWorld) -> None:
        self.world = world

    # ------------------------------------------------------- VehicleAdapter

    def get_state(self, vehicle_id: str) -> VehicleState:
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            return VehicleState(vehicle_id, v.segment.at(self.world.clock.now()),
                                0 if v.landed else 1, v.yaw)

    def get_pose(self, vehicle_id: str) -> Position:
        with self.world.lock:
            return self.world._vehicle(vehicle_id).segment.at(self.world.clock.now())

    def get_collision(self, vehicle_id: str) -> CollisionInfo:
        with self.world.lock:
            return self.world._vehicle(vehicle_id).collision

    def has_control(self, vehicle_id: str) -> bool:
        with self.world.lock:
            return self.world._vehicle(vehicle_id).api

    def take_control(self, vehicle_id: str) -> None:
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            v.api = True
            v.armed = True

    def release(self, vehicle_id: str) -> None:
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            v.armed = False
            v.api = False
            now = self.world.clock.now()
            here = v.segment.at(now)
            if not v.landed:
                # Motors cut in the air: it falls. The skill layer must never.
                self.world._knot(v)
                ground = Position(here.x, here.y, self.world.ground_z)
                v.segment = _static(ground)
                v.landed = True
                self.world._knot(v)
                self.world._touch(v, GROUND_OBJECT, now, depth=0.0)

    def execute_primitive(self, vehicle_id: str, command: PrimitiveCommand) -> PrimitiveResult:
        kind, p = command.kind, command.params
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            message = self.world.faults.raise_on.get((vehicle_id, kind))
        if message is not None:
            raise RuntimeError(message)
        if kind is PrimitiveKind.TAKE_OFF:
            self._require_armed(v)
            here = self.world.position(vehicle_id)
            self._move(v, Position(here.x, here.y, self.world.ground_z - TAKEOFF_HEIGHT_M),
                       TAKEOFF_SPEED_MPS, None)
        elif kind is PrimitiveKind.MOVE_TO_Z:
            self._require_armed(v)
            here = self.world.position(vehicle_id)
            target_z = p["z"]
            if vehicle_id in self.world.faults.stuck_land and target_z > self.world.ground_z - 2.0:
                return PrimitiveResult(vehicle_id, kind)        # the descent that does not descend
            self._move(v, Position(here.x, here.y, target_z), p["speed"], p.get("timeout"))
        elif kind is PrimitiveKind.MOVE_TO_POSITION:
            self._require_armed(v)
            self._move(v, Position(p["x"], p["y"], p["z"]), p["speed"], p.get("timeout"))
        elif kind is PrimitiveKind.VELOCITY:
            self._require_armed(v)
            here = self.world.position(vehicle_id)
            yaw = math.radians(v.yaw)
            dx = p["vx"] * math.cos(yaw) - p["vy"] * math.sin(yaw)
            dy = p["vx"] * math.sin(yaw) + p["vy"] * math.cos(yaw)
            duration = max(0.0, p["duration"])
            speed = math.hypot(p["vx"], p["vy"])
            target = Position(here.x + dx * duration, here.y + dy * duration, here.z)
            if speed > 0 and duration > 0:
                self._move(v, target, speed, None)
            else:
                self.world.clock.sleep(duration)
        elif kind is PrimitiveKind.HOVER:
            pass                                               # hold: no motion, no time
        elif kind is PrimitiveKind.LAND:
            self._require_armed(v)
            if vehicle_id not in self.world.faults.stuck_land:
                here = self.world.position(vehicle_id)
                self._move(v, Position(here.x, here.y, self.world.ground_z), LAND_SPEED_MPS,
                           p.get("timeout"))
                with self.world.lock:
                    if self.world.position(vehicle_id).z >= self.world.ground_z - 1e-6:
                        v.landed = True
                        self.world._knot(v)
                        self.world._touch(v, GROUND_OBJECT, self.world.clock.now())
        elif kind is PrimitiveKind.ROTATE_TO_YAW:
            self._require_armed(v)
            self._rotate(v, p["yaw"], p.get("timeout"))
        else:  # unreachable: PrimitiveCommand rejects unknown kinds
            raise ValueError(f"unhandled primitive {kind!r}")
        return PrimitiveResult(vehicle_id, kind)

    def stop(self, vehicle_id: str) -> None:
        self.execute_primitive(vehicle_id, PrimitiveCommand.hover())

    def cancel(self, vehicle_id: str) -> None:
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            if v.moving:                       # like cancelLastTask: nothing running, nothing to do
                v.cancel_requested = True

    # --------------------------------------------------------- SceneAdapter

    def confirm_connection(self) -> None:
        return None

    def reset(self) -> None:
        with self.world.lock:
            for v in self.world.vehicles.values():
                self.world._knot(v)
                v.segment = _static(v.spawn)
                v.yaw, v.landed, v.api, v.armed = 0.0, True, False, False
                self.world._knot(v)
                v.moving = v.cancel_requested = False
                v.collision = CollisionInfo(False)

    def list_vehicles(self) -> list[str]:
        with self.world.lock:
            return list(self.world.vehicles)

    def add_vehicle(self, vehicle_id: str, vehicle_type: str, position: Position) -> bool:
        # As simAddVehicle: the pose is ignored; it appears at the player start.
        with self.world.lock:
            if vehicle_id in self.world.vehicles:
                return False
            spawn = Position(0.0, 0.0, self.world.ground_z)
            self.world.vehicles[vehicle_id] = _Vehicle(vehicle_id, spawn, _static(spawn))
            self.world._knot(self.world.vehicles[vehicle_id])
            return True

    def place_vehicle(self, vehicle_id: str, position: Position,
                      ignore_collision: bool = True) -> None:
        with self.world.lock:
            v = self.world._vehicle(vehicle_id)
            rest = Position(position.x, position.y, self.world.ground_z)   # it falls to rest
            self.world._knot(v)
            v.segment = _static(rest)
            v.spawn = rest
            v.landed = True
            self.world._knot(v)

    # ------------------------------------------------------------- motion

    def _require_armed(self, v: _Vehicle) -> None:
        with self.world.lock:
            if not (v.api and v.armed):
                raise RuntimeError(f"{v.name} is not armed under API control")

    def _move(self, v: _Vehicle, target: Position, speed: float, timeout: float | None) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        world, clock = self.world, self.world.clock
        speed *= world.faults.speed_factor.get(v.name, 1.0)
        with world.lock:
            now = clock.now()
            start = v.segment.at(now)
            if target.z > world.ground_z:                       # solid ground: stop at it
                target = Position(target.x, target.y, world.ground_z)
                world._touch(v, GROUND_OBJECT, now)
            distance = math.dist((start.x, start.y, start.z), (target.x, target.y, target.z))
            stalled = v.name in world.faults.stalled
            duration = distance / speed
            limit = MAX_PRIMITIVE_S if timeout is None else max(0.0, timeout)
            if stalled:
                v.segment = _static(start)
                end = now + limit
            else:
                v.segment = _Segment(start, target, now, now + duration)
                end = now + min(duration, limit)
            v.moving = True
            v.cancel_requested = False
            if target.z < world.ground_z - 1e-6:
                v.landed = False
            world._knot(v)                  # the start: here, and airborne if leaving the ground
        cancelled = False
        try:
            while True:
                with world.lock:
                    if v.cancel_requested:
                        cancelled = True
                        break
                remaining = end - clock.now()
                if remaining <= 1e-9:
                    break
                clock.sleep(min(world.tick_s, remaining))
                with world.lock:
                    world._check_contacts(v)
        finally:
            with world.lock:
                # A move that ran its full course ends EXACTLY at its target:
                # summed ticks drift in the last digits (0.1 x 100 != 10.0).
                completed = not cancelled and not stalled and duration <= limit
                world._knot(v)
                v.segment = _static(target if completed else v.segment.at(clock.now()))
                world._knot(v)
                v.moving = False
                v.cancel_requested = False

    def _rotate(self, v: _Vehicle, yaw: float, timeout: float | None) -> None:
        world, clock = self.world, self.world.clock
        with world.lock:
            start = v.yaw
            error = (yaw - start + 180.0) % 360.0 - 180.0
            duration = abs(error) / YAW_RATE_DEG_S
            limit = MAX_PRIMITIVE_S if timeout is None else max(0.0, timeout)
            t0 = clock.now()
            end = t0 + min(duration, limit)
            v.moving = True
            v.cancel_requested = False
        try:
            while True:
                with world.lock:
                    if v.cancel_requested:
                        break
                remaining = end - clock.now()
                if remaining <= 1e-9:
                    break
                clock.sleep(min(world.tick_s, remaining))
        finally:
            with world.lock:
                elapsed = clock.now() - t0
                f = 1.0 if duration == 0 else min(1.0, elapsed / duration)
                v.yaw = (start + error * f + 180.0) % 360.0 - 180.0
                v.moving = False
                v.cancel_requested = False
