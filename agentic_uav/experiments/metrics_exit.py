"""Phase 15's exit: every primary metric has a written definition and a tested implementation (AUV-14).

    p = static_checks()                         # defined, tested, pre_registered: the document, the tests, git
    p = scored_checks(rows, batch_dir)          # computed everywhere, in range, agreeing with the judge
    compare_scores(rows_a, rows_b)              # deterministic

AUV-14's exit criterion for Phase 15: "Every primary metric has a written
definition and a tested implementation. No metric should be invented after
inspecting the final results." Checked:

    defined              the implementation's registry is exactly docs/METRICS.md's ids, at its version, and every
                         primary metric's row says what it is
    tested               every primary metric's id is asserted in tests/test_metrics.py
    pre_registered       docs/METRICS.md was committed before the metrics code existed, and is unchanged since
                         (a change would be a new version); every result carries its SHA-256
    computed_everywhere  on a batch with every arm, network and failure: every run has every metric, or the
                         reason it has none -- and the reasons are the definitions' (a value wherever the
                         definition gives one)
    in_range             fractions in [0, 1], counts whole and not negative, times within the window, a
                         completion within the deadline, p50 <= p95
    agrees_with_judge    success is the judge's; the cells coordination efficiency finds searched are exactly
                         the judge's coverage
    deterministic        the batch flown twice scores the same, run for run; one batch scored twice, byte for byte
    old_logs             Phase 14's committed batch (log version 1, no trajectories) scores without error: what it
                         lacks -- sizes, payload digests, trajectories -- is "not available", everything else a value
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
from typing import Any

from .metrics import (DOC, NOT_APPLICABLE, NOT_AVAILABLE, NOT_RECORDED, PRIMARY, REGISTRY, UNDEFINED, VERSION,
                      check_registry, doc_sha256, doc_text, load_run)
from .provenance import REPO_ROOT

CHECKS = ("defined", "tested", "pre_registered", "computed_everywhere", "in_range", "agrees_with_judge",
          "deterministic", "old_logs")
TESTS = os.path.join(REPO_ROOT, "tests", "test_metrics.py")
CODE = "agentic_uav/experiments/metrics.py"
DOC_REL = "docs/METRICS.md"
FRACTIONS = ("P1.coverage", "P1.target_detection", "P1.safe_return", "P1.mission_score")
COUNTS = ("P5.collisions", "P5.separation_violations", "P5.zone_entries", "P5.emergency_fallbacks",
          "P5.unsafe_proposals", "P5.guardian_interventions", "P6.messages", "P6.bytes", "P6.duplicates", "P6.expired",
          "CE.total_cells", "CE.unique_cells", "D2.redundant_searches", "D3.task_reassignments", "D4.orphaned_tasks",
          "D5.role_changes", "D6.role_oscillations", "D7.stale_message_decisions", "D8.invalid_llm_outputs",
          "D10.llm_calls", "D11.fallback_use", "D15.conflicting_claims")
ALWAYS = ("P1.success", "P1.coverage", "P1.target_detection", "P1.safe_return", "P1.mission_score", "P2.completion_s",
          "P2.censored", "P5.collisions", "P5.separation_violations", "P5.zone_entries", "P5.emergency_fallbacks",
          "P5.unsafe_proposals", "P5.guardian_interventions", "P6.messages", "P6.bytes", "P6.duplicates",
          "P6.expired", "CE.total_cells", "CE.unique_cells", "D1.area_searched_pct", "D3.task_reassignments",
          "D4.orphaned_tasks", "D5.role_changes", "D6.role_oscillations", "D7.stale_message_decisions",
          "D13.battery_used_pct", "D14.distance_m", "D15.conflicting_claims")
MODEL = ("D8.invalid_llm_outputs", "D9.llm_latency_p50_s", "D9.llm_latency_p95_s", "D10.llm_calls", "D11.fallback_use")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def static_checks() -> dict[str, list[str]]:
    p: dict[str, list[str]] = {"defined": list(check_registry()), "tested": [], "pre_registered": []}
    text = doc_text()
    for m in PRIMARY:
        row = next((line for line in text.splitlines() if line.startswith(f"| `{m}` |")), None)
        if row is None or len(row.split("|")[2].strip()) < 20:
            p["defined"].append(f"{m}: no written definition")
    with io.open(TESTS, encoding="utf-8") as h:
        code = h.read()
    body = code.split('"""', 2)[2] if code.count('"""') >= 2 else code          # past the module docstring
    for m in PRIMARY:
        if not re.search(rf'"{re.escape(m)}"', body):
            p["tested"].append(f"{m}: never asserted in tests/test_metrics.py")
    try:
        doc_added = _git("log", "--diff-filter=A", "--format=%H %ct", "--", DOC_REL).splitlines()[-1].split()
        code_added = _git("log", "--diff-filter=A", "--format=%H %ct", "--", CODE).splitlines()
        if not code_added:
            p["pre_registered"].append("the metrics code is not committed")
        else:
            first_code = code_added[-1].split()
            before = subprocess.run(["git", "merge-base", "--is-ancestor", doc_added[0], first_code[0]],
                                    cwd=REPO_ROOT, capture_output=True).returncode == 0
            if doc_added[0] == first_code[0] or not before or int(doc_added[1]) > int(first_code[1]):
                p["pre_registered"].append("the definitions were not committed before the metrics code")
        changed = _git("log", "--format=%H", f"{doc_added[0]}..HEAD", "--", DOC_REL)
        if changed and VERSION == 1:
            p["pre_registered"].append(f"docs/METRICS.md changed after it was registered, still version 1: {changed}")
        if _git("status", "--porcelain", "--", DOC_REL):
            p["pre_registered"].append("docs/METRICS.md has uncommitted changes")
    except (subprocess.CalledProcessError, IndexError) as exc:
        p["pre_registered"].append(f"git could not show the registration: {exc}")
    return p


def scored_checks(rows: list[dict[str, Any]], batch_dir: str) -> dict[str, list[str]]:
    from .architecture import load_architecture
    from .experiment import load_failure
    from .scenarios import load_scenario
    from ..simulator.coverage import searchable_cells
    p: dict[str, list[str]] = {"computed_everywhere": [], "in_range": [], "agrees_with_judge": []}
    sha = doc_sha256()
    cells: dict[str, int] = {}
    for r in rows:
        rid, v, a, c = r["run_id"], r["values"], r["absent"], r["config"]
        if r["definitions_sha256"] != sha or r["metrics_version"] != VERSION:
            p["computed_everywhere"].append(f"{rid}: scored under another definition")
        if set(v) | set(a) != set(REGISTRY) or set(v) & set(a):
            p["computed_everywhere"].append(f"{rid}: not every metric has exactly a value or a reason")
        run = load_run(os.path.join(batch_dir, rid))
        if run.status != "completed":
            continue
        arch = load_architecture(c["architecture"])
        sc = load_scenario(c["scenario"])
        agents = arch.team != "scripted"
        for m in ALWAYS:
            if m not in v:
                why = a.get(m, {"kind": "missing", "why": "neither a value nor a reason"})
                p["computed_everywhere"].append(f"{rid}: {m} absent ({why['kind']}: {why['why']})")
        if agents:
            for m in ("D2.redundant_searches", "P6.messages_per_completed_task"):
                if m not in v and a.get(m, {}).get("kind") != UNDEFINED:
                    p["computed_everywhere"].append(f"{rid}: {m} absent ({a.get(m, {}).get('kind')})")
        stopped = bool(load_failure(c["failure"]).stop)
        p4 = a.get("P4.recovery_s", {}).get("kind")
        if "P4.recovery_s" not in v and (not stopped and p4 != NOT_APPLICABLE):
            p["computed_everywhere"].append(f"{rid}: P4 absent without a stop, but not as not applicable")
        if stopped and "P4.recovery_s" not in v and p4 != NOT_APPLICABLE:
            p["computed_everywhere"].append(f"{rid}: P4 absent after a stop: {a.get('P4.recovery_s')}")
        nominal = c["network"] == "nominal" and c["failure"] == "none"
        p3 = a.get("P3.continuity_retention", {}).get("kind")
        if nominal and p3 != NOT_APPLICABLE or not nominal and "P3.continuity_retention" not in v and \
                p3 not in (NOT_AVAILABLE, UNDEFINED):
            p["computed_everywhere"].append(f"{rid}: P3 is not as defined for its condition")
        decides = arch.decider == "llm" and c["planner"] != "none"
        for m in MODEL:
            if decides and m not in v:
                p["computed_everywhere"].append(f"{rid}: {m} absent where a model decides")
            if not decides and a.get(m, {}).get("kind") != NOT_APPLICABLE:
                p["computed_everywhere"].append(f"{rid}: {m} not 'not applicable' where no model decides")
        if decides and a.get("D12.tokens", {}).get("kind") not in (NOT_RECORDED, None):
            p["computed_everywhere"].append(f"{rid}: D12 absent for another reason than not recorded")
        # in range
        for m in FRACTIONS:
            if m in v and not 0.0 <= v[m] <= 1.0:
                p["in_range"].append(f"{rid}: {m} = {v[m]}")
        for m in COUNTS:
            if m in v and (not isinstance(v[m], int) or isinstance(v[m], bool) or v[m] < 0):
                p["in_range"].append(f"{rid}: {m} = {v[m]!r}")
        window = run.report["report"]["window_s"]
        if not 0.0 <= v["P2.completion_s"] <= sc.mission.deadline_s:
            p["in_range"].append(f"{rid}: P2 {v['P2.completion_s']} outside 0..{sc.mission.deadline_s}")
        if "P4.recovery_s" in v and not 0.0 <= v["P4.recovery_s"] <= window:
            p["in_range"].append(f"{rid}: P4 {v['P4.recovery_s']} outside the window")
        if "CE.coordination_efficiency" in v and not 0.0 < v["CE.coordination_efficiency"] <= 1.0:
            p["in_range"].append(f"{rid}: CE {v['CE.coordination_efficiency']}")
        if "P3.continuity_retention" in v and v["P3.continuity_retention"] < 0:
            p["in_range"].append(f"{rid}: P3 negative")
        if "D9.llm_latency_p50_s" in v and v["D9.llm_latency_p50_s"] > v["D9.llm_latency_p95_s"]:
            p["in_range"].append(f"{rid}: latency p50 > p95")
        # the judge
        if v["P1.success"] != run.report["report"]["success"]:
            p["agrees_with_judge"].append(f"{rid}: success is not the judge's")
        n = cells.setdefault(c["scenario"], len(searchable_cells(sc, 1.0)[0]))
        if "CE.unique_cells" in v and abs(v["CE.unique_cells"] / n - run.report["report"]["coverage"]["fraction"]) \
                > 1e-6:
            p["agrees_with_judge"].append(f"{rid}: the cells searched ({v['CE.unique_cells']}/{n}) are not the "
                                          f"judge's coverage {run.report['report']['coverage']['fraction']}")
    return p


def compare_scores(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[str]:
    if [r["run_id"] for r in a] != [r["run_id"] for r in b]:
        return ["the two batches have different runs"]
    return [f"{x['run_id']}: scored differently" for x, y in zip(a, b)
            if (x["values"], x["absent"], x.get("twin")) != (y["values"], y["absent"], y.get("twin"))]


def old_log_checks(rows: list[dict[str, Any]]) -> list[str]:
    p = []
    lacking = ("P6.bytes", "P6.duplicates", "CE.coordination_efficiency", "CE.total_cells", "CE.unique_cells")
    for r in rows:
        talked = r["values"].get("P6.messages", 0) > 0          # a flight with no messages lacks nothing for P6
        for m in lacking:
            if not talked and m.startswith("P6."):
                continue
            if r["absent"].get(m, {}).get("kind") != NOT_AVAILABLE:
                p.append(f"{r['run_id']}: {m} should be not available on a version-1 log")
        for m in ("P1.success", "P2.completion_s", "P5.guardian_interventions", "P6.messages", "D3.task_reassignments"):
            if m not in r["values"]:
                p.append(f"{r['run_id']}: {m} should have a value")
    return p


def read_rows(batch_dir: str) -> list[dict[str, Any]]:
    with io.open(os.path.join(batch_dir, "metrics.jsonl"), encoding="utf-8") as h:
        return [json.loads(line) for line in h]


__all__ = ["CHECKS", "static_checks", "scored_checks", "compare_scores", "old_log_checks", "read_rows", "DOC"]
