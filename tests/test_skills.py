"""Phase 3 skill-layer tests, all on the kinematic mock (no simulator, no LLM).

Checks that skills return the right STRUCTURED result: waypoints reached within
tolerance succeed, unreachable-in-time waypoints time out, waypoint following
works, and the four-drone exit-criterion mission completes.

Run:  python tests/test_skills.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.control import skills as sk
from agentic_uav.control.skill_executor import SkillExecutor
from agentic_uav.core.enums import SkillStatus
from agentic_uav.core.models import Position3D
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  ok    {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        failed += 1


def fresh():
    a = MockVehicleAdapter()
    return a, SkillExecutor(a)


# 1) take off then reach a waypoint -> success, within tolerance
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
r = ex.execute("D", sk.GoToWaypointCommand(waypoint=Position3D(30, 0, -8)))
check("go_to_waypoint reaches target -> success", r.status is SkillStatus.SUCCESS)
check("final position within tolerance",
      r.final_position.distance_to(Position3D(30, 0, -8)) <= 1.5)
check("structured result has timing", r.ended_at >= r.started_at)

# 2) waypoint unreachable within timeout -> timeout
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
# 1000 m at 4 m/s needs 250 s, but timeout is 5 s
r = ex.execute("D", sk.GoToWaypointCommand(
    waypoint=Position3D(1000, 0, -8), speed_mps=4.0, timeout_s=5.0))
check("far waypoint with short timeout -> timeout", r.status is SkillStatus.TIMEOUT)
check("timeout result carries an error code", r.error_code == "timeout")

# 3) follow a list of waypoints -> success, ends at the last one
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
wps = [Position3D(10, 0, -8), Position3D(10, 10, -8), Position3D(0, 10, -8)]
r = ex.execute("D", sk.FollowWaypointsCommand(waypoints=wps))
check("follow_waypoints -> success", r.status is SkillStatus.SUCCESS)
check("ends at final waypoint",
      r.final_position.distance_to(wps[-1]) <= 1.5)

# 4) hold returns success and advances the clock
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
before = a.now("D")
r = ex.execute("D", sk.HoldPositionCommand(duration_s=5.0))
check("hold -> success", r.status is SkillStatus.SUCCESS)
check("hold advanced simulated time by ~5s", (a.now("D") - before) >= 5.0)

# 5) land brings the drone to the ground
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
r = ex.execute("D", sk.LandCommand())
check("land -> success", r.status is SkillStatus.SUCCESS)
check("landed near ground level", abs(a.get_position("D").z) <= 0.5)

# 6) exit criterion: 4 drones take off -> waypoint -> hold -> home -> land
a, ex = fresh()
targets = {"D1": Position3D(20, 0, -8), "D2": Position3D(0, 20, -8),
           "D3": Position3D(-20, 0, -8), "D4": Position3D(0, -20, -8)}
all_ok = True
for vid, wp in targets.items():
    seq = [sk.TakeOffCommand(), sk.GoToWaypointCommand(waypoint=wp),
           sk.HoldPositionCommand(duration_s=3.0), sk.ReturnHomeCommand(),
           sk.LandCommand()]
    for cmd in seq:
        res = ex.execute(vid, cmd)
        all_ok = all_ok and res.status is SkillStatus.SUCCESS
check("four-drone takeoff/waypoint/hold/return/land all succeed", all_ok)

# 7) a multi-leg skill runs under ONE budget, and a stalled leg fails fast.
#    The timeout used to be handed to every leg, so a twelve-leg sweep could
#    take twelve times its timeout and a pinned drone waited the full timeout
#    on each leg. Found when a CARLA-Air run went silent mid-sweep.


class StuckOnLeg(MockVehicleAdapter):
    """A vehicle that cannot make progress towards one particular waypoint:
    it burns whatever time it is given and stays where it is."""

    def __init__(self, stuck_x):
        super().__init__(0.0)
        self.stuck_x = stuck_x
        self.leg_timeouts = []

    def go_to_waypoint(self, vehicle_id, waypoint, speed_mps, timeout_s):
        self.leg_timeouts.append(timeout_s)
        if waypoint.x == self.stuck_x:
            self._advance(vehicle_id, timeout_s)          # pinned in place
            from agentic_uav.core.models import NavOutcome
            return NavOutcome(final_position=self.get_position(vehicle_id),
                              elapsed_s=timeout_s, timed_out=True)
        return super().go_to_waypoint(vehicle_id, waypoint, speed_mps, timeout_s)


a = StuckOnLeg(stuck_x=50.0)
ex = SkillExecutor(a)
ex.execute("D", sk.TakeOffCommand())
t0 = a.now("D")
r = ex.execute("D", sk.SearchRegionCommand(
    min_x=10, min_y=10, max_x=50, max_y=50, altitude=-8.0,
    lane_spacing_m=8.0, speed_mps=4.0, tolerance_m=1.5, timeout_s=600.0))
spent = a.now("D") - t0
check("a sweep with a stalled leg fails rather than reporting success",
      r.status is not SkillStatus.SUCCESS)
check("the stalled leg gives up in well under the 600 s skill timeout",
      spent < 120.0)
check("no leg is ever handed the whole skill timeout",
      max(a.leg_timeouts) < 600.0)

# A healthy sweep is unaffected: every leg is reached in its expected time.
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
r = ex.execute("D", sk.SearchRegionCommand(
    min_x=10, min_y=10, max_x=50, max_y=50, altitude=-8.0,
    lane_spacing_m=8.0, speed_mps=4.0, tolerance_m=1.5, timeout_s=600.0))
check("a healthy sweep still succeeds", r.status is SkillStatus.SUCCESS)

# And the budget is for the whole skill: a timeout shorter than the sweep
# stops the sweep part-way instead of letting each leg run to it.
a, ex = fresh()
ex.execute("D", sk.TakeOffCommand())
t0 = a.now("D")
r = ex.execute("D", sk.SearchRegionCommand(
    min_x=10, min_y=10, max_x=50, max_y=50, altitude=-8.0,
    lane_spacing_m=8.0, speed_mps=4.0, tolerance_m=1.5, timeout_s=30.0))
check("a 30 s budget stops a ~70 s sweep part-way",
      r.status is not SkillStatus.SUCCESS)
check("and the whole skill stays within roughly its budget",
      a.now("D") - t0 <= 30.0 + 20.0)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
