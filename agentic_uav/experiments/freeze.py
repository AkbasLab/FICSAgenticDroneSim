"""Freeze the final configuration (Phase 17.4).

After the pilots: stop changing prompts, task rules and metrics; freeze the
network profiles and the scenario families; create held-out random seeds.

"Stop changing" is only a promise unless something notices a change. This
module takes a fingerprint of everything 17.4 names, in six groups, and stores
it in `configs/frozen/freeze.json`:

  prompts        the LLM system prompt, tool set and decision schema limits,
                 plus the guardrail benchmark's prompt and prompt suite
  task_rules     bid weights, leases, bid window, health thresholds, the agent's
                 waiting rules - and the source of the files that implement them
  metrics        the metric definitions and score weights, and evaluation.py
  networks       the final calibrated profiles, message lifetimes, network model
  scenarios      every mission file and the named failure profiles
  seeds          the held-out seeds, disjoint from every pilot and calibration seed

Each group records the value of every item, not just a hash, so `check()` can
say *what* changed. Source files are hashed after normalising line endings, so
the same file checked out on Windows and Linux fingerprints the same.

A deliberate change is allowed - frozen does not mean wrong forever - but it
has to be made with `scripts/freeze.py --refreeze --reason "..."`, which
records the reason in the freeze file's history. Results produced before and
after a refreeze are then known not to be comparable.
"""

import hashlib
import inspect
import json
import os
import random
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FREEZE_PATH = os.path.join(ROOT, "configs", "frozen", "freeze.json")
HELDOUT_PATH = os.path.join(ROOT, "configs", "frozen", "heldout_seeds.yaml")

HELDOUT_COUNT = 100
HELDOUT_TAG = "FICSAgenticDroneSim/heldout/v1"
HELDOUT_RANGE = (10_000, 99_999)

#: Source files whose *logic* is a task rule, a metric, or the network model.
#: Constants alone would not notice a change to how a bid is compared.
RULE_SOURCES = {
    "task_rules": ["agentic_uav/coordination/bidding.py",
                   "agentic_uav/coordination/task_allocator.py",
                   "agentic_uav/coordination/tasks.py",
                   "agentic_uav/coordination/roles.py",
                   "agentic_uav/coordination/role_manager.py",
                   "agentic_uav/agents/persistent_agent.py",
                   "agentic_uav/agents/search_policy.py",
                   "agentic_uav/agents/safety_guardian.py",
                   # added in the pre-run review: how messages are delivered,
                   # how the centralized controller behaves, how skills report
                   "agentic_uav/coordination/message_bus.py",
                   "agentic_uav/coordination/fleet_controller.py",
                   "agentic_uav/control/skill_executor.py"],
    "metrics": ["agentic_uav/experiments/evaluation.py",
                "agentic_uav/experiments/metrics.py"],
    "networks": ["agentic_uav/coordination/network_model.py",
                 "agentic_uav/coordination/comms_conditions.py",
                 "configs/networks/final_profiles.yaml"],
    # Phase 18: how scenarios are generated per seed, and how runs are judged
    "scenarios": ["agentic_uav/simulator/scenario_family.py"],
    "design": ["configs/experiments/factorial_main.yaml",
               "configs/experiments/factorial_gemini.yaml",
               "configs/experiments/exclusion_criteria.yaml",
               "agentic_uav/experiments/factorial.py",
               "agentic_uav/experiments/pilot.py",
               # the run loop decides scheduling and how a fault lands
               "agentic_uav/experiments/architectures.py"],
    "prompts": ["agentic_uav/agents/context_builder.py",
                # when the model is consulted, corrected, or bypassed
                "agentic_uav/agents/llm_policy.py",
                "agentic_uav/agents/llm_tools.py",
                "agentic_uav/agents/decision_schema.py",
                "configs/benchmark/guardrail_prompts.yaml"],
}


