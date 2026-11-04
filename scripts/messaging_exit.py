#!/usr/bin/env python3
"""Phase 7's exit: four agents talk, and their team beliefs update only when messages are delivered.

    python scripts/messaging_exit.py                       # seeds 1-20, each flown talking, blocked, silent
    python scripts/messaging_exit.py --seeds 17 --block t
    python scripts/messaging_exit.py --scenario search_relay_live_small    # the live variant's pair, on the mock

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

Outputs, under phases/phase-07-inter-agent-messaging/results/ by default:

    messaging-exit-<stamp>[-<block>].jsonl   a header; per seed, the checks and every decision's team block;
                                             for the scenario's own seed, the talking flight's full message log
    messaging-exit-<stamp>[-<block>].md      the table and the verdict

Exit code 0 only if every check passed on every seed.
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
    parser.add_argument("--scenario", choices=sorted(TASKS), default=SCENARIO)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
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


if __name__ == "__main__":
    sys.exit(main())
