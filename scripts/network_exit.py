#!/usr/bin/env python3
"""Phase 10's exit: the same mission replayed under four network conditions, with reproducible delivery.

    python scripts/network_exit.py                          # seeds 1-20, the four conditions, both ways, twice
    python scripts/network_exit.py --seeds 17 --conditions nominal,partitioned --block t

AUV-10's exit criterion: "The same mission can be replayed under nominal,
degraded, severe and partitioned conditions with reproducible message
delivery." How each part is shown is in `experiments/network_exit.py`: the
canonical four-drone mission with Phase 9's agents, each seed under each
condition with no stop and with Drone1 stopped at 60 s, every flight twice,
and on Phase 9's own network once; checked -- reproducible, as configured,
nominal is Phase 9, known exactly. How the team fared under each condition is
recorded beside it, as findings, not pass conditions.

Outputs, under phases/phase-10-degraded-communications/results/ by default:

    network-exit-<stamp>[-<block>].jsonl   a header (the manifests, the verdict, the findings by condition); per
                                           seed the checks and each flight's findings; for the scenario's own seed,
                                           every drone's record in every flight
    network-exit-<stamp>[-<block>].md      the checks, the findings, the verdict

Exit code 0 only if every check passed on every seed.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.core.messages import lifetimes  # noqa: E402
from agentic_uav.experiments.allocation import allocation_path, load_allocation  # noqa: E402
from agentic_uav.experiments.conditions import CONDITIONS, load_network, network_path  # noqa: E402
from agentic_uav.experiments.network_exit import (  # noqa: E402
    CHECKS,
    STOP_AT_S,
    VARIANTS,
    exit_checks,
    findings,
    network_flights,
)
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import LINK_WINDOW_S, load_recovery, recovery_path  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-10-degraded-communications", "results")
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


def conditions_arg(text: str) -> tuple[str, ...]:
    names = tuple(n.strip() for n in text.split(",") if n.strip())
    unknown = [n for n in names if n not in CONDITIONS]
    if unknown or "nominal" not in names:
        raise argparse.ArgumentTypeError(f"conditions are {CONDITIONS}, nominal always among them; got {names}")
    return names


def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def by_condition(rows: list[dict], names: tuple[str, ...]) -> dict[str, dict]:
    """Each condition and variant's findings, over the seeds."""
    out: dict[str, dict] = {}
    for c in names:
        for label, _ in VARIANTS:
            fs = [r["findings"][c][label] for r in rows]
            done = [f["completion_s"] for f in fs if f["completion_s"] is not None]
            est = [f["estimated_loss"] for f in fs if f["estimated_loss"] is not None]
            entry = {"met": sum(f["met"] for f in fs), "of": len(fs),
                     "completion_s": [min(done), round(statistics.median(done), 1), max(done)] if done else None,
                     "searched_twice": sum(f["searched_twice"] for f in fs),
                     "lease_expiries": sum(f["lease_expiries"] for f in fs),
                     "false_alarms": {k: sum(f["false_alarms"].get(k, 0) for f in fs)
                                      for k in ("suspected", "unreachable", "failed")},
                     "estimated_loss": round(statistics.mean(est), 4) if est else None,
                     "stale_decisions": sum(f["stale_decisions"] for f in fs),
                     "deliveries": {s: sum(f["deliveries"][s] for f in fs) for s in fs[0]["deliveries"]}}
            if label != "no stop":
                entry.update(detected=sum(f["detected"] for f in fs), reassigned=sum(f["reassigned"] for f in fs),
                             taken_by=sorted({d for f in fs for d in f["taken_by"]}))
            out[f"{c} / {label}"] = entry
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--conditions", type=conditions_arg, default=CONDITIONS)
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
    models = {c: load_network(c) for c in args.conditions}
    wall = time.perf_counter()
    rows: list[dict] = []
    extra: list[dict] = []
    for seed in args.seeds:
        flights = network_flights(scenario, seed, config, health, models)
        checks = exit_checks(flights, scenario)
        rows.append({"kind": "seed", "seed": seed, "checks": checks,
                     "findings": {c: {label: findings(flights["flown"][(c, label)][0]) for label, _ in VARIANTS}
                                  for c in args.conditions}})
        if seed == scenario.random_seed:
            for (c, label), (run, _) in flights["flown"].items():
                extra.append({"kind": "records", "seed": seed, "condition": c, "flight": label,
                              "network": run.network.as_json(), "stopped": run.stopped, "policies": run.policies})
    wall = time.perf_counter() - wall

    ok = all(r["checks"]["all"] for r in rows)
    summary = by_condition(rows, args.conditions)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": rel(scenario_path(SCENARIO)), "allocation_manifest": rel(allocation_path()),
              "recovery_manifest": rel(recovery_path()),
              "conditions": {c: models[c].as_json() for c in args.conditions},
              "manifests": {c: rel(network_path(c)) for c in args.conditions},
              "lifetimes_s": lifetimes(), "link_window_s": LINK_WINDOW_S, "stop_at_s": STOP_AT_S,
              "seeds": list(args.seeds), "seeds_passed": sum(r["checks"]["all"] for r in rows),
              "exit_criterion_met": ok, "findings": summary, "wall_s": round(wall, 2), "code": provenance()}

    lines = [f"# Network exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/network_exit.py`, {wall:.1f} s wall. Four rule agents told only the team mission; "
             f"each seed under {', '.join(args.conditions)}, with no stop and with Drone1 stopped at {STOP_AT_S:g} s, "
             "every flight twice, and on Phase 9's network once.", "",
             "| Seed | " + " | ".join(CHECKS) + " |", "|---|" + "---|" * len(CHECKS)]
    for r in rows:
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if r["checks"][k]["ok"] else "**no**" for k in CHECKS) + " |")
    lines += ["", "**How the team fared, beside the exit** (over the seeds; not pass conditions):", "",
              "| Condition / flight | Met | Completion s (min, median, max) | Searched twice | Leases run out "
              "| False alarms (suspected, unreachable, failed) | Loss estimated | Stale decisions | Stop detected, task taken |",
              "|---|---|---|---|---|---|---|---|---|"]
    for k, f in summary.items():
        fa = f["false_alarms"]
        stop = "-" if "detected" not in f else f"{f['detected']}/{f['of']}, {f['reassigned']}/{f['of']}"
        lines.append(f"| {k} | {f['met']}/{f['of']} | {f['completion_s']} | {f['searched_twice']} | {f['lease_expiries']} "
                     f"| {fa['suspected']}, {fa['unreachable']}, {fa['failed']} | {f['estimated_loss']} "
                     f"| {f['stale_decisions']} | {stop} |")
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {header['seeds_passed']} of {len(rows)} seeds "
                  "passed every check.", ""]
    problems = [f"seed {r['seed']}, {k}: {p}" for r in rows for k in CHECKS for p in r["checks"][k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"network-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in [header] + rows + extra:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines))
    print("\n".join(lines))
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
