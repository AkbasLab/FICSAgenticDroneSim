"""The main factorial experiment (Phase 18).

A design file names the factors; this module turns it into one experiment
configuration per (architecture, team size, network, failure, seed), decides
for every finished run whether it is valid or excluded - by the predeclared
technical criteria in `exclusion_criteria.yaml` and nothing else - and reports
whether every cell has enough valid replications.

Three rules are enforced here rather than left to discipline:

  * **Common random numbers (18.1).** Every configuration in a design uses
    `crn: true` (one random stream per network link) and a generated scenario
    whose targets, restricted region, batteries and fault are decided by the
    seed alone - so for one seed every architecture faces the same mission.
  * **Held-out results stay held out (18.2).** A design on the `test` split
    runs only with an unchanged freeze, and the first test run seals the
    fingerprint (prompts included) into `configs/frozen/test_seal.json`. A
    later test run under a different fingerprint is refused: the prompt cannot
    be tuned after the held-out results have been seen.
  * **Exclusions are technical (exit criterion).** `classify()` reads the
    manifest, the log audit and the LLM transcripts. It never reads coverage,
    duplicates, time or any other outcome.
"""

import hashlib
import itertools
import json
import os
import time
from typing import Any, Dict, List, Optional

from .experiment_config import ARCHITECTURE_ALIASES, ExperimentConfig

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEAL_PATH = os.path.join(ROOT, "configs", "frozen", "test_seal.json")
DEFAULT_EXCLUSIONS = os.path.join(ROOT, "configs", "experiments", "exclusion_criteria.yaml")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()[:16]


def load_design(path) -> Dict[str, Any]:
    import yaml
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    for k in ("design_id", "split", "architectures", "team_sizes", "network_profiles",
              "failure_profiles", "seed_plan"):
        if k not in d:
            raise KeyError(f"design {path} is missing {k!r}")
    d["_path"] = path
    d["_sha256"] = _sha(path)
    return d


def load_exclusions(path=DEFAULT_EXCLUSIONS) -> Dict[str, Any]:
    import yaml
    with open(path, encoding="utf-8") as f:
        e = yaml.safe_load(f) or {}
    e["_path"] = path
    e["_sha256"] = _sha(path)
    return e


def team_sizes(design, stage="1"):
    ts = design["team_sizes"]
    if isinstance(ts, list):
        return list(ts)
    if stage == "all":
        return [n for k in sorted(ts) for n in ts[k]]
    return list(ts[f"stage{stage}"])


def seeds(design) -> List[int]:
    from ..simulator.scenario_family import seeds_for
    plan = design["seed_plan"]
    if plan.get("split", design["split"]) != design["split"]:
        raise ValueError("seed_plan.split must match the design's split")
    return seeds_for(design["split"], int(plan["count"]), start=int(plan.get("start", 1)),
                     skip=int(plan.get("skip", 0)))


def arch_key(a):
    return ARCHITECTURE_ALIASES.get(str(a).lower(), str(a).upper())


def run_id(design, key, n, net, fail, seed):
    return f"{design['design_id']}_{key}_n{n}_{net}_{fail}_s{seed}"


def cell_of(cfg):
    return (cfg.architecture_key, cfg.team_size, cfg.network_profile, cfg.failure_profile)


def expand(design, stage="1") -> List[ExperimentConfig]:
    out = []
    for a, n, net, fail, seed in itertools.product(
            design["architectures"], team_sizes(design, stage),
            design["network_profiles"], design["failure_profiles"], seeds(design)):
        key = arch_key(a)
        out.append(ExperimentConfig(
            experiment_id=run_id(design, key, n, net, fail, seed),
            architecture=a, scenario=f"family:{design['split']}",
            team_size=int(n), network_profile=net, failure_profile=fail,
            random_seed=int(seed), planner=design.get("planner", "scripted"),
            heartbeat_s=float(design.get("heartbeat_s", 8.0)),
            max_steps=int(design.get("max_steps", 600)),
            crn=True, fault_interrupts_skill=bool(design.get("fault_interrupts_skill", True)),
            notes=f"factorial {design['design_id']}"))
    return out


