"""Phase 3 exit criterion: four drones take off, go to distinct waypoints, hold,
return home, and land - each skill returning a STRUCTURED result (not a print).

Deterministic on the mock adapter (no simulator needed):
    python scripts/phase3_demo.py

Fly it for real in AirSim (simulator running, drones spawned):
    python scripts/phase3_demo.py --adapter airsim
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.control import skills as sk
from agentic_uav.control.skill_executor import SkillExecutor
from agentic_uav.core.models import Position3D


def make_adapter(name):
    if name == "mock":
        from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
        return MockVehicleAdapter()
    if name == "airsim":
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        return AirSimVehicleAdapter()
    raise ValueError("adapter must be 'mock' or 'airsim'")


# four distinct waypoints (a rough square around the origin, at cruise altitude)
WAYPOINTS = {
    "Drone1": Position3D(20.0, 0.0, -8.0),
    "Drone2": Position3D(0.0, 20.0, -8.0),
    "Drone3": Position3D(-20.0, 0.0, -8.0),
    "Drone4": Position3D(0.0, -20.0, -8.0),
}


def run_one(executor, vid, waypoint):
    """Take off -> go to waypoint -> hold -> return home -> land."""
    plan = [
        ("TAKE_OFF", sk.TakeOffCommand()),
        ("GO_TO_WAYPOINT", sk.GoToWaypointCommand(waypoint=waypoint)),
        ("HOLD_POSITION", sk.HoldPositionCommand(duration_s=3.0)),
        ("RETURN_HOME", sk.ReturnHomeCommand()),
        ("LAND", sk.LandCommand()),
    ]
    results = []
    for name, command in plan:
        r = executor.execute(vid, command)
        results.append((name, r))
        print(f"  [{vid}] {name:16} -> {r.status.value:8} "
              f"({r.duration_s:.1f}s)"
              + (f"  error={r.error_code}" if r.error_code else ""))
        if r.status.value not in ("success",):
            break
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="mock", help="mock | airsim")
    args = ap.parse_args()

    adapter = make_adapter(args.adapter)
    executor = SkillExecutor(adapter)

    if args.adapter == "airsim":
        from agentic_uav.simulator import scenario_manager
        scenario_manager.spawn_missing_drones(adapter.client, len(WAYPOINTS))

    print(f"Phase 3 demo - {len(WAYPOINTS)} drones ({args.adapter} adapter)\n")

    all_results = {}
    # mock is deterministic; run sequentially so the output is readable. On
    # airsim you'd thread these (each drone has its own client).
    for vid, wp in WAYPOINTS.items():
        print(f"{vid}: take off -> {(wp.x, wp.y, wp.z)} -> hold -> home -> land")
        all_results[vid] = run_one(executor, vid, wp)
        print()

    # exit-criterion check: every skill of every drone succeeded
    ok = all(r.status.value == "success"
             for results in all_results.values() for _n, r in results)
    print("EXIT CRITERION:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
