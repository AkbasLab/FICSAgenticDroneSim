#!/usr/bin/env python3
"""Run a batch of experiment configurations, unattended, one result directory per run (Phase 14).

    python scripts/run_batch.py phase14_exit                     # configs/experiments/phase14_exit.toml
    python scripts/run_batch.py my_batch.toml --jobs 10          # runs side by side, the same directories
    python scripts/run_batch.py phase14_exit --resume runs/experiments/phase14-exit-20261106-120000
    python scripts/run_batch.py pilot --ollama-host http://127.0.0.1:11435     # runs whose model is on a server

A batch file lists experiments: architecture, scenario, team size, network, failure, seed and planner, each a value
or a list (`agentic_uav/experiments/experiment.py`). Every combination is one run; the file is read strictly and
refused whole before anything flies. Output, under runs/experiments/ by default (not tracked by git):

    <batch_id>-<stamp>/batch.json      the batch, its source and the code
    <batch_id>-<stamp>/<run_id>/       manifest.json, report.json, events.jsonl.gz, records.json.gz
    <batch_id>-<stamp>/index.jsonl     one row per run; summary.md the same as a table

Nothing asks a question. A crashed run is recorded as crashed, with its traceback, and the batch goes on.
Exit code: 0 if every run completed (met or not), 1 if any crashed or is unfinished, 2 if the batch was refused.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.batch import DEFAULT_ROOT, read_index, run_batch  # noqa: E402
from agentic_uav.experiments.experiment import load_batch  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="a configs/experiments name, or a path to a batch .toml")
    parser.add_argument("--jobs", type=int, default=1, help="runs flown at once, each in its own process")
    parser.add_argument("--out", default=DEFAULT_ROOT, help="where the batch directory is made")
    parser.add_argument("--resume", metavar="DIR", help="finish this batch directory: complete runs are kept")
    parser.add_argument("--ollama-host", default=None, help="the model server, for runs whose planner is llm:<name>")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        batch = load_batch(args.batch)
    except (OSError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2
    print(f"batch {batch.batch_id}: {len(batch.runs)} runs" + (f", {args.jobs} at once" if args.jobs > 1 else ""))
    try:
        out = run_batch(batch, args.out, jobs=args.jobs, resume=args.resume, endpoint=args.ollama_host,
                        progress=lambda line: print(line, flush=True))
    except RuntimeError as exc:
        print(f"refused: {exc}")
        return 2
    rows = read_index(out)
    bad = [r for r in rows if r["status"] != "completed"]
    print(f"{len(rows)} runs, {len(rows) - len(bad)} completed, {len(bad)} crashed or unfinished")
    print(f"batch   : {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
