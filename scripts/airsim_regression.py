#!/usr/bin/env python3
"""Phase 16's AirSim regression set (AUV-15, 16.3): five live checks, kept deliberately small.

    python scripts/airsim_regression.py --dry-run                   # every check's mock twin, no simulator
    python scripts/airsim_regression.py --check single-waypoint     # one live check; CarlaAir must be up
    python scripts/airsim_regression.py --list

Each check is a flight the project already knows how to fly live, run through its own script (which writes its
own record and compares the flight with its mock twin), judged here by what the check is for:

    single-waypoint  a single-drone waypoint mission    Phase 5's live mission ("search S1" on search_single_live_small):
                                                         take off, fly the task, land at the pad -- the script's checks
    pair-apart       a two-drone non-conflicting mission Phase 8's live pair: the two divide the sectors as the twin does,
                                                         land, no collision -- the script's checks
    four-search      four drones together                Phase 3's four drones, each flying its skills (take off, waypoint,
                                                         hold, home, land) live: every skill succeeds. A four-drone SEARCH
                                                         is flown only on the mock: Town10HD's surveyed airspace holds the
                                                         two-sector live layout, and nothing avoids its buildings
    reassign         task reassignment during flight     Phase 9's live pair with the keep-out: one drone stopped, the other
                                                         detects it and takes its task in flight (checks `detected`,
                                                         `reassigned`, `kept_out`) -- the mission itself need not be met
    return-home      the return-home fallback            Phase 5's live mission with a fault injected once: the drone
                                                         recovers or returns home, and lands -- the script's checks

Between live checks the simulator is relaunched (`.\\CarlaAir.ps1 --kill`, then `.\\CarlaAir.ps1 Town10HD`): spawned
drones linger. `four-search` needs a fresh launch. Every check is flown by a person; this script never starts the
simulator.

Outputs, under phases/phase-16-testing-and-verification/results/ by default:

    airsim-regression-<stamp>-<check|dry-run>.jsonl / .md     each check: the command, its exit code, its record,
                                                               the verdict
    <check>/                                                  the flown script's own record

Exit code 0 only if every check run passed.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO, "phases", "phase-16-testing-and-verification", "results")
TIMEOUT_S = 3600
SINGLE = ["--scenario", "search_single_live_small", "--task", "search S1"]


@dataclass(frozen=True)
class Check:
    name: str
    what: str
    script: str
    live: tuple[str, ...]
    mock: tuple[str, ...]
    needs: tuple[str, ...] = ()         # header checks that must hold (else: the script's own exit code)
    record: str = "*.jsonl"


CHECKS = (
    Check("single-waypoint", "a single-drone waypoint mission", "single_agent_exit.py",
          ("--sim", "airsim", *SINGLE), (*SINGLE, "--seeds", "1", "--no-trouble")),
    Check("pair-apart", "a two-drone non-conflicting mission", "allocation_exit.py",
          ("--sim", "airsim"), ("--seeds", "1")),
    Check("four-search", "four drones together (skills; a four-drone search on the mock only)",
          "four_drone_skills.py", ("--sim", "airsim"), ()),
    Check("reassign", "task reassignment during flight", "recovery_exit.py",
          ("--sim", "airsim", "--keep-out"), ("--seeds", "1"), needs=("detected", "reassigned", "kept_out")),
    Check("return-home", "the return-home fallback", "single_agent_exit.py",
          ("--sim", "airsim", *SINGLE, "--fault-once"), ("--seeds", "1")),     # the twin: Phase 5's troubles,
                                                                                # on the scenario they are sized for
)
BY_NAME = {c.name: c for c in CHECKS}


def repo_rel(path: str) -> str:
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:                      # another drive
        return path.replace("\\", "/")
    return (path if rel.startswith("..") else rel).replace("\\", "/")


def latest_record(out_dir: str, pattern: str) -> str | None:
    files = sorted(glob.glob(os.path.join(out_dir, pattern)), key=os.path.getmtime)
    return files[-1] if files else None


def verdict(check: Check, exit_code: int, record: str | None, live: bool) -> tuple[bool, str]:
    """Whether the check passed, and why."""
    if not live or not check.needs:
        return exit_code == 0, f"the script's own checks: exit code {exit_code}"
    if record is None:
        return False, "no record was written"
    with io.open(record, encoding="utf-8") as h:
        head = json.loads(h.readline())
    got = {k: (v.get("ok") if isinstance(v, dict) else v) for k, v in (head.get("checks") or {}).items()}
    missing = [k for k in check.needs if k not in got]
    if missing:
        return False, f"the record has no {missing}"
    failed = [k for k in check.needs if not got[k]]
    return not failed, ("held: " + ", ".join(check.needs)) if not failed else f"failed: {failed}"


def run_check(check: Check, live: bool, out: str, extra: list[str]) -> dict[str, Any]:
    where = os.path.join(out, check.name if live else f"{check.name}-dry-run")
    os.makedirs(where, exist_ok=True)
    args = [sys.executable, os.path.join(REPO, "scripts", check.script),
            *(check.live if live else check.mock), "--out", where, "--block", "regression", *(extra if live else [])]
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    wall = time.perf_counter()
    done = subprocess.run(args, cwd=REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=TIMEOUT_S, encoding="utf-8", errors="replace")
    record = latest_record(where, check.record)
    ok, why = verdict(check, done.returncode, record, live)
    return {"check": check.name, "what": check.what, "live": live, "command": args[1:], "started": started,
            "wall_s": round(time.perf_counter() - wall, 1), "exit_code": done.returncode,
            "record": None if record is None else repo_rel(record),
            "passed": ok, "why": why, "tail": (done.stdout + done.stderr)[-1500:]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--check", choices=sorted(BY_NAME), help="fly this one check live (CarlaAir must be up)")
    what.add_argument("--dry-run", action="store_true", help="every check's mock twin, no simulator")
    what.add_argument("--list", action="store_true")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--host", default=None, help="AirSim host, passed to the flown script")
    parser.add_argument("--port", default=None, help="AirSim port, passed to the flown script")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    if args.list:
        for c in CHECKS:
            print(f"{c.name:16s} {c.what}\n{'':16s} python scripts/{c.script} {' '.join(c.live)}")
        return 0
    extra = [*(["--host", args.host] if args.host else []), *(["--port", args.port] if args.port else [])]
    checks = CHECKS if args.dry_run else (BY_NAME[args.check],)
    rows = []
    for c in checks:
        print(f"{c.name}: {'mock twin' if args.dry_run else 'LIVE'} ...", flush=True)
        rows.append(run_check(c, not args.dry_run, args.out, extra))
        print(f"  {'PASSED' if rows[-1]['passed'] else 'FAILED'} -- {rows[-1]['why']} ({rows[-1]['wall_s']} s)",
              flush=True)
    stem = f"airsim-regression-{time.strftime('%Y%m%d-%H%M%S')}-{'dry-run' if args.dry_run else args.check}"
    os.makedirs(args.out, exist_ok=True)
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for r in rows:
            h.write(json.dumps(r) + "\n")
    lines = [f"# AirSim regression — {'dry run (mock twins)' if args.dry_run else args.check + ', live'}", "",
             "| Check | What | Passed | Why | Exit | Record |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['check']} | {r['what']} | {'yes' if r['passed'] else '**no**'} | {r['why']} | {r['exit_code']} | "
              f"`{r['record']}` |" for r in rows]
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
