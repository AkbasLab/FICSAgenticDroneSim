"""Run the canonical search-and-relay mission with the scripted controller.

This is the Phase 4 exit criterion in runnable form: load the canonical
scenario, fly the fixed non-agentic script on the deterministic mock simulator
(or AirSim with --airsim), and print the evaluated mission report. Exit code 0
means the mission met every success criterion.

    python scripts/run_canonical_mission.py
    python scripts/run_canonical_mission.py --airsim
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.mission_runner import run_scripted_mission
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--airsim", action="store_true",
                    help="fly on AirSim instead of the mock simulator")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)

    if args.airsim:
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        adapter = AirSimVehicleAdapter()
    else:
        adapter = MockVehicleAdapter(ground_z=0.0)

    report = run_scripted_mission(scenario, adapter)
    _print_report(scenario, report)
    return 0 if report.success else 1


def _print_report(scenario, report):
    print(f"\n=== Canonical mission: {scenario.scenario_id} ===")
    print(f"assignment / skills: {report.detail}")
    print(f"coverage: {report.coverage:.1%} "
          f"(required {scenario.mission.required_coverage:.0%})")
    print(f"sectors searched: {report.sectors_searched}")
    print("detections:")
    for d in report.detections:
        flag = "reported" if d.reported else "NOT reported"
        print(f"  {d.target_id} by {d.by_vehicle} at t={d.at_time_s:.1f}s ({flag})")
    print("\ncriteria:")
    for name, ok in report.criteria.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\nMISSION {'SUCCESS' if report.success else 'FAILED'}\n")


if __name__ == "__main__":
    sys.exit(main())
