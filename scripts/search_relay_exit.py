#!/usr/bin/env python3
"""Phase 4's exit: the scripted controller flies the canonical mission across 20 seeds.

    python scripts/search_relay_exit.py                         # search_relay_001, seeds 1-20, the mock
    python scripts/search_relay_exit.py --seeds 17              # one seed
    python scripts/search_relay_exit.py --scenario path/to/x.toml

AUV-05's exit criterion: "a fully scripted, non-agentic controller can
complete the canonical mission". Here: `control/scripted.py` plans from the
brief alone, the four drones fly it on the mock (`MockWorld`, simulated
time, observed exactly), and `experiments/evaluation.py` judges every seed
against AUV-05's six criteria. The seeds move the targets; the plan cannot
see them.

Outputs, under phases/phase-04-search-relay-mission/results/ by default:

    search-relay-exit-mock-<stamp>[-<block>].jsonl   a header, then one row per seed
    search-relay-exit-mock-<stamp>[-<block>].md      the table and the verdict

Exit code 0 only if every seed met: mission success, and every planned skill
succeeded with no safety landing.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS, exit_runs  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-04-search-relay-mission", "results")


def seeds_arg(text: str) -> tuple[int, ...]:
    """'17', '1-20' or '1,5,9'."""
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def table(runs) -> list[str]:
    lines = ["| Seed | Targets (sector) | Met | Completion s | Coverage | Reported at s | "
             "Closest pair m | Lowest battery % | Failing |",
             "|---|---|---|---|---|---|---|---|---|"]
    for run in runs:
        r = run.report
        f = r.facts
        targets = ", ".join(f"{t.id} ({t.x:.0f}, {t.y:.0f}) {t.sector}" for t in f.targets)
        reports = ", ".join(
            f"{t.id} {rep.reported_at - r.start:.1f}" if (rep := f.first_report(t.id)) else f"{t.id} -"
            for t in f.targets)
        lowest = min(b.remaining for b in f.batteries)
        failing = [c.id for c in r.criteria if not c.passed] + ([] if run.skills_ok else ["skills"])
        lines.append(f"| {run.seed} | {targets} | {'yes' if run.met else '**no**'} | "
                     f"{'-' if r.completion_s is None else f'{r.completion_s:.1f}'} | "
                     f"{r.coverage.fraction:.4f} | {reports} | "
                     f"{r.components['min_separation_m']} | {lowest:.1f} | {', '.join(failing) or '-'} |")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="search_relay_001", help="id or path")
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS, help="e.g. 1-20, 17, 1,5,9")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL", help="short label appended to the file names")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario = load_scenario(args.scenario)
    wall = time.perf_counter()
    runs = exit_runs(scenario, args.seeds)
    wall = time.perf_counter() - wall
    met = sum(run.met for run in runs)
    ok = met == len(runs)
    plan = runs[0].plan if runs else {}

    os.makedirs(args.out, exist_ok=True)
    stem = (f"search-relay-exit-mock-{time.strftime('%Y%m%d-%H%M%S')}"
            + (f"-{args.block}" if args.block else ""))
    header = {"kind": "header", "t": started, "sim": "mock", "observer": "mock-exact",
              "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
              "seeds": list(args.seeds), "met": met, "runs": len(runs), "exit_criterion_met": ok,
              "wall_s": round(wall, 2), "code": provenance()}
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(header) + "\n")
        for run in runs:
            h.write(json.dumps(run.as_json()) + "\n")

    lines = [f"# Search-and-relay exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/search_relay_exit.py`, {len(runs)} seeds "
             f"({wall:.1f} s wall). Controller: `control/scripted.py`, from the brief alone. "
             f"Observer: the mock's exact trace. Judge: `experiments/evaluation.py`.", "",
             "## The plan (the same for every seed)", "",
             "| Drone | Sector | Height m | Lanes m | Length m | Estimated s | Estimated battery % |",
             "|---|---|---|---|---|---|---|"]
    for d, p in plan.items():
        lines.append(f"| {d} | {', '.join(p.sectors)} | {p.altitude_m:g} | {p.lane_spacing_m:.2f} | "
                     f"{p.length_m:.1f} | {p.estimated_s:.0f} | {p.estimated_battery_used:.1f} |")
    lines += ["", "## Every seed", ""] + table(runs)
    done = [r.report.completion_s for r in runs if r.report.completion_s is not None]
    if done:
        lines += ["", f"Completion: {min(done):.1f}–{max(done):.1f} s of the "
                      f"{scenario.mission.deadline_s:g} s deadline."]
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {met} of {len(runs)} seeds met "
                  f"(mission success, and every planned skill succeeded with no safety landing).", ""]
    summary = "\n".join(lines)
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary)
    print(summary)
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
