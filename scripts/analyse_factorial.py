"""Analyse a finished factorial run (Phase 18) - tables, paired tests, LLM diagnostics.

    python scripts/analyse_factorial.py results/main_v1
    python scripts/make_paper_figures.py --only fig8      # heatmaps from the JSON this writes
    python scripts/make_paper_figures.py --only fig9      # what the LLM agent actually chose

Reads only the result directory. Writes paper/figure_data/factorial_<design>.json
and prints a summary. Every comparison is **paired by seed**: with common random
numbers, run k of architecture X and run k of architecture Y fly the same
mission, so differences are tested within seed, not between groups.

  success   exact two-sided McNemar test on the discordant pairs
  time      mean paired difference with a 95% bootstrap interval (seeded)

No scipy needed. Exclusions follow runs.csv (status == valid only).
"""

import argparse
import csv
import glob
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHS = ["A", "B", "C", "D", "DV2"]
NETS = ["final_nominal", "final_moderate", "final_severe", "final_partitioned"]
FAILS = ["none", "one_failure"]


def load_runs(directory):
    with open(os.path.join(directory, "runs.csv"), encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "valid"]
    for r in rows:
        r["team_size"] = int(r["team_size"])
        r["seed"] = int(r["seed"])
        r["success"] = r["mission_success"] == "True"
        r["coverage"] = float(r["coverage"]) if r["coverage"] else 0.0
        r["mission_time_s"] = float(r["mission_time_s"]) if r["mission_time_s"] else None
        r["duplicated_sectors"] = int(float(r["duplicated_sectors"] or 0))
    return rows


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0, c - h), 4), round(min(1, c + h), 4)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p on discordant counts b (X ok, Y fail), c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired(rows, x, y, key=lambda r: (r["team_size"], r["network"], r["failure"], r["seed"])):
    a = {key(r): r for r in rows if r["architecture"] == x}
    b = {key(r): r for r in rows if r["architecture"] == y}
    keys = sorted(set(a) & set(b))
    disc_xy = sum(1 for k in keys if a[k]["success"] and not b[k]["success"])
    disc_yx = sum(1 for k in keys if b[k]["success"] and not a[k]["success"])
    diffs = [a[k]["mission_time_s"] - b[k]["mission_time_s"] for k in keys
             if a[k]["mission_time_s"] is not None and b[k]["mission_time_s"] is not None]
    rng = random.Random(20261109)
    boots = []
    if diffs:
        for _ in range(2000):
            s = [diffs[rng.randrange(len(diffs))] for _ in diffs]
            boots.append(sum(s) / len(s))
        boots.sort()
    return {"pairs": len(keys),
            "success_rate_x": round(sum(a[k]["success"] for k in keys) / len(keys), 4),
            "success_rate_y": round(sum(b[k]["success"] for k in keys) / len(keys), 4),
            "x_only_success": disc_xy, "y_only_success": disc_yx,
            "mcnemar_p": mcnemar_exact(disc_xy, disc_yx),
            "time_diff_mean_s": round(sum(diffs) / len(diffs), 1) if diffs else None,
            "time_diff_ci95_s": [round(boots[49], 1), round(boots[1949], 1)] if boots else None}


def cells(rows):
    out = []
    groups = defaultdict(list)
    for r in rows:
        groups[(r["architecture"], r["team_size"], r["network"], r["failure"])].append(r)
    for (a, n, net, f), rs in sorted(groups.items()):
        k = sum(r["success"] for r in rs)
        times = [r["mission_time_s"] for r in rs if r["mission_time_s"] is not None]
        ok_times = [r["mission_time_s"] for r in rs if r["success"]]
        out.append({"architecture": a, "team_size": n, "network": net, "failure": f,
                    "n": len(rs), "successes": k, "success_rate": round(k / len(rs), 4),
                    "success_ci95": wilson(k, len(rs)),
                    "coverage_mean": round(sum(r["coverage"] for r in rs) / len(rs), 4),
                    "dup_mean": round(sum(r["duplicated_sectors"] for r in rs) / len(rs), 3),
                    "time_mean_s": round(sum(times) / len(times), 1) if times else None,
                    "time_mean_successful_s": round(sum(ok_times) / len(ok_times), 1)
                    if ok_times else None})
    return out


