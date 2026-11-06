#!/usr/bin/env python3
"""Phase 14's exit: a batch command runs a list of configurations unattended, one complete directory per run.

    python scripts/batch_exit.py                     # configs/experiments/phase14_exit.toml, 10 runs at once
    python scripts/batch_exit.py --jobs 4 --block t

AUV-14's exit criterion: "a batch command executes a list of scenario configurations without manual prompts and
produces one complete result directory per run." The batch is flown by `scripts/run_batch.py` as a child process
with nothing to read from, twice; then three of its runs are removed from the second directory and the batch is
resumed there. Checks (`experiments/batch_exit.py`): unattended, one directory per run, manifests complete, every
event type, events well formed, as configured, failures kept, deterministic, resumes.

Outputs, under phases/phase-14-experiment-runner/results/ by default:

    batch-exit-<stamp>[-<block>].jsonl / .md     the checks and the verdict
    <the first batch directory>/                 the batch itself, every run's directory, as flown

The two working directories go under runs/experiments/ (not tracked). Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
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

from agentic_uav.experiments.batch import DEFAULT_ROOT, read_index  # noqa: E402
from agentic_uav.experiments.batch_exit import CHECKS, compare_batches, manifests_of, run_checks  # noqa: E402
from agentic_uav.experiments.experiment import load_batch  # noqa: E402
from agentic_uav.experiments.experiment_run import MANIFEST  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402

BATCH = "phase14_exit"
DEFAULT_OUT = os.path.join(REPO, "phases", "phase-14-experiment-runner", "results")
RESUMED = (2, 18, 37)            # a stopped flight, a mission not met, a replayed model: removed, then resumed
TIMEOUT_S = 3600


def repo_rel(path: str) -> str:
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:                      # another drive
        return path.replace("\\", "/")
    return (path if rel.startswith("..") else rel).replace("\\", "/")


def batch_command(args: list[str]) -> tuple[int, str, str | None]:
    """`scripts/run_batch.py` as a child process with no input; its exit code, output and batch directory."""
    done = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "run_batch.py"), *args], cwd=REPO,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S,
                          encoding="utf-8", errors="replace")
    out_dir = next((line.split(":", 1)[1].strip() for line in done.stdout.splitlines()
                    if line.startswith("batch   :")), None)
    return done.returncode, done.stdout + done.stderr, out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--work", default=DEFAULT_ROOT, help="where the two working batch directories go")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    wall = time.perf_counter()
    batch = load_batch(BATCH)
    ids = [r.run_id for r in batch.runs]
    p: dict[str, list[str]] = {k: [] for k in CHECKS}

    rc1, out1, first = batch_command([BATCH, "--jobs", str(args.jobs), "--out", args.work])
    print(f"first : exit {rc1}, {first}", flush=True)
    if rc1 != 0 or first is None:
        p["unattended"].append(f"the batch command exited {rc1}: {out1[-800:]}")
    rc2, out2, second = batch_command([BATCH, "--jobs", str(args.jobs), "--out", args.work])
    print(f"second: exit {rc2}, {second}", flush=True)
    if rc2 != 0 or second is None:
        p["unattended"].append(f"the second batch command exited {rc2}: {out2[-800:]}")
    if first and second:
        for k, v in run_checks(batch, first).items():
            p[k] += v
        p["deterministic"] += compare_batches(first, second, ids)
        removed = [batch.runs[i - 1].run_id for i in RESUMED]
        kept = [r for r in ids if r not in removed]
        before = manifests_of(second, kept)
        for rid in removed:
            shutil.rmtree(os.path.join(second, rid))
        rc3, out3, _ = batch_command([BATCH, "--jobs", str(args.jobs), "--resume", second])
        print(f"resume: exit {rc3}", flush=True)
        if rc3 != 0:
            p["resumes"].append(f"the resumed batch exited {rc3}: {out3[-800:]}")
        if manifests_of(second, kept) != before:
            p["resumes"].append("a run already complete was flown again")
        if not all(os.path.isfile(os.path.join(second, rid, MANIFEST)) for rid in removed):
            p["resumes"].append("a removed run was not flown again")
        else:
            p["resumes"] += compare_batches(first, second, ids)
    wall = time.perf_counter() - wall
    checks = {k: {"ok": not v, "problems": v[:30]} for k, v in p.items()}
    ok = all(c["ok"] for c in checks.values())
    rows = read_index(first) if first else []

    os.makedirs(args.out, exist_ok=True)
    kept_dir = None
    if first:
        kept_dir = os.path.join(args.out, os.path.basename(first))
        shutil.copytree(first, kept_dir)
    stem = f"batch-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    header = {"kind": "header", "t": started, "batch": BATCH, "runs": len(ids), "jobs": args.jobs,
              "first": first, "second": second, "kept": None if kept_dir is None else repo_rel(kept_dir),
              "resumed": [batch.runs[i - 1].run_id for i in RESUMED], "exit_criterion_met": ok, "checks": checks,
              "completed": sum(r["status"] == "completed" for r in rows), "met": sum(bool(r.get("met")) for r in rows),
              "wall_s": round(wall, 1), "code": provenance()}
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(header, default=str) + "\n")
        for r in rows:
            h.write(json.dumps({"kind": "run", **r}, default=str) + "\n")
    lines = [f"# Batch exit — {BATCH}, mock", "",
             f"Run {started}, `scripts/batch_exit.py`, {wall:.0f} s wall. `scripts/run_batch.py {BATCH}` as a child "
             f"process with no input, {args.jobs} runs at once, twice; then runs {list(RESUMED)} removed from the "
             "second directory and the batch resumed there.", "",
             f"{len(rows)} runs: {header['completed']} completed, {header['met']} met the mission. "
             f"The batch as flown: `{header['kept']}`.", "", "| Check | Result |", "|---|---|"]
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
