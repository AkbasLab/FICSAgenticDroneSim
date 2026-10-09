"""When a model proposes a waypoint, how often is it legal - and what helps?

    python scripts/probe_waypoints.py --n 100                       # scripted stand-in (plumbing check)
    python scripts/probe_waypoints.py --backend ollama --n 100 --save runs/probe_llama31_8b

Every condition sees the same seeded situations, so the comparison is fair.
Nothing flies; "legal" is judged by the SafetyGuardian's own checks.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.waypoint_probe import run_probe

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


def _pct(v):
    return "  n/a" if v is None else f"{v * 100:4.0f}%"


def print_summary(result):
    s = result["summary"]
    print(f"\nn = {result['n']} seeded situations, seed {result['seed']}\n")
    print(f"{'condition':10} {'chose waypoint':>15} {'raw point legal':>16} {'flown legal':>12} {'fallback':>9}")
    for cond in ("none", "context", "repair"):
        e = s[cond]
        flown = _pct(e.get("flown_legal_rate")) if cond == "repair" else _pct(e["raw_legal_rate"])
        print(f"{cond:10} {_pct(e['waypoint_rate']):>15} {_pct(e['raw_legal_rate']):>16} {flown:>12} {_pct(e['fallback_rate']):>9}")
    r = s["repair"]
    print(f"\nrepair: {_pct(r['repaired_rate'])} of waypoints needed repair, mean move "
          f"{r['mean_repair_distance_m'] if r['mean_repair_distance_m'] is None else round(r['mean_repair_distance_m'], 1)} m")
    f = s["feedback"]
    print(f"feedback: {f['illegal_first_proposals']} illegal first proposals -> retried with a waypoint "
          f"{f['retried_with_a_waypoint']}, legal on retry {_pct(f['retry_legal_rate'])}, "
          f"same point again {_pct(f['retry_same_point_rate'])}, gave up {_pct(f['retry_gave_up_rate'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--backend", choices=["scripted", "ollama"], default="scripted")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--save", default=None)
    parser.add_argument("--show-zones", action="store_true",
                        help="GMB: put the no-fly zones active at the decision time into the model's prompt")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    card = None
    if args.backend == "ollama":
        from fics_drone.agents.ollama_backend import OllamaBackend
        backend = OllamaBackend(args.model)
        card = backend.card()
        for w in card.warnings():
            print(f"WARNING: {w}")
        print(f"loading {args.model} ... ready in {backend.warm_up():.1f}s", flush=True)
    else:
        backend = ScriptedBackend()

    def progress(i, n):
        if i % 10 == 0 or i == n:
            print(f"  {i}/{n}", flush=True)

    result = run_probe(backend, scenario, n=args.n, seed=args.seed, timeout_s=args.timeout, progress=progress,
                       show_zones=args.show_zones)
    print_summary(result)

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, "probe.json"), "w", encoding="utf-8") as f:
            json.dump({"model_card": card.to_dict() if card else None, **result}, f, indent=2, default=str)
        print(f"\nsaved to {args.save}")


if __name__ == "__main__":
    main()
