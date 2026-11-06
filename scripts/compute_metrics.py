#!/usr/bin/env python3
"""Score a batch directory with the pre-registered metrics (Phase 15, docs/METRICS.md).

    python scripts/compute_metrics.py runs/experiments/phase14-exit-20261106-120000

Every run of the batch is scored from its own directory -- P1 to P6, coordination efficiency and the 15
diagnostics -- and P3 is paired with each degraded run's nominal twin in the batch. A metric a run cannot have
is recorded as absent, with its kind (not available, not applicable, undefined, not recorded) and why; never 0.
Every result carries docs/METRICS.md's version and SHA-256. Written into the batch directory:

    <run_id>/metrics.json     the run's metrics
    metrics.jsonl             one row per run
    metrics.md                a table of the main ones

Refused (exit code 2) if the implementation and docs/METRICS.md disagree.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.metrics import batch_metrics, check_registry, write_metrics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch_dir")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    problems = check_registry()
    if problems:
        print("refused: the implementation and docs/METRICS.md disagree: " + "; ".join(problems))
        return 2
    rows = batch_metrics(args.batch_dir)
    write_metrics(args.batch_dir, rows)
    print(f"{len(rows)} runs scored with docs/METRICS.md version {rows[0]['metrics_version'] if rows else '?'}")
    print(f"metrics : {os.path.join(args.batch_dir, 'metrics.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
