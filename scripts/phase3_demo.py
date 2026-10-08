"""Phase 3 exit criterion: N drones take off, fly to distinct waypoints, hold,
return home and land - concurrently, every skill reporting SUCCESS.

Usage:
    python -m scripts.phase3_demo                            # 4 drones, mock adapter
    python -m scripts.phase3_demo --drones 2 --adapter airsim
    python -m scripts.phase3_demo --names Drone1,Drone2 --adapter airsim
"""

import argparse
import math
import sys
import threading

from fics_drone.control import skills
from fics_drone.control.navigation import DEFAULT_HEIGHT
from fics_drone.core.skill_result import SkillStatus
from fics_drone.simulator.mock_adapter import MockVehicleAdapter

WAYPOINT_RADIUS = 10.0
HOLD_SECS = 2.0


def waypoint_for(index, total):
    angle = 2 * math.pi * index / total
    return (WAYPOINT_RADIUS * math.cos(angle), WAYPOINT_RADIUS * math.sin(angle), DEFAULT_HEIGHT)


def make_adapter(kind, name):
    if kind == "mock":
        return MockVehicleAdapter(name)
    from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
    return AirSimVehicleAdapter(name)


def run_one_drone(adapter, waypoint, out):
    out.append(("take_off", skills.take_off(adapter)))
    out.append(("go_to_waypoint", skills.go_to_waypoint(adapter, *waypoint)))
    out.append(("hold_position", skills.hold_position(adapter, HOLD_SECS)))
    out.append(("return_home", skills.return_home(adapter)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drones", type=int, default=4)
    parser.add_argument("--adapter", choices=["mock", "airsim"], default="mock")
    parser.add_argument("--names", type=str, default=None,
                         help="comma-separated vehicle names (must match settings.json "
                              "for --adapter airsim); overrides --drones count")
    args = parser.parse_args()

    names = args.names.split(",") if args.names else [f"Drone{i + 1}" for i in range(args.drones)]
    adapters = {n: make_adapter(args.adapter, n) for n in names}
    waypoints = {n: waypoint_for(i, len(names)) for i, n in enumerate(names)}
    results = {n: [] for n in names}

    threads = [threading.Thread(target=run_one_drone, args=(adapters[n], waypoints[n], results[n]))
               for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_ok = True
    for name in names:
        print(f"\n{name}:")
        for step_name, r in results[name]:
            ok = r.status == SkillStatus.SUCCESS
            all_ok = all_ok and ok
            detail = f" error={r.error}" if r.error else ""
            print(f"  {step_name:16s} {r.status.value:8s} pos={r.final_position} "
                  f"elapsed={r.elapsed_s:.1f}s{detail}")

    print(f"\n{'ALL DRONES SUCCEEDED' if all_ok else 'SOME STEPS FAILED'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
