"""Pilot experiments (Phase 17.1) and the log-completeness audit (exit criterion).

A pilot matrix is a small factorial design expanded into ordinary experiment
configurations, so pilots go through exactly the runner the final experiments
will use - a pilot that used a different code path would debug the wrong thing.

`audit_run` answers the second half of the Phase 17 exit criterion: does the
runner produce complete, interpretable logs? It checks each result directory
for the files, the event types the configuration implies, per-drone state, and
- the part that catches real defects - that the event stream *agrees* with the
reported result: the sectors the events say were swept must be the sectors the
result counts, and the duplicates likewise. A log that disagrees with its own
summary cannot be used to explain that summary.
"""

import itertools
import math
import os
from typing import Any, Dict, List

from .experiment_config import ARCHITECTURE_ALIASES, ExperimentConfig


def load_matrix(path) -> Dict[str, Any]:
    import yaml
    with open(path, encoding="utf-8") as f:
        m = yaml.safe_load(f) or {}
    required = ("pilot_id", "architectures", "team_sizes", "network_profiles",
                "failure_profile", "seeds")
    missing = [k for k in required if k not in m]
    if missing:
        raise KeyError(f"pilot matrix is missing {', '.join(missing)}")
    return m


def expand(matrix) -> List[ExperimentConfig]:
    """Every combination, with an experiment_id that names its cell and seed.
    Refuses held-out seeds: a pilot that looked at them would spend them."""
    from .freeze import check_seed_use
    check_seed_use(matrix["seeds"], purpose=f"pilot {matrix['pilot_id']}")
    out = []
    for arch, n, net, seed in itertools.product(
            matrix["architectures"], matrix["team_sizes"],
            matrix["network_profiles"], matrix["seeds"]):
        key = ARCHITECTURE_ALIASES.get(str(arch).lower(), str(arch).upper())
        out.append(ExperimentConfig(
            experiment_id=f"{matrix['pilot_id']}_{key}_n{n}_{net}_s{seed}",
            architecture=arch, scenario=matrix.get("scenario", "search_relay_001"),
            team_size=int(n), network_profile=net,
            failure_profile=matrix["failure_profile"], random_seed=int(seed),
            planner=matrix.get("planner", "scripted"),
            heartbeat_s=float(matrix.get("heartbeat_s", 8.0)),
            max_steps=int(matrix.get("max_steps", 600)),
            notes=f"pilot {matrix['pilot_id']}"))
    return out


# --- the audit ----------------------------------------------------------------

#: Event types every completed run must contain, whatever the architecture.
ALWAYS = ("MISSION_STARTED", "MISSION_COMPLETED", "OBSERVATION_RECEIVED",
          "BELIEF_UPDATED", "DECISION_PROPOSED", "SKILL_STARTED",
          "SKILL_COMPLETED")
FILES = ("manifest.json", "config.yaml", "events.jsonl", "result.json",
         "tracks.json")