def cells(design, stage="1"):
    return list(itertools.product(
        [arch_key(a) for a in design["architectures"]], team_sizes(design, stage),
        design["network_profiles"], design["failure_profiles"]))


# --- 18.2 the held-out seal --------------------------------------------------------


def seal_path(design_id):
    """Each held-out design has its own seal. main_v1's keeps the original name."""
    if design_id == "main_v1":
        return SEAL_PATH
    return os.path.join(os.path.dirname(SEAL_PATH), f"test_seal_{design_id}.json")


def _sealed_seeds_of_other_designs(design):
    """{design_id: seeds} for every other sealed held-out design."""
    import glob
    out = {}
    folder = os.path.dirname(SEAL_PATH)
    for path in glob.glob(os.path.join(folder, "test_seal*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                seal = json.load(f)
        except (OSError, ValueError):
            continue
        did = seal.get("design_id")
        if did == design["design_id"]:
            continue
        used = seal.get("seeds")
        if used is None:                       # seals written before seeds were stored
            other = os.path.join(ROOT, "configs", "experiments",
                                 "factorial_main.yaml" if did == "main_v1"
                                 else f"factorial_{did}.yaml")
            if os.path.exists(other):
                used = seeds(load_design(other))
        out[did] = list(used or [])
    return out


def check_test_split(design, fingerprint_now, exclusions):
    """Raise unless a test-split design may run now. Returns the seal (written
    on the first call). Each held-out design is sealed separately, and no two
    may share a held-out seed: a follow-up design is evaluated on seeds that
    no earlier result was produced from."""
    if design["split"] != "test":
        return None
    from .freeze import check
    r = check()
    if not r["ok"]:
        raise RuntimeError("held-out runs need an unchanged freeze:\n  "
                           + "\n  ".join(r["changes"][:10]))
    mine = set(seeds(design))
    for other, used in _sealed_seeds_of_other_designs(design).items():
        clash = sorted(mine & set(used))
        if clash:
            raise RuntimeError(f"held-out seeds {clash[:5]}... were already used by "
                               f"sealed design {other}; a new design needs seeds no "
                               "earlier result has seen")
    path = seal_path(design["design_id"])
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            seal = json.load(f)
        if seal["fingerprint"] != fingerprint_now:
            changed = sorted(g for g in fingerprint_now
                             if fingerprint_now.get(g) != seal["fingerprint"].get(g))
            raise RuntimeError(
                f"the configuration has changed since held-out results were first "
                f"produced ({seal['sealed_at']}): {', '.join(changed)}. Results on the "
                "test split may not be produced by a configuration tuned after seeing "
                "them. Use a new design on the development split instead.")
        if seal.get("exclusions_sha256") != exclusions["_sha256"]:
            raise RuntimeError("the exclusion criteria changed after held-out results "
                               "were first produced; they must be declared in advance")
        return seal
    seal = {"sealed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "design_id": design["design_id"], "design_sha256": design["_sha256"],
            "fingerprint": fingerprint_now,
            "exclusions_sha256": exclusions["_sha256"],
            "seeds": sorted(mine),
            "note": "Written by the first held-out run. From here on the prompts, "
                    "rules, metrics, profiles, scenarios and exclusion criteria are "
                    "fixed for the test split."}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seal, f, indent=1, sort_keys=True)
    return seal


# --- exit criterion: classification -------------------------------------------------


def _read(directory, name):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def transcript_problems(directory, manifest) -> List[str]:
    """18.4: for an agentic run, every model call must be saved with its input,
    its structured output, its validation result, the action taken, and any
    fallback. Returns what is missing."""
    if not _is_agentic(manifest.get("architecture_key")):
        return []
    out = []
    events_path = os.path.join(directory, "events.jsonl")
    called = {}
    if os.path.exists(events_path):
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                if e["type"] == "LLM_CALLED":
                    called[e["vehicle"]] = called.get(e["vehicle"], 0) + 1
    for vid, n in sorted(called.items()):
        t = _read(directory, os.path.join("llm", f"{vid}.json"))
        if t is None:
            out.append(f"{vid}: no saved transcript")
            continue
        turns = t.get("turns", [])
        if len(turns) != n:
            out.append(f"{vid}: {n} model decisions in the events, {len(turns)} saved")
        if not t.get("model"):
            out.append(f"{vid}: no model card in the transcript")
        for turn in turns:
            where = f"{vid} step {turn.get('step')}"
            problem = _turn_problem(turn)
            if problem:
                out.append(f"{where}: {problem}")
                break
    return out


def _turn_problem(turn):
    """What a saved decision is missing, or None. A decision the model made
    needs its input, raw output, parsed output, action and result; every model
    attempt needs its reply (or why there was none) and its validation result;
    a fallback needs its cause."""
    exchanges = turn.get("exchanges") or []
    if exchanges and not turn.get("user_prompt"):
        return "model input not saved"
    for ex in exchanges:
        if ex.get("transport_error"):
            continue
        if ex.get("raw_response") is None:
            return f"attempt {ex.get('attempt')}: reply not saved"
        if ex.get("validation") is None:
            return f"attempt {ex.get('attempt')}: validation result not saved"
    if turn.get("used_fallback"):
        if not turn.get("fallback_cause"):
            return "fallback without a cause"
        return None
    missing = [k for k in ("user_prompt", "raw_response", "parsed", "tool", "outcome")
               if not turn.get(k)]
    return f"missing {', '.join(missing)}" if missing else None


def classify(directory, expected: ExperimentConfig, exclusions, fingerprint) -> Dict[str, Any]:
    """`valid` or `excluded`, with the criteria that applied. Outcome fields
    are never consulted."""
    from .pilot import audit_run
    m = _read(directory, "manifest.json") or {}
    reasons = []
    crit = {c["id"]: c for c in exclusions.get("criteria", [])}

    status = m.get("status")
    system_failure = False
    if status != "completed":
        etype = m.get("error_type") or "unknown"
        infra = set(crit.get("X1_infrastructure_error", {}).get("exception_types", []))
        # A run whose manifest still says "running" with no error recorded was
        # never allowed to finish: the process was killed, the window closed,
        # or the machine slept. An exception in the system under test is
        # always recorded (error_type), so this is the machine, not the system
        # - X1. Found in main_v2: one such run was counted as a DV2 failure
        # and skipped on resume instead of being re-run.
        if status == "running" and not m.get("error_type"):
            etype = "process ended without finishing (killed or interrupted)"
            reasons.append(f"X1_infrastructure_error: {etype}")
        elif etype in infra or not m:
            reasons.append(f"X1_infrastructure_error: {etype}: {(m.get('error_message') or '')[:80]}")
        else:
            system_failure = True               # a result, not an exclusion

    if status == "completed" and "X2_incomplete_logs" in crit:
        a = audit_run(directory)
        if a["problems"]:
            reasons.append("X2_incomplete_logs: " + "; ".join(a["problems"][:3]))
        tp = transcript_problems(directory, m)
        if tp:
            reasons.append("X2_incomplete_logs: transcript " + "; ".join(tp[:3]))

    if "X3_configuration_mismatch" in crit and m:
        if fingerprint and m.get("freeze_fingerprint") and m["freeze_fingerprint"] != fingerprint:
            reasons.append("X3_configuration_mismatch: freeze fingerprint differs")
        if m.get("random_seed") != expected.random_seed:
            reasons.append("X3_configuration_mismatch: seed")
        if m.get("architecture_key") != expected.architecture_key:
            reasons.append("X3_configuration_mismatch: architecture")
        if m.get("team") and len(m["team"]) != expected.team_size:
            reasons.append("X3_configuration_mismatch: team size")

    if "X4_model_unreachable" in crit and _is_agentic(m.get("architecture_key")):
        frac = _transport_failure_fraction(directory)
        limit = float(crit["X4_model_unreachable"].get("max_transport_failure_fraction", 0.2))
        if frac is not None and frac > limit:
            reasons.append(f"X4_model_unreachable: {100 * frac:.0f}% of model calls "
                           f"never reached the model")

    return {"status": "excluded" if reasons else "valid", "reasons": reasons,
            "system_failure": system_failure}


def _is_agentic(key) -> bool:
    """D and every model-driven variant of it (DV2, the ablations)."""
    from .architectures import ALL
    sp = ALL.get(key)
    return sp is not None and sp.policy == "llm"


def _transport_failure_fraction(directory) -> Optional[float]:
    d = os.path.join(directory, "llm")
    if not os.path.isdir(d):
        return None
    attempts = failed = 0
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        t = _read(d, name) or {}
        for turn in t.get("turns", []):
            for ex in turn.get("exchanges", []) or []:
                attempts += 1
                if str(ex.get("transport_error") or "").startswith("backend:"):
                    failed += 1
    return None if attempts == 0 else failed / attempts


# --- the per-run row and the cell report ----------------------------------------------

OUTCOMES = ("coverage", "duplicated_sectors", "mission_time_s", "drones_home",
            "delivery_rate", "guardian_interventions", "targets_found")


def row(cfg, directory, verdict, attempt):
    r = _read(directory, "result.json") or {}
    m = _read(directory, "manifest.json") or {}
    survivors = cfg.team_size - len([x for x in str(r.get("stopped", "-")).split(",")
                                     if x and x != "-"])
    out = {"experiment_id": cfg.experiment_id, "architecture": cfg.architecture_key,
           "team_size": cfg.team_size, "network": cfg.network_profile,
           "failure": cfg.failure_profile, "seed": cfg.random_seed, "attempt": attempt,
           "status": verdict["status"], "exclusion": " | ".join(verdict["reasons"]),
           "system_failure": verdict["system_failure"],
           "wall_clock_s": m.get("wall_clock_s")}
    for k in OUTCOMES:
        out[k] = r.get(k)
    out["mission_success"] = (bool(r) and r.get("coverage") == 1.0
                              and r.get("drones_home") == survivors)
    if verdict["system_failure"]:
        out["mission_success"] = False
    return out


def sufficiency(rows, design, exclusions, stage="1"):
    need = int(design.get("min_valid_override") or exclusions.get("min_valid_per_cell", 18))
    by = {}
    for r in rows:
        by.setdefault((r["architecture"], r["team_size"], r["network"], r["failure"]), []).append(r)
    out = []
    for c in cells(design, stage):
        rs = by.get(c, [])
        valid = [r for r in rs if r["status"] == "valid"]
        out.append({"architecture": c[0], "team_size": c[1], "network": c[2], "failure": c[3],
                    "planned": len(seeds(design)), "run": len(rs), "valid": len(valid),
                    "excluded": len(rs) - len(valid), "required": need,
                    "sufficient": len(valid) >= need})
    return out


def mean_sd(vals):
    import math
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    return m, sd


def comparison(rows, factor):
    """Mean outcomes for architecture x `factor` ("network" or "failure"),
    valid runs only - the two comparisons Phase 18 names as most important."""
    by = {}
    for r in rows:
        if r["status"] == "valid":
            by.setdefault((r["architecture"], r[factor]), []).append(r)
    out = []
    for (a, f), rs in sorted(by.items()):
        line = {"architecture": a, factor: f, "n": len(rs),
                "success_rate": sum(1 for r in rs if r["mission_success"]) / len(rs)}
        for k in ("coverage", "duplicated_sectors", "mission_time_s"):
            line[f"{k}_mean"], line[f"{k}_sd"] = mean_sd([r[k] for r in rs])
        out.append(line)
    return out
