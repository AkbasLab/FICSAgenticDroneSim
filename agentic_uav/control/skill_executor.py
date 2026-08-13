"""Executes high-level skills against a VehicleAdapter and returns SkillResults.

The executor is where each skill's contract is enforced: it times the skill,
checks the success condition (e.g. within tolerance of the waypoint), and maps
the navigation outcome to a structured status (success / failed / timeout /
aborted). Mission-level skills (search, inspect, rendezvous, relay) are composed
here from the waypoint and hold primitives - the "first implementation calls
existing movement" approach.
"""

from ..core.enums import SkillStatus, SkillType
from ..core.models import NavOutcome, Position3D, SkillResult
from . import navigation as nav
from . import skills as sk


class SkillExecutor:
    def __init__(self, adapter):
        self.adapter = adapter

    def execute(self, vehicle_id: str, command) -> SkillResult:
        st = command.skill_type
        started = self.adapter.now(vehicle_id) if hasattr(self.adapter, "now") else 0.0
        try:
            if st is SkillType.TAKE_OFF:
                out = self.adapter.takeoff(vehicle_id, command.target_altitude,
                                           command.timeout_s)
                return self._result(vehicle_id, st, started, out,
                                    target=None, tol=None)

            if st is SkillType.GO_TO_WAYPOINT:
                out = self.adapter.go_to_waypoint(vehicle_id, command.waypoint,
                                                  command.speed_mps, command.timeout_s)
                return self._result(vehicle_id, st, started, out,
                                    command.waypoint, command.tolerance_m)

            if st is SkillType.FOLLOW_WAYPOINTS:
                return self._follow(vehicle_id, command, started)

            if st is SkillType.HOLD_POSITION:
                out = self.adapter.hold(vehicle_id, command.duration_s)
                return self._result(vehicle_id, st, started, out, None, None)

            if st is SkillType.RETURN_HOME:
                out = self.adapter.go_to_waypoint(vehicle_id, command.home,
                                                  command.speed_mps, command.timeout_s)
                return self._result(vehicle_id, st, started, out,
                                    command.home, command.tolerance_m)

            if st is SkillType.LAND:
                out = self.adapter.land(vehicle_id, command.timeout_s)
                return self._result(vehicle_id, st, started, out, None, None)

            if st is SkillType.EMERGENCY_HOLD:
                self.adapter.cancel(vehicle_id)
                out = self.adapter.hold(vehicle_id, 0.0)
                return self._result(vehicle_id, st, started, out, None, None)

            if st is SkillType.INSPECT_POINT:
                out = self.adapter.go_to_waypoint(vehicle_id, command.point,
                                                  command.speed_mps, command.timeout_s)
                res = self._result(vehicle_id, st, started, out,
                                   command.point, command.tolerance_m)
                if res.status is SkillStatus.SUCCESS:
                    self.adapter.hold(vehicle_id, command.dwell_s)
                    res.ended_at = self._now(vehicle_id)
                return res

            if st is SkillType.RENDEZVOUS:
                out = self.adapter.go_to_waypoint(vehicle_id, command.point,
                                                  command.speed_mps, command.timeout_s)
                return self._result(vehicle_id, st, started, out,
                                    command.point, command.tolerance_m)

            if st is SkillType.ACT_AS_RELAY:
                out = self.adapter.go_to_waypoint(vehicle_id, command.position,
                                                  command.speed_mps, command.timeout_s)
                res = self._result(vehicle_id, st, started, out,
                                   command.position, command.tolerance_m)
                if res.status is SkillStatus.SUCCESS:
                    self.adapter.hold(vehicle_id, command.duration_s)
                    res.ended_at = self._now(vehicle_id)
                return res

            if st is SkillType.SEARCH_REGION:
                return self._search(vehicle_id, command, started)

            return SkillResult(SkillStatus.FAILED, skill=str(st),
                               error_code="unknown_skill")
        except Exception as e:
            return SkillResult(SkillStatus.FAILED, skill=str(st),
                               started_at=started, ended_at=self._now(vehicle_id),
                               error_code="exception", detail=str(e))

    # --- composed skills ---

    def _follow(self, vehicle_id, command, started):
        last = None
        for wp in command.waypoints:
            out = self.adapter.go_to_waypoint(vehicle_id, wp, command.speed_mps,
                                              command.timeout_s)
            last = out
            reached = out.final_position.distance_to(wp) <= command.tolerance_m
            if not reached:
                return self._result(vehicle_id, SkillType.FOLLOW_WAYPOINTS,
                                    started, out, wp, command.tolerance_m)
        if last is None:
            return SkillResult(SkillStatus.FAILED, skill=str(SkillType.FOLLOW_WAYPOINTS),
                               started_at=started, ended_at=self._now(vehicle_id),
                               error_code="no_waypoints")
        return self._result(vehicle_id, SkillType.FOLLOW_WAYPOINTS, started, last,
                            command.waypoints[-1], command.tolerance_m)

    def _search(self, vehicle_id, command, started):
        waypoints = _lawnmower(command)
        follow = sk.FollowWaypointsCommand(
            waypoints=waypoints, speed_mps=command.speed_mps,
            tolerance_m=command.tolerance_m, timeout_s=command.timeout_s)
        res = self._follow(vehicle_id, follow, started)
        res.skill = str(SkillType.SEARCH_REGION)
        return res

    # --- helpers ---

    def _now(self, vehicle_id):
        return self.adapter.now(vehicle_id) if hasattr(self.adapter, "now") else 0.0

    def _result(self, vehicle_id, skill_type, started, out: NavOutcome,
                target, tol) -> SkillResult:
        ended = self._now(vehicle_id)
        if target is not None and tol is not None:
            reached = out.final_position.distance_to(target) <= tol
        else:
            reached = not out.timed_out

        if reached:
            status = SkillStatus.SUCCESS
            error = None
        elif out.timed_out:
            status = SkillStatus.TIMEOUT
            error = "timeout"
        else:
            status = SkillStatus.FAILED
            error = "not_reached"

        return SkillResult(
            status=status, skill=str(skill_type),
            started_at=started, ended_at=ended,
            final_position=out.final_position, error_code=error,
        )


def _lawnmower(command):
    """Generate boustrophedon sweep waypoints over the region."""
    wps = []
    y = command.min_y
    going_right = True
    while y <= command.max_y + 1e-9:
        xs = ([command.min_x, command.max_x] if going_right
              else [command.max_x, command.min_x])
        for x in xs:
            wps.append(Position3D(x, y, command.altitude))
        going_right = not going_right
        y += command.lane_spacing_m
    return wps
