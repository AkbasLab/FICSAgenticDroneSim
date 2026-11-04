#!/usr/bin/env python3
"""Phase 9's exit: a drone stopped mid-mission, and the rest carry on with no new human command.

    python scripts/recovery_exit.py                       # seeds 1-20: no stop, and each drone stopped (twice)
    python scripts/recovery_exit.py --seeds 17 --block t

AUV-09's exit criterion: "During a four-drone mission, one agent can be
intentionally stopped. The remaining agents detect the disruption, reassign
its task, and continue without a new human command." How each part is shown
is in `experiments/recovery_exit.py`: each seed flown with no stop and with
each drone stopped in turn at 60 s, each stopped flight twice, every message
delivered; checked -- detected, no false alarm, reassigned, continued, no new
human command, roles from interactions, deterministic, known exactly.

Beside the exit: a reprioritization flight (a drone stopped, the deadline cut
so its task cannot be redone) and the 9.4 report -- the five conditions of
controlled emergence, and two of AUV-19's proxies, reported, not claimed.

Outputs, under phases/phase-09-roles-and-failure-recovery/results/ by default:

    recovery-exit-<stamp>[-<block>].jsonl   a header (manifests, reprioritization, 9.4); per seed the checks,
                                            the division and the reassignments; for the scenario's own seed,
                                            every drone's record with Drone1 stopped, and its messages
    recovery-exit-<stamp>[-<block>].md      the table, the reprioritization, 9.4, the verdict

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
from agentic_uav.experiments.message_log import message_log  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery, recovery_path  # noqa: E402
from agentic_uav.experiments.recovery_exit import (  # noqa: E402
    CHECKS,
    STOP_AT_S,
    emergence_report,
    exit_checks,
    recovery_flights,
    reprioritization,
    validated,
)
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-09-roles-and-failure-recovery", "results")
SCENARIO = "search_relay_001"


def seeds_arg(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return tuple(out)


def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


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
    scenario = load_scenario(SCENARIO)
    config, health = load_allocation(), load_recovery()
    wall = time.perf_counter()
    rows: list[dict] = []
    for seed in args.seeds:
        flights = recovery_flights(scenario, seed, config, health)
        checks = exit_checks(flights, scenario)
        rows.append({"kind": "seed", "seed": seed, "checks": checks,
                     "division": flights["no stop"].searched,
                     "searched": {k: f.searched for k, f in flights.items() if not k.endswith("again")},
                     "completion_s": {k: f.team.report.completion_s for k, f in flights.items()
                                      if not k.endswith("again")},
                     "validated": all(validated(f) for f in flights.values())})
        if seed == scenario.random_seed:
            f = flights["Drone1 stopped"]
            rows.append({"kind": "records", "seed": seed, "flight": "Drone1 stopped", "stopped": f.stopped,
                         "policies": f.policies})
            rows += [{"kind": "message", "seed": seed, "flight": "Drone1 stopped", **r}
                     for r in message_log(f.team.deliveries, f.team.traces, f.team.start)]
    seed_rows = [r for r in rows if r["kind"] == "seed"]
    trouble = reprioritization(scenario, config, health)
    emergence = emergence_report(seed_rows, scenario)
    wall = time.perf_counter() - wall

    ok = all(r["checks"]["all"] for r in seed_rows)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": rel(scenario_path(SCENARIO)), "allocation_manifest": rel(allocation_path()),
              "recovery_manifest": rel(recovery_path()), "allocation": config.as_json(), "health": health.as_json(),
              "network": "every message delivered (range unlimited)", "stop_at_s": STOP_AT_S,
              "seeds": list(args.seeds), "seeds_passed": sum(r["checks"]["all"] for r in seed_rows),
              "exit_criterion_met": ok, "reprioritization": trouble, "emergence": emergence,
              "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Recovery exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/recovery_exit.py`, {wall:.1f} s wall. Four rule agents told only the team "
             f"mission, every message delivered; each seed flown with no stop and with each drone stopped at "
             f"{STOP_AT_S:g} s, each stopped flight twice. Health thresholds {health.as_json()}.", "",
             "| Seed | " + " | ".join(CHECKS) + " | Reassigned (stopped → taken by) |",
             "|---|" + "---|" * len(CHECKS) + "---|"]
    for r in seed_rows:
        c = r["checks"]
        taken = "; ".join(f"{x['stopped']}'s {x['task'].split()[1] if x['task'] else '-'} → {x['taken_by']}"
                          for x in c["reassigned"]["reassignments"])
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if c[k]["ok"] else "**no**" for k in CHECKS) + f" | {taken} |")
    problems = [f"seed {r['seed']}, {k}: {p}" for r in seed_rows for k in CHECKS for p in r["checks"][k]["problems"]]
    t = trouble
    lines += ["", f"**Reprioritization, beside the exit** -- {t['stopped']} stopped, the deadline cut to "
                  f"{t['deadline_s']:g} s: {'as it should' if t['ok'] else '**not as it should**'}. {t['task']} "
                  f"abandoned in every survivor's book ({', '.join(f'{d} at {a[0][0]:g} s' for d, a in t['abandoned'].items() if a)}); "
                  f"nobody chased it; the team ended at {t['ended_s']:g} s with the partial result ({t['coverage']}).", "",
              "**9.4, controlled emergence** -- the five conditions:", ""]
    lines += [f"* {name}: {'held' if v['held'] else '**not held**'} -- {v['how']}"
              for name, v in emergence["conditions"].items()]
    px = emergence["proxies"]
    lines += ["", f"Proxies (AUV-19), reported, not claimed: {len(px['assignment distance from one drone per sector']['drones_off_the_naive_assignment'])} "
                  f"of {px['assignment distance from one drone per sector']['of']} drones off the one-drone-per-sector "
                  f"assignment; {px['allocation divergence across seeds']['distinct_divisions']} distinct division(s) "
                  f"over {px['allocation divergence across seeds']['seeds']} seeds -- "
                  f"{px['allocation divergence across seeds']['note']}.", "",
              f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {header['seeds_passed']} of {len(seed_rows)} seeds "
              "passed every check.", ""]
    if problems or not trouble["ok"]:
        lines += ["Problems:", ""] + [f"* {p}" for p in (problems + trouble["problems"])[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"recovery-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok and trouble["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
