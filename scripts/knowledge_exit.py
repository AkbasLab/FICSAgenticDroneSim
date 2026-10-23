#!/usr/bin/env python3
"""Phase 6's exit: for each decision, exactly what the agent knew and what it did not know.

    python scripts/knowledge_exit.py                       # 20 seeds: the single agent, then the pair
    python scripts/knowledge_exit.py --seeds 17 --block t

AUV-06's exit criterion: "the experiment logger can show, for each decision,
exactly what the agent knew and what it did not know." Two sets of flights
on the mock, every decision of every agent logged by
`experiments/knowledge.py`:

* SINGLE: one rule agent on `search_single_001`, told only "search S3"
  (Phase 5's exit task).
* PAIR: two independent rule agents on `search_pair_001`, Drone1 told
  "search S1" and Drone2 "search S2". Neither hears the other: each knows
  its teammate is on the roster, and nothing more.

For every decision the record holds what the agent knew (each field, its
source and age), what it recorded as unknown, the truth gap (computed from
the flight's ground truth, which the agent never had), and three checks:
complete, correct, no leak.

Outputs, under phases/phase-06-belief-state/results/ by default:

    knowledge-exit-<stamp>[-<block>].jsonl   a header, one row per flight, one per decision
    knowledge-exit-<stamp>[-<block>].md      the summary and the verdict

Exit code 0 only if every flight met its task and every decision passed all
three checks.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.knowledge import Truth, knowledge_log, summary  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402
from agentic_uav.experiments.single_agent import (  # noqa: E402
    EXIT_TASK,
    PAIR_TASKS,
    fly_agent_on_mock,
    fly_agents_on_mock,
)

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-06-belief-state", "results")
SINGLE, PAIR = "search_single_001", "search_pair_001"


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def flights(seeds: tuple[int, ...]):
    """(kind, seed, tasks, met, report, entries) for every flight: the single agent's, then the pair's."""
    single, pair = load_scenario(SINGLE), load_scenario(PAIR)
    for seed in seeds:
        scenario = dataclasses.replace(single, random_seed=seed)
        run = fly_agent_on_mock(scenario, EXIT_TASK)
        truth = Truth(scenario, run.trajectories, run.report.start, run.report.until)
        yield "single", seed, {"Drone1": EXIT_TASK}, run.met, run.report, knowledge_log({"Drone1": run.trace}, truth)
    for seed in seeds:
        scenario = dataclasses.replace(pair, random_seed=seed)
        team = fly_agents_on_mock(scenario, PAIR_TASKS)
        truth = Truth(scenario, team.trajectories, team.start, team.report.until)
        yield "pair", seed, dict(PAIR_TASKS), team.met, team.report, knowledge_log(team.traces, truth)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    wall = time.perf_counter()
    rows: list[dict] = []
    table: list[tuple] = []
    for kind, seed, tasks, met, report, entries in flights(args.seeds):
        s = summary(entries)
        rows.append({"kind": "flight", "set": kind, "seed": seed, "tasks": tasks, "met": met,
                     "completion_s": report.completion_s, "summary": s})
        rows += [{"kind": "decision", "set": kind, "seed": seed, **e.as_json()} for e in entries]
        table.append((kind, seed, met, s))
    wall = time.perf_counter() - wall

    decisions = sum(s["decisions"] for *_, s in table)
    passed = sum(s["ok"] for *_, s in table)
    met = sum(m for _, _, m, _ in table)
    ok = met == len(table) and passed == decisions
    header = {"kind": "header", "t": started, "seeds": list(args.seeds),
              "scenarios": {k: os.path.relpath(scenario_path(n), REPO).replace(os.sep, "/")
                            for k, n in (("single", SINGLE), ("pair", PAIR))},
              "flights": len(table), "flights_met": met, "decisions": decisions, "decisions_passed": passed,
              "exit_criterion_met": ok, "wall_s": round(wall, 2), "code": provenance()}

    lines = ["# Knowledge log — Phase 6 exit, mock", "",
             f"Run {started}, `scripts/knowledge_exit.py`, {wall:.1f} s wall. Logger: `experiments/knowledge.py`; "
             f"agents: `agents/drone_agent.py` with `agents/rule_policy.py`.", "",
             "| Set | Seed | Task met | Decisions | Passed | Known items | Unknown items | Truth-gap items |",
             "|---|---|---|---|---|---|---|---|"]
    for kind, seed, m, s in table:
        lines.append(f"| {kind} | {seed} | {'yes' if m else '**no**'} | {s['decisions']} | {s['ok']} | "
                     f"{s['known']} | {s['unknown']} | {s['gap']} |")
    problems = [p for *_, s in table for p in s["problems"]]
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {met} of {len(table)} flights met their "
                  f"tasks; {passed} of {decisions} decisions logged complete, correct and without a leak.", ""]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"knowledge-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
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
