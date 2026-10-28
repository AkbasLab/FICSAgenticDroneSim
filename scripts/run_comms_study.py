"""Phase 10: replays the same allocation mission under each named network
condition and prints delivery stats, so "the agentic version holds up under
severe comms" means something checkable, not just claimed.

    python scripts/run_comms_study.py                  # all conditions
    python scripts/run_comms_study.py --condition severe
    python scripts/run_comms_study.py --seed 42         # a different draw
    python scripts/run_comms_study.py --estimates       # agents' own view of link quality
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.coordination.comms_conditions import ORDER
from fics_drone.experiments.experiment_config import DEFAULT_SCENARIO, ExperimentConfig
from fics_drone.experiments.experiment_runner import run_experiment

MOCK_SPEED_MPS = 25.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--condition", choices=ORDER, default=None, help="default: run all")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--estimates", action="store_true")
    parser.add_argument("--out-root", default=None,
                        help="where experiment folders go (default runs/experiments)")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d_%H%M%S"),
                        help="suffix that keeps experiment ids unique")
    args = parser.parse_args()

    conditions = [args.condition] if args.condition else ORDER
    kwargs = {"out_root": args.out_root} if args.out_root else {}

    print(f"{'condition':<12}{'sectors':<9}{'sent':<7}{'deliv':<7}{'rate':<7}{'delay':<9}drops")
    for name in conditions:
        cfg = ExperimentConfig(f"comms_{name}_s{args.seed}_{args.tag}", zone_profile="static",
                               scenario=args.scenario, repeats=1,
                               mock_speed_mps=MOCK_SPEED_MPS, seed=args.seed,
                               network_profile=name, comms_estimates=args.estimates)
        result = run_experiment(cfg, **kwargs)
        if result.error:
            sys.exit(f"{name}: experiment failed:\n{result.error}")
        c = result.runs[0]["comms"]
        drops_str = ", ".join(f"{k}={v}" for k, v in c["drops"].items()) or "none"
        sectors = f"{c['sectors_done']}/{c['sectors_total']}"
        rate = f"{c['delivery_rate_pct']:.0f}%"
        delay = f"{c['mean_delay_s']:.2f}s"
        print(f"{name:<12}{sectors:<9}{c['sent']:<7}{c['delivered']:<7}"
              f"{rate:<7}{delay:<9}{drops_str}")
        for agent_name, peers in c.get("loss_estimates", {}).items():
            for peer, loss in peers.items():
                print(f"    {agent_name} estimates {peer}: loss={loss:.2f}")


if __name__ == "__main__":
    main()
