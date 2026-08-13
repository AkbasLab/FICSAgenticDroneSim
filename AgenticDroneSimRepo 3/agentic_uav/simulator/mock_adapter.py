"""Kinematic mock simulator - a VehicleAdapter with no AirSim (Phase 3.4).

It approximates waypoint travel with simple constant-speed kinematics on a
deterministic, simulated clock (no real sleeping). It is NOT a replacement for
AirSim experiments; it exists for unit tests, communication and task-allocation
testing, rapid debugging, and CI.

Determinism: travel time = distance / speed. If that exceeds the timeout, the
drone moves only as far as it could in the allotted time and reports timed_out,
so the skill layer can detect a missed waypoint. Every vehicle keeps its own
simulated clock, so concurrent drones don't interfere.
"""

from ..control import navigation as nav
from ..core.models import NavOutcome, Position3D, VehicleState


class MockVehicleAdapter:
    def __init__(self, ground_z: float = 0.0):
        self._ground = ground_z
        self._pos = {}        # vehicle_id -> Position3D (starts on the ground)
        self._heading = {}    # vehicle_id -> heading degrees
        self._clock = {}      # vehicle_id -> simulated seconds elapsed
        self.log = []         # (vehicle_id, event, detail) for tests/inspection
        self._action_log = [] # (vehicle_id, action) for the low-level Phase 1/2 path

    # --- helpers ---

    def _p(self, vid) -> Position3D:
        if vid not in self._pos:
            self._pos[vid] = Position3D(0.0, 0.0, self._ground)
            self._heading[vid] = 0.0
            self._clock[vid] = 0.0
        return self._pos[vid]

    def _advance(self, vid, seconds):
        self._clock[vid] = self._clock.get(vid, 0.0) + seconds

    def now(self, vid) -> float:
        self._p(vid)
        return self._clock[vid]

    # --- state ---

    def get_position(self, vehicle_id: str) -> Position3D:
        p = self._p(vehicle_id)
        return Position3D(p.x, p.y, p.z)

    def get_state(self, vehicle_id: str) -> VehicleState:
        p = self._p(vehicle_id)
        return VehicleState(vehicle_id=vehicle_id, position=Position3D(p.x, p.y, p.z),
                            heading_deg=self._heading[vehicle_id], armed=True)

    # --- navigation primitives ---

    def takeoff(self, vehicle_id, target_altitude, timeout_s) -> NavOutcome:
        p = self._p(vehicle_id)
        target = Position3D(p.x, p.y, target_altitude)
        return self._travel(vehicle_id, target, nav.CLIMB_SPEED, timeout_s, "takeoff")

    def go_to_waypoint(self, vehicle_id, waypoint, speed_mps, timeout_s) -> NavOutcome:
        return self._travel(vehicle_id, waypoint, speed_mps, timeout_s, "go_to_waypoint")

    def turn_to_heading(self, vehicle_id, heading_deg, timeout_s) -> NavOutcome:
        self._p(vehicle_id)
        # simple model: turning is quick and always succeeds
        self._heading[vehicle_id] = heading_deg % 360
        self._advance(vehicle_id, 1.0)
        return NavOutcome(final_position=self.get_position(vehicle_id),
                          elapsed_s=1.0, timed_out=False)

    def hold(self, vehicle_id, duration_s) -> NavOutcome:
        self._p(vehicle_id)
        self._advance(vehicle_id, duration_s)
        self.log.append((vehicle_id, "hold", duration_s))
        return NavOutcome(final_position=self.get_position(vehicle_id),
                          elapsed_s=duration_s, timed_out=False)

    def land(self, vehicle_id, timeout_s) -> NavOutcome:
        p = self._p(vehicle_id)
        target = Position3D(p.x, p.y, self._ground)
        out = self._travel(vehicle_id, target, nav.LAND_SLOW_SPEED, timeout_s, "land")
        return out

    def cancel(self, vehicle_id) -> None:
        self.log.append((vehicle_id, "cancel", None))

    def stop(self, vehicle_id) -> None:
        self.log.append((vehicle_id, "stop", None))
        self._action_log.append((vehicle_id, "stop"))

    # --- low-level Phase 1/2 path (kept so the LLM planners + old test work) ---

    def execute_skill(self, vehicle_id, command):
        from ..core.enums import SkillStatus
        from ..core.models import SkillResult
        self._action_log.append((vehicle_id, command.action))
        return SkillResult(SkillStatus.SUCCESS, skill=command.action)

    def actions_for(self, vehicle_id):
        return [a for (vid, a) in self._action_log if vid == vehicle_id]

    # --- kinematics ---

    def _travel(self, vid, target: Position3D, speed, timeout_s, label) -> NavOutcome:
        start = self._p(vid)
        dist = start.distance_to(target)
        speed = max(speed, 0.001)
        travel_time = dist / speed

        if travel_time <= timeout_s or timeout_s <= 0:
            self._pos[vid] = Position3D(target.x, target.y, target.z)
            self._advance(vid, travel_time)
            self.log.append((vid, label, "reached"))
            return NavOutcome(final_position=self.get_position(vid),
                              elapsed_s=travel_time, timed_out=False)

        # ran out of time: move only as far as possible, report timeout
        frac = (speed * timeout_s) / dist
        self._pos[vid] = Position3D(
            start.x + (target.x - start.x) * frac,
            start.y + (target.y - start.y) * frac,
            start.z + (target.z - start.z) * frac,
        )
        self._advance(vid, timeout_s)
        self.log.append((vid, label, "timeout"))
        return NavOutcome(final_position=self.get_position(vid),
                          elapsed_s=timeout_s, timed_out=True)
