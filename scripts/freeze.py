#!/usr/bin/env python3
"""The freeze (AUV-16 17.4): check the frozen files, or record a change as a new dated version.

    python scripts/freeze.py                               # check: exit 0 if the tree is its latest frozen version
    python scripts/freeze.py --note "what changed and why" # a new version: today's date, the note, the digests

The scope and the rule: agentic_uav/experiments/freeze.py. The record: configs/frozen.toml. tests/test_freeze.py
runs the check in every suite, and so in CI.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.freeze import FROZEN, add_version, check  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--note", help="record the tree as a new frozen version, with this note")
    parser.add_argument("--root", default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.note is not None:
        try:
            v = add_version(args.root, args.note)
        except ValueError as exc:
            print(f"not recorded: {exc}")
            return 1
        print(f"frozen version {v['number']}, {v['date']}: {len(v['files'])} files -> {FROZEN}")
        return 0
    problems = check(args.root)
    for p in problems:
        print(p)
    if not problems:
        print(f"the tree is its latest frozen version ({FROZEN})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
