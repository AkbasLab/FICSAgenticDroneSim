#!/usr/bin/env python3
"""Phase 7's exit: four agents talk, and their team beliefs update only when messages are delivered.

    python scripts/messaging_exit.py                       # seeds 1-20, each flown talking, blocked, silent
    python scripts/messaging_exit.py --seeds 17 --block t
    python scripts/messaging_exit.py --scenario search_relay_live_small    # the live variant's pair, on the mock
    python scripts/messaging_exit.py --sim airsim --block live1           # that pair, live in CarlaAir

AUV-07's exit criterion: "Four deterministic agents exchange heartbeats and
status messages while flying. Their local team beliefs update only when
messages are delivered." `experiments/messaging.py` says how each part is
shown: every seed is flown TALKING (Phase 7's perfect network, 100 m),
BLOCKED (range cut to 1 m: sent, never delivered) and SILENT (no messaging),
and checked -- met, exchanged, only on delivery, known exactly, blocked
moves nothing, steers nothing.

`--scenario search_relay_live_small` flies the live variant's two agents
(S1, S2; a 20 m radio) the same three ways: the mock gate for the live flight
of step 6. The exit itself is the canonical four.

`--sim airsim` flies that pair once, live (`fly_agents_live`), and holds it
to the four checks a flight can be held to on its own -- met, exchanged, only
on delivery, known exactly (within one observed poll of flight, Phase 6's
live allowance). A live flight cannot also be flown blocked and silent, so
the mock twin of the same scenario is flown beside it with all six.

Outputs, under phases/phase-07-inter-agent-messaging/results/ by default:

    messaging-exit-<stamp>[-<block>].jsonl   a header; per seed, the checks and every decision's team block;
                                             for the scenario's own seed, the talking flight's full message log
    messaging-exit-<stamp>[-<block>].md      the table and the verdict

    messaging-live-<stamp>[-<block>].jsonl   live: a header, the flight with its checks and team beliefs,
                                             every message, and the mock twin's checks
    messaging-live-<stamp>[-<block>].md      live: the checks beside the twin's, and the verdict

Exit code 0 only if every check passed on every seed (live: on the flight).
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

from agentic_uav.experiments.message_log import message_log  # noqa: E402
from agentic_uav.experiments.messaging import (  # noqa: E402
    BLOCKED_RANGE_M,
    exit_checks,
    messaging_flights,
    talking_checks,
    team_beliefs,
)
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402
from agentic_uav.experiments.single_agent import MESSAGE_DELAY_S, PAIR_TASKS, TEAM_TASKS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-07-inter-agent-messaging", "results")
SCENARIO = "search_relay_001"
LIVE_SCENARIO = "search_relay_live_small"
TASKS = {SCENARIO: TEAM_TASKS, LIVE_SCENARIO: PAIR_TASKS}      # who flies, per scenario
CHECKS = ("met", "exchanged", "only_on_delivery", "known_exactly", "blocked_moves_nothing", "steers_nothing")
LIVE_CHECKS = CHECKS[:4]                 # what one flight can be held to on its own


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    parser.add_argument("--scenario", choices=sorted(TASKS), default=None,
                        help=f"default {SCENARIO}; live, only {LIVE_SCENARIO}")
    parser.add_argument("--sim", choices=("mock", "airsim"), default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--poll-hz", type=float, default=None)
    args = parser.parse_args(argv)
    if args.sim == "airsim":
        if args.scenario not in (None, LIVE_SCENARIO):
            parser.error(f"live, only {LIVE_SCENARIO} flies: its pads are the spawn layout")
        args.scenario = LIVE_SCENARIO
    else:
        for name, flag in (("port", "--port"), ("poll_hz", "--poll-hz")):
            if getattr(args, name) is not None:
                parser.error(f"{flag} is for --sim airsim")
        args.scenario = args.scenario or SCENARIO
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.sim == "airsim":
        return live(args, started)
    scenario = load_scenario(args.scenario)
    tasks = TASKS[args.scenario]
    is_exit = args.scenario == SCENARIO
    wall = time.perf_counter()
    rows: list[dict] = []
    table = []
    for seed in args.seeds:
        flights = messaging_flights(scenario, seed, tasks)
        checks = exit_checks(flights, scenario)
        talk = flights["talking"]
        rows.append({"kind": "seed", "seed": seed, "checks": checks,
                     "completion_s": talk.report.completion_s, "team_beliefs": team_beliefs(talk)})
        if seed == scenario.random_seed:
            rows += [{"kind": "message", "seed": seed, **r}
                     for r in message_log(talk.deliveries, talk.traces, talk.start)]
        table.append((seed, checks))
    wall = time.perf_counter() - wall

    ok = all(c["all"] for _, c in table)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
              "tasks": tasks, "seeds": list(args.seeds), "range_m": scenario.network.communication_range_m,
              "blocked_range_m": BLOCKED_RANGE_M, "delay_s": MESSAGE_DELAY_S,
              "seeds_passed": sum(c["all"] for _, c in table),
              ("exit_criterion_met" if is_exit else "live_variant_gate_passed"): ok,
              "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Messaging exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/messaging_exit.py`, {wall:.1f} s wall. {len(tasks)} rule agents, "
             f"{', '.join(t.split()[-1] for t in tasks.values())}, each flown "
             f"talking (range {scenario.network.communication_range_m:g} m, read at the next tick), blocked "
             f"(range {BLOCKED_RANGE_M:g} m) and silent.", "",
             "| Seed | " + " | ".join(CHECKS) + " | Records checked | Delivered / out of range / pending |",
             "|---|" + "---|" * len(CHECKS) + "---|---|"]
    for seed, c in table:
        st = c["messages"]["by_status"]
        lines.append(f"| {seed} | " + " | ".join("yes" if c[k]["ok"] else "**no**" for k in CHECKS)
                     + f" | {c['only_on_delivery']['records_checked']} | "
                       f"{st.get('delivered', 0)} / {st.get('out_of_range', 0)} / {st.get('pending', 0)} |")
    problems = [f"seed {s}, {k}: {p}" for s, c in table for k in CHECKS for p in c[k]["problems"]]
    verdict = f"Exit criterion: {'MET' if ok else 'NOT MET'}" if is_exit else         f"Live-variant gate: {'PASSED' if ok else 'NOT PASSED'} (the gate for the live flight, not the exit)"
    lines += ["", f"**{verdict}** — {header['seeds_passed']} of {len(table)} seeds "
                  f"passed every check.", ""]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"messaging-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


def live(args, started: str) -> int:
    """One live flight of the talking pair in CarlaAir."""
    from agentic_uav.core.clock import RealClock
    from agentic_uav.simulator.airsim_adapter import AIRSIM_PORT, AirSimAdapter
    port = args.port or AIRSIM_PORT
    return report_live(args, started, lambda: AirSimAdapter.connect(args.host, port), RealClock())


def report_live(args, started: str, connect, clock) -> int:
    """Fly the pair live, hold it to the four checks, and fly its mock twin beside it with all six.

    The twin is not a pass condition: it is there so the live record can be
    read against one where the truth is exact, and to show the blocked and
    silent flights a live flight cannot have.
    """
    from agentic_uav.agents.rule_policy import RulePolicy
    from agentic_uav.experiments.knowledge import observed_poll_hz, poll_tolerance
    from agentic_uav.experiments.message_log import summary as log_summary
    from agentic_uav.experiments.single_agent import fly_agents_live
    from agentic_uav.simulator.observer import DEFAULT_POLL_HZ

    scenario = load_scenario(args.scenario)
    tasks = TASKS[args.scenario]
    hz = DEFAULT_POLL_HZ if args.poll_hz is None else args.poll_hz
    speed = RulePolicy().speed_mps                       # what the agents will actually ask for

    wall = time.perf_counter()
    flight = fly_agents_live(scenario, tasks, connect(), connect, clock, poll_hz=hz)
    wall = time.perf_counter() - wall
    # The allowance from the rate the poller KEPT (Phase 6): known only once flown.
    polled = observed_poll_hz(flight.samples, flight.poll_hz)
    tol = poll_tolerance(scenario, polled["hz"], speed)
    run = flight.as_run("live")
    checks = talking_checks(run, scenario, tol)
    ok = all(checks[k]["ok"] for k in LIVE_CHECKS)
    rows = message_log(run.deliveries, run.traces, run.start)
    messages = log_summary(rows)

    twin_flights = messaging_flights(scenario, scenario.random_seed, tasks)
    twin = exit_checks(twin_flights, scenario)

    header = {"kind": "header", "t": started, "sim": "airsim", "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
              "tasks": tasks, "observer": flight.observer, "poll_hz": hz, "poll": polled, "speed_mps": speed,
              "tolerance": tol, "range_m": flight.range_m, "delay_s": MESSAGE_DELAY_S,
              "checks": {k: checks[k]["ok"] for k in LIVE_CHECKS}, "live_flight_met": ok,
              "mock_twin_all": twin["all"], "wall_s": round(wall, 2), "code": provenance()}
    out_rows = [header,
                {**flight.as_json(), "set": "live", "checks": checks, "messages": messages,
                 "completion_s": run.report.completion_s, "team_beliefs": team_beliefs(run)},
                *({"kind": "message", "set": "live", **r} for r in rows),
                {"kind": "twin", "set": "mock_twin", "checks": twin,
                 "completion_s": twin_flights["talking"].report.completion_s,
                 "team_beliefs": team_beliefs(twin_flights["talking"])}]

    def cell(c: dict | None) -> str:
        return "-" if c is None else ("yes" if c["ok"] else "**no**")

    st, tst = messages["by_status"], twin["messages"]["by_status"]
    skills = "; ".join(f"{d}: " + ", ".join(f"{k} {v}" for k, v in sk) for d, sk in flight.skills.items())
    lines = [f"# Messaging live — {scenario.scenario_id}", "",
             f"Run {started}, `scripts/messaging_exit.py --sim airsim`, {wall:.1f} s of flight. "
             f"{len(tasks)} rule agents talking, " + ", ".join(f"{d} told {t!r}" for d, t in tasks.items())
             + f"; radio {flight.range_m:g} m, judged on the poller's latest positions; observer {flight.observer}.",
             "",
             f"Correct here means within **{tol['position_m']:g} m** and **{tol['battery']:g} %** of battery: "
             f"{tol['why']} (the poller kept {polled['kept_hz']:.4g} Hz over {polled['samples']} samples, "
             f"worst gap {polled['worst_gap_s']} s).", "",
             "| Check | Live | Mock twin |", "|---|---|---|"]
    lines += [f"| {k} | {cell(checks.get(k))} | {cell(twin.get(k))} |" for k in CHECKS]
    lines += [f"| Teammate records checked | {checks['only_on_delivery']['records_checked']} | "
              f"{twin['only_on_delivery']['records_checked']} |",
              f"| Delivered / out of range / pending | {st.get('delivered', 0)} / {st.get('out_of_range', 0)} / "
              f"{st.get('pending', 0)} | {tst.get('delivered', 0)} / {tst.get('out_of_range', 0)} / "
              f"{tst.get('pending', 0)} |",
              f"| In a belief / read by the policy | {messages['in_belief']} / {messages['read_by_policy']} | "
              f"{twin['messages']['in_belief']} / {twin['messages']['read_by_policy']} |",
              f"| Skills | {skills} | - |",
              f"| Contacts | {', '.join(f'{c.drone}-{c.object}' for c in flight.contacts) or 'none'} | - |", "",
              "Blocked and silent cannot be flown live: those rows are the mock twin's alone.", "",
              f"**Live flight: {'MET' if ok else 'NOT MET'}** — the four checks one flight can be held to"
              + ("" if ok else "; failed: " + ", ".join(k for k in LIVE_CHECKS if not checks[k]["ok"]))
              + ". A live flight of the variant, not the exit.", ""]
    problems = [f"{k}: {p}" for k in LIVE_CHECKS for p in checks[k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"messaging-live-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in out_rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
