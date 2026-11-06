"""Phase 15: the evaluation metrics, exactly as pre-registered in docs/METRICS.md (AUV-14).

    run = load_run("runs/experiments/<batch>/<run_id>")
    values, absent = run_metrics(run)                      # {id: value}, {id: (kind, why)} for those it has not
    rows = batch_metrics("runs/experiments/<batch>")       # every run, with the paired P3

THE DEFINITIONS ARE THE DOCUMENT'S. `docs/METRICS.md` was committed before this
module existed; every id it defines is implemented here under that id, and
nothing else is (`check_registry`). Every result records the document's
SHA-256 and version, so a number can always be traced to the definition it
was computed under. A metric whose input a run lacks is ABSENT -- not
available, not applicable, undefined or not recorded -- with its reason;
never 0.

Every metric reads one run's directory (Phase 14) alone: its manifest,
report, event log, records and trajectories. P3 is paired: it needs the
batch, to find each degraded run's nominal twin.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

from .provenance import REPO_ROOT

DOC = os.path.join(REPO_ROOT, "docs", "METRICS.md")
VERSION = 1
NOMINAL_NETWORK, NO_FAILURE = "nominal", "none"
STALE_S = 2.0                      # D7: the guardian's command timeout
OSCILLATION_S = 30.0               # D6
CELL_M = 1.0                       # CE: the judge's grid
HEARTBEAT = "heartbeat"
NOT_AVAILABLE, NOT_APPLICABLE, UNDEFINED, NOT_RECORDED = "not available", "not applicable", "undefined", \
    "not recorded"

REGISTRY = (
    "P1.success", "P1.coverage", "P1.target_detection", "P1.safe_return", "P1.mission_score",
    "P2.completion_s", "P2.censored",
    "P3.continuity_retention",
    "P4.recovery_s", "P4.censored",
    "P5.collisions", "P5.separation_violations", "P5.zone_entries", "P5.emergency_fallbacks",
    "P5.unsafe_proposals", "P5.guardian_interventions",
    "P6.messages", "P6.bytes", "P6.messages_per_completed_task", "P6.duplicates", "P6.expired",
    "CE.coordination_efficiency", "CE.total_cells", "CE.unique_cells",
    "D1.area_searched_pct", "D2.redundant_searches", "D3.task_reassignments", "D4.orphaned_tasks",
    "D5.role_changes", "D6.role_oscillations", "D7.stale_message_decisions", "D8.invalid_llm_outputs",
    "D9.llm_latency_p50_s", "D9.llm_latency_p95_s", "D10.llm_calls", "D11.fallback_use", "D12.tokens",
    "D13.battery_used_pct", "D14.distance_m", "D15.conflicting_claims",
)
PRIMARY = tuple(m for m in REGISTRY if m.startswith("P"))
_ID = re.compile(r"`((?:P[1-6]|CE|D\d{1,2})\.[a-z0-9_]+)`")


# ------------------------------------------------------------ the document

def doc_text(path: str = DOC) -> str:
    with io.open(path, encoding="utf-8") as h:
        return h.read()


def doc_sha256(path: str = DOC) -> str:
    with io.open(path, "rb") as h:
        return hashlib.sha256(h.read()).hexdigest()


def doc_ids(text: str) -> list[str]:
    """Every id the document defines: the backticked ids in the first cell of a table row."""
    out: list[str] = []
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        first = line.split("|")[1]
        for m in _ID.findall(first):
            if m not in out:
                out.append(m)
    return out


def doc_version(text: str) -> int | None:
    m = re.search(r"^# Evaluation metrics — definitions, version (\d+)", text, re.M)
    return int(m.group(1)) if m else None


def check_registry(path: str = DOC) -> list[str]:
    """Why the implementation must not score: it and the document disagree."""
    text = doc_text(path)
    p = []
    ids = doc_ids(text)
    if set(ids) != set(REGISTRY):
        p += [f"defined but not implemented: {i}" for i in ids if i not in REGISTRY]
        p += [f"implemented but not defined: {i}" for i in REGISTRY if i not in ids]
    if doc_version(text) != VERSION:
        p.append(f"the document is version {doc_version(text)}; this implementation is version {VERSION}")
    return p


# ------------------------------------------------------------ one run

@dataclass
class Run:
    run_id: str
    config: dict[str, Any]
    report: dict[str, Any] | None
    events: list[dict[str, Any]] | None
    records: dict[str, Any] | None
    trajectories: dict[str, list[list[Any]]] | None
    status: str


def _gz_json(path: str) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as h:
        return json.load(h)


def load_run(run_dir: str) -> Run:
    def opt(name: str, reader: Any) -> Any:
        p = os.path.join(run_dir, name)
        return reader(p) if os.path.isfile(p) else None

    def events(p: str) -> list[dict[str, Any]]:
        with gzip.open(p, "rt", encoding="utf-8") as h:
            return [json.loads(line) for line in h]

    def plain(p: str) -> Any:
        with io.open(p, encoding="utf-8") as h:
            return json.load(h)

    m = plain(os.path.join(run_dir, "manifest.json"))
    return Run(m["run_id"], m["config"], opt("report.json", plain), opt("events.jsonl.gz", events),
               opt("records.json.gz", _gz_json), opt("trajectories.json.gz", _gz_json), m["status"])


def _of(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind]


def _model_decides(config: dict[str, Any]) -> bool:
    from .architecture import load_architecture
    return load_architecture(config["architecture"]).decider == "llm" and config["planner"] != "none"


def nearest_rank(xs: list[float], pct: float) -> float:
    s = sorted(xs)
    return s[max(1, math.ceil(pct / 100.0 * len(s))) - 1]


def run_metrics(run: Run) -> tuple[dict[str, Any], dict[str, tuple[str, str]]]:
    """Every per-run metric (all but P3): its value, or why it has none."""
    from .scenarios import load_scenario
    v: dict[str, Any] = {}
    a: dict[str, tuple[str, str]] = {}
    if run.status != "completed" or run.report is None or run.events is None:
        for m in REGISTRY:
            a[m] = (NOT_AVAILABLE, f"the run {run.status}: no report or event log")
        return v, a
    sc = load_scenario(run.config["scenario"])
    rep, ev = run.report["report"], run.events
    comp = rep["components"]
    window = rep["window_s"]

    # P1
    v["P1.success"] = bool(rep["success"])
    v["P1.coverage"], v["P1.target_detection"], v["P1.safe_return"] = (
        comp["coverage"], comp["target_detection"], comp["safe_return"])
    v["P1.mission_score"] = (comp["coverage"] + comp["target_detection"] + comp["safe_return"]) / 3.0
    # P2
    v["P2.censored"] = not rep["success"]
    v["P2.completion_s"] = rep["completion_s"] if rep["success"] else float(sc.mission.deadline_s)
    # P4
    _recovery(run, ev, window, v, a)
    # P5
    guard = _of(ev, "GUARDIAN_INTERVENED")
    v["P5.collisions"], v["P5.separation_violations"], v["P5.zone_entries"] = (
        comp["collisions"], comp["separation_violations"], comp["zone_entries"])
    v["P5.emergency_fallbacks"] = sum(e["outcome"] == "execute_safe_fallback" for e in guard)
    v["P5.unsafe_proposals"] = sum(e["outcome"] in ("reject_and_replan", "approve_with_modification") for e in guard)
    v["P5.guardian_interventions"] = len(guard)
    # P6
    sent = _of(ev, "MESSAGE_SENT")
    v["P6.messages"] = len(sent)
    if all(isinstance(e["bytes"], int) and not isinstance(e["bytes"], bool) for e in sent):
        v["P6.bytes"] = sum(e["bytes"] for e in sent)
    else:
        a["P6.bytes"] = (NOT_AVAILABLE, "the event log's sizes are not numbers (log version 1's defect)")
    searched = run.report.get("searched")
    if searched is None:
        a["P6.messages_per_completed_task"] = (NOT_AVAILABLE, "the report has no searched tasks (no agents)")
    else:
        done = {t for ts in searched.values() for t in ts}
        if done:
            v["P6.messages_per_completed_task"] = len(sent) / len(done)
        else:
            a["P6.messages_per_completed_task"] = (UNDEFINED, "no task was completed")
    if any("payload_digest" not in e for e in sent):
        a["P6.duplicates"] = (NOT_AVAILABLE, "the event log has no payload digests (log version 1)")
    else:
        v["P6.duplicates"] = duplicates(sent)
    v["P6.expired"] = sum(e["why"] == "expired" for e in _of(ev, "MESSAGE_DROPPED"))
    # CE
    _efficiency(run, sc, window, v, a)
    # D1-D15
    v["D1.area_searched_pct"] = 100.0 * comp["coverage"]
    if searched is None:
        a["D2.redundant_searches"] = (NOT_AVAILABLE, "the report has no searched tasks (no agents)")
    else:
        counts: dict[str, int] = {}
        for ts in searched.values():
            for t in ts:
                counts[t] = counts.get(t, 0) + 1
        v["D2.redundant_searches"] = sum(max(0, n - 1) for n in counts.values())
    per_task: dict[str, int] = {}
    for e in _of(ev, "TASK_ASSIGNED"):
        per_task[e["task"]] = per_task.get(e["task"], 0) + 1
    v["D3.task_reassignments"] = sum(max(0, n - 1) for n in per_task.values())
    by_sector = run.report["report"]["coverage"]["by_sector"]
    v["D4.orphaned_tasks"] = sum(1 for s in sc.sectors if by_sector.get(s.id, 0.0) < sc.mission.required_coverage)
    roles = _of(ev, "ROLE_CHANGED")
    v["D5.role_changes"] = len(roles)
    v["D6.role_oscillations"] = oscillations(roles)
    v["D7.stale_message_decisions"] = stale_decisions(ev)
    _model(run, ev, v, a)
    batteries = run.report["report"]["facts"]["batteries"]
    v["D13.battery_used_pct"] = sum(b["used"] for b in batteries)
    v["D14.distance_m"] = sum(b["flown_m"] for b in batteries)
    v["D15.conflicting_claims"] = sum(str(e.get("why", "")).startswith("lost: lost to")
                                      for e in _of(ev, "TASK_RELEASED"))
    a.setdefault("P3.continuity_retention", (NOT_AVAILABLE, "paired: computed across a batch"))
    return v, a


def _recovery(run: Run, ev: list[dict[str, Any]], window: float, v: dict, a: dict) -> None:
    stops = [e for e in _of(ev, "FAULT_INJECTED") if e["fault"] == "stop"]
    if not stops:
        a["P4.recovery_s"] = a["P4.censored"] = (NOT_APPLICABLE, "no drone was stopped")
        return
    if run.records is None or "policies" not in run.records:
        a["P4.recovery_s"] = a["P4.censored"] = (NOT_AVAILABLE, "no records of the tasks each drone completed")
        return
    times, censored = [], False
    for stop in stops:
        d, t0 = stop["drone"], stop["t"]
        held: set[str] = set()
        for e in ev:
            if e["t"] >= t0:
                break
            if e["drone"] == d and e["type"] == "TASK_ASSIGNED":
                held.add(e["task"])
            elif e["drone"] == d and e["type"] == "TASK_RELEASED":
                held.discard(e["task"])
        lost = held - set(run.records["policies"].get(d, {}).get("completed", []))
        if not lost:
            continue
        taken = [e["t"] for e in ev if e["type"] == "TASK_ASSIGNED" and e["t"] >= t0 and e["drone"] != d
                 and e["task"] in lost]
        if taken:
            times.append(min(taken) - t0)
        else:
            times.append(window - t0)
            censored = True
    if not times:
        a["P4.recovery_s"] = a["P4.censored"] = (NOT_APPLICABLE, "the stopped drone had no task left to lose")
        return
    v["P4.recovery_s"] = max(times)
    v["P4.censored"] = censored


def duplicates(sent: list[dict[str, Any]]) -> int:
    """Messages repeating one their sender sent earlier, still within its lifetime (heartbeats aside)."""
    last: dict[tuple, tuple[float, float]] = {}
    n = 0
    for e in sorted(sent, key=lambda e: e["t"]):
        if e["message_type"] == HEARTBEAT:
            continue
        key = (e["drone"], e["message_type"], tuple(e["recipients"]), e["payload_digest"])
        if key in last and e["t"] - last[key][0] < last[key][1]:
            n += 1
        last[key] = (e["t"], e["ttl_s"])
    return n


def oscillations(roles: list[dict[str, Any]]) -> int:
    n = 0
    by: dict[str, list[dict[str, Any]]] = {}
    for e in roles:
        by.setdefault(e["drone"], []).append(e)
    for changes in by.values():
        changes.sort(key=lambda e: e["t"])
        for prev, cur in zip(changes, changes[1:]):
            if cur["role"] == prev["previous"] and cur["t"] - prev["t"] <= OSCILLATION_S:
                n += 1
    return n


def stale_decisions(ev: list[dict[str, Any]]) -> int:
    stale = {(e["drone"], e["t"]) for e in _of(ev, "MESSAGE_RECEIVED") if e["delay_s"] > STALE_S}
    return sum(1 for e in _of(ev, "DECISION_PROPOSED") if "message" in e["triggers"] and (e["drone"], e["t"]) in stale)


def _model(run: Run, ev: list[dict[str, Any]], v: dict, a: dict) -> None:
    ids = ("D8.invalid_llm_outputs", "D9.llm_latency_p50_s", "D9.llm_latency_p95_s", "D10.llm_calls",
           "D11.fallback_use", "D12.tokens")
    if not _model_decides(run.config):
        for i in ids:
            a[i] = (NOT_APPLICABLE, "no model decides in this run")
        return
    calls = _of(ev, "LLM_CALLED")
    v["D8.invalid_llm_outputs"] = sum(bool(e.get("problems")) for e in calls)
    lat = [x for e in calls for x in (e.get("latency_s") or []) if x is not None]
    if lat:
        v["D9.llm_latency_p50_s"], v["D9.llm_latency_p95_s"] = nearest_rank(lat, 50), nearest_rank(lat, 95)
    else:
        a["D9.llm_latency_p50_s"] = a["D9.llm_latency_p95_s"] = (UNDEFINED, "no model call was timed")
    v["D10.llm_calls"] = sum(e.get("calls", 0) for e in calls)
    v["D11.fallback_use"] = sum(e["kind"] == "fallback" for e in calls)
    logs = [x for g in ((run.records or {}).get("llm") or {}).values() for x in g.get("log", [])]
    tokens = [x["tokens"] for x in logs if x.get("tokens") is not None]
    if tokens:
        v["D12.tokens"] = sum(tokens)
    else:
        a["D12.tokens"] = (NOT_RECORDED, "the model client does not record tokens yet (planned for Phase 17)")


def _efficiency(run: Run, sc: Any, window: float, v: dict, a: dict) -> None:
    ids = ("CE.coordination_efficiency", "CE.total_cells", "CE.unique_cells")
    if not run.trajectories:
        for i in ids:
            a[i] = (NOT_AVAILABLE, "no trajectories in the run directory (before Phase 15)")
        return
    import numpy as np

    from ..simulator.coverage import covered_at, searchable_cells
    from ..simulator.trajectory import Knot, Trajectory
    trajs = {d: Trajectory(d, [Knot(float(k[0]), float(k[1]), float(k[2]), float(k[3]), bool(k[4])) for k in ks])
             for d, ks in run.trajectories.items() if ks}
    start = min(t.knots[0].t for t in trajs.values())
    cells, _ = searchable_cells(sc, CELL_M)
    union = np.zeros(len(cells), dtype=bool)
    total = 0
    for t in trajs.values():
        hit = np.isfinite(covered_at(cells, [t], sc.detection.radius_m, sc.detection.min_observation_s, start,
                                     start + window))
        total += int(hit.sum())
        union |= hit
    v["CE.total_cells"], v["CE.unique_cells"] = total, int(union.sum())
    if total:
        v["CE.coordination_efficiency"] = int(union.sum()) / total
    else:
        a["CE.coordination_efficiency"] = (UNDEFINED, "no cell was searched")


# ------------------------------------------------------------ a batch

def _twin_key(c: dict[str, Any]) -> tuple:
    return c["architecture"], c["scenario"], c["team_size"], c["seed"], c["planner"]


def batch_metrics(batch_dir: str) -> list[dict[str, Any]]:
    """Every run of a batch directory: its metrics, P3 paired with its nominal twin."""
    problems = check_registry()
    if problems:
        raise ValueError("the metrics implementation and docs/METRICS.md disagree: " + "; ".join(problems))
    sha = doc_sha256()
    runs = sorted((d for d in os.listdir(batch_dir) if os.path.isfile(os.path.join(batch_dir, d, "manifest.json"))))
    rows = []
    for rid in runs:
        run = load_run(os.path.join(batch_dir, rid))
        values, absent = run_metrics(run)
        rows.append({"run_id": rid, "config": run.config, "values": values, "absent": absent})
    twins = {_twin_key(r["config"]): r for r in rows
             if r["config"]["network"] == NOMINAL_NETWORK and r["config"]["failure"] == NO_FAILURE}
    for r in rows:
        c = r["config"]
        r["absent"].pop("P3.continuity_retention", None)
        if c["network"] == NOMINAL_NETWORK and c["failure"] == NO_FAILURE:
            r["absent"]["P3.continuity_retention"] = (NOT_APPLICABLE, "the run is itself in the nominal condition")
            continue
        twin = twins.get(_twin_key(c))
        score = r["values"].get("P1.mission_score")
        if twin is None or score is None or twin["values"].get("P1.mission_score") is None:
            r["absent"]["P3.continuity_retention"] = (NOT_AVAILABLE, "no nominal twin in the batch")
        elif twin["values"]["P1.mission_score"] == 0:
            r["absent"]["P3.continuity_retention"] = (UNDEFINED, "the twin's mission score is 0")
        else:
            r["values"]["P3.continuity_retention"] = score / twin["values"]["P1.mission_score"]
            r["twin"] = twin["run_id"]
    for r in rows:
        r.update({"metrics_version": VERSION, "definitions_sha256": sha})
        r["absent"] = {k: {"kind": kind, "why": why} for k, (kind, why) in sorted(r["absent"].items())}
        missing = [m for m in REGISTRY if m not in r["values"] and m not in r["absent"]]
        if missing:
            raise AssertionError(f"{r['run_id']}: neither a value nor a reason for {missing}")
    return rows


def write_metrics(batch_dir: str, rows: list[dict[str, Any]]) -> None:
    """Each run's metrics.json, and the batch's metrics.jsonl and metrics.md."""
    for r in rows:
        with io.open(os.path.join(batch_dir, r["run_id"], "metrics.json"), "w", encoding="utf-8",
                     newline="\n") as h:
            json.dump(r, h, indent=1, sort_keys=True, default=str)
    with io.open(os.path.join(batch_dir, "metrics.jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for r in rows:
            h.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    with io.open(os.path.join(batch_dir, "metrics.md"), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary(rows))


def _fmt(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.3g}" if abs(x) < 1000 else f"{x:.0f}"
    return str(x)


def summary(rows: list[dict[str, Any]]) -> str:
    cols = ("P1.success", "P2.completion_s", "P3.continuity_retention", "P4.recovery_s", "P5.guardian_interventions",
            "P6.messages", "P6.duplicates", "CE.coordination_efficiency", "D3.task_reassignments")
    lines = [f"# Metrics (docs/METRICS.md version {VERSION}, sha256 {rows[0]['definitions_sha256'][:12] if rows else ''})",
             "", "Censored values are marked `≥`; — is absent (the run's metrics.json says why).", "",
             "| Run | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            x = r["values"].get(c)
            cens = (c == "P2.completion_s" and r["values"].get("P2.censored")) or \
                   (c == "P4.recovery_s" and r["values"].get("P4.censored"))
            cells.append(("≥" if cens else "") + _fmt(x))
        lines.append(f"| {r['run_id']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
