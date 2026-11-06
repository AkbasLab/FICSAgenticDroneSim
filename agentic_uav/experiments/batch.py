"""Phase 14: run a batch of experiment configurations, unattended, one directory per run (AUV-14, the exit).

    out = run_batch(load_batch("phase14_exit"), "runs/experiments", jobs=10)     # a new batch directory
    out = run_batch(batch, "runs/experiments", resume="runs/experiments/<dir>")  # finish an interrupted one

The batch directory holds:

    batch.json      the batch as read (every run's configuration), its source file and digest, the code, and when
                    it ran -- written first, so even an interrupted batch says what it was
    <run_id>/       one per run (`experiment_run.py`): manifest, report, events, records
    index.jsonl     one row per run, in the batch's order: status, met, completion, events, error
    summary.md      the same, as a table

NO PROMPTS: nothing waits for a person. A model on a server is checked
once, before the first run -- the server must serve the pinned digest -- and
the batch refuses to start if it does not. RESUMING: a run whose directory
already has its manifest is not flown again, so a batch stopped by a sleeping
laptop or a dropped connection is finished by running it again on the same
directory. Runs fly side by side with `jobs` > 1; each is independent, so the
directories are the same either way.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import os
import time
from typing import Any

from .experiment import Batch, parse_planner
from .experiment_run import index_row, run_one
from .provenance import REPO_ROOT, file_digest, provenance

BATCH_FILE, INDEX, SUMMARY = "batch.json", "index.jsonl", "summary.md"
DEFAULT_ROOT = os.path.join(REPO_ROOT, "runs", "experiments")


def preflight_models(batch: Batch, endpoint: str | None) -> list[str]:
    """Why the batch must not start: a pinned model the server does not serve. Nothing for echo or replay."""
    from .llm import load_llm, preflight
    names = sorted({parse_planner(r.planner).arg for r in batch.runs if parse_planner(r.planner).kind == "llm"})
    if names and endpoint is None:
        return [f"runs use a model ({', '.join(names)}), but no endpoint was given"]
    problems = []
    for n in names:
        try:
            problems += preflight(load_llm(n), endpoint)
        except Exception as exc:                     # a server not reachable is a reason not to start
            problems.append(f"{n} at {endpoint}: {type(exc).__name__}: {exc}")
    return problems


def _one(run: Any, out_dir: str, endpoint: str | None) -> dict[str, Any]:
    return run_one(run, out_dir, endpoint)


def run_batch(batch: Batch, root: str = DEFAULT_ROOT, jobs: int = 1, resume: str | None = None,
              endpoint: str | None = None, progress: Any = print) -> str:
    """Fly every run of `batch` into a batch directory (new under `root`, or `resume`); returns that directory."""
    problems = preflight_models(batch, endpoint)
    if problems:
        raise RuntimeError("the batch was not started: " + "; ".join(problems))
    if resume:
        out_dir = resume
        with io.open(os.path.join(out_dir, BATCH_FILE), encoding="utf-8") as h:
            before = json.load(h)
        if before["batch"]["runs"] != batch.as_json()["runs"]:
            raise RuntimeError(f"{out_dir} holds a different batch: resume only the batch it was started with")
    else:
        out_dir = os.path.join(root, f"{batch.batch_id}-{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(out_dir, exist_ok=False)
        source = batch.source if os.path.isabs(batch.source) else os.path.join(REPO_ROOT, batch.source)
        head = {"batch": batch.as_json(), "source_sha256": file_digest(source) if batch.source else None,
                "code": provenance(), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "jobs": jobs,
                "endpoint": endpoint}
        with io.open(os.path.join(out_dir, BATCH_FILE), "w", encoding="utf-8", newline="\n") as h:
            json.dump(head, h, indent=1, sort_keys=True, default=str)
    rows: dict[int, dict[str, Any]] = {}
    if jobs > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_one, r, out_dir, endpoint): r for r in batch.runs}
            for fut in concurrent.futures.as_completed(futures):
                run = futures[fut]
                try:
                    rows[run.index] = fut.result()
                except Exception as exc:     # the worker itself died: the run has no manifest, so resume flies it
                    rows[run.index] = {"run_id": run.run_id, "index": run.index, "status": "unfinished",
                                       "error": f"{type(exc).__name__}: {exc}"}
                progress(_line(rows[run.index], len(rows), len(batch.runs)))
    else:
        for run in batch.runs:
            rows[run.index] = _one(run, out_dir, endpoint)
            progress(_line(rows[run.index], len(rows), len(batch.runs)))
    ordered = [rows[r.index] for r in batch.runs]
    with io.open(os.path.join(out_dir, INDEX), "w", encoding="utf-8", newline="\n") as h:
        for row in ordered:
            h.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    with io.open(os.path.join(out_dir, SUMMARY), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary(batch, ordered))
    return out_dir


def _line(row: dict[str, Any], done: int, total: int) -> str:
    what = row["status"] if row["status"] != "completed" else ("met" if row.get("met") else "not met")
    return f"[{done}/{total}] {row['run_id']}: {what}" + (f" ({row['error']})" if row.get("error") else "")


def summary(batch: Batch, rows: list[dict[str, Any]]) -> str:
    counts = {s: sum(r["status"] == s for r in rows) for s in ("completed", "crashed", "unfinished")}
    lines = [f"# Batch {batch.batch_id}", "", batch.description, "",
             f"{len(rows)} runs: {counts['completed']} completed ({sum(bool(r.get('met')) for r in rows)} met the "
             f"mission), {counts['crashed']} crashed, {counts['unfinished']} unfinished.", "",
             "| Run | Status | Met | Completion s | Events | Error |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['run_id']} | {r['status']} | {r.get('met')} | {r.get('completion_s')} | "
                     f"{r.get('events')} | {r.get('error') or ''} |")
    return "\n".join(lines) + "\n"


def read_index(out_dir: str) -> list[dict[str, Any]]:
    with io.open(os.path.join(out_dir, INDEX), encoding="utf-8") as h:
        return [json.loads(line) for line in h]


__all__ = ["run_batch", "read_index", "preflight_models", "index_row", "DEFAULT_ROOT"]
