"""Phase 19.4: classify every failed mission, with a trace excerpt for each.

    python scripts/phase19_failures.py results/main_v1 results/main_v2

Reads the run directories (events.jsonl, llm/*.json) and
paper/figure_data/phase19_runs.csv; writes
paper/figure_data/phase19_failures.csv (one row per failed run) and
paper/figure_data/phase19_failure_traces.md (an excerpt of the decision trace
behind every class, for inspection).

Each failed run gets one PRIMARY cause - the first rule below that matches,
in this order - and a list of CONTRIBUTING factors. The order puts the cause
nearest the decision first: a drone that never left its pad is checked before
coverage, because a run can only be judged on coverage once every surviving
drone's state is explained.

  EVALUATION_ARTEFACT            a surviving drone that never took off (it lost
                                 every bid and stayed on its own pad) is scored
                                 "not home"; nothing failed in flight
  STALE_INFORMATION              a surviving drone was left airborne after its
                                 decision loop ran out (>= 150 decisions, or
                                 >= 20 at one simulated instant) while waiting
                                 on an allocation state that lost coordination
                                 messages had left out of date
  SAFETY_GUARDIAN_DEADLOCK       a surviving drone left airborne whose last
                                 commands were guardian rejections/escalations
  LLM_MISSION_MISINTERPRETATION  (D, DV2) coverage < 1 and the model chose
                                 start_search on a sector its own context
                                 reported already searched >= 3 times
  LLM_INVALID_ACTION             (D, DV2) a drone's decision loop ended early
                                 with it airborne right after a rejected model
                                 reply; or coverage < 1 with >= 30% of replies
                                 rejected as invalid
  INSUFFICIENT_BATTERY           coverage < 1 and a survivor returned on a
                                 battery-floor override while work remained
  COMMUNICATION_PARTITION        coverage < 1 in the partitioned condition
  TASK_NOT_REALLOCATED           coverage < 1: a sector was never searched
                                 while the survivors declared "no work
                                 available" (the lost drone's sector, or one
                                 whose assignment was lost)
  NAVIGATION_FAILURE             a flight skill reported failure on a drone
                                 left airborne
  UNCLASSIFIED                   none of the above (inspected by hand)

Contributing factors: CONFLICTING_CLAIMS (a sector flown twice, or a
0.0 m separation rejection: two drones on the same sweep), ROLE_OSCILLATION
(more role changes than 2 x team size), COMMUNICATION_PARTITION,
INSUFFICIENT_BATTERY (battery-floor return), LLM_INVALID_ACTION (>= 10% of
replies rejected as malformed), AGENT_LOOP_EXIT (a drone's decision loop ended
while it was airborne - a lifecycle defect, see docs/ANALYSIS_phase19.md).
"""

import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "paper", "figure_data")
LOOP = 20
BUDGET = 150
COORD = ("task_award", "task_complete", "task_accept", "task_bid", "task_claim",
         "task_announcement", "task_release")


