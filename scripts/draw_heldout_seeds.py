#!/usr/bin/env python3
"""Draw Phase 18's held-out seeds from freeze version 1 and write configs/seeds/heldout.toml (AUV-16 17.4).

    python scripts/draw_heldout_seeds.py            # writes the file (refuses if it exists)
    python scripts/draw_heldout_seeds.py --check    # recomputes them and compares with the file

How they are derived, and why: agentic_uav/experiments/heldout.py. Drawn once; the file is then in the frozen scope
(configs/), so it can change only with a new dated freeze version.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.freeze import load  # noqa: E402
from agentic_uav.experiments.heldout import HELDOUT, draw, freeze_digest, load_heldout, write_heldout  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="recompute and compare with the committed file")
    args = parser.parse_args(argv)
    versions = load(REPO)
    if not versions:
        print("no freeze yet: the held-out seeds are drawn from freeze version 1")
        return 1
    if args.check:
        want = draw(freeze_digest(versions[0]))
        got = load_heldout(REPO)
        print("the committed held-out seeds are the ones freeze version 1 gives" if got == want else
              f"{HELDOUT} differs from what freeze version 1 gives: {want}")
        return 0 if got == want else 1
    if os.path.exists(os.path.join(REPO, HELDOUT)):
        print(f"{HELDOUT} exists: the held-out seeds are drawn once (use --check)")
        return 1
    test, reserve = write_heldout(REPO, versions[0])
    print(f"test    {test}\nreserve {reserve}\n-> {HELDOUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
