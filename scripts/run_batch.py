"""Run a list of experiment configurations unattended (Phase 14 exit criterion).

    python scripts/run_batch.py configs/experiments/exp_0042.yaml
    python scripts/run_batch.py configs/experiments/              # a directory
    python scripts/run_batch.py configs/experiments/sweep_architectures.yaml \\
        --out results/sweep1 --repeat 5

No prompts, no interactive choices: a batch is meant to be started and left.
Each configuration produces one complete result directory, and a configuration
that crashes still produces one - with its manifest, the events up to the
failure, and the traceback - because a failed agentic run is usually the most
informative one in the batch.

The process exits 0 when every run completed and 1 when any did not, so a batch
can be used in a script without parsing its output.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.experiment_config import ExperimentConfig
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment


def expand(configs, repeat, seed_stride=1):
    """`--repeat n` turns one config into n, varying only the seed.

    The experiment_id gets the seed appended so the directories do not collide
    and a result can always be traced back to the seed that produced it.
    """
    if repeat <= 1:
        return list(configs)
    out = []
    for cfg in configs:
        for i in range(repeat):
            seed = cfg.random_seed + i * seed_stride
            d = cfg.as_dict()
            d["random_seed"] = seed
            d["experiment_id"] = f"{cfg.experiment_id}_s{seed}"
            clone = ExperimentConfig.from_dict(d)
            clone._source_path = getattr(cfg, "_source_path", None)  # noqa: SLF001
            out.append(clone)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="+",
                    help="YAML files, a list file, or a directory")
    ap.add_argument("--out", default="results", help="result root directory")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run each configuration this many times, varying the seed")
    ap.add_argument("--seed-stride", type=int, default=1)
    ap.add_argument("--keep-going", action="store_true", default=True,
                    help="continue after a failed run (default)")
    ap.add_argument("--stop-on-error", dest="keep_going", action="store_false")
    args = ap.parse_args()

    configs = []
    for path in args.configs:
        configs.extend(ExperimentConfig.load_many(path))
    configs = expand(configs, args.repeat, args.seed_stride)

    if not configs:
        print("no configurations found")
        return 1

    print(f"{len(configs)} run(s) -> {args.out}\n")
    started = time.monotonic()
    results, failures = [], []

    for i, cfg in enumerate(configs, 1):
        print(f"[{i}/{len(configs)}] {cfg.experiment_id} "
              f"({cfg.architecture_key}, {cfg.network_profile}, "
              f"seed {cfg.random_seed})", flush=True)
        outcome = run_experiment(cfg, out_root=args.out, root=ROOT)
        results.append(outcome)
        print(f"        {outcome.summary()}", flush=True)
        for w in outcome.manifest.warnings:
            print(f"        warning: {w}", flush=True)
        if not outcome.ok:
            failures.append(outcome)
            if not args.keep_going:
                print("\nstopping after the first failure (--stop-on-error)")
                break

    _write_index(args.out, results, time.monotonic() - started)

    print(f"\n{len(results) - len(failures)}/{len(results)} completed "
          f"in {time.monotonic() - started:.1f}s")
    if failures:
        # Reported, not hidden: these directories are the ones worth opening.
        print(f"\n{len(failures)} failed run(s), preserved for inspection:")
        for f in failures:
            print(f"  {f.directory}  "
                  f"{f.manifest.error_type}: "
                  f"{(f.manifest.error_message or '')[:70]}")
    return 1 if failures else 0


def _write_index(out_root, results, elapsed_s):
    """One table of every run in the batch, for analysis and for finding runs."""
    os.makedirs(out_root, exist_ok=True)
    rows = []
    for r in results:
        row = {"experiment_id": r.config.experiment_id,
               "architecture": r.config.architecture_key,
               "scenario": r.config.scenario,
               "network_profile": r.config.network_profile,
               "failure_profile": r.config.failure_profile,
               "seed": r.config.random_seed,
               "planner": r.config.planner,
               "status": r.manifest.status,
               "completed": r.manifest.completed,
               "wall_clock_s": r.manifest.wall_clock_s,
               "git_sha": r.manifest.git_sha,
               "directory": r.directory,
               "error_type": r.manifest.error_type}
        if r.result is not None:
            row.update({k: v for k, v in r.result.as_row().items()
                        if k not in row})
        rows.append(row)

    with open(os.path.join(out_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"runs": len(rows), "elapsed_s": round(elapsed_s, 1),
                   "rows": rows}, f, indent=1, default=str)

    if rows:
        import csv
        fields = sorted({k for row in rows for k in row})
        with open(os.path.join(out_root, "index.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
