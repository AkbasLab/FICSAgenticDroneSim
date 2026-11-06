#!/usr/bin/env python3
"""Phase 15's exit: every primary metric has a written definition and a tested implementation.

    python scripts/metrics_exit.py
    python scripts/metrics_exit.py --block t

AUV-14's exit for Phase 15: "Every primary metric has a written definition and a tested implementation. No metric
should be invented after inspecting the final results." The definitions are docs/METRICS.md, committed before the
metrics code; the implementation is `experiments/metrics.py`, tested in tests/test_metrics.py. Here the batch
`phase14_exit` (every arm, three networks, three failure profiles, both team sizes) is flown twice by
`scripts/run_batch.py` and scored twice by `scripts/compute_metrics.py`, each a child process with no input; and
Phase 14's committed batch is scored as it is. Checks (`experiments/metrics_exit.py`): defined, tested,
pre-registered, computed everywhere, in range, agrees with the judge, deterministic, old logs.

Outputs, under phases/phase-15-evaluation-metrics/results/ by default:

    metrics-exit-<stamp>[-<block>].jsonl / .md     the checks and the verdict
    <the scored batch>/                            the batch as flown, with every run's metrics.json

Working directories go under runs/experiments/ (not tracked). Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import filecmp
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.batch import DEFAULT_ROOT  # noqa: E402
from agentic_uav.experiments.metrics import VERSION, doc_sha256  # noqa: E402
from agentic_uav.experiments.metrics_exit import (CHECKS, compare_scores, old_log_checks, read_rows,  # noqa: E402
                                                   scored_checks, static_checks)
from agentic_uav.experiments.provenance import provenance  # noqa: E402

BATCH = "phase14_exit"
DEFAULT_OUT = os.path.join(REPO, "phases", "phase-15-evaluation-metrics", "results")
PHASE14 = os.path.join(REPO, "phases", "phase-14-experiment-runner", "results", "phase14-exit-20261106-113936")
TIMEOUT_S = 3600


def child(script: str, args: list[str]) -> tuple[int, str]:
    done = subprocess.run([sys.executable, os.path.join(REPO, "scripts", script), *args], cwd=REPO,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S,
                          encoding="utf-8", errors="replace")
    return done.returncode, done.stdout + done.stderr


def fly(work: str, jobs: int) -> str | None:
    rc, out = child("run_batch.py", [BATCH, "--jobs", str(jobs), "--out", work])
    d = next((line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("batch   :")), None)
    return d if rc == 0 else None


def repo_rel(path: str) -> str:
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:
        return path.replace("\\", "/")
    return (path if rel.startswith("..") else rel).replace("\\", "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--work", default=DEFAULT_ROOT)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    code = provenance()
    wall = time.perf_counter()
    p: dict[str, list[str]] = {k: [] for k in CHECKS}
    for k, v in static_checks().items():
        p[k] += v

    first, second = fly(args.work, args.jobs), fly(args.work, args.jobs)
    print(f"flown : {first}, {second}", flush=True)
    rows: list = []
    if not first or not second:
        p["computed_everywhere"].append("the batch command failed")
    else:
        for d in (first, second):
            rc, out = child("compute_metrics.py", [d])
            if rc != 0:
                p["computed_everywhere"].append(f"scoring {d} failed: {out[-600:]}")
        rows = read_rows(first)
        for k, v in scored_checks(rows, first).items():
            p[k] += v
        p["deterministic"] += compare_scores(rows, read_rows(second))
        kept = os.path.join(first, "metrics.jsonl.first")
        shutil.copyfile(os.path.join(first, "metrics.jsonl"), kept)
        child("compute_metrics.py", [first])
        if not filecmp.cmp(kept, os.path.join(first, "metrics.jsonl"), shallow=False):
            p["deterministic"].append("one batch scored twice is not byte-for-byte the same")
        os.remove(kept)
    old = os.path.join(args.work, f"phase14-scored-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copytree(PHASE14, old)
    rc, out = child("compute_metrics.py", [old])
    if rc != 0:
        p["old_logs"].append(f"Phase 14's batch could not be scored: {out[-600:]}")
    else:
        old_rows = read_rows(old)
        p["old_logs"] += old_log_checks(old_rows)
        if len(old_rows) != len(glob.glob(os.path.join(old, "*", "manifest.json"))):
            p["old_logs"].append("not every run of Phase 14's batch was scored")
    wall = time.perf_counter() - wall

    checks = {k: {"ok": not v, "problems": v[:30]} for k, v in p.items()}
    ok = all(c["ok"] for c in checks.values())
    os.makedirs(args.out, exist_ok=True)
    kept_dir = None
    if first:
        kept_dir = os.path.join(args.out, os.path.basename(first))
        shutil.copytree(first, kept_dir)
    stem = f"metrics-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    header = {"kind": "header", "t": started, "batch": BATCH, "metrics_version": VERSION,
              "definitions_sha256": doc_sha256(), "first": first, "second": second, "phase14_scored": old,
              "kept": None if kept_dir is None else repo_rel(kept_dir), "runs": len(rows),
              "exit_criterion_met": ok, "checks": checks, "wall_s": round(wall, 1), "code": code}
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(header, default=str) + "\n")
        for r in rows:
            h.write(json.dumps({"kind": "run", "run_id": r["run_id"], "values": r["values"],
                                "absent": r["absent"]}, default=str, sort_keys=True) + "\n")
    lines = [f"# Metrics exit — docs/METRICS.md version {VERSION}", "",
             f"Run {started}, `scripts/metrics_exit.py`, {wall:.0f} s wall. The batch `{BATCH}` flown twice by "
             "`scripts/run_batch.py` and scored by `scripts/compute_metrics.py`, child processes with no input; "
             "Phase 14's committed batch scored as it is.", "",
             f"{len(rows)} runs scored with definitions sha256 `{doc_sha256()[:16]}`. The scored batch: "
             f"`{header['kept']}`.", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {k} | {'yes' if c['ok'] else '**no**'} |" for k, c in checks.items()]
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}**", ""]
    problems = [f"{k}: {x}" for k, c in checks.items() for x in c["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {x}" for x in problems[:40]] + [""]
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
