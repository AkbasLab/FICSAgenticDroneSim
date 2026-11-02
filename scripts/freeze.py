"""Freeze the final configuration, or check that nothing frozen has changed (Phase 17.4).

    python scripts/freeze.py                     # check (exit 1 if anything changed)
    python scripts/freeze.py --write             # first freeze: held-out seeds + fingerprint
    python scripts/freeze.py --refreeze --reason "fixed X, results before this are not comparable"

What is frozen: prompts, task rules, metrics, the calibrated network profiles,
the scenario families, and the held-out seeds (see agentic_uav/experiments/freeze.py).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import freeze as fz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="create the first freeze")
    ap.add_argument("--refreeze", action="store_true",
                    help="accept the current state as the new freeze (needs --reason)")
    ap.add_argument("--reason", default=None)
    args = ap.parse_args()

    if args.write:
        if fz.load() is not None:
            print("Already frozen. Use --refreeze --reason \"...\" to change it.")
            return 1
        seeds = fz.write_heldout()
        data = fz.write()
        print(f"Wrote {len(seeds)} held-out seeds to {os.path.relpath(fz.HELDOUT_PATH, fz.ROOT)}")
        print(f"Froze {len(data['groups'])} groups to {os.path.relpath(fz.FREEZE_PATH, fz.ROOT)}:")
        for g, h in data["fingerprint"].items():
            print(f"  {g:12s} {h}")
        return 0

    if args.refreeze:
        if not args.reason:
            print("--refreeze needs --reason: say what changed and why, so results "
                  "on either side of the change are never mixed.")
            return 2
        before = fz.check()
        data = fz.write(reason=args.reason)
        print(f"Refrozen ({len(before['changes'])} change(s) accepted): {args.reason}")
        for c in before["changes"]:
            print(f"  {c}")
        return 0

    r = fz.check()
    if r["ok"]:
        print(f"Frozen configuration unchanged since {r['frozen_at']}.")
        return 0
    print("FROZEN CONFIGURATION HAS CHANGED:" if r["frozen"] else "NOT FROZEN:")
    for c in r["changes"]:
        print(f"  {c}")
    print("\nIf the change is intended: python scripts/freeze.py --refreeze --reason \"...\"")
    return 1


if __name__ == "__main__":
    sys.exit(main())
