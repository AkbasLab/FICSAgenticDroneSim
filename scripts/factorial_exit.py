#!/usr/bin/env python3
"""Phase 18's exit: every cell has its valid paired replications, by docs/EXCLUSIONS.md only.

    python scripts/factorial_exit.py <batch dir> [<batch dir> ...]                 # the held-out design
    python scripts/factorial_exit.py <dirs> --replacements phase18_reserve_1       # + batch files for the reserves
    python scripts/factorial_exit.py <dirs> --dry --seeds 1,2 --reserve 3,4 --required 2   # a dry run's design

The checks: agentic_uav/experiments/factorial_exit.py. Writes factorial-exit-<stamp>[-<block>].json/.md under
phases/phase-18-main-factorial/results/ (or --out). Exit code 0 only if every check passed.
`--dry` is for D answered by the echo: no model server, so X3, X5, variability and requests do not apply.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments import factorial_exit as F  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-18-main-factorial", "results")


def ints(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.split(",") if x.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("batch_dirs", nargs="+")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", default="")
    parser.add_argument("--replacements", help="write batch files for the reserve runs still needed, with this stem")
    parser.add_argument("--dry", action="store_true", help="D by the echo: no model server")
    parser.add_argument("--seeds", type=ints, help="the test seeds (default: configs/seeds/heldout.toml)")
    parser.add_argument("--reserve", type=ints, help="the reserve seeds (default: configs/seeds/heldout.toml)")
    parser.add_argument("--required", type=int, help=f"valid paired seeds a cell needs (default {F.REQUIRED})")
    args = parser.parse_args(argv)

    d = F.design(REPO)
    d = dataclasses.replace(d, test=args.seeds or d.test, reserve=args.reserve or d.reserve,
                            required=args.required or d.required, live_model=not args.dry)
    result = F.run_checks(F.load_runs(args.batch_dirs), d, REPO)
    result["batch_dirs"] = [os.path.basename(os.path.normpath(b)) for b in args.batch_dirs]
    result["dry"] = args.dry
    os.makedirs(args.out, exist_ok=True)
    stem = os.path.join(args.out, f"factorial-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else ""))
    with open(stem + ".json", "w", encoding="utf-8", newline="\n") as h:
        json.dump(result, h, indent=1, sort_keys=True)
    with open(stem + ".md", "w", encoding="utf-8", newline="\n") as h:
        h.write(F.report_md(result))
    for k in F.CHECKS:
        n = len(result["problems"][k])
        print(f"{k:22s} {'ok' if n == 0 else f'{n} problem(s)'}")
    print(f"excluded {len(result['excluded'])}; flags {len(result['flags'])}; "
          f"cells complete {sum(1 for c in result['cells'].values() if not c['needed'])} of {len(result['cells'])}")
    if args.replacements:
        for p in F.write_replacements(result, d, os.path.join(REPO, "configs", "experiments"), args.replacements):
            print("replacements ->", p)
    print(("MET" if result["met"] else "NOT MET") + f" -> {stem}.md")
    return 0 if result["met"] else 1


if __name__ == "__main__":
    sys.exit(main())
