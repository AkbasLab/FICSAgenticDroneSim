#!/usr/bin/env python3
"""Phase 6's exit: for each decision, exactly what the agent knew and what it did not know.

    python scripts/knowledge_exit.py                       # 20 seeds: the single agent, then the pair
    python scripts/knowledge_exit.py --seeds 17 --block t
    python scripts/knowledge_exit.py --sim airsim --block live1        # CarlaAir running, one flight

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

LIVE (`--sim airsim`, Phase 6 step 6): one flight in CarlaAir of the live-sized
scenario (`search_single_live_small`, told only "search S1"), every decision
logged the same way, and the same flight run on the mock beside it. The live
run is checked within `poll_tolerance` rather than the mock's 0.01 m, because
the belief is the last poll before a decision while the truth is interpolated
between the polls around it -- up to one poll of flight apart however right the
logger is. The tolerance is derived from the poll rate and the speed, and both
are written into the record. Outputs knowledge-live-<stamp>[-<block>].jsonl
and .md; exit code 0 only if the flight met its task and every decision passed.
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

from agentic_uav.experiments.knowledge import (  # noqa: E402
    TOLERANCE,
    Truth,
    knowledge_log,
    observed_poll_hz,
    poll_tolerance,
    summary,
)
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
LIVE_SCENARIO = "search_single_live_small"          # Phase 5's live variant, unchanged
LIVE_TASK = "search S1"


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
    parser.add_argument("--sim", choices=("mock", "airsim"), default="mock")
    parser.add_argument("--scenario", default=None, help=f"live only; default {LIVE_SCENARIO}")
    parser.add_argument("--task", default=None, help=f"live only; default {LIVE_TASK!r}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--poll-hz", type=float, default=None)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.sim == "airsim":
        args.scenario = args.scenario or LIVE_SCENARIO
        args.task = args.task or LIVE_TASK
        return live(args, started)
    for name, flag in (("scenario", "--scenario"), ("task", "--task"), ("poll_hz", "--poll-hz")):
        if getattr(args, name) is not None:
            parser.error(f"{flag} is for --sim airsim; the mock flies {SINGLE} and {PAIR}")
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


def live(args, started: str) -> int:
    """One live flight of the agent in CarlaAir, with every decision logged."""
    from agentic_uav.core.clock import RealClock
    from agentic_uav.simulator.airsim_adapter import AIRSIM_PORT, AirSimAdapter
    port = args.port or AIRSIM_PORT
    return report_live(args, started, lambda: AirSimAdapter.connect(args.host, port), RealClock())


def report_live(args, started: str, connect, clock) -> int:
    """Fly live, log every decision, and log the mock's flight of the same scenario beside it.

    The mock twin is not a pass condition -- it is there so the live log can
    be read against one taken where the truth is exact.
    """
    from agentic_uav.agents.rule_policy import RulePolicy
    from agentic_uav.experiments.single_agent import fly_agent_live, fly_agent_on_mock
    from agentic_uav.simulator.observer import DEFAULT_POLL_HZ

    scenario = load_scenario(args.scenario)
    hz = DEFAULT_POLL_HZ if args.poll_hz is None else args.poll_hz
    speed = RulePolicy().speed_mps                       # what the agent will actually ask for

    wall = time.perf_counter()
    flight = fly_agent_live(scenario, args.task, connect(), connect, clock, poll_hz=hz)
    wall = time.perf_counter() - wall
    (drone,) = flight.samples
    # The allowance comes from the rate the poller KEPT, which is the one that
    # bounds the lag -- so it can only be worked out once the flight is flown.
    polled = observed_poll_hz(flight.samples, flight.poll_hz)
    tol = poll_tolerance(scenario, polled["hz"], speed)
    run = flight.as_run("live")
    truth = Truth(scenario, flight.trajectories(), flight.start, flight.end)
    entries = knowledge_log({drone: flight.trace}, truth, tol)
    s = summary(entries)

    mock = fly_agent_on_mock(scenario, args.task, "mock twin")
    mock_truth = Truth(scenario, mock.trajectories, mock.report.start, mock.report.until)
    mock_entries = knowledge_log({drone: mock.trace}, mock_truth)
    ms = summary(mock_entries)

    ok = bool(run.met) and s["decisions"] > 0 and s["ok"] == s["decisions"]
    rows = [{"kind": "header", "t": started, "sim": "airsim", "scenario": scenario.scenario_id,
             "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
             "task": args.task, "drone": drone, "observer": flight.observer, "poll_hz": hz,
             "poll": polled, "speed_mps": speed, "tolerance": tol,
             "mock_tolerance": TOLERANCE, "met": run.met,
             "decisions": s["decisions"], "decisions_passed": s["ok"], "exit_criterion_met": ok,
             "wall_s": round(wall, 2), "code": provenance()},
            {"kind": "flight", "set": "live", "met": run.met, "summary": s, **flight.as_json()}]
    rows += [{"kind": "decision", "set": "live", **e.as_json()} for e in entries]
    rows.append({"kind": "flight", "set": "mock_twin", "met": mock.met, "summary": ms,
                 "completion_s": mock.report.completion_s})
    rows += [{"kind": "decision", "set": "mock_twin", **e.as_json()} for e in mock_entries]

    lines = [f"# Knowledge log — Phase 6 live, {scenario.scenario_id}", "",
             f"Run {started}, `scripts/knowledge_exit.py --sim airsim`, {wall:.1f} s of flight. Told only "
             f"{args.task!r}. Observer {flight.observer}. Logger: `experiments/knowledge.py`; agent: "
             f"`agents/drone_agent.py` with `agents/rule_policy.py`.", "",
             f"Correct here means within **{tol['position_m']:g} m** and **{tol['battery']:g} %** of battery: "
             f"{tol['why']}. The belief is the last poll before a decision and the truth is interpolated "
             f"between the polls around it, so they stand up to one poll of flight apart however right the "
             f"logger is. The mock's own allowance, {TOLERANCE['position_m']:g} m, holds only where both "
             f"sides come from one trajectory.", "",
             f"The poller was asked for {polled['asked_hz']:g} Hz and kept {polled['hz']:.4g} Hz across "
             f"{polled['samples']} samples: worst gap {polled['worst_gap_s']} s, median "
             f"{polled['median_gap_s']} s. The allowance is the WORST gap, since that is what bounds the "
             f"lag; the median is here so that one stalled poll widening it would show.", "",
             "| | Live | Mock twin |", "|---|---|---|",
             f"| Task met | {'yes' if run.met else '**no**'} | {'yes' if mock.met else 'no'} |",
             f"| Decisions | {s['decisions']} | {ms['decisions']} |",
             f"| Passed all three checks | {s['ok']} | {ms['ok']} |",
             f"| Known items | {s['known']} | {ms['known']} |",
             f"| Unknown items | {s['unknown']} | {ms['unknown']} |",
             f"| Truth-gap items | {s['gap']} | {ms['gap']} |",
             f"| Completion s | {secs(run.report.completion_s)} | {secs(mock.report.completion_s)} |",
             f"| Skills | {', '.join(f'{k} {st}' for k, st in flight.skills)} | "
             f"{', '.join(f'{k} {st}' for k, st in mock.skills)} |",
             f"| Contacts | {', '.join(f'{c.drone}-{c.object}' for c in flight.contacts) or 'none'} | - |", "",
             f"**{'MET' if ok else 'NOT MET'}** — {s['ok']} of {s['decisions']} decisions logged complete, "
             f"correct and without a leak"
             + ("" if run.met else "; the flight did not meet its task") + ".", ""]
    if s["problems"]:
        lines += ["Problems:", ""] + [f"* {p}" for p in s["problems"][:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"knowledge-live-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


def secs(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


if __name__ == "__main__":
    sys.exit(main())
