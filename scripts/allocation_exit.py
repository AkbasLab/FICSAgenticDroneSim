#!/usr/bin/env python3
"""Phase 8's exit: four drones, one team mission, the sectors divided with no central assignment.

    python scripts/allocation_exit.py                        # seeds 1-20, each flown deliberating and contested, twice
    python scripts/allocation_exit.py --seeds 17 --block t
    python scripts/allocation_exit.py --sim airsim --block live1          # two drones dividing S1, S2 in CarlaAir

AUV-08's exit criterion: "Four drones receive one team mission, divide the
sectors without a central assignment, complete the work, and resolve
simultaneous claims deterministically." `experiments/allocation_exit.py`
says how each part is shown: every seed flown DELIBERATING (the manifest's
bid window) and CONTESTED (no window: every drone claims at once), each
twice, every message delivered; and checked -- met, no central assignment,
one holder each, conflicts resolved by the rules, leases renewed,
deterministic, known exactly. The manifest the run used
(`configs/allocation/default.toml`) is recorded with it.

Beside the exit, as a finding and not a pass condition: the scenario's own
100 m radio, flown once.

`--sim airsim` flies the live variant's pair once (`fly_team_live`), told
only the team mission, deliberating, every message delivered, and holds it
to the six checks one flight can meet (determinism needs a second flight);
the mock twin of the same scenario is flown beside it with all seven.

Outputs, under phases/phase-08-decentralized-task-allocation/results/ by default:

    allocation-exit-<stamp>[-<block>].jsonl   a header; per seed, the checks, the division, the conflicts;
                                              for the scenario's own seed, each drone's book and every message
    allocation-exit-<stamp>[-<block>].md      the table, the finding, and the verdict

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

from agentic_uav.experiments.allocation import allocation_path, load_allocation  # noqa: E402
from agentic_uav.experiments.allocation_exit import (  # noqa: E402
    CHECKS,
    MODES,
    allocation_flights,
    exit_checks,
    hundred_metre_finding,
)
from agentic_uav.experiments.message_log import message_log  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-08-decentralized-task-allocation", "results")
SCENARIO = "search_relay_001"
LIVE_SCENARIO = "search_relay_live_small"
HAND_ASSIGNMENT_S = 192.1        # Phase 4's scripted controller, fixed assignment, on the mock (its run of record)


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def secs(v) -> str:
    return "-" if v is None else f"{v:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    parser.add_argument("--manifest", default="default")
    parser.add_argument("--sim", choices=("mock", "airsim"), default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--poll-hz", type=float, default=None)
    args = parser.parse_args(argv)
    if args.sim == "mock":
        for name, flag in (("port", "--port"), ("poll_hz", "--poll-hz")):
            if getattr(args, name) is not None:
                parser.error(f"{flag} is for --sim airsim")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.sim == "airsim":
        return live(args, started)
    scenario = load_scenario(SCENARIO)
    config = load_allocation(args.manifest)
    wall = time.perf_counter()
    rows: list[dict] = []
    table = []
    for seed in args.seeds:
        flights = allocation_flights(scenario, seed, config)
        checks = exit_checks(flights, scenario)
        rows.append({"kind": "seed", "seed": seed, "checks": checks,
                     "completion_s": {m: flights[m].team.report.completion_s for m in MODES},
                     "division": {m: flights[m].searched for m in MODES}})
        if seed == scenario.random_seed:
            for m in MODES:
                f = flights[m]
                rows.append({"kind": "books", "seed": seed, "mode": m, "nets": f.nets})
                rows += [{"kind": "message", "seed": seed, "mode": m, **r}
                         for r in message_log(f.team.deliveries, f.team.traces, f.team.start)]
        table.append((seed, checks, {m: flights[m].team.report.completion_s for m in MODES},
                      flights["deliberating"].searched))
    finding = hundred_metre_finding(scenario, config)
    wall = time.perf_counter() - wall

    ok = all(c["all"] for _, c, _, _ in table)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(SCENARIO), REPO).replace(os.sep, "/"),
              "manifest": os.path.relpath(allocation_path(args.manifest), REPO).replace(os.sep, "/"),
              "config": config.as_json(), "network": "every message delivered (range unlimited)",
              "seeds": list(args.seeds), "modes": list(MODES), "hand_assignment_s": HAND_ASSIGNMENT_S,
              "seeds_passed": sum(c["all"] for _, c, _, _ in table), "exit_criterion_met": ok,
              "finding_100m": finding, "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Allocation exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/allocation_exit.py`, {wall:.1f} s wall. Four rule agents told only the team "
             f"mission, every message delivered; each seed flown deliberating (bid window "
             f"{config.bid_window_s:g} s) and contested (no window), each twice. Manifest "
             f"`{header['manifest']}`: weights {config.weights.as_json()}, progress every "
             f"{config.progress_period_s:g} s, lease {config.lease_s:g} s.", "",
             "| Seed | " + " | ".join(CHECKS) + " | Division (deliberating) | Conflicts (contested) | Completion s |",
             "|---|" + "---|" * len(CHECKS) + "---|---|---|"]
    for seed, c, completion, division in table:
        div = ", ".join(f"{d} {t[0].split()[1]}" for d, t in sorted(division.items()) if t)
        conflicts = "; ".join(f"{x['task_id'].split()[1]}: {len(x['claims'])} claims, {x['winner']} kept"
                              for x in c["conflicts_resolved"]["conflicts"])
        lines.append(f"| {seed} | " + " | ".join("yes" if c[k]["ok"] else "**no**" for k in CHECKS)
                     + f" | {div} | {conflicts or '-'} | {secs(completion['deliberating'])} / "
                       f"{secs(completion['contested'])} |")
    problems = [f"seed {s}, {k}: {p}" for s, c, _, _ in table for k in CHECKS for p in c[k]["problems"]]
    lines += ["", f"Phase 4's scripted controller, with the hand assignment Drone *i* to S*i*, completes in "
                  f"{HAND_ASSIGNMENT_S:g} s on the mock -- for comparison, not a pass condition.", "",
              f"**The finding beside the exit** -- the scenario's own {finding['range_m']:g} m radio, one flight: "
              f"met {finding['met']}; {finding['searches']} searches of {finding['sectors']} sectors; "
              f"{finding['lease_expiries']} lease expiries: a drone searching a far sector is out of everyone's "
              "reach, its reports go unheard, its lease runs out while it works, and a teammate searches the "
              "sector again. Not part of the exit (decided 2026-11-04); Phase 10's subject.", "",
              f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {header['seeds_passed']} of {len(table)} seeds "
              "passed every check.", ""]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"allocation-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


def live(args, started: str) -> int:
    """One live flight of the pair dividing its mission in CarlaAir."""
    from agentic_uav.core.clock import RealClock
    from agentic_uav.simulator.airsim_adapter import AIRSIM_PORT, AirSimAdapter
    port = args.port or AIRSIM_PORT
    return report_live(args, started, lambda: AirSimAdapter.connect(args.host, port), RealClock())


def report_live(args, started: str, connect, clock) -> int:
    """Fly the live variant's pair, told only the team mission; hold it to the six checks one flight can meet,
    and fly its mock twin beside it with all seven. The twin is not a pass condition."""
    from agentic_uav.agents.rule_policy import RulePolicy
    from agentic_uav.experiments.allocation import fly_team_live
    from agentic_uav.experiments.allocation_exit import LIVE_CHECKS, live_checks
    from agentic_uav.experiments.knowledge import observed_poll_hz, poll_tolerance
    from agentic_uav.simulator.observer import DEFAULT_POLL_HZ

    scenario = load_scenario(LIVE_SCENARIO)
    config = load_allocation(args.manifest)
    hz = DEFAULT_POLL_HZ if args.poll_hz is None else args.poll_hz
    wall = time.perf_counter()
    live_flight = fly_team_live(scenario, config, connect(), connect, clock, poll_hz=hz)
    wall = time.perf_counter() - wall
    polled = observed_poll_hz(live_flight.flight.samples, live_flight.flight.poll_hz)
    tol = poll_tolerance(scenario, polled["hz"], RulePolicy().speed_mps)
    run = live_flight.as_run("live")
    checks = live_checks(run, scenario, tol)
    ok = checks["all"]
    twin_flights = allocation_flights(scenario, scenario.random_seed, config)
    twin = exit_checks(twin_flights, scenario)
    rows_msgs = message_log(run.team.deliveries, run.team.traces, run.team.start)

    header = {"kind": "header", "t": started, "sim": "airsim", "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(LIVE_SCENARIO), REPO).replace(os.sep, "/"),
              "manifest": os.path.relpath(allocation_path(args.manifest), REPO).replace(os.sep, "/"),
              "config": config.as_json(), "network": "every message delivered (range unlimited)",
              "observer": live_flight.flight.observer, "poll": polled, "tolerance": tol,
              "checks": {k: checks[k]["ok"] for k in LIVE_CHECKS}, "live_flight_met": ok,
              "mock_twin_all": twin["all"], "wall_s": round(wall, 2), "code": provenance()}
    out_rows = [header,
                {**live_flight.as_json(), "set": "live", "checks": checks,
                 "completion_s": run.team.report.completion_s},
                *({"kind": "message", "set": "live", **r} for r in rows_msgs),
                {"kind": "twin", "set": "mock_twin", "checks": twin,
                 "division": {m: twin_flights[m].searched for m in MODES},
                 "completion_s": {m: twin_flights[m].team.report.completion_s for m in MODES},
                 "nets": {m: twin_flights[m].nets for m in MODES}}]

    def cell(c):
        return "-" if c is None else ("yes" if c["ok"] else "**no**")

    division = "; ".join(f"{d} {', '.join(t)}" for d, t in sorted(live_flight.searched.items()))
    twin_div = "; ".join(f"{d} {', '.join(t)}" for d, t in sorted(twin_flights["deliberating"].searched.items()))
    skills = "; ".join(f"{d}: " + ", ".join(f"{k} {v}" for k, v in sk) for d, sk in live_flight.flight.skills.items())
    lines = [f"# Allocation live — {scenario.scenario_id}", "",
             f"Run {started}, `scripts/allocation_exit.py --sim airsim`, {wall:.1f} s of flight. Two rule agents told "
             f"only the team mission, every message delivered, deliberating (bid window {config.bid_window_s:g} s); "
             f"observer {live_flight.flight.observer}.", "",
             f"Correct here means within **{tol['position_m']:g} m** and **{tol['battery']:g} %** of battery: {tol['why']}.",
             "", "| Check | Live | Mock twin |", "|---|---|---|"]
    lines += [f"| {k} | {cell(checks.get(k))} | {cell(twin.get(k))} |" for k in CHECKS]
    lines += [f"| Division | {division} | {twin_div} |",
              f"| Completion s | {secs(run.team.report.completion_s)} | "
              f"{secs(twin_flights['deliberating'].team.report.completion_s)} |",
              f"| Skills | {skills} | - |",
              f"| Contacts | {', '.join(f'{c.drone}-{c.object}' for c in live_flight.flight.contacts) or 'none'} | - |",
              "", "Determinism needs a second flight: that row is the mock twin's alone.", "",
              f"**Live flight: {'MET' if ok else 'NOT MET'}** — the six checks one flight can be held to"
              + ("" if ok else "; failed: " + ", ".join(k for k in LIVE_CHECKS if not checks[k]["ok"]))
              + ". A live flight of the variant, not the exit.", ""]
    problems = [f"{k}: {p}" for k in LIVE_CHECKS for p in checks[k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]
    os.makedirs(args.out, exist_ok=True)
    stem = f"allocation-live-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
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
