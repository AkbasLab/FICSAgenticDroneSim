"""Runs one Phase 5 persistent agent and prints its decision trace.

    python scripts/run_persistent_agent.py                  # Drone1, sector A
    python scripts/run_persistent_agent.py --sector D        # a different sector
    python scripts/run_persistent_agent.py --battery 8       # low-battery abort (mock: simulated seconds)
    python scripts/run_persistent_agent.py --airsim          # fly it (AirSim: real seconds)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.decision_log import DecisionLogger
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.core.scenario import load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--sector", default="A", choices=["A", "B", "C", "D"])
    parser.add_argument("--battery", type=float, default=None)
    parser.add_argument("--airsim", action="store_true")
    parser.add_argument("--log", action="store_true", help="print the KNEW/DID NOT KNOW/DECIDED trail")
    parser.add_argument("--log-json", default=None, help="also write the full trail to this file")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    spec = next(d for d in scenario.drones if d.sector == args.sector)
    battery_s = args.battery if args.battery is not None else spec.battery_s

    if args.airsim:
        from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
        adapter = AirSimVehicleAdapter(spec.name)
    else:
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)

    logger = DecisionLogger() if (args.log or args.log_json) else None
    agent = PersistentAgent(adapter, scenario, args.sector, spec.spawn_offset, battery_s,
                             logger=logger, drone_name=spec.name)
    report = agent.run()

    if args.log:
        logger.print_all()
        print()
    for line in report.trace:
        print(line)
    print(f"\ntarget_found: {report.target_found}")
    print(f"battery_frac_at_end: {report.battery_frac_at_end:.2f}")
    if args.log_json:
        logger.to_json(args.log_json)
        print(f"wrote {args.log_json}")


if __name__ == "__main__":
    main()
