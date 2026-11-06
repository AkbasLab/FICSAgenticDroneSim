#!/usr/bin/env python3
"""Phase 16's exit: most coordination and communication defects can be discovered without launching CARLA-Air.

    python scripts/testing_exit.py                 # everything below; about an hour, 4 copies at once
    python scripts/testing_exit.py --jobs 2 --block t

AUV-15's exit criterion: "Most coordination and communication defects can be discovered without launching
CARLA-Air." Shown two ways, and alongside what Phase 16 built:

    planted      the 37 defects in tests/planted_defects.py -- realistic coordination and communication defects,
                 fixed before they were first run -- each planted alone in a throwaway copy of the repository,
                 against the simulator-free tests named there. Bar, fixed beforehand: at least 90 % discovered
    history      the project's own defects, Phases 3-15, classed by what found them
                 (evidence/defect-history-2026-11-06.md): coordination and communication defects found without the
                 simulator must be most of them
    traceable    docs/TESTING.md names a real test for every item of 16.1, 16.2 and 16.4 (tests/test_traceability.py)
    scenarios    AUV-15's seven integration scenarios pass on the mock (tests/test_integration_mock.py)
    deterministic  same architecture, model output and seed: the same run (tests/test_determinism.py)
    regression   the five live AirSim checks, each flown and passed (results/airsim-regression-*.jsonl)

Outputs, under phases/phase-16-testing-and-verification/results/ by default:

    testing-exit-<stamp>[-<block>].jsonl / .md     each part, each planted defect and what caught it, the verdict

Exit code 0 only if every part passed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.provenance import provenance  # noqa: E402

OUT = os.path.join(REPO, "phases", "phase-16-testing-and-verification")
DEFAULT_OUT = os.path.join(OUT, "results")
HISTORY = os.path.join(OUT, "evidence", "defect-history-2026-11-06.md")
PLANTED = os.path.join(REPO, "tests", "planted_defects.py")
BAR = 0.90
REGRESSION = ("single-waypoint", "pair-apart", "four-search", "reassign", "return-home")
TIMEOUT_S = 900
PARTS = ("planted", "history", "traceable", "scenarios", "deterministic", "regression")


def unittest_passes(cwd: str, pattern: str) -> tuple[bool, str]:
    """`python -B -m unittest discover -p pattern` in `cwd`: no bytecode written, so no stale bytecode is ever read."""
    try:
        done = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", pattern],
                              cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "hung"
    return done.returncode == 0, (done.stdout + done.stderr)[-300:]


def plant(job: tuple[str, list[tuple[int, tuple]], list[str]]) -> list[dict]:
    """Plant each defect alone in the copy `root`, run the tests until one fails, restore. One copy per worker."""
    root, defects, tests = job
    out = []
    for i, (path, old, new, note) in defects:
        full = os.path.join(root, path)
        with io.open(full, encoding="utf-8", newline="") as h:
            original = h.read()
        if original.count(old) != 1:
            out.append({"index": i, "file": path, "note": note, "planted": False, "caught": False, "by": None})
            continue
        with io.open(full, "w", encoding="utf-8", newline="") as h:
            h.write(original.replace(old, new))
        by = None
        try:
            for pattern in tests:
                ok, tail = unittest_passes(root, pattern)
                if not ok:
                    by = pattern if tail != "hung" else f"{pattern} (hung)"
                    break
        finally:
            with io.open(full, "w", encoding="utf-8", newline="") as h:
                h.write(original)
        out.append({"index": i, "file": path, "note": note, "planted": True, "caught": by is not None, "by": by})
    return out


def planted(jobs: int) -> tuple[list[str], list[dict]]:
    spec = runpy.run_path(PLANTED)
    defects, tests = list(enumerate(spec["DEFECTS"], 1)), spec["TESTS"]
    work = tempfile.mkdtemp(prefix="auv-planted-")
    roots = []
    try:
        for k in range(jobs):
            root = os.path.join(work, f"copy{k}")
            shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", "runs", "__pycache__", "results"))
            roots.append(root)
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
            rows = [r for part in pool.map(plant, [(roots[k], defects[k::jobs], tests) for k in range(jobs)])
                    for r in part]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    rows.sort(key=lambda r: r["index"])
    p = [f"defect {r['index']} ({r['file']}) could not be planted: its text is not there once" for r in rows
         if not r["planted"]]
    caught = sum(r["caught"] for r in rows)
    if caught < BAR * len(rows):
        p.append(f"{caught} of {len(rows)} discovered: below the {BAR:.0%} bar")
    return p, rows


def history() -> tuple[list[str], dict]:
    with io.open(HISTORY, encoding="utf-8") as h:
        cells = [[c.strip() for c in line.split("|")[1:-1]] for line in h
                 if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
    live = lambda r: r[3] == "**L**"  # noqa: E731
    counts = {"all": [sum(not live(r) for r in cells), sum(live(r) for r in cells)],
              "coordination": [sum(not live(r) for r in cells if r[4] == "C"),
                               sum(live(r) for r in cells if r[4] == "C")]}
    n, l_ = counts["coordination"]
    return ([] if n > l_ else [f"coordination defects found live ({l_}) are not fewer than those found without "
                                f"the simulator ({n})"]), counts


def regression() -> tuple[list[str], dict]:
    got = {}
    for check in REGRESSION:
        files = sorted(glob.glob(os.path.join(DEFAULT_OUT, f"airsim-regression-*-{check}.jsonl")))
        if files:
            with io.open(files[-1], encoding="utf-8") as h:
                row = json.loads(h.readline())
            got[check] = {"passed": row["passed"], "why": row["why"], "record": row["record"],
                          "file": os.path.relpath(files[-1], REPO).replace("\\", "/")}
    p = [f"{c}: not flown" for c in REGRESSION if c not in got]
    p += [f"{c}: flown, not passed ({g['why']})" for c, g in got.items() if not g["passed"]]
    return p, got


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    started, code, wall = time.strftime("%Y-%m-%dT%H:%M:%S"), provenance(), time.perf_counter()
    p: dict[str, list[str]] = {k: [] for k in PARTS}
    for part, pattern in (("traceable", "test_traceability.py"), ("scenarios", "test_integration_mock.py"),
                          ("deterministic", "test_determinism.py")):
        ok, tail = unittest_passes(REPO, pattern)
        if not ok:
            p[part].append(f"{pattern} failed: {tail}")
        print(f"{part}: {'yes' if ok else 'NO'}", flush=True)
    p["history"], tally = history()
    p["regression"], flights = regression()
    print("planting the defects ...", flush=True)
    p["planted"], rows = planted(args.jobs)
    caught = sum(r["caught"] for r in rows)
    wall = time.perf_counter() - wall
    checks = {k: {"ok": not v, "problems": v} for k, v in p.items()}
    ok = all(c["ok"] for c in checks.values())
    share = lambda xs: round(100.0 * xs[0] / max(1, sum(xs)), 1)  # noqa: E731
    header = {"kind": "header", "t": started, "exit_criterion_met": ok, "checks": checks,
              "planted": {"defects": len(rows), "discovered": caught, "bar": BAR},
              "history": {k: {"without_simulator": v[0], "live": v[1], "pct_without": share(v)} for k, v in tally.items()},
              "regression": flights, "wall_s": round(wall, 1), "code": code}
    os.makedirs(args.out, exist_ok=True)
    stem = f"testing-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(header) + "\n")
        for r in rows:
            h.write(json.dumps({"kind": "defect", **r}) + "\n")
    lines = [f"# Testing exit — AUV-15", "", f"Run {started}, `scripts/testing_exit.py`, {wall:.0f} s wall.", "",
             "| Part | Result |", "|---|---|"]
    lines += [f"| {k} | {'yes' if c['ok'] else '**no**'} |" for k, c in checks.items()]
    lines += ["", f"**Planted:** {caught} of {len(rows)} defects discovered without the simulator "
                  f"({100 * caught / max(1, len(rows)):.1f} %; bar {BAR:.0%}).",
              f"**History:** coordination and communication defects {tally['coordination'][0]} found without the "
              f"simulator, {tally['coordination'][1]} live ({share(tally['coordination'])} %); every code defect "
              f"{tally['all'][0]} / {tally['all'][1]} ({share(tally['all'])} %).",
              f"**Regression:** {sum(g['passed'] for g in flights.values())} of {len(REGRESSION)} live checks passed.", "",
              "| # | Defect | File | Discovered by |", "|---|---|---|---|"]
    lines += [f"| {r['index']} | {r['note']} | `{r['file']}` | {r['by'] or '**not discovered**'} |" for r in rows]
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}**", ""]
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines[:16]))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
