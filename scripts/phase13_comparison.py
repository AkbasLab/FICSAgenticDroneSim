"""Phase 13 architecture comparison - measured data for the paper figure.

    python scripts/phase13_comparison.py                 # 10 seeds, writes the JSON
    python scripts/phase13_comparison.py --seeds 20
    python scripts/make_paper_figures.py --only fig7     # then draw it

Runs the five architectures (A-E) under the four Phase 10 network conditions,
each with no failure and with Drone2 switched off at t = 1 s, on the canonical
scenario, and writes paper/figure_data/architectures.json. D uses the scripted
control backend, not a language model: this is the Phase 13 fairness check,
not the Phase 18 result.

Note on `severe`: Phase 17 found that this profile's 4 msg/s rate limit, not
its packet loss, decides what is delivered in the stepped simulator, so it
gives the same outcome for every seed. It is kept here because it is the
Phase 13 condition; the calibrated levels for the final experiment are in
configs/networks/final_profiles.yaml.
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.agents.llm_backends import ScriptedBackend
from agentic_uav.experiments import architectures as arch
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONDITIONS = ["nominal", "moderate", "severe", "partitioned"]
ARCHS = ["A", "B", "C", "D", "E"]
FAILURES = {"none": {}, "drone2_lost_t1": {"Drone2": 1.0}}


def ms(v):
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
    return round(m, 4), round(sd, 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--first-seed", type=int, default=17)
    args = ap.parse_args()
    from run_llm_agents import sensible_model

    sc = load_scenario(os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml"))
    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    runs, cells = [], []
    for k in ARCHS:
        for cond in CONDITIONS:
            for fname, kill in FAILURES.items():
                rs = []
                for seed in seeds:
                    be = ScriptedBackend(default=sensible_model) if k == "D" else None
                    r = arch.run_architecture(k, sc, lambda _v: MockVehicleAdapter(0.0),
                                              condition=cond, seed=seed, backend=be,
                                              stop_at=kill, heartbeat_interval_s=8.0)
                    survivors = len(sc.vehicles) - len(r.stopped)
                    row = {"architecture": k, "condition": cond, "failure": fname,
                           "seed": seed, "coverage": r.coverage,
                           "duplicated_sectors": r.duplicated_sectors,
                           "mission_time_s": round(r.mission_time_s, 2),
                           "drones_home": r.drones_home, "survivors": survivors,
                           "delivery_rate": round(r.delivery_rate, 4),
                           "success": r.coverage == 1.0 and r.drones_home == survivors}
                    runs.append(row)
                    rs.append(row)
                cell = {"architecture": k, "name": arch.spec(k).name, "condition": cond,
                        "failure": fname, "n": len(rs),
                        "success_rate": sum(r["success"] for r in rs) / len(rs)}
                for m in ("coverage", "duplicated_sectors", "mission_time_s", "delivery_rate"):
                    cell[f"{m}_mean"], cell[f"{m}_sd"] = ms([r[m] for r in rs])
                cells.append(cell)
                print(f"{k} {cond:11s} {fname:15s} cov {cell['coverage_mean']:.2f} "
                      f"dup {cell['duplicated_sectors_mean']:.1f} "
                      f"t {cell['mission_time_s_mean']:.0f} "
                      f"success {100 * cell['success_rate']:.0f}%")
    out = os.path.join(ROOT, "paper", "figure_data", "architectures.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"scenario": "search_relay_001", "seeds": seeds, "heartbeat_s": 8.0,
                   "planner_D": "scripted control backend (not a language model)",
                   "cells": cells, "runs": runs}, f, indent=1)
    print(f"\nwrote {out} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