def _norm_bytes(path):
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def file_hash(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return "missing"
    return hashlib.sha256(_norm_bytes(path)).hexdigest()[:16]


def _h(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()[:16]


# --- the snapshot -----------------------------------------------------------


def snapshot() -> Dict[str, Dict[str, Any]]:
    """Current values of everything 17.4 freezes, grouped."""
    from ..agents import context_builder, decision_schema, llm_tools
    from ..agents import persistent_agent as pa
    from ..agents import search_policy as sp
    from ..coordination import bidding, comms_conditions as cc, roles
    from ..coordination import task_allocator as ta
    from . import evaluation as ev
    from . import experiment_config as ec
    from . import guardrail_benchmark as gb

    groups: Dict[str, Dict[str, Any]] = {}

    groups["prompts"] = {
        "llm_system_prompt": _h(context_builder.SYSTEM_PROMPT),
        "llm_tools": {t.name: f"{t.category}:{_h(repr(t.params))}"
                      for t in llm_tools.TOOLS},
        "reason_codes": list(llm_tools.REASON_CODES),
        "decision_limits": {"MAX_OUTGOING_MESSAGES": decision_schema.MAX_OUTGOING_MESSAGES,
                            "MAX_PAYLOAD_KEYS": decision_schema.MAX_PAYLOAD_KEYS,
                            "MAX_RECIPIENTS": decision_schema.MAX_RECIPIENTS},
        "benchmark_system_prompt": _h(gb.SYSTEM_PROMPT),
    }
    groups["task_rules"] = {
        "bid_weights": bidding.BidWeights().as_dict(),
        "bid_limits": {"MAX_RANGE_M": bidding.MAX_RANGE_M,
                       "MAX_WORKLOAD": bidding.MAX_WORKLOAD},
        "lease_s": ta.DEFAULT_LEASE_S, "bid_window_s": ta.DEFAULT_BID_WINDOW_S,
        "health_thresholds": {"suspect": roles.SUSPECT_AFTER_MISSED,
                              "unreachable": roles.UNREACHABLE_AFTER_MISSED,
                              "failed": roles.FAILED_AFTER_MISSED},
        "agent_waiting": {k: getattr(pa, k) for k in (
            "MAX_IDLE_ROUNDS", "GROUND_WAIT_S", "MAX_GROUND_WAITS", "IDLE_WAIT_S",
            "MAX_IDLE_WAITS", "STAND_BY_FOR_TEAMMATES", "GOSSIP_COMPLETIONS",
            "STAND_BY_LEASES")},
        "search": {k: getattr(sp, k) for k in (
            "DEFAULT_SPEED", "DEFAULT_TOLERANCE", "LANE_SPACING", "LEG_TIMEOUT")},
    }
    groups["metrics"] = {
        "primary_definitions": _h(ev.PRIMARY_METRIC_DEFINITIONS),
        "derived_definitions": _h(ev.DERIVED_METRIC_DEFINITIONS),
        "score_weights": _h(ev.DEFAULT_WEIGHTS),
        "collision_radius_m": ev.COLLISION_RADIUS_M,
        "separation_sample_dt_s": ev.SEPARATION_SAMPLE_DT_S,
    }
    groups["networks"] = {
        "final_profiles": {n: cc.condition(n).describe() for n in cc.FINAL},
        "message_ttls": {getattr(k, "value", str(k)): v
                         for k, v in cc.TTL_BY_TYPE.items()},
        "default_ttl_s": cc.DEFAULT_TTL_S,
    }
    groups["scenarios"] = {
        "missions": {name: file_hash(os.path.join("configs", "missions", name))
                     for name in sorted(os.listdir(os.path.join(ROOT, "configs", "missions")))
                     if name.endswith((".yaml", ".yml", ".json"))},
        "failure_profiles": ec.FAILURE_PROFILES,
        "family_parameters": _family_parameters(),
    }
    held = heldout_seeds()
    groups["seeds"] = {"heldout_count": len(held), "heldout": _h(held),
                       "heldout_tag": HELDOUT_TAG}

    for group, files in RULE_SOURCES.items():
        groups.setdefault(group, {})["sources"] = {f: file_hash(f) for f in files}
    return groups


def _family_parameters():
    try:
        from ..simulator import scenario_family
        return {"parameters": scenario_family.PARAMETERS,
                "quadrants": scenario_family.QUADRANTS,
                "max_team": scenario_family.MAX_TEAM}
    except Exception as e:                                      # noqa: BLE001
        return f"unavailable: {e}"


def fingerprint(groups) -> Dict[str, str]:
    return {g: _h(v) for g, v in sorted(groups.items())}


# --- held-out seeds ----------------------------------------------------------


def development_seeds() -> List[int]:
    """Every seed used during development - pilots, calibration, the batch
    examples - collected from the config files, so held-out seeds can be
    guaranteed never to have been looked at."""
    import yaml
    used = set()
    for sub in ("experiments", "networks"):
        d = os.path.join(ROOT, "configs", sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
                except Exception:                               # noqa: BLE001
                    continue
            for item in (data if isinstance(data, list) else [data]):
                if not isinstance(item, dict):
                    continue
                for k in ("seeds",):
                    used.update(int(s) for s in item.get(k, []) or [])
                if "random_seed" in item:
                    used.add(int(item["random_seed"]))
    return sorted(used)


def validation_seeds() -> List[int]:
    """Seeds the Phase 17 pilots and the calibration used: the validation split
    of 18.2. Read from the pilot matrices (`pilot_id`) and calibration ladders
    (`loss_axis`), not from every config, so a development design does not turn
    its own seeds into validation seeds by listing them."""
    import yaml
    used = set()
    for sub in ("experiments", "networks"):
        d = os.path.join(ROOT, "configs", sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
                except Exception:                               # noqa: BLE001
                    continue
            if isinstance(data, dict) and ("pilot_id" in data or "loss_axis" in data):
                used.update(int(x) for x in data.get("seeds", []) or [])
    return sorted(used)


def generate_heldout(count=HELDOUT_COUNT, exclude=()) -> List[int]:
    """Deterministic from a fixed tag, so anyone can regenerate and verify
    them; drawn from a range no development seed uses."""
    rng = random.Random(HELDOUT_TAG)
    lo, hi = HELDOUT_RANGE
    exclude = set(exclude)
    out = []
    while len(out) < count:
        s = rng.randint(lo, hi)
        if s not in exclude and s not in out:
            out.append(s)
    return out


def heldout_seeds() -> List[int]:
    if not os.path.exists(HELDOUT_PATH):
        return []
    import yaml
    with open(HELDOUT_PATH, encoding="utf-8") as f:
        return [int(s) for s in (yaml.safe_load(f) or {}).get("heldout_seeds", [])]


def write_heldout():
    import yaml
    seeds = generate_heldout(exclude=development_seeds())
    os.makedirs(os.path.dirname(HELDOUT_PATH), exist_ok=True)
    with open(HELDOUT_PATH, "w", encoding="utf-8") as f:
        f.write("# Held-out seeds for the final experiments (Phase 17.4).\n"
                "# Never use these in a pilot, a calibration or a debugging run.\n"
                f"# Generated by random.Random({HELDOUT_TAG!r}) in "
                f"{HELDOUT_RANGE[0]}..{HELDOUT_RANGE[1]},\n"
                "# excluding every seed in configs/experiments and configs/networks.\n")
        yaml.safe_dump({"heldout_seeds": seeds}, f, sort_keys=False)
    return seeds


def check_seed_use(seeds, purpose="development"):
    """Raise if a development run is about to use a held-out seed."""
    held = set(heldout_seeds())
    clash = sorted(set(int(s) for s in seeds) & held)
    if clash:
        raise ValueError(f"{purpose} run uses held-out seed(s) {clash}; those are "
                         "reserved for the final experiments")


# --- freeze file ------------------------------------------------------------


def write(reason="initial freeze after the Phase 17 pilots"):
    groups = snapshot()
    history = []
    if os.path.exists(FREEZE_PATH):
        with open(FREEZE_PATH, encoding="utf-8") as f:
            history = json.load(f).get("history", [])
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reason": reason,
             "fingerprint": fingerprint(groups)}
    data = {"frozen_at": entry["at"], "fingerprint": entry["fingerprint"],
            "groups": groups, "history": history + [entry]}
    os.makedirs(os.path.dirname(FREEZE_PATH), exist_ok=True)
    with open(FREEZE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True, default=str)
    return data


def load():
    if not os.path.exists(FREEZE_PATH):
        return None
    with open(FREEZE_PATH, encoding="utf-8") as f:
        return json.load(f)


def diff(frozen_groups, current_groups) -> List[str]:
    """Human-readable list of what changed since the freeze."""
    out = []
    for g in sorted(set(frozen_groups) | set(current_groups)):
        a, b = frozen_groups.get(g, {}), current_groups.get(g, {})
        a, b = json.loads(json.dumps(a, default=str)), json.loads(json.dumps(b, default=str))
        for k in sorted(set(a) | set(b)):
            if a.get(k) == b.get(k):
                continue
            if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
                for kk in sorted(set(a[k]) | set(b[k])):
                    if a[k].get(kk) != b[k].get(kk):
                        out.append(f"{g}.{k}.{kk}: {a[k].get(kk)!r} -> {b[k].get(kk)!r}")
            else:
                out.append(f"{g}.{k}: {str(a.get(k))[:60]!r} -> {str(b.get(k))[:60]!r}")
    return out


def check() -> Dict[str, Any]:
    """Compare the code and configs now with the freeze. `ok` is False if
    anything frozen has changed, or the held-out seeds overlap development."""
    frozen = load()
    if frozen is None:
        return {"ok": False, "frozen": False, "changes": ["no freeze file - run "
                                                          "scripts/freeze.py --write"]}
    now = snapshot()
    changes = diff(frozen["groups"], now)
    held = set(heldout_seeds())
    overlap = sorted(held & set(development_seeds()))
    if overlap:
        changes.append(f"seeds: held-out seeds also used in development: {overlap}")
    return {"ok": not changes, "frozen": True, "frozen_at": frozen.get("frozen_at"),
            "changes": changes, "fingerprint": fingerprint(now)}
