"""GMB study: the same four-drone missions flown with straight legs and with NavRL flying the legs.

    python scripts/run_navrl_study.py --repeats 3 --save runs/navrl_study       (in the NavRL conda env: needs torch)

Both arms are the real mission stack on the kinematic mock (guardian per leg, per-tick zone monitor, steer-out, confirm
flow, four drones, deterministic search policy). They differ ONLY in how an approved leg is flown:
  straight  one move command per leg (the stack as it was)
  navrl     NavRL's pretrained policy, one velocity per 0.1 s tick, shown the zones that are on as lidar-style rays

NavRL flies about 1.9 m/s, so both arms fly at that speed (the mock's usual 15 m/s would make "straight" look faster
for a reason that has nothing to do with the planner). Zone times and drift speed are stretched by k = 15 / speed so a
zone still appears at the same point of the flight as in the 15 m/s studies; exposure and mission times are in the
stretched time, and the table also gives them divided by k ("mock-equivalent seconds").

Not in this study: NavRL alone with no guardian (the stack's guardian is always on; that arm is in the 2D harness,
navrl_arms.py), a model in the policy slot, real flight.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.experiments.experiment_config import DEFAULT_SCENARIO, ZONE_PROFILES, ExperimentConfig
from fics_drone.experiments.experiment_runner import run_experiment

ARMS = ("straight", "navrl")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--speed", type=float, default=1.9, help="mock speed for both arms, m/s (NavRL's free speed)")
    parser.add_argument("--leg-timeout", type=float, default=120.0)
    parser.add_argument("--only", default=None, help="one zone profile")
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--save", default=None)
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()
    k = 15.0 / args.speed
    kwargs = {"out_root": args.out_root} if args.out_root else {}
    results = {}
    for profile in ZONE_PROFILES:
        if args.only and profile != args.only:
            continue
        for arm in args.arms.split(","):
            cfg = ExperimentConfig(
                f"navrl_{profile}_{arm}_{args.tag}", zone_profile=profile, zone_monitor="tick", scenario=args.scenario,
                repeats=args.repeats, mock_speed_mps=args.speed, appear_s=5.0 * k, expire_s=12.0 * k, drift_s=3.0 * k,
                zone_speed_scale=1.0 / k, leg_planner=arm, leg_timeout_s=args.leg_timeout,
                notes=f"navrl study, k={k:.2f}; both arms at {args.speed} m/s")
            result = run_experiment(cfg, **kwargs)
            results[f"{profile}/{arm}"] = {"runs": result.runs, "error": result.error}
            if result.error:
                print(f"{profile}/{arm}: ERROR\n{result.error}", flush=True)
            for i, r in enumerate(result.runs):
                g, m = r["guardian"], r["mission"]
                print(f"{profile:14}{arm:9} run {i + 1}: cmds {g['commands']:3} interventions {g['interventions']:2} "
                      f"steer-outs {g['steer_outs']} interrupts {g['zone_interrupts']} | exposure {m['zone_exposure_s']}s "
                      f"({m['zone_exposure_s'] / k:.2f}s mock-eq) | coverage {m['coverage']:.0%} "
                      f"targets {len(m['targets_found'])} {m['mission_s']}s ({m['mission_s'] / k:.1f}s mock-eq) "
                      f"home={m['all_home']}", flush=True)
    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"k": k, "speed": args.speed, "results": results}, f, indent=1, default=str)
        print("saved", args.save)


if __name__ == "__main__":
    main()
