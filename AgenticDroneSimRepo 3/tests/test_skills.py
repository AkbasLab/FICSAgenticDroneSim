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

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
