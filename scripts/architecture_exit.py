#!/usr/bin/env python3
"""Phase 13's exit: every architecture selected by configuration, flown by one harness.

    python scripts/architecture_exit.py                      # seeds 1-20, every configuration
    python scripts/architecture_exit.py --jobs 10                 # the same record, seeds side by side
    python scripts/architecture_exit.py --seeds 17 --block t

AUV-13's exit criterion: "The architecture can be selected through configuration rather than maintaining four
unrelated programs." How each part is shown is in `experiments/architecture_exit.py`: every configuration in
configs/architectures/ (A, B, C, D, E and the ablations) through `fly_architecture`, with no stop and with
Drone1 stopped at 60 s; D by the echo, and on seeds 1-5 also replayed from Phase 12's recorded llama3.3:70b
replies; the first five seeds flown twice. Checked: by configuration, arms as claimed, ablations off, limits
kept, deterministic. How each arm fared is recorded beside, as findings -- Phase 17 runs the experiments.

Outputs, under phases/phase-13-comparison-architectures/results/ by default:

    architecture-exit-<stamp>[-<block>].jsonl   a header (configurations, manifests, verdict, findings by arm);
                                                per seed the checks and each flight's findings
    architecture-exit-<stamp>[-<block>].md      the checks, the arms side by side, the verdict

Exit code 0 only if every check passed on every seed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.coordination.keepout import parse_keepout  # noqa: E402
from agentic_uav.experiments.allocation import allocation_path, load_allocation  # noqa: E402
from agentic_uav.experiments.architecture import all_architectures, load_architecture  # noqa: E402
from agentic_uav.experiments.architecture_exit import CHECKS, by_arm, exit_checks, findings, seed_flights  # noqa: E402
from agentic_uav.experiments.guardian_exit import guardian_path, load_guardian  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery, recovery_path  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-13-comparison-architectures", "results")
KEEPOUT = os.path.join(REPO, "configs", "keepout", "default.toml")
PHASE12 = os.path.join(REPO, "phases", "phase-12-llm-agent-policy", "results", "llm-exit-20261105-150453-exit.jsonl")
SCENARIO = "search_relay_001"
TWICE_UP_TO = 5


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def context() -> dict:
    return {"alloc": load_allocation(), "health": load_recovery(), "limits": load_guardian(),
            "keep_out": parse_keepout(load_toml(KEEPOUT), KEEPOUT)}


def load_phase12() -> dict:
    with io.open(PHASE12, encoding="utf-8") as h:
        return {(r["seed"], r["flight"]): r for r in map(json.loads, h) if r["kind"] == "flight"}


def one_seed(seed: int, phase12: dict) -> dict:
    """One seed's flights, checks and findings. Self-contained, so seeds can fly in separate processes."""
    scenario, ctx = load_scenario(SCENARIO), context()
    ctx["phase9"] = fly_recovery_on_mock(dataclasses.replace(scenario, random_seed=seed), ctx["alloc"],
                                         ctx["health"], "no stop")
    flights = seed_flights(scenario, seed, ctx, twice=seed <= TWICE_UP_TO, phase12=phase12)
    checks = exit_checks(flights, scenario, ctx)
    return {"kind": "seed", "seed": seed, "checks": checks, "findings": findings(flights),
            "flights": len(flights)}


def seed_line(row: dict) -> str:
    return (f"seed {row['seed']}: " + ", ".join(f"{k} {'yes' if row['checks'][k]['ok'] else 'NO'}" for k in CHECKS)
            + f" ({row['flights']} configurations x flights)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    parser.add_argument("--jobs", type=int, default=1, help="seeds flown at once, each in its own process (same "
                        "record either way: every seed is independent)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario = load_scenario(SCENARIO)
    phase12 = load_phase12()
    wall = time.perf_counter()
    rows = []
    jobs = [(seed, {k: v for k, v in phase12.items() if k[0] == seed}) for seed in args.seeds]
    if args.jobs > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for row in pool.map(one_seed, *zip(*jobs)):          # each seed in its own process; kept in seed order
                rows.append(row)
                print(seed_line(row), flush=True)
    else:
        for seed, rec in jobs:
            rows.append(one_seed(seed, rec))
            print(seed_line(rows[-1]), flush=True)
    wall = time.perf_counter() - wall
    ok = all(r["checks"]["all"] for r in rows)
    summary = by_arm(rows)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "architectures": {n: load_architecture(n).as_json() for n in all_architectures()},
              "manifests": {"allocation": os.path.relpath(allocation_path(), REPO),
                            "recovery": os.path.relpath(recovery_path(), REPO),
                            "guardian": os.path.relpath(guardian_path(), REPO), "keep_out": os.path.relpath(KEEPOUT, REPO),
                            "phase12_record": os.path.relpath(PHASE12, REPO)},
              "seeds": list(args.seeds), "seeds_passed": sum(r["checks"]["all"] for r in rows),
              "exit_criterion_met": ok, "findings": summary, "wall_s": round(wall, 1), "code": provenance()}

    lines = [f"# Architecture exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/architecture_exit.py`, {wall:.0f} s wall. Every configuration in "
             f"`configs/architectures/` ({len(header['architectures'])}) through `fly_architecture`, each seed with no "
             "stop and with Drone1 stopped at 60 s; models by the echo, and D replayed from Phase 12's 70B on seeds "
             f"1-5; seeds 1-{TWICE_UP_TO} flown twice. A perfect network (each arm under degraded links is Phase 17's to compare); the guardian and keep-out unless switched off.",
             "", "| Seed | " + " | ".join(CHECKS) + " |", "|---|" + "---|" * len(CHECKS)]
    for r in rows:
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if r["checks"][k]["ok"] else "**no**" for k in CHECKS) + " |")
    lines += ["", "**Each configuration over the seeds** (findings, not experiments: Phase 17 runs those):", "",
              "| Configuration / flight | Met | Completion s (min, median, max) |", "|---|---|---|"]
    for k, f in summary.items():
        lines.append(f"| {k} | {f['met']}/{f['of']} | {f['completion_s']} |")
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {header['seeds_passed']} of {len(rows)} seeds "
                  "passed every check.", ""]
    problems = [f"seed {r['seed']}, {k}: {p}" for r in rows for k in CHECKS for p in r["checks"][k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:40]] + [""]
    os.makedirs(args.out, exist_ok=True)
    stem = f"architecture-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
