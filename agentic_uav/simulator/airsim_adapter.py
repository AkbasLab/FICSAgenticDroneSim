"""AirSim implementation of VehicleAdapter (Phase 3 navigation primitives).

All real AirSim calls live here and nowhere else. One MultirotorClient PER
VEHICLE, because AirSim's RPC client is not safe to share across the threads that
fly drones concurrently (the baseline's Multiple.py did the same).
"""

import threading
import time

import airsim

from ..control import navigation as nav
from ..core.models import NavOutcome, Position3D, VehicleState


class AirSimVehicleAdapter:
    def __init__(self):
        self.client = airsim.MultirotorClient()   # setup/spawn client
        self.client.confirmConnection()
        self._clients = {}
        self._clients_lock = threading.Lock()
        self._ground_z = {}   # vehicle_id -> ground level recorded at takeoff
        self._t0 = time.monotonic()   # mission clock origin

    def now(self, vehicle_id=None) -> float:
        """Seconds since this adapter was created.

        The agent layer needs a clock: battery depletion, information ageing and
        message timestamps are all measured against it. The mock keeps a
        *simulated* per-vehicle clock; here real time is the truth and all
        vehicles share it, which is what we want when they fly concurrently.
        """
        return time.monotonic() - self._t0

    def _client_for(self, vehicle_id):
        c = self._clients.get(vehicle_id)
        if c is None:
            with self._clients_lock:
                c = self._clients.get(vehicle_id)
                if c is None:
                    c = airsim.MultirotorClient()
                    c.confirmConnection()
                    self._clients[vehicle_id] = c
        return c

    # --- state ---

    def get_position(self, vehicle_id: str) -> Position3D:
        c = self._client_for(vehicle_id)
        p = c.getMultirotorState(vehicle_name=vehicle_id).kinematics_estimated.position
        return Position3D(p.x_val, p.y_val, p.z_val)

    def get_state(self, vehicle_id: str) -> VehicleState:
        c = self._client_for(vehicle_id)
        s = c.getMultirotorState(vehicle_name=vehicle_id)
        p = s.kinematics_estimated.position
        _, _, yaw = airsim.to_eularian_angles(s.kinematics_estimated.orientation)
        import math
        return VehicleState(vehicle_id=vehicle_id,
                            position=Position3D(p.x_val, p.y_val, p.z_val),
                            heading_deg=math.degrees(yaw), armed=True)

    # --- navigation primitives ---

    def takeoff(self, vehicle_id, target_altitude, timeout_s) -> NavOutcome:
        c = self._client_for(vehicle_id)
        t0 = time.time()
        c.enableApiControl(True, vehicle_name=vehicle_id)
        c.armDisarm(True, vehicle_name=vehicle_id)
        self._ground_z[vehicle_id] = self.get_position(vehicle_id).z
        c.takeoffAsync(vehicle_name=vehicle_id).join()
        c.moveToZAsync(target_altitude, nav.CLIMB_SPEED, vehicle_name=vehicle_id).join()
        return self._outcome(vehicle_id, t0, timeout_s)

    def go_to_waypoint(self, vehicle_id, waypoint, speed_mps, timeout_s) -> NavOutcome:
        c = self._client_for(vehicle_id)
        t0 = time.time()
        c.moveToPositionAsync(waypoint.x, waypoint.y, waypoint.z, speed_mps,
                              timeout_sec=timeout_s, vehicle_name=vehicle_id).join()
        return self._outcome(vehicle_id, t0, timeout_s)

    def turn_to_heading(self, vehicle_id, heading_deg, timeout_s) -> NavOutcome:
        c = self._client_for(vehicle_id)
        t0 = time.time()
        c.rotateToYawAsync(heading_deg, timeout_sec=timeout_s,
                           vehicle_name=vehicle_id).join()
        return self._outcome(vehicle_id, t0, timeout_s)

    def hold(self, vehicle_id, duration_s) -> NavOutcome:
        c = self._client_for(vehicle_id)
        t0 = time.time()
        c.hoverAsync(vehicle_name=vehicle_id).join()
        time.sleep(duration_s)
        return self._outcome(vehicle_id, t0, duration_s + 1.0)

    def land(self, vehicle_id, timeout_s) -> NavOutcome:
        c = self._client_for(vehicle_id)
        t0 = time.time()
        ground = self._ground_z.get(vehicle_id, 0.0)
        # fast descent to 4 m above ground, settle, slow final approach
        c.moveToZAsync(ground - nav.LAND_FAST_ABOVE, nav.LAND_FAST_SPEED,
                       vehicle_name=vehicle_id).join()
        c.hoverAsync(vehicle_name=vehicle_id).join()
        time.sleep(nav.LAND_SETTLE_SECS)
        c.moveToZAsync(ground, nav.LAND_SLOW_SPEED, vehicle_name=vehicle_id).join()
        c.armDisarm(False, vehicle_name=vehicle_id)
        return self._outcome(vehicle_id, t0, timeout_s)

    def cancel(self, vehicle_id) -> None:
        c = self._client_for(vehicle_id)
        try:
            c.cancelLastTask(vehicle_name=vehicle_id)
            c.hoverAsync(vehicle_name=vehicle_id)
        except Exception:
            pass

    # --- low-level Phase 1/2 path (kept so the LLM planners still fly) ---

    def execute_skill(self, vehicle_id, command):
        """Map a low-level SkillCommand onto the navigation primitives."""
        from ..core.enums import ActionType, SkillStatus
        from ..core.models import SkillResult
        a, p = command.action, command.params
        try:
            if a == ActionType.ARM_TAKEOFF.value:
                self.takeoff(vehicle_id, nav.ALTITUDE, 30.0)
            elif a == ActionType.FLY_TO.value:
                self.go_to_waypoint(vehicle_id, Position3D(p["x"], p["y"], p["z"]),
                                    nav.FLY_TO_SPEED, 60.0)
            elif a in (ActionType.FLY_STRAIGHT.value, ActionType.FLY_BACKWARD.value,
                       ActionType.FLY_LEFT.value, ActionType.FLY_RIGHT.value):
                vx, vy = nav.direction_velocity(a)
                cur = self.get_position(vehicle_id)
                target = Position3D(cur.x + vx * p["duration"],
                                    cur.y + vy * p["duration"], cur.z)
                self.go_to_waypoint(vehicle_id, target, nav.MOVE_SPEED,
                                    p["duration"] + 10.0)
            elif a == ActionType.HOVER.value:
                self.hold(vehicle_id, p["duration"])
            elif a == ActionType.SET_ALTITUDE.value:
                cur = self.get_position(vehicle_id)
                self.go_to_waypoint(vehicle_id, Position3D(cur.x, cur.y, p["z"]),
                                    nav.CLIMB_SPEED, 30.0)
            elif a == ActionType.LAND.value:
                self.land(vehicle_id, 45.0)
            else:
                return SkillResult(SkillStatus.FAILED, skill=a,
                                   error_code="unknown_action")
            return SkillResult(SkillStatus.SUCCESS, skill=a)
        except Exception as e:
            return SkillResult(SkillStatus.FAILED, skill=a, detail=str(e))

    def stop(self, vehicle_id) -> None:
        c = self._client_for(vehicle_id)
        try:
            c.armDisarm(False, vehicle_name=vehicle_id)
            c.enableApiControl(False, vehicle_name=vehicle_id)
        except Exception:
            pass

    # --- helper ---

    def _outcome(self, vehicle_id, t0, timeout_s) -> NavOutcome:
        elapsed = time.time() - t0
        return NavOutcome(final_position=self.get_position(vehicle_id),
                          elapsed_s=elapsed, timed_out=elapsed >= timeout_s)
