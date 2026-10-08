"""A mock VehicleAdapter that actually travels, at a fixed speed, instead of
teleporting like MockVehicleAdapter does. Phase 2-3's tests need the
instant-arrival mock (fast, deterministic, no real time passing) - this one
exists because Phase 4's scorer needs a real path to score: coverage,
no-fly-zone crossings, and separation are all about where a drone was
*between* waypoints, not just where it ends up. Position is computed from
real elapsed wall-clock time since the last start_move_to()/start_hover(),
so get_position() gives a different answer each time it's polled mid-flight -
exactly what a telemetry recorder sampling on a timer needs to see.
"""

import math
import time

from ..core.interfaces import VehicleAdapter

DEFAULT_SPEED_MPS = 5.0  # matches control.navigation.MOVE_SPEED


class KinematicMockVehicleAdapter(VehicleAdapter):
    def __init__(self, vehicle_name="KinematicMockDrone",
                 start_position=(0.0, 0.0, 0.0), speed_mps=DEFAULT_SPEED_MPS):
        self.vehicle_name = vehicle_name
        self.speed_mps = speed_mps
        self._pos = start_position
        self._target = None  # None while hovering/idle
        self._move_start_time = None
        self._move_start_pos = start_position

    def connect_and_takeoff(self):
        pass  # ground_z bookkeeping isn't relevant to a mock

    def execute(self, commands):
        # Phase 4 drives drones through skills (go_to_waypoint/follow_waypoints),
        # not raw execute() - this exists only so the class satisfies the
        # VehicleAdapter contract.
        raise NotImplementedError("KinematicMockVehicleAdapter is driven via skills, not execute()")

    def land(self):
        self._target = None

    def _advance(self):
        """Recompute self._pos from real elapsed time, called before every
        position/speed read so a poll mid-flight sees genuine progress."""
        if self._target is None or self._move_start_time is None:
            return
        elapsed = time.monotonic() - self._move_start_time
        travel = self.speed_mps * elapsed
        dx = self._target[0] - self._move_start_pos[0]
        dy = self._target[1] - self._move_start_pos[1]
        dz = self._target[2] - self._move_start_pos[2]
        dist = math.dist(self._move_start_pos, self._target)
        if dist <= 1e-9 or travel >= dist:
            self._pos = self._target
            self._target = None  # arrived - now idle, get_speed() reports 0
            return
        frac = travel / dist
        self._pos = (
            self._move_start_pos[0] + dx * frac,
            self._move_start_pos[1] + dy * frac,
            self._move_start_pos[2] + dz * frac,
        )

    def get_position(self):
        self._advance()
        return self._pos

    def get_speed(self):
        self._advance()
        return self.speed_mps if self._target is not None else 0.0

    def start_move_to(self, x, y, z):
        self._advance()  # settle wherever we actually are before retargeting
        self._move_start_pos = self._pos
        self._move_start_time = time.monotonic()
        self._target = (x, y, z)

    def start_hover(self):
        self._advance()
        self._target = None
