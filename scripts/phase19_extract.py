"""Phase 19.0: one row per held-out run, from the result directories alone.

    python scripts/phase19_extract.py results/main_v1 results/main_v2

Writes paper/figure_data/phase19_runs.csv. Everything Phase 19 analyses is
derived here from each run's saved files (result.json, events.jsonl,
llm/*.json), so the analysis can be re-run without re-flying anything.

Columns, beyond the run's identity and runs.csv outcome fields:

  mission score   0.5*coverage + 0.3*target_detection + 0.2*safe_return
                  (docs/METRICS.md weights, fixed in advance). target_detection
                  is targets_found / 2; safe_return is drones_home / survivors.
  messages        MESSAGE_SENT events (per recipient), MESSAGE_DROPPED
  recovery        lost vehicle, its unfinished sector (the task it was flying
                  when stopped, unless it had already swept it), and the time
                  until a teammate starts flying toward that sector
                  (recovery_start_s, = RecoveryTime) and starts sweeping it
                  (recovery_sweep_s, = ProductiveResumption, docs/METRICS.md).
                  None when nothing was orphaned or it was never recovered.
  guardian        interventions by outcome, and how many concerned a drone
                  that never landed
  LLM (D, DV2)    model decisions, tool counts, rejections, fallbacks,
                  perseveration (start_search chosen by the model on a sector
                  the context already reported searched), idle reports, the
                  longest run of decisions at one simulated instant, and
                  whether any agent reached its step budget
"""

import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "paper", "figure_data", "phase19_runs.csv")
W = (0.5, 0.3, 0.2)
TARGETS = 2
FLY_SKILLS = ("go_to_waypoint", "search_region")
AGENT_STEP_BUDGET = 150          # turns per agent at which a loop is treated as exhausted


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _events(d):
    p = os.path.join(d, "events.jsonl")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _sector(task):
    return str(task or "").replace("SEARCH_SECTOR_", "")


def event_features(ev, team, stopped):
    f = {}
    types = Counter(e["type"] for e in ev)
    f["msgs_sent"] = types.get("MESSAGE_SENT", 0)
    f["msgs_dropped"] = types.get("MESSAGE_DROPPED", 0)
    f["role_changes"] = sum(1 for e in ev if e["type"] == "ROLE_CHANGED"
                            and "from" in (e.get("data") or {}))
    f["skill_failures"] = sum(1 for e in ev if e["type"] == "SKILL_COMPLETED"
                              and (e.get("data") or {}).get("outcome") not in
                              (None, "success", "sector_searched"))

    # who landed
    landed = {e["vehicle"] for e in ev if e["type"] == "SKILL_COMPLETED"
              and (e.get("data") or {}).get("skill") == "land"
              and (e.get("data") or {}).get("outcome") == "success"}
    survivors = [v for v in team if v not in stopped]
    not_landed = sorted(v for v in survivors if v not in landed)
    f["not_landed"] = ";".join(not_landed)

    # guardian
    g = [e for e in ev if e["type"] == "GUARDIAN_INTERVENED"]
    go = Counter((e.get("data") or {}).get("outcome") for e in g)
    f["guardian_reject"] = go.get("reject_and_replan", 0)
    f["guardian_fallback"] = go.get("execute_safe_fallback", 0)
    f["guardian_modify"] = go.get("approve_with_modification", 0)
    f["guardian_on_not_landed"] = sum(1 for e in g if e.get("vehicle") in not_landed)
    f["guardian_separation"] = sum(1 for e in g if "separation" in
                                   json.dumps(e.get("data") or {}))

    # sweeps
    # A sweep's own `started_at` is used, not the event time: the event is
    # stamped at the sweep's start in some runs and its end in others (found
    # in Phase 19), so the event time cannot be used for timing.
    sweeps = [((e.get("data") or {}).get("started_at", e["t"]), e["vehicle"],
               (e.get("data") or {}).get("sector")) for e in ev
              if e["type"] == "SKILL_COMPLETED"
              and (e.get("data") or {}).get("outcome") == "sector_searched"]
    f["sweeps"] = len(sweeps)

    # failure and recovery
    fault = next((e for e in ev if e["type"] == "FAULT_INJECTED"), None)
    f.update(fault_t=None, lost=None, orphan=None, recovery_start_s=None,
             recovery_sweep_s=None, orphan_recovered=None)
    if fault:
        tf, lost = fault["t"], fault["vehicle"]
        f["fault_t"], f["lost"] = round(tf, 2), lost
        held = [e for e in ev if e["type"] == "SKILL_STARTED" and e["vehicle"] == lost
                and e["t"] <= tf and (e.get("data") or {}).get("task")]
        task = (held[-1]["data"]["task"]) if held else None
        sec = _sector(task)
        done_before = any(v == lost and s == sec and t <= tf for t, v, s in sweeps)
        if task and not done_before:
            f["orphan"] = sec
            start = next((e["t"] for e in ev if e["type"] == "SKILL_STARTED"
                          and e["t"] > tf and e["vehicle"] != lost
                          and (e.get("data") or {}).get("skill") in FLY_SKILLS
                          and _sector((e.get("data") or {}).get("task")) == sec), None)
            sweep = next((t for t, v, s in sweeps if t > tf and v != lost and s == sec), None)
            f["recovery_start_s"] = None if start is None else round(start - tf, 1)
            f["recovery_sweep_s"] = None if sweep is None else round(sweep - tf, 1)
            f["orphan_recovered"] = sweep is not None
    return f