def audit_run(directory) -> Dict[str, Any]:
    """Problems with one result directory. An empty `problems` list = complete."""
    from .timeline import build_timeline, findings, load_run
    problems: List[str] = []
    for name in FILES:
        if not os.path.exists(os.path.join(directory, name)):
            problems.append(f"missing {name}")
    run = load_run(directory)
    m, ev, result = run["manifest"], run["events"], run["result"]
    if m.get("status") != "completed":
        problems.append(f"run status {m.get('status')!r}: {m.get('error_message')}")
    if not ev:
        problems.append("event stream is empty")
        return {"directory": directory, "problems": problems}

    times = [e["t"] for e in ev]
    if any(b < a - 1e-9 for a, b in zip(times, times[1:])):
        problems.append("events are not in time order")
    types = {e["type"] for e in ev}
    for t in ALWAYS:
        if t not in types:
            problems.append(f"no {t} events")
    team = m.get("team") or sorted({e["vehicle"] for e in ev
                                    if str(e.get("vehicle", "")).startswith("Drone")})
    faults = {v: t for v, t in (m.get("faults") or {}).items() if v in team}
    if faults and "FAULT_INJECTED" not in types:
        problems.append("a fault was configured but no FAULT_INJECTED event")
    if len(team) > 1 and "MESSAGE_SENT" not in types:
        problems.append("a multi-drone team sent no messages")
    if _agentic(m.get("architecture_key")) and "LLM_CALLED" not in types:
        problems.append("agentic architecture with no LLM_CALLED events")

    # per-drone state needed to read the run
    for v in team:
        beliefs = [e for e in ev if e["type"] == "BELIEF_UPDATED" and e["vehicle"] == v]
        if not beliefs:
            problems.append(f"{v}: no belief updates")
            continue
        if all(e["data"].get("role") is None for e in beliefs):
            problems.append(f"{v}: role never recorded")
        if all(e["data"].get("position") is None for e in beliefs):
            problems.append(f"{v}: position never recorded")
    tracks = (run["tracks"] or {}).get("tracks", {})
    for v in team:
        if not tracks.get(v):
            problems.append(f"{v}: no flown track")

    # the event stream must agree with the reported result
    tl = None
    try:
        tl = build_timeline(run)
    except Exception as e:                                      # noqa: BLE001
        problems.append(f"timeline could not be built: {type(e).__name__}: {e}")
    if tl is not None and result:
        swept = {}
        for p in tl["progress"]:
            swept.setdefault(p["sector"], set()).add(p["vehicle"])
        if len(swept) != result.get("sectors_searched"):
            problems.append(f"events show {len(swept)} sectors swept, result says "
                            f"{result.get('sectors_searched')}")
        dup = sum(1 for vs in swept.values() if len(vs) > 1)
        if dup != result.get("duplicated_sectors"):
            problems.append(f"events show {dup} duplicated sectors, result says "
                            f"{result.get('duplicated_sectors')}")
    return {"directory": directory, "problems": problems,
            "findings": findings(tl) if tl else []}


# --- summaries -----------------------------------------------------------------

METRICS = ("coverage", "duplicated_sectors", "mission_time_s", "drones_home",
           "delivery_rate", "guardian_interventions")


def _ms(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    return m, sd


def summarise(rows) -> List[Dict[str, Any]]:
    """One line per cell (architecture, team size, network): mean and sd over
    seeds, the mission success rate, and whether the seeds changed anything."""
    cells = {}
    for r in rows:
        cells.setdefault((r["architecture"], r["team_size"], r["network"]), []).append(r)
    out = []
    for (a, n, net), rs in cells.items():          # matrix order
        line = {"architecture": a, "team_size": n, "network": net, "runs": len(rs)}
        for k in METRICS:
            m, sd = _ms([r.get(k) for r in rs])
            line[f"{k}_mean"], line[f"{k}_sd"] = m, sd
        line["success_rate"] = sum(1 for r in rs if r.get("success")) / len(rs)
        # Outcomes only: delivery rate always moves with the seed under loss, so
        # it says nothing about whether the seed changed what the team did.
        outcome = ("coverage", "duplicated_sectors", "mission_time_s", "drones_home")
        line["seeds_identical"] = len({tuple(r.get(k) for k in outcome) for r in rs}) == 1
        line["incomplete_logs"] = sum(1 for r in rs if r.get("audit_problems"))
        out.append(line)
    return out


def success(result, team_size):
    """Mission success for the pilot: every sector searched and every surviving
    drone landed at home."""
    if not result:
        return False
    survivors = team_size - len([s for s in str(result.get("stopped", "-")).split(",")
                                 if s and s != "-"])
    return result.get("coverage") == 1.0 and result.get("drones_home") == survivors


def _agentic(key):
    from .architectures import ALL
    sp = ALL.get(key)
    return sp is not None and sp.policy == "llm"
