"""Compare a waypoint probe run under dynamic zones against the static baseline (same model, same
seed, same situations - zones are not in the prompt and do not move the rng).

    python scripts/analyze_dynamic_probe.py runs/probe_llama31_8b_schema_v2 runs/probe_llama31_8b_dynamic_zones \
        --scenario configs/missions/search_relay_dynamic_001.json

Also replays the seeded situations to measure how often the drone was ALREADY inside an active zone
(the guardian's steer-out case) and how far the exit move is - no model involved for that part.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.safety_guardian import SafetyGuardian, SafetyLimits
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.waypoint_probe import make_situation


def pct(v):
    return "  n/a" if v is None else f"{v * 100:4.0f}%"


def checks_breakdown(rows, cond):
    counts = {}
    for r in rows:
        for name in (r[cond].get("failed_checks") or []):
            counts[name] = counts.get(name, 0) + 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("dynamic")
    ap.add_argument("--scenario", required=True, help="the dynamic scenario the second run used")
    args = ap.parse_args()
    base = json.load(open(os.path.join(args.baseline, "probe.json")))
    dyn = json.load(open(os.path.join(args.dynamic, "probe.json")))
    assert base["seed"] == dyn["seed"] and base["n"] == dyn["n"], "runs are not comparable (seed or n differ)"
    print(f"n = {dyn['n']}, seed {dyn['seed']}; model {dyn.get('model_card', {}) and dyn['model_card'].get('model')}\n")

    print(f"{'condition':9} {'static legal':>13} {'dynamic legal':>14} {'dynamic flown legal':>20} {'fallback':>9}")
    for cond in ("none", "context", "repair"):
        b, d = base["summary"][cond], dyn["summary"][cond]
        flown = d.get("flown_legal_rate") if cond == "repair" else d["raw_legal_rate"]
        print(f"{cond:9} {pct(b['raw_legal_rate']):>13} {pct(d['raw_legal_rate']):>14} {pct(flown):>20} {pct(d['fallback_rate']):>9}")
    r_b, r_d = base["summary"]["repair"], dyn["summary"]["repair"]
    print(f"\nrepair: needed repair {pct(r_b['repaired_rate'])} -> {pct(r_d['repaired_rate'])}; mean move "
          f"{r_b['mean_repair_distance_m']:.1f} m -> {r_d['mean_repair_distance_m']:.1f} m")
    fb_b, fb_d = base["summary"]["feedback"], dyn["summary"]["feedback"]
    print(f"feedback retries: legal {pct(fb_b['retry_legal_rate'])} -> {pct(fb_d['retry_legal_rate'])}, "
          f"same point again {pct(fb_b['retry_same_point_rate'])} -> {pct(fb_d['retry_same_point_rate'])}")
    print("\nchecks failing on the model's own first proposal (none):")
    print("   static :", checks_breakdown(base["rows"], "none") or "-")
    print("   dynamic:", checks_breakdown(dyn["rows"], "none") or "-")

    # replay the seeded situations to see how many start INSIDE an active zone
    scenario = load_scenario(args.scenario)
    guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(scenario))
    rng = random.Random(dyn["seed"])
    inside, moves = 0, []
    for _ in range(dyn["n"]):
        spec, belief = make_situation(scenario, rng)
        world = (belief.position[0] + spec.spawn_offset[0], belief.position[1] + spec.spawn_offset[1], belief.position[2])
        ev = guardian._exit_active_zone(belief, world)
        if ev is not None and ev.move_m is not None:
            inside += 1
            moves.append(ev.move_m)
    print(f"\nreplay: {inside} of {dyn['n']} situations start INSIDE an active zone (steer-out case)"
          + (f"; mean exit move {sum(moves) / len(moves):.1f} m, max {max(moves):.1f} m" if moves else ""))


if __name__ == "__main__":
    main()
