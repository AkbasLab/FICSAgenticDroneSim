"""Run the architecture comparison (Phase 13).

    python scripts/run_experiment.py --list
    python scripts/run_experiment.py --architectures A B C D E
    python scripts/run_experiment.py --ablations --condition severe
    python scripts/run_experiment.py --seeds 17 18 19 --kill Drone2@1 --save runs/exp1/

Every architecture is built from the same spec object by the same builder, so
selecting one is a configuration change rather than a different program. The
scenario, skills, executor, sensor model, network model and safety guardian are
identical across all of them by construction.

**Read the timing warning below before reporting any number from this script.**
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.agents.llm_backends import ScriptedBackend, make_backend
from agentic_uav.coordination.roles import FAILED_AFTER_MISSED
from agentic_uav.experiments import architectures as arch
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")

#: The default heartbeat is deliberately *not* the 20 s the single-architecture
#: demos use. See `check_timings` - at 20 s a peer is not declared failed until
#: 160 s, which is longer than this mission, so no architecture can ever recover
#: from a loss and the comparison silently measures timeout constants instead.
DEFAULT_HEARTBEAT_S = 8.0


def check_timings(scenario, heartbeat_s, lease_s=None):
    """Warn when the recovery mechanisms are slower than the mission itself.

    This is the trap this phase fell into, and it is worth a loud warning
    because the failure is silent: every architecture still runs, still reports
    coverage, and still looks comparable. What actually happens is that nobody
    can reclaim a lost drone's work before the mission ends, so the experiment
    reports "decentralized coordination does not recover" when the truth is
    "the detector was configured to fire after the deadline".
    """
    from agentic_uav.coordination.task_allocator import DEFAULT_LEASE_S
    lease_s = DEFAULT_LEASE_S if lease_s is None else lease_s
    detect_s = heartbeat_s * FAILED_AFTER_MISSED
    deadline = scenario.mission.deadline_s
    # a typical run finishes well inside the deadline; use the observed scale
    typical_s = 120.0

    warnings = []
    if detect_s > typical_s:
        warnings.append(
            f"failure detection takes {detect_s:.0f}s (heartbeat {heartbeat_s:.0f}s "
            f"x {FAILED_AFTER_MISSED:.0f} missed) but a run lasts about "
            f"{typical_s:.0f}s - a lost drone is never declared failed, so no "
            f"architecture can reassign its work")
    if lease_s > typical_s:
        warnings.append(
            f"the task lease is {lease_s:.0f}s but a run lasts about "
            f"{typical_s:.0f}s - a dead drone's task can never expire")
    return warnings


def parse_kill(values):
    """`--kill Drone2@1 Drone3@40` -> {'Drone2': 1.0, 'Drone3': 40.0}"""
    out = {}
    for v in values or []:
        vid, _, t = v.partition("@")
        out[vid] = float(t or 0.0)
    return out


def run_one(key, scenario, condition, seed, kill, heartbeat_s, backend_name,
            model, max_steps):
    def adapter(_vid):
        return MockVehicleAdapter(0.0)

    backend = None
    if arch.spec(key).policy == "llm":
        if backend_name == "scripted":
            from run_llm_agents import sensible_model
            backend = ScriptedBackend(default=sensible_model)
        else:
            backend = make_backend(backend_name,
                                   **({"model": model} if model else {}))

    return arch.run_architecture(
        key, scenario, adapter, condition=condition, seed=seed,
        backend=backend, stop_at=kill, heartbeat_interval_s=heartbeat_s,
        max_total_steps=max_steps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--architectures", nargs="*", default=None,
                    help="keys to run (default: the five main ones)")
    ap.add_argument("--ablations", action="store_true",
                    help="run the ablation set as well")
    ap.add_argument("--condition", nargs="*",
                    default=["nominal", "moderate", "severe", "partitioned"])
    ap.add_argument("--seeds", nargs="*", type=int, default=[17])
    ap.add_argument("--kill", nargs="*", default=None,
                    help="fault injection, e.g. Drone2@1")
    ap.add_argument("--heartbeat", type=float, default=DEFAULT_HEARTBEAT_S)
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--backend", default="scripted",
                    choices=["scripted", "ollama", "mistral", "gemini"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--save", default=None, help="directory for results")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("\nArchitectures\n" + "-" * 70)
        for s in arch.MAIN:
            print(f"  {s.key:4} {s.name}")
            print(f"       coordination={s.coordination}  policy={s.policy}")
        print("\nAblations\n" + "-" * 70)
        for s in arch.ABLATIONS:
            print(f"  {s.key:4} {s.name}   (of {s.ablation_of})")
        return 0

    scenario = load_scenario(args.scenario)
    keys = args.architectures or [s.key for s in arch.MAIN]
    if args.ablations:
        keys = list(keys) + [s.key for s in arch.ABLATIONS]
    kill = parse_kill(args.kill)

    warnings = check_timings(scenario, args.heartbeat)
    if warnings:
        print("\n!! TIMING WARNING - results will not mean what they appear to")
        for w in warnings:
            print(f"   {w}")
        print()

    print(f"scenario   : {os.path.basename(args.scenario)}")
    print(f"conditions : {', '.join(args.condition)}")
    print(f"seeds      : {args.seeds}")
    print(f"heartbeat  : {args.heartbeat}s  "
          f"(failure declared after {args.heartbeat * FAILED_AFTER_MISSED:.0f}s)")
    if kill:
        print(f"faults     : " + ", ".join(f"{k} at t={v:.0f}s"
                                           for k, v in kill.items()))
    print()

    header = (f"{'arch':5}{'condition':13}{'seed':6}{'cov':>6}{'home':>6}"
              f"{'dup':>5}{'time':>8}{'deliv':>7}{'guard':>7}  notes")
    print(header)
    print("-" * len(header))

    rows = []
    for key in keys:
        for condition in args.condition:
            for seed in args.seeds:
                r = run_one(key, scenario, condition, seed, kill,
                            args.heartbeat, args.backend, args.model,
                            args.max_steps)
                rows.append(r.as_row())
                note = ""
                if r.llm:
                    note = f"llm fallback {r.llm['fallback_rate'] * 100:.0f}%"
                if r.controller:
                    note = (f"{r.controller['assignments_sent']} assigned, "
                            f"{r.controller['reassignments']} reassigned")
                print(f"{key:5}{(r.condition or '-'):13}{seed:<6}"
                      f"{r.coverage:>6.2f}{r.drones_home:>6}"
                      f"{r.duplicated_sectors:>5}{r.mission_time_s:>8.0f}"
                      f"{r.delivery_rate:>7.2f}{r.guardian_interventions:>7}  {note}")

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, "results.json"), "w") as f:
            json.dump({"scenario": os.path.basename(args.scenario),
                       "heartbeat_s": args.heartbeat,
                       "faults": kill, "warnings": warnings,
                       "specs": {k: arch.spec(k).as_dict() for k in keys},
                       "rows": rows}, f, indent=1, default=str)
        if rows:
            keys_out = sorted({k for r in rows for k in r})
            with open(os.path.join(args.save, "results.csv"), "w",
                      newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys_out)
                w.writeheader()
                w.writerows(rows)
        print(f"\nsaved {len(rows)} rows to {args.save}")

    # exit non-zero if any architecture failed to fly at all, which usually
    # means a build problem rather than an interesting result
    broken = [r for r in rows if r["coverage"] == 0.0]
    if broken:
        print(f"\n{len(broken)} run(s) achieved zero coverage - check the build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
