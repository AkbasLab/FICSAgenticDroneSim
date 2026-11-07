#!/usr/bin/env python3
"""One run's timeline as a page, or every run's in a batch (Phase 17, AUV-16 17.2).

    python scripts/timeline.py runs/experiments/<batch>/<run_id>     # writes <run_id>/timeline.html
    python scripts/timeline.py runs/experiments/<batch>              # every run of the batch

Per drone: task, role, skills, communication outages, model decisions, guardian interventions, marks; for the
team: messages over time, partitions, reallocations, mission progress. From the run's directory alone.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.timeline import write_timeline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="a run directory, or a batch directory")
    args = parser.parse_args(argv)
    if os.path.isfile(os.path.join(args.path, "manifest.json")):
        runs = [args.path]
    else:
        runs = sorted(os.path.join(args.path, d) for d in os.listdir(args.path)
                      if os.path.isfile(os.path.join(args.path, d, "events.jsonl.gz")))
    for r in runs:
        print(write_timeline(r))
    return 0 if runs else 1


if __name__ == "__main__":
    sys.exit(main())
