"""GMB study: what does the guardian do when no-fly zones change during a mission?

    python scripts/run_dynamic_zone_study.py                   # 3 repeats per condition, mock
    python scripts/run_dynamic_zone_study.py --repeats 5 --save runs/dynamic_zone_mock

Four agents, deterministic policy, kinematic mock (nothing flies). Conditions differ ONLY in the
scenario's no-fly zones. Metrics were fixed before this was run (see
projects/akbas-lab/GMB_DYNAMIC_BOUNDARIES.md, decision 4):

  per run   guardian: commands evaluated, interventions, intervention rate, by outcome,
                      failed checks, steer-outs (exit_zone)
            mission:  coverage, targets found, no-fly violations, separation violations,
                      mission seconds, all home

This is a MOCK, DETERMINISTIC-POLICY pilot, so the numbers say what the guardian does, not what an
LLM policy does. Mission time is real wall-clock time (the mock moves in real time), so zone
timings are approximate and runs vary slightly.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.experiments.experiment_config import (DEFAULT_SCENARIO, ZONE_MONITORS,
                                                      ZONE_PROFILES, ExperimentConfig, apply_zones)
from fics_drone.experiments.experiment_runner import run_experiment

MOCK_SPEED_MPS = 15.0
MODES = ("cmd = guardian acts at command boundaries only; "
         "tick = per-control-tick zone monitor")


def condition_pairs(only=None):
    """(zone profile, monitor) pairs; the static control runs under cmd only."""
    for name in ZONE_PROFILES:
        if only and name != only:
            continue
        for monitor in (("cmd",) if name == "static" else ZONE_MONITORS):
            yield name, monitor


def conditions(base, appear_s=5.0, expire_s=12.0, drift_s=3.0):
    """name -> scenario. run_dynamic_zone_llm.py imports this, so keep its signature."""
    return {name: apply_zones(base, name, appear_s, expire_s, drift_s)
            for name in ZONE_PROFILES}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", default=None, help="run one condition by name")
    parser.add_argument("--save", default=None, help="directory to write results.json into")
    parser.add_argument("--out-root", default=None,
                        help="where experiment folders go (default runs/experiments)")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M%S"),
                        help="suffix that keeps experiment ids unique")
    args = parser.parse_args()

    kwargs = {"out_root": args.out_root} if args.out_root else {}
    results = {}
    for name, monitor in condition_pairs(args.only):
        label = f"{name}/{monitor}"
        cfg = ExperimentConfig(f"zone_{name}_{monitor}_{args.tag}", zone_profile=name,
                               zone_monitor=monitor, scenario=args.scenario,
                               repeats=args.repeats, mock_speed_mps=MOCK_SPEED_MPS)
        result = run_experiment(cfg, **kwargs)
        for i, r in enumerate(result.runs):
            g, m = r["guardian"], r["mission"]
            print(f"{label:18} run {i + 1}: cmds {g['commands']:3} "
                  f"interventions {g['interventions']:2} "
                  f"steer-outs {g['steer_outs']} ({g['steer_out_distance_m']} m) "
                  f"interrupts {g['zone_interrupts']} | "
                  f"exposure {m['zone_exposure_s']}s | coverage {m['coverage']:.0%} "
                  f"targets {len(m['targets_found'])} "
                  f"{m['mission_s']}s home={m['all_home']}")
        if result.error:
            print(f"{label}: FAILED\n{result.error}")
        results[label] = result.runs

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"repeats": args.repeats, "policy": "deterministic",
                       "modes": MODES, "mock_speed_mps": MOCK_SPEED_MPS,
                       "results": results}, f, indent=2)
        print(f"\nsaved to {args.save}/results.json")


if __name__ == "__main__":
    main()