def llm_features(d):
    files = glob.glob(os.path.join(d, "llm", "*.json"))
    if not files:
        return {}
    tools, rej, fb = Counter(), Counter(), Counter()
    persev = idle_report = model = turns_total = 0
    max_same_t = 0
    budget_hit = False
    latency = 0.0
    for p in files:
        t = _read(p) or {}
        turns = t.get("turns", [])
        turns_total += len(turns)
        budget_hit |= len(turns) >= AGENT_STEP_BUDGET
        streak, last_t = 0, None
        for x in turns:
            ts = x.get("time_s")
            streak = streak + 1 if (ts is not None and ts == last_t) else 1
            last_t = ts
            max_same_t = max(max_same_t, streak)
            if x.get("rejection_reason"):
                rej[x["rejection_reason"]] += 1
            if x.get("used_fallback"):
                fb[x.get("fallback_cause") or "?"] += 1
                continue
            if not x.get("tool"):
                continue
            model += 1
            latency += x.get("latency_s") or 0.0
            tools[x["tool"]] += 1
            if x["tool"] in ("start_search", "report_task_complete"):
                try:
                    ctx = json.loads((x.get("user_prompt") or "").split(
                        "\n\nAvailable tools:")[0])
                except ValueError:
                    continue
                held = (ctx.get("role_and_task") or {}).get("task")
                prog = (ctx.get("belief") or {}).get("progress") or {}
                if x["tool"] == "start_search" and held and prog.get("sector_searched"):
                    persev += 1
                if x["tool"] == "report_task_complete" and (not held or prog.get("reported")):
                    idle_report += 1
    return {"llm_turns": turns_total, "llm_model_decisions": model,
            "llm_start_search": tools.get("start_search", 0),
            "llm_report_complete": tools.get("report_task_complete", 0),
            "llm_report_target": tools.get("report_target", 0),
            "llm_send_bid": tools.get("send_bid", 0),
            "llm_perseveration": persev, "llm_idle_report": idle_report,
            "llm_rej_wrong_phase": rej.get("wrong_phase", 0),
            "llm_rej_format": sum(v for k, v in rej.items() if k != "wrong_phase"),
            "llm_fb_wrong_phase": fb.get("wrong_phase", 0),
            "llm_fb_not_converging": fb.get("coordination_not_converging", 0),
            "llm_fb_total": sum(fb.values()),
            "llm_max_same_instant": max_same_t, "llm_budget_hit": budget_hit,
            "llm_latency_total_s": round(latency, 1)}


def rows_for(directory):
    design = os.path.basename(os.path.normpath(directory))
    with open(os.path.join(directory, "runs.csv"), encoding="utf-8") as f:
        runs = [r for r in csv.DictReader(f) if r["status"] == "valid"]
    out = []
    for r in runs:
        d = os.path.join(directory, r["experiment_id"])
        res = _read(os.path.join(d, "result.json")) or {}
        man = _read(os.path.join(d, "manifest.json")) or {}
        n = int(r["team_size"])
        team = man.get("team") or [f"Drone{i + 1}" for i in range(n)]
        stopped = [s for s in str(res.get("stopped", "-")).split(",") if s and s != "-"]
        row = {"design": design, "experiment_id": r["experiment_id"],
               "arch": r["architecture"], "team_size": n, "network": r["network"],
               "failure": r["failure"], "seed": int(r["seed"]),
               "has_logs": bool(res),
               "success": r["mission_success"] == "True",
               "system_failure": r.get("system_failure") == "True",
               "coverage": float(r["coverage"]) if r["coverage"] else None,
               "time_s": float(r["mission_time_s"]) if r["mission_time_s"] else None,
               "dup": int(float(r["duplicated_sectors"])) if r["duplicated_sectors"] else None,
               "delivery": float(r["delivery_rate"]) if r["delivery_rate"] else None,
               "targets_found": int(float(r["targets_found"])) if r["targets_found"] else None,
               "drones_home": int(float(r["drones_home"])) if r["drones_home"] else None,
               "survivors": n - len(stopped), "total_steps": res.get("total_steps")}
        if row["coverage"] is not None:
            td = min(1.0, (row["targets_found"] or 0) / TARGETS)
            sr = (row["drones_home"] or 0) / max(1, row["survivors"])
            row.update(target_detection=round(td, 4), safe_return=round(sr, 4),
                       score=round(W[0] * row["coverage"] + W[1] * td + W[2] * sr, 4))
        if res:
            row.update(event_features(_events(d), team, stopped))
            row.update(llm_features(d))
        out.append(row)
    return out


def main(argv):
    rows = []
    for d in argv[1:]:
        rows += rows_for(d)
        print(f"{d}: {sum(1 for r in rows if r['design'] == os.path.basename(os.path.normpath(d)))} runs")
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