def _events(d):
    with open(os.path.join(d, "events.jsonl"), encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def _llm(d):
    turns = []
    for p in glob.glob(os.path.join(d, "llm", "*.json")):
        with open(p, encoding="utf-8") as f:
            turns += json.load(f).get("turns", [])
    return turns


def vehicle_state(ev, v):
    took_off = any(e["type"] == "SKILL_STARTED" and e.get("vehicle") == v
                   and (e.get("data") or {}).get("skill") == "take_off" for e in ev)
    dec = [e for e in ev if e["type"] == "DECISION_PROPOSED" and e.get("vehicle") == v]
    same = Counter(round(e["t"], 3) for e in dec)
    loop_t, loop_n = (same.most_common(1)[0] if same else (None, 0))
    overrides = [(e.get("data") or {}).get("guardian_override") for e in dec[-6:]]
    fails = [e for e in ev if e["type"] == "SKILL_COMPLETED" and e.get("vehicle") == v
             and (e.get("data") or {}).get("outcome") not in (None, "success",
                                                             "sector_searched")]
    last_obj = [(round(e["t"], 1), (e.get("data") or {}).get("objective")) for e in dec[-5:]]
    lost_coord = sum(1 for e in ev if e["type"] == "MESSAGE_DROPPED"
                     and (e.get("data") or {}).get("to") == v
                     and (e.get("data") or {}).get("type") in COORD)
    return {"took_off": took_off, "loop_t": loop_t, "loop_n": loop_n,
            "decisions": len(dec), "last_decision_t": round(dec[-1]["t"], 1) if dec else None,
            "lost_coordination_msgs": lost_coord,
            "guardian_tail": sum(1 for o in overrides if o),
            "skill_failures": len(fails), "last_objectives": last_obj}


def classify(r, d):
    ev = _events(d)
    n = int(r["team_size"])
    stopped = {r["lost"]} if r.get("lost") else set()
    not_landed = [v for v in (r["not_landed"] or "").split(";") if v]
    states = {v: vehicle_state(ev, v) for v in not_landed}
    reasons = [(e.get("data") or {}).get("reason", "") for e in ev
               if e["type"] == "ROLE_CHANGED" and "from" in (e.get("data") or {})]
    overrides = [str((e.get("data") or {}).get("guardian_override") or "") for e in ev
                 if e["type"] == "DECISION_PROPOSED"]
    battery_return = any("battery" in x and "below floor" in x for x in reasons + overrides)
    no_work = any(x == "no work available" for x in reasons)
    sep0 = sum(1 for x in overrides if "separation (0.0 m" in x)
    cov = float(r["coverage"]) if r["coverage"] else 0.0
    agentic = r["arch"] in ("D", "DV2")
    turns = _llm(d) if agentic else []
    model = [t for t in turns if t.get("tool") and not t.get("used_fallback")]
    persev = int(r.get("llm_perseveration") or 0)
    fmt_rej = int(r.get("llm_rej_format") or 0)
    replies = max(1, len([t for t in turns if t.get("raw_response")]))

    contributing = []
    if int(float(r["dup"] or 0)) > 0 or sep0:
        contributing.append("CONFLICTING_CLAIMS")
    if int(r["role_changes"] or 0) > 2 * n:
        contributing.append("ROLE_OSCILLATION")
    if r["network"] == "final_partitioned":
        contributing.append("COMMUNICATION_PARTITION")
    if battery_return:
        contributing.append("INSUFFICIENT_BATTERY")
    if agentic and fmt_rej / replies >= 0.10:
        contributing.append("LLM_INVALID_ACTION")

    primary, evidence = None, ""
    grounded = [v for v, s in states.items() if not s["took_off"]]
    looping = [v for v, s in states.items() if s["took_off"]
               and (s["loop_n"] >= LOOP or s["decisions"] >= BUDGET)]
    end_t = float(r["time_s"] or 0)
    early = [v for v, s in states.items() if s["took_off"] and v not in looping
             and s["last_decision_t"] is not None and s["last_decision_t"] < end_t - 30]
    last_rejected = False
    if agentic and early:
        mine = [t for t in turns if t.get("vehicle_id") == early[0] and t.get("raw_response")]
        last_rejected = bool(mine and mine[-1].get("rejection_reason"))
    guarded = [v for v, s in states.items() if s["took_off"] and s["guardian_tail"] >= 3]
    navfail = [v for v, s in states.items() if s["skill_failures"]]
    if grounded:
        primary = "EVALUATION_ARTEFACT"
        evidence = f"{','.join(grounded)} never took off; scored not home"
    elif looping:
        v = looping[0]
        st = states[v]
        primary = "STALE_INFORMATION"
        evidence = (f"{v} held '{st['last_objectives'][-1][1]}' for {st['decisions']} decisions "
                    f"(up to {st['loop_n']} at one instant, t={st['loop_t']} s) waiting on an "
                    f"allocation that a lost message had left out of date "
                    f"({st['lost_coordination_msgs']} coordination messages to it were lost); "
                    f"its step budget ran out with it airborne")
        contributing.append("AGENT_LOOP_EXIT")
    elif early and last_rejected:
        primary = "LLM_INVALID_ACTION"
        evidence = (f"{early[0]}'s last model reply was rejected; its decision loop ended at "
                    f"t={states[early[0]]['last_decision_t']} s with the drone airborne")
        contributing.append("AGENT_LOOP_EXIT")
    elif guarded:
        primary = "SAFETY_GUARDIAN_DEADLOCK"
        evidence = f"{guarded[0]}'s last decisions were guardian overrides"
    elif cov < 1 and agentic and persev >= 3:
        primary = "LLM_MISSION_MISINTERPRETATION"
        evidence = (f"model chose start_search on an already-searched sector {persev} times "
                    f"in {len(model)} accepted decisions")
    elif cov < 1 and agentic and fmt_rej / replies >= 0.30:
        primary = "LLM_INVALID_ACTION"
        evidence = f"{fmt_rej} of {replies} replies rejected as invalid"
    elif cov < 1 and battery_return:
        primary = "INSUFFICIENT_BATTERY"
        evidence = "battery-floor return with work remaining"
    elif cov < 1 and r["network"] == "final_partitioned":
        primary = "COMMUNICATION_PARTITION"
        evidence = "coverage < 1 under the partition"
    elif cov < 1:
        primary = "TASK_NOT_REALLOCATED"
        evidence = (f"orphan {r['orphan'] or '-'} recovered={r['orphan_recovered'] or '-'}; "
                    f"survivors declared 'no work available'={no_work}")
    elif navfail:
        primary = "NAVIGATION_FAILURE"
        evidence = f"{navfail[0]} reported a failed flight skill"
    else:
        primary = "UNCLASSIFIED"
        evidence = f"not landed: {not_landed}; states {states}"
    return primary, [c for c in contributing if c != primary], evidence, ev, turns, states


def excerpt(r, ev, turns, states, k=10):
    lines = [f"### {r['experiment_id']}  (coverage {r['coverage']}, end {r['time_s']} s, "
             f"not landed: {r['not_landed'] or '-'})", "", "```"]
    focus = [v for v in states] or ([r["lost"]] if r.get("lost") else [])
    keep = ("SKILL_STARTED", "ROLE_CHANGED", "FAULT_INJECTED", "GUARDIAN_INTERVENED",
            "DECISION_PROPOSED", "MESSAGE_DROPPED")
    sel = [e for e in ev if e["type"] in keep and (not focus or e.get("vehicle") in focus
                                                   or e["type"] == "FAULT_INJECTED")
           and "message_id" not in (e.get("data") or {})
           or (e["type"] == "SKILL_COMPLETED"
               and (e.get("data") or {}).get("outcome") == "sector_searched")]
    for e in sel[-k:]:
        d = e.get("data") or {}
        brief = {x: d[x] for x in ("skill", "task", "objective", "sector", "reason", "outcome",
                                   "guardian_override", "fault", "from", "to") if d.get(x)}
        lines.append(f"{e['t']:7.1f}  {e.get('vehicle', ''):7s} {e['type']:20s} "
                     f"{json.dumps(brief)[:110]}")
    if turns:
        lines.append("--- last model decisions ---")
        for t in turns[-4:]:
            lines.append(f"{(t.get('time_s') or 0):7.1f}  {t.get('vehicle_id', ''):7s} "
                         f"tool={t.get('tool')} fallback={t.get('used_fallback')} "
                         f"cause={t.get('fallback_cause')} rejected={t.get('rejection_reason')}")
    lines.append("```")
    return "\n".join(lines)


def main(argv):
    roots = {os.path.basename(os.path.normpath(p)): p for p in argv[1:]}
    with open(os.path.join(DATA, "phase19_runs.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out, traces, by_class = [], defaultdict(list), Counter()
    for r in rows:
        if r["success"] == "True" or r["has_logs"] != "True" or r["arch"] == "B":
            continue
        d = os.path.join(roots[r["design"]], r["experiment_id"])
        primary, contrib, evidence, ev, turns, states = classify(r, d)
        by_class[(r["design"], r["arch"], primary)] += 1
        out.append({"design": r["design"], "experiment_id": r["experiment_id"],
                    "arch": r["arch"], "team_size": r["team_size"],
                    "network": r["network"], "failure": r["failure"], "seed": r["seed"],
                    "coverage": r["coverage"], "primary": primary,
                    "contributing": ";".join(contrib), "evidence": evidence})
        traces[primary].append(excerpt(r, ev, turns, states))
    with open(os.path.join(DATA, "phase19_failures.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    with open(os.path.join(DATA, "phase19_failure_traces.md"), "w", encoding="utf-8") as f:
        f.write("# Phase 19.4 - decision-trace excerpts by failure class\n\n"
                "Generated by scripts/phase19_failures.py; up to three runs per class.\n\n")
        for cls in sorted(traces):
            f.write(f"## {cls} ({len(traces[cls])} runs)\n\n")
            for t in traces[cls][:3]:
                f.write(t + "\n\n")
    b = [r for r in rows if r["arch"] == "B" and r["success"] != "True"]
    print(f"B failures (never redistributes work, by design): {len(b)}")
    for k, v in sorted(by_class.items()):
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