def llm_diagnostics(directory, arch="D"):
    """What an agentic architecture's model actually chose, from every transcript.
    For DV2 it also separates phase changes the *model* made from those the
    deterministic fallback made after a rejected wrong-phase choice - so a DV2
    success can be attributed honestly."""
    tools, fallbacks, rejections = Counter(), Counter(), Counter()
    runs, only_search, latencies, conf = 0, 0, [], []
    reported = {True: [0, 0], False: [0, 0]}      # reported? -> [successes, runs]
    wrong_phase_fallbacks = model_completions = 0
    with open(os.path.join(directory, "runs.csv"), encoding="utf-8") as f:
        success = {r["experiment_id"]: r["mission_success"] == "True"
                   for r in csv.DictReader(f) if r["status"] == "valid"}
    for d in sorted(glob.glob(os.path.join(directory, f"*_{arch}_n*"))):
        rid = os.path.basename(d)
        if rid not in success:
            continue
        runs += 1
        chosen = Counter()
        for path in glob.glob(os.path.join(d, "llm", "*.json")):
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
            for x in t.get("turns", []):
                if x.get("used_fallback"):
                    fallbacks[x.get("fallback_cause") or "?"] += 1
                if x.get("tool"):
                    tools[x["tool"]] += 1
                    chosen[x["tool"]] += 1
                if x.get("rejection_reason"):
                    rejections[x["rejection_reason"]] += 1
                if x.get("used_fallback") and x.get("fallback_cause") == "wrong_phase":
                    wrong_phase_fallbacks += 1
                if not x.get("used_fallback") and x.get("tool") in (
                        "report_task_complete", "report_target"):
                    model_completions += 1
                if x.get("exchanges") and not x.get("used_fallback"):
                    latencies.append(x.get("latency_s") or 0.0)
                    if x.get("confidence") is not None:
                        conf.append(x["confidence"])
        if set(chosen) <= {"start_search"}:
            only_search += 1
        rep = (chosen.get("report_target", 0) + chosen.get("report_task_complete", 0)) > 0
        reported[rep][0] += success[rid]
        reported[rep][1] += 1
    total = sum(tools.values())
    return {"runs": runs, "model_decisions": total,
            "tools": dict(tools.most_common()),
            "start_search_share": round(tools.get("start_search", 0) / total, 4) if total else None,
            "runs_only_start_search": only_search,
            "fallback_causes": dict(fallbacks.most_common()),
            "rejections": dict(rejections.most_common()),
            "latency_mean_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "confidence_mean": round(sum(conf) / len(conf), 3) if conf else None,
            "success_if_ever_reported": reported[True],
            "success_if_never_reported": reported[False],
            "completions_by_model": model_completions,
            "wrong_phase_fallbacks": wrong_phase_fallbacks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    args = ap.parse_args()
    d = args.directory
    rows = load_runs(d)
    design = os.path.basename(os.path.normpath(d))
    present = sorted({r["architecture"] for r in rows})
    llm_archs = [a for a in present if a.startswith("D")]
    pairs = [(x, y) for x, y in (("C", "A"), ("C", "B"), ("C", "D"), ("A", "D"),
                                 ("C", "DV2"), ("A", "DV2"))
             if x in present and y in present]
    comparisons = {}
    for x, y in pairs:
        comparisons[f"{x}_vs_{y}"] = {"all": paired(rows, x, y)}
        for net in NETS:
            comparisons[f"{x}_vs_{y}"][net] = paired([r for r in rows if r["network"] == net], x, y)
        for fl in FAILS:
            comparisons[f"{x}_vs_{y}"][fl] = paired([r for r in rows if r["failure"] == fl], x, y)
    out = {"design": design, "runs": len(rows), "cells": cells(rows),
           "architectures": present, "comparisons": comparisons,
           "llm": llm_diagnostics(d, llm_archs[0]) if llm_archs else None,
           "llm_by_arch": {a: llm_diagnostics(d, a) for a in llm_archs}}
    path = os.path.join(ROOT, "paper", "figure_data", f"factorial_{design}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)

    print(f"{design}: {len(rows)} valid runs\n")
    print("Paired comparisons (same seed, same mission), all conditions pooled:")
    for name, c in comparisons.items():
        a = c["all"]
        print(f"  {name:8s} success {a['success_rate_x']:.0%} vs {a['success_rate_y']:.0%}  "
              f"McNemar p={a['mcnemar_p']:.2g}  time diff {a['time_diff_mean_s']} s "
              f"(95% CI {a['time_diff_ci95_s']})")
    for a, L in out["llm_by_arch"].items():
        if not L["model_decisions"]:
            continue
        print(f"\nLLM agent {a}: {L['model_decisions']} model decisions in {L['runs']} runs; "
              f"start_search {L['start_search_share']:.1%}; {L['runs_only_start_search']} runs "
              f"chose nothing else; mean latency {L['latency_mean_s']} s; "
              f"mean confidence {L['confidence_mean']}")
        print(f"  task completions chosen by the model: {L['completions_by_model']}; "
              f"made by the fallback after a wrong-phase choice: "
              f"{L['wrong_phase_fallbacks']}")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
