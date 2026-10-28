"""One drone is switched off mid-mission - the team detects it and finishes
the work without it.

    python scripts/run_failure_recovery.py                    # kill Drone2 at t=15s (mock)
    python scripts/run_failure_recovery.py --kill Drone3 --at 40
    python scripts/run_failure_recovery.py --airsim
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.coordination.message_bus import MessageBus
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.experiment_config import DEFAULT_SCENARIO, ExperimentConfig
from fics_drone.experiments.experiment_runner import recovery_summary, run_experiment
from fics_drone.experiments.team_runner import run_team_with_faults


def print_report(summary):
    """The same console report this script has always printed."""
    print("\n--- allocation result ---")
    for name, sector_id in summary["assignment"].items():
        print(f"{name}: {sector_id}")

    print("\n--- results ---")
    for name, d in summary["drones"].items():
        killed = " (KILLED)" if d["killed"] else ""
        print(f"{name}{killed}: target_found={d['target_found']} "
              f"battery_frac={d['battery_frac_at_end']:.2f}")

    print(f"\nsectors completed: {summary['sectors_completed']}/{summary['sectors_total']} "
          f"{summary['completed_sector_ids']}")


def run_on_airsim(args):
    """Real AirSim: direct adapters, so the runner does not record this path
    (it cannot be exercised off the sim machine)."""
    from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
    scenario = load_scenario(args.scenario)
    adapters = {d.name: AirSimVehicleAdapter(d.name) for d in scenario.drones}
    kill = (args.kill, args.at)
    reports, agents, _bus, assignment = run_team_with_faults(
        scenario, adapters, bus=MessageBus(), kill_name=kill[0], kill_at_s=kill[1])
    print_report(recovery_summary(scenario, agents, reports, assignment, kill))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--airsim", action="store_true")
    parser.add_argument("--kill", default="Drone2")
    parser.add_argument("--at", type=float, default=15.0,
                        help="elapsed seconds into the mission to kill --kill")
    parser.add_argument("--out-root", default=None,
                        help="where the experiment folder goes (default runs/experiments)")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M%S"),
                        help="suffix that keeps experiment ids unique")
    args = parser.parse_args()

    print(f"!! {args.kill} will be switched off at t={args.at}s (teammates not informed)")
    if args.airsim:
        run_on_airsim(args)
        return

    cfg = ExperimentConfig(f"recovery_{args.kill}_at{args.at:g}_{args.tag}",
                           zone_profile="static", scenario=args.scenario, repeats=1,
                           kill_vehicle=args.kill, kill_at_s=args.at)
    kwargs = {"out_root": args.out_root} if args.out_root else {}
    result = run_experiment(cfg, **kwargs)
    if result.error:
        sys.exit(f"experiment failed:\n{result.error}")
    print_report(result.runs[0]["recovery"])
    print(f"\nrecorded in {result.directory}")


if __name__ == "__main__":
    main()
