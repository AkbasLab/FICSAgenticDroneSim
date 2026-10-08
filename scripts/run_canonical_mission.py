"""Runs the Phase 4 canonical mission and scores it.

    python scripts/run_canonical_mission.py           # mock (kinematic), scored
    python scripts/run_canonical_mission.py --airsim  # fly it for real in CarlaAir
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.evaluation.metrics import score_run
from fics_drone.experiments.mission_runner import run_scripted_mission
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter
from fics_drone.telemetry.recorder import TelemetryRecorder

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def build_adapters(scenario, airsim: bool):
    if airsim:
        from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
        return {d.name: AirSimVehicleAdapter(d.name) for d in scenario.drones}
    return {d.name: KinematicMockVehicleAdapter(d.name) for d in scenario.drones}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--airsim", action="store_true")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    adapters = build_adapters(scenario, args.airsim)

    offsets = {d.name: d.spawn_offset for d in scenario.drones}
    recorder = TelemetryRecorder(adapters, world_offsets=offsets)
    recorder.start()
    import time
    start = time.monotonic()
    run_scripted_mission(scenario, adapters)
    elapsed = time.monotonic() - start
    recorder.stop()

    report = score_run(scenario, recorder.log, elapsed)
    print(f"Coverage: {report.coverage_fraction:.1%} ({'PASS' if report.coverage_pass else 'FAIL'})")
    print(f"Targets found: {report.targets_found} ({'PASS' if report.targets_pass else 'FAIL'})")
    print(f"No-fly violations: {report.no_fly_violations or 'none'} "
          f"({'PASS' if report.no_fly_pass else 'FAIL'})")
    print(f"Separation violations: {report.separation_violations or 'none'} "
          f"({'PASS' if report.separation_pass else 'FAIL'})")
    print(f"Battery: {report.battery_violations or 'within budget'} "
          f"({'PASS' if report.battery_pass else 'FAIL'})")
    print(f"Deadline: {report.deadline_s:.1f}s / {scenario.deadline_s}s "
          f"({'PASS' if report.deadline_pass else 'FAIL'})")
    print(f"All home: {report.all_home} ({'PASS' if report.all_home_pass else 'FAIL'})")
    print(f"\nOVERALL: {'PASS' if report.overall_pass else 'FAIL'}")


if __name__ == "__main__":
    main()
