"""Run every test suite and every demo, and report one pass/fail summary.

This is the "is the whole thing still working?" command - run it before pushing,
after a refactor, or when handing the repo to someone new. Nothing here needs a
simulator, a GPU, an API key or a network connection.

    python scripts/run_all_tests.py
    python scripts/run_all_tests.py --quick    # test suites only, skip demos
"""

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (phase, label, path, expected test count or None for demos)
SUITES = [
    ("3",   "Skills + contracts",        "tests/test_skills.py", 12),
    ("1-2", "Behavior preservation",     "tests/test_behavior_preservation.py", 4),
    ("4",   "Mission scoring",           "tests/test_mission.py", 6),
    ("5",   "Persistent agent loop",     "tests/test_persistent_agent.py", 5),
    ("6",   "Belief state + truth split", "tests/test_belief_state.py", 11),
    ("7",   "Message protocol",          "tests/test_messaging.py", 14),
    ("8",   "Decentralized allocation",  "tests/test_allocation.py", 21),
    ("3-8", "AirSim code path (fake sim)", "tests/test_airsim_path.py", 13),
]

DEMOS = [
    ("3", "4-drone skill demo",      "scripts/phase3_demo.py"),
    ("3", "All 11 skills",           "scripts/phase3_showcase.py"),
    ("4", "Canonical mission",       "scripts/run_canonical_mission.py"),
    ("5", "Persistent agent",        "scripts/run_persistent_agent.py"),
    ("6", "Belief audit trail",      "scripts/run_persistent_agent.py --log"),
    ("7", "4-agent team mission",    "scripts/run_team_mission.py"),
    ("8", "Decentralized allocation", "scripts/run_allocation_mission.py"),
]


def run(cmd):
    started = time.time()
    proc = subprocess.run([sys.executable] + cmd.split(), cwd=ROOT,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr, time.time() - started


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip the demos")
    args = ap.parse_args()

    print("=" * 66)
    print("  AgenticDroneSimRepo - full verification (no simulator required)")
    print("=" * 66)

    failures = []
    total_tests = 0

    print("\nTEST SUITES")
    print("-" * 66)
    for phase, label, path, expected in SUITES:
        code, out, err, secs = run(path)
        passed = _count(out, "passed")
        failed = _count(out, "failed")
        total_tests += passed
        ok = code == 0 and failed == 0 and (expected is None or passed == expected)
        status = "PASS" if ok else "FAIL"
        note = "" if expected is None or passed == expected else f" (expected {expected})"
        print(f"  [{status}] P{phase:<4} {label:<28} {passed:>2} passed{note}  {secs:.1f}s")
        if not ok:
            failures.append((label, err or out))

    if not args.quick:
        print("\nDEMOS (exit 0 = the phase's exit criterion held)")
        print("-" * 66)
        for phase, label, cmd in DEMOS:
            code, out, err, secs = run(cmd)
            status = "PASS" if code == 0 else "FAIL"
            print(f"  [{status}] P{phase:<4} {label:<28} exit {code}        {secs:.1f}s")
            if code != 0:
                failures.append((label, err or out))

    print("\n" + "=" * 66)
    if failures:
        print(f"  {len(failures)} FAILURE(S)")
        for label, detail in failures:
            print(f"\n--- {label} ---")
            print("\n".join(detail.strip().splitlines()[-15:]))
        print("=" * 66)
        return 1

    print(f"  ALL GREEN - {total_tests} tests passed"
          f"{'' if args.quick else f', {len(DEMOS)} demos completed'}")
    print("=" * 66)
    return 0


def _count(text, word):
    """Pull N out of a '12 passed, 0 failed' line."""
    for line in text.splitlines():
        if word in line:
            parts = line.replace(",", " ").split()
            for i, p in enumerate(parts):
                if p == word and i > 0 and parts[i - 1].isdigit():
                    return int(parts[i - 1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
