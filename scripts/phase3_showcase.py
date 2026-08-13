"""Exercise every Phase 3 skill once and print its structured result.

A quick way to see the whole skill vocabulary in action. Deterministic on the
mock (no simulator needed):

    python scripts/phase3_showcase.py

Add --adapter airsim to run the same showcase on one real drone in the sim.
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
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    return AirSimVehicleAdapter()


def show(executor, vid, label, command):
    r = executor.execute(vid, command)
    pos = r.final_position
    where = f"({pos.x:.0f},{pos.y:.0f},{pos.z:.0f})" if pos else "-"
    print(f"  {label:16} -> {r.status.value:8} {r.duration_s:6.1f}s  end={where}"
          + (f"  error={r.error_code}" if r.error_code else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="mock")
    args = ap.parse_args()
    ex = SkillExecutor(make_adapter(args.adapter))
    vid = "Drone1"

    if args.adapter == "airsim":
        from agentic_uav.simulator import scenario_manager
        scenario_manager.spawn_missing_drones(ex.adapter.client, 1)

    print(f"Phase 3 skill showcase ({args.adapter})\n")

    show(ex, vid, "TAKE_OFF", sk.TakeOffCommand())
    show(ex, vid, "GO_TO_WAYPOINT", sk.GoToWaypointCommand(waypoint=Position3D(20, 0, -8)))
    show(ex, vid, "FOLLOW_WAYPOINTS", sk.FollowWaypointsCommand(
        waypoints=[Position3D(20, 10, -8), Position3D(10, 10, -8), Position3D(10, 0, -8)]))
    show(ex, vid, "SET_ALTITUDE(up)", sk.GoToWaypointCommand(waypoint=Position3D(10, 0, -15)))
    show(ex, vid, "SEARCH_REGION", sk.SearchRegionCommand(
        min_x=0, min_y=0, max_x=30, max_y=20, lane_spacing_m=10))
    show(ex, vid, "INSPECT_POINT", sk.InspectPointCommand(point=Position3D(5, 5, -8), dwell_s=2))
    show(ex, vid, "RENDEZVOUS", sk.RendezvousCommand(point=Position3D(0, 0, -8)))
    show(ex, vid, "ACT_AS_RELAY", sk.ActAsRelayCommand(position=Position3D(15, 15, -8), duration_s=5))
    show(ex, vid, "HOLD_POSITION", sk.HoldPositionCommand(duration_s=4))
    show(ex, vid, "EMERGENCY_HOLD", sk.EmergencyHoldCommand())
    show(ex, vid, "RETURN_HOME", sk.ReturnHomeCommand())
    show(ex, vid, "LAND", sk.LandCommand())

    print("\n--- a deliberate timeout (unreachable waypoint in the time budget) ---")
    show(ex, "Drone2", "TAKE_OFF", sk.TakeOffCommand())
    show(ex, "Drone2", "GO_TO_WAYPOINT", sk.GoToWaypointCommand(
        waypoint=Position3D(5000, 0, -8), speed_mps=4.0, timeout_s=5.0))


if __name__ == "__main__":
    main()
