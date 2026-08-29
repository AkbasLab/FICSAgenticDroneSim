"""Run one deterministic persistent agent on a single search task (Phase 5).

The agent is given only a task ("search sector S1 and report"), NOT a preflight
action list. It decides each skill itself, in a closed loop, and reacts to what
happens. Exit code 0 means it completed the task (searched, reported, returned,
landed).

    python scripts/run_persistent_agent.py
    python scripts/run_persistent_agent.py --sector S3
    python scripts/run_persistent_agent.py --airsim
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.objectives import SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--sector", default="S1", help="which sector to assign")
    ap.add_argument("--battery", type=float, default=None,
                    help="override battery budget (s) to see the low-battery reaction")
    ap.add_argument("--airsim", action="store_true")
    ap.add_argument("--log", action="store_true",
                    help="print the per-decision belief audit trail")
    ap.add_argument("--log-json", default=None,
                    help="write full belief snapshots to a JSON file")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)
    sector = next((s for s in scenario.sectors if s.sector_id == args.sector),
                  scenario.sectors[0])
    vehicle = scenario.vehicles[0]
    battery = args.battery if args.battery is not None else vehicle.battery_s

    if args.airsim:
        from agentic_uav.simulator import scenario_manager
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        adapter = AirSimVehicleAdapter()
        scenario_manager.spawn_missing_drones(adapter.client, 1)
    else:
        adapter = MockVehicleAdapter(ground_z=0.0)

    # Ground truth lives on the simulator side; the agent only gets a sensor.
    truth = GroundTruth(scenario)
    sensor = SensorModel(truth)

    task = SearchTask(task_id=f"search_{sector.sector_id}", sector=sector,
                      report_to=scenario.base.position)

    agent = PersistentAgent(vehicle_id=vehicle.vehicle_id, adapter=adapter,
                            home=vehicle.start, battery_total_s=battery,
                            cruise_altitude=sector.altitude, sensor=sensor,
                            roster=truth.roster(), sector_ids=truth.sector_ids())
    agent.belief.brief(scenario)
    report = agent.run(task)
    _print(report)
    if args.log:
        print("=== decision audit trail (what the agent knew / didn't know) ===\n")
        print(report.log.format_text())
        if args.log_json:
            report.log.to_json(args.log_json)
            print(f"(full belief snapshots written to {args.log_json})")
    return 0 if report.completed else 1


def _print(r):
    print(f"\n=== Persistent agent: {r.vehicle_id} / task {r.task_id} ===")
    print("decision trace (event -> objective):")
    for d in r.decisions:
        print(f"  {d}")
    print(f"\nsector searched : {r.sector_searched}")
    print(f"reported        : {r.reported}")
    print(f"detections      : {r.detections or 'none'}")
    print(f"returned home   : {r.returned_home}")
    print(f"landed          : {r.landed}")
    print(f"battery left     : {r.battery_frac_end:.0%}")
    print(f"steps           : {r.steps}")
    if r.completed:
        print("\nTASK COMPLETE (searched, reported, returned, landed)\n")
    elif r.aborted_safely:
        print("\nTASK ABORTED SAFELY (did not finish search, but landed safely)\n")
    else:
        print("\nTASK FAILED\n")


if __name__ == "__main__":
    sys.exit(main())
