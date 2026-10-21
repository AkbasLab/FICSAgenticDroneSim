#!/usr/bin/env python3
"""Phase 4's exit: the scripted controller flies the search-and-relay mission, judged on every seed.

    python scripts/search_relay_exit.py                         # search_relay_001, seeds 1-20, the mock
    python scripts/search_relay_exit.py --seeds 17              # one seed
    python scripts/search_relay_exit.py --scenario path/to/x.toml

    python scripts/search_relay_exit.py --sim airsim --scenario search_relay_live_small --block live1
    python scripts/search_relay_exit.py --judge results/<file>.jsonl --seeds 1-20

AUV-05's exit criterion: "a fully scripted, non-agentic controller can
complete the canonical mission". `control/scripted.py` plans from the brief
alone and `experiments/evaluation.py` judges the flight against AUV-05's six
criteria. The seeds move the targets; the plan cannot see them.

THREE WAYS TO RUN:

* `--sim mock` (default): one flight per seed on a fresh `MockWorld`,
  simulated time, observed exactly.
* `--sim airsim`: ONE flight in CarlaAir, polled at `--poll-hz`, judged
  against every seed -- the same thing as flying it once per seed, because
  the path cannot depend on targets the controller never sees. The simulator
  must be up with one drone declared in settings.json; Drone2 onwards are
  spawned at runtime, and the leftover-drone check refuses a scene that holds
  others. Only the live-sized scenario fits the airspace flown so far.
* `--judge FILE`: judge a saved live flight again, against `--seeds`.

Outputs, under phases/phase-04-search-relay-mission/results/ by default:

    search-relay-exit-<sim>-<stamp>[-<block>].jsonl   a header, a flight row (live), one row per seed
    search-relay-exit-<sim>-<stamp>[-<block>].md      the tables and the verdict

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

from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import (  # noqa: E402
    EXIT_SEEDS,
    LiveFlight,
    compare_to_mock,
    exit_runs,
    fly_live,
    fly_on_mock,
    plan_json,
)
from agentic_uav.simulator.observer import DEFAULT_POLL_HZ  # noqa: E402

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


def table(rows) -> list[str]:
    """rows: (seed, report, met, skills_ok) for each seed."""
    lines = ["| Seed | Targets (sector) | Met | Completion s | Coverage | Reported at s | "
             "Closest pair m | Lowest battery % | Failing |",
             "|---|---|---|---|---|---|---|---|---|"]
    for seed, r, met, skills_ok in rows:
        f = r.facts
        targets = ", ".join(f"{t.id} ({t.x:.0f}, {t.y:.0f}) {t.sector}" for t in f.targets)
        reports = ", ".join(
            f"{t.id} {rep.reported_at - r.start:.1f}" if (rep := f.first_report(t.id)) else f"{t.id} -"
            for t in f.targets)
        lowest = min(b.remaining for b in f.batteries)
        failing = [c.id for c in r.criteria if not c.passed] + ([] if skills_ok else ["skills"])
        lines.append(f"| {seed} | {targets} | {'yes' if met else '**no**'} | "
                     f"{'-' if r.completion_s is None else f'{r.completion_s:.1f}'} | "
                     f"{r.coverage.fraction:.4f} | {reports} | "
                     f"{r.components['min_separation_m']} | {lowest:.1f} | {', '.join(failing) or '-'} |")
    return lines


def plan_table(plan_rows: dict) -> list[str]:
    lines = ["| Drone | Sector | Height m | Lanes m | Lanes flown (x) | Length m | Estimated s | Estimated battery % |",
             "|---|---|---|---|---|---|---|---|"]
    for d, p in plan_rows.items():
        flown = ", ".join(f"{r[0]:g} to {r[2]:g}" for r in p["searched"])
        lines.append(f"| {d} | {', '.join(p['sectors'])} | {p['altitude_m']:g} | {p['lane_spacing_m']:.2f} | "
                     f"{flown} | {p['length_m']} | {p['estimated_s']:.0f} | {p['estimated_battery_used']} |")
    return lines


def comparison_table(cmp: dict) -> list[str]:
    lines = ["| Drone | Polls | Max off track m | Median off track m | Max height error at cruise m | "
             "Pad error m |", "|---|---|---|---|---|---|"]
    for d, c in cmp["drones"].items():
        lines.append(f"| {d} | {c['samples']} | {c['max_off_track_m']} | {c['median_off_track_m']} | "
                     f"{c['max_height_error_at_cruise_m']} | {c['pad_error_m']} |")
    lines += ["", "| | Live | Mock |", "|---|---|---|",
              f"| Completion s | {cmp['completion_s']['live']} | {cmp['completion_s']['mock']} |",
              f"| Coverage | {cmp['coverage']['live']} | {cmp['coverage']['mock']} |",
              f"| Closest pair m | {cmp['closest_pair_m']['live']} | {cmp['closest_pair_m']['mock']} |"]
    for d, b in cmp["battery_used"].items():
        lines.append(f"| {d} battery used % (estimated {b['estimated']}) | {b['live']} | {b['mock']} |")
    return lines


def write(out: str, stem: str, rows: list[dict], summary: str) -> str:
    os.makedirs(out, exist_ok=True)
    with io.open(os.path.join(out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in rows:
            h.write(json.dumps(row) + "\n")
    with io.open(os.path.join(out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary)
    return os.path.join(out, stem + ".jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="search_relay_001", help="id or path")
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS, help="e.g. 1-20, 17, 1,5,9")
    parser.add_argument("--sim", choices=("mock", "airsim"), default="mock")
    parser.add_argument("--judge", metavar="FILE", help="judge a saved live flight again")
    parser.add_argument("--poll-hz", type=float, default=DEFAULT_POLL_HZ, help="live observer rate")
    parser.add_argument("--host", default="127.0.0.1", help="AirSim host")
    parser.add_argument("--port", type=int, default=None, help="AirSim port")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL", help="short label appended to the file names")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario = load_scenario(args.scenario)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
              "seeds": list(args.seeds), "code": provenance()}
    suffix = f"-{args.block}" if args.block else ""
    when = time.strftime("%Y%m%d-%H%M%S")

    if args.judge or args.sim == "airsim":
        if args.judge:
            with io.open(args.judge, encoding="utf-8") as h:
                saved = [json.loads(line) for line in h]
            flight = LiveFlight.from_json(next(r for r in saved if r.get("kind") == "flight"), scenario)
            kind, title = "rejudge", f"a saved live flight, judged again (`{os.path.basename(args.judge)}`)"
        else:
            from agentic_uav.simulator.airsim_adapter import AIRSIM_PORT, AirSimAdapter
            port = args.port or AIRSIM_PORT
            scene = AirSimAdapter.connect(args.host, port)
            flight = fly_live(scenario, scene, lambda: AirSimAdapter.connect(args.host, port), RealClock(),
                              poll_hz=args.poll_hz)
            kind, title = "airsim", "CarlaAir, one flight"
        reports = [(s, flight.judge(s)) for s in args.seeds]
        rows = [(s, r, flight.met(r), flight.skills_ok) for s, r in reports]
        met = sum(m for _, _, m, _ in rows)
        mock = fly_on_mock(scenario)
        comparison = compare_to_mock(flight, mock)
        ok = met == len(rows)
        header.update(sim=kind, observer=flight.observer, met=met, runs=len(rows), exit_criterion_met=ok,
                      skills_ok=flight.skills_ok, contacts=len(flight.contacts))
        records = ([header] + ([flight.as_json()] if not args.judge else [])
                   + [{"kind": "comparison", "mock_seed": mock.seed, **comparison}]
                   + [{"kind": "seed", "seed": s, "met": m, "report": r.as_json()} for s, r, m, _ in rows])
        skills = "; ".join(f"{d}: " + ", ".join(f"{k['skill']} {k['status']}" for k in ks)
                           for d, ks in flight.skills.items())
        lines = [f"# Search-and-relay — {scenario.scenario_id}, {title}", "",
                 f"Run {started}, `scripts/search_relay_exit.py`. Controller: `control/scripted.py`, from "
                 f"the brief alone. Observer: {flight.observer}. Judge: `experiments/evaluation.py`, "
                 f"against {len(rows)} seeds — the one flight judged on every target layout.", "",
                 "## The plan", ""] + plan_table(plan_json(flight.plan)) + [
                 "", f"Skills: {skills}. Contacts polled: "
                 + (", ".join(f"{c.drone}–{c.object}" for c in flight.contacts) or "none") + ".",
                 "", "## Live beside the mock (seed " + str(mock.seed) + ")", ""] + comparison_table(comparison) + [
                 "", "## Every seed", ""] + table(rows) + [
                 "", f"**{'MET' if ok else 'NOT MET'}** — {met} of {len(rows)} seeds met (mission success, and "
                 f"every planned skill succeeded with no safety landing).", ""]
        summary = "\n".join(lines)
        raw = write(args.out, f"search-relay-exit-{kind}-{when}{suffix}", records, summary)
        print(summary)
        print(f"raw     : {raw}")
        return 0 if ok else 1

    wall = time.perf_counter()
    runs = exit_runs(scenario, args.seeds)
    wall = time.perf_counter() - wall
    met = sum(run.met for run in runs)
    ok = met == len(runs)
    header.update(sim="mock", observer="mock-exact", met=met, runs=len(runs), exit_criterion_met=ok,
                  wall_s=round(wall, 2))
    lines = [f"# Search-and-relay exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/search_relay_exit.py`, {len(runs)} seeds "
             f"({wall:.1f} s wall). Controller: `control/scripted.py`, from the brief alone. "
             f"Observer: the mock's exact trace. Judge: `experiments/evaluation.py`.", "",
             "## The plan (the same for every seed)", ""]
    lines += plan_table(plan_json(runs[0].plan)) if runs else []
    lines += ["", "## Every seed", ""] + table([(r.seed, r.report, r.met, r.skills_ok) for r in runs])
    done = [r.report.completion_s for r in runs if r.report.completion_s is not None]
    if done:
        lines += ["", f"Completion: {min(done):.1f}–{max(done):.1f} s of the "
                      f"{scenario.mission.deadline_s:g} s deadline."]
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {met} of {len(runs)} seeds met "
                  f"(mission success, and every planned skill succeeded with no safety landing).", ""]
    summary = "\n".join(lines)
    raw = write(args.out, f"search-relay-exit-mock-{when}{suffix}", [header] + [r.as_json() for r in runs], summary)
    print(summary)
    print(f"raw     : {raw}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
