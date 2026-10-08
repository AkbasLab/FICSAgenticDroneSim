"""Runs all 4 agents together, sharing target knowledge over messages.

    python scripts/run_team_mission.py              # mock, 4 agents
    python scripts/run_team_mission.py --messages    # print the message log
    python scripts/run_team_mission.py --beliefs     # print each agent's final team view
    python scripts/run_team_mission.py --blackout    # same mission, bus delivers nothing
    python scripts/run_team_mission.py --airsim      # fly it for real
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.experiments.team_runner import run_team_threaded
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--airsim", action="store_true")
    parser.add_argument("--blackout", action="store_true", help="bus delivers nothing - proves team belief updates only via real messages")
    parser.add_argument("--messages", action="store_true")
    parser.add_argument("--beliefs", action="store_true")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    if args.airsim:
        from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
        adapters = {d.name: AirSimVehicleAdapter(d.name) for d in scenario.drones}
    else:
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=15.0) for d in scenario.drones}

    bus = MessageBus(drop_all=args.blackout)
    reports, agents, bus = run_team_threaded(scenario, adapters, bus=bus)

    for name, report in reports.items():
        print(f"{name}: target_found={report.target_found} battery_frac={report.battery_frac_at_end:.2f}")

    if args.messages:
        print("\n--- message log ---")
        for entry in bus.log:
            print(f"[{entry.created_t:.1f}s] {entry.type} {entry.sender}->{entry.recipient}: "
                  f"{'delivered' if entry.delivered else 'DROPPED ('+entry.reason+')'}")

    if args.beliefs:
        print("\n--- final team belief per agent ---")
        for name, agent in agents.items():
            known = {tid: s.source for tid, s in agent.belief.mission.targets_known.items()}
            print(f"{name} (sector {agent.belief.mission.sector_id}): targets_known={known}")


if __name__ == "__main__":
    main()
