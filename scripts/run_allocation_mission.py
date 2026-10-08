"""4 drones divide the sectors themselves, no central assignment.

    python scripts/run_allocation_mission.py           # mock
    python scripts/run_allocation_mission.py --bids     # every bid, explained
    python scripts/run_allocation_mission.py --airsim   # fly it for real
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.experiments.team_runner import run_team_with_allocation
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--airsim", action="store_true")
    parser.add_argument("--bids", action="store_true", help="print every bid this run saw")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    if args.airsim:
        from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
        adapters = {d.name: AirSimVehicleAdapter(d.name) for d in scenario.drones}
    else:
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=15.0) for d in scenario.drones}

    bus = MessageBus()
    reports, agents, bus, assignment = run_team_with_allocation(scenario, adapters, bus=bus)

    print("--- allocation result ---")
    for name, sector_id in assignment.items():
        print(f"{name}: {sector_id if sector_id else '(won nothing)'}")

    assigned_sectors = [s for s in assignment.values() if s is not None]
    print(f"\nconverged: {len(set(assigned_sectors)) == len(scenario.sectors) == len(assigned_sectors)} "
          f"({len(set(assigned_sectors))}/{len(scenario.sectors)} sectors, each claimed once)")

    print("\n--- mission results ---")
    for name, report in reports.items():
        print(f"{name}: target_found={report.target_found} battery_frac={report.battery_frac_at_end:.2f}")

    if args.bids:
        print("\n--- bids seen (sender's own view) ---")
        for entry in bus.log:
            if entry.type == "task_bid":
                print(f"[{entry.created_t:.1f}s] {entry.sender} -> {entry.recipient}")


if __name__ == "__main__":
    main()
