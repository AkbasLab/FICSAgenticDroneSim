#!/usr/bin/env python3
"""Phase 11's exit: unsafe and invalid commands injected through both channels, and none executed.

    python scripts/guardian_exit.py                         # seeds 1-20, every injection
    python scripts/guardian_exit.py --seeds 17 --only rule-zone,llm-nan --block t

AUV-11's exit criterion: "Unsafe or invalid LLM and rule-policy commands can be
deliberately injected, and the guardian prevents their execution." How each
part is shown is in `experiments/guardian_exit.py`: the canonical four-drone
mission with Phase 9's agents on Phase 9's network, each seed flown without a
guardian, guarded and clean, guarded through the LLM channel, and once per
injection (33: rule-policy and LLM channel, at least one per check); checked
-- clean is Phase 9, the channel is transparent, no interventions when clean,
every injection stopped, every limit kept. What each injection cost the
mission is recorded beside it, as findings, not pass conditions.

Outputs, under phases/phase-11-runtime-safety-guardian/results/ by default:

    guardian-exit-<stamp>[-<block>].jsonl   a header (the manifest, the injections, the verdict, the findings
                                            by injection); per seed the checks and each injection's findings;
                                            for the scenario's own seed, every guarded flight's guardian records
                                            and every injection's record
    guardian-exit-<stamp>[-<block>].md      the checks, the findings, the verdict

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
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.experiments.allocation import allocation_path, load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import (  # noqa: E402
    CHECKS,
    INJECTIONS,
    exit_checks,
    guardian_flights,
    guardian_path,
    injection_findings,
    load_guardian,
)
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery, recovery_path  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario, scenario_path  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-11-runtime-safety-guardian", "results")
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


def only_arg(text: str) -> tuple[str, ...]:
    names = tuple(n.strip() for n in text.split(",") if n.strip())
    known = {i.name for i in INJECTIONS}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise argparse.ArgumentTypeError(f"no injection called {unknown}; they are {sorted(known)}")
    return names


def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def by_injection(rows: list[dict], injections: tuple) -> dict[str, dict]:
    """Each injection over the seeds: as expected, the mission met, the delay, the knock-ons."""
    out = {}
    for inj in injections:
        fs = [r["findings"][inj.name] for r in rows]
        delays = [f["delay_s"] for f in fs if f["delay_s"] is not None]
        out[inj.name] = {
            "channel": inj.channel, "check": inj.check, "expected": inj.outcome, "what": inj.what,
            "made": sum(f["made_at_s"] is not None for f in fs), "of": len(fs),
            "as_expected": sum(f["outcome"] == inj.outcome and inj.check in (f["checks"] or []) for f in fs),
            "fallbacks": dict(Counter(f["fallback"] for f in fs if f["fallback"])),
            "met": sum(f["met"] for f in fs),
            "delay_s": [min(delays), round(statistics.median(delays), 1), max(delays)] if delays else None,
            "knock_on": sum(len(f["knock_on"]) for f in fs),
            "knock_on_checks": dict(Counter(c for f in fs for k in f["knock_on"] for c in k["checks"])),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--only", type=only_arg, help="some injections only (comma-separated names)")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario = load_scenario(SCENARIO)
    config, health, limits = load_allocation(), load_recovery(), load_guardian()
    injections = tuple(i for i in INJECTIONS if args.only is None or i.name in args.only)
    wall = time.perf_counter()
    rows: list[dict] = []
    extra: list[dict] = []
    for seed in args.seeds:
        flights = guardian_flights(scenario, seed, config, health, limits, injections)
        checks = exit_checks(flights, limits, scenario)
        rows.append({"kind": "seed", "seed": seed, "checks": checks, "findings": injection_findings(flights)})
        if seed == scenario.random_seed:
            for label, run, record in ([("clean", flights["clean"], None), ("clean, LLM", flights["channel"], None)]
                                       + [(n, r, rec) for n, (r, rec) in flights["injected"].items()]):
                extra.append({"kind": "records", "seed": seed, "flight": label, "injection": record,
                              "guardians": run.guardians, "executed": run.executed})
        print(f"seed {seed}: " + ", ".join(f"{k} {'yes' if checks[k]['ok'] else 'NO'}" for k in CHECKS), flush=True)
    wall = time.perf_counter() - wall

    ok = all(r["checks"]["all"] for r in rows)
    summary = by_injection(rows, injections)
    header = {"kind": "header", "t": started, "scenario": scenario.scenario_id,
              "scenario_file": rel(scenario_path(SCENARIO)), "allocation_manifest": rel(allocation_path()),
              "recovery_manifest": rel(recovery_path()), "guardian_manifest": rel(guardian_path()),
              "limits": limits.as_json(), "injections": [i.as_json() for i in injections],
              "seeds": list(args.seeds), "seeds_passed": sum(r["checks"]["all"] for r in rows),
              "exit_criterion_met": ok, "findings": summary, "wall_s": round(wall, 2), "code": provenance()}

    flights_per_seed = 3 + len(injections)
    lines = [f"# Guardian exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/guardian_exit.py`, {wall:.1f} s wall. Four rule agents told only the team "
             f"mission, on Phase 9's network; each seed flown without a guardian, guarded and clean, guarded through "
             f"the LLM channel, and once per injection ({len(injections)}): {flights_per_seed} flights a seed, "
             f"{flights_per_seed * len(rows)} in all.", "",
             "| Seed | " + " | ".join(CHECKS) + " |", "|---|" + "---|" * len(CHECKS)]
    for r in rows:
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if r["checks"][k]["ok"] else "**no**" for k in CHECKS) + " |")
    lines += ["", "**Each injection, over the seeds** (outcome and check as expected is part of the exit; "
                  "the mission's cost is a finding):", "",
              "| Injection | Channel | Expected | Made | As expected | Fallback | Mission met "
              "| Delay s (min, median, max) | Knock-on |", "|---|---|---|---|---|---|---|---|---|"]
    for name, f in summary.items():
        fb = ", ".join(f"{k} {v}" for k, v in f["fallbacks"].items()) or "-"
        knock = f"{f['knock_on']}" + (f" ({', '.join(f'{k} {v}' for k, v in f['knock_on_checks'].items())})"
                                      if f["knock_on_checks"] else "")
        lines.append(f"| {name} | {f['channel']} | {f['expected']} ({f['check']}) | {f['made']}/{f['of']} "
                     f"| {f['as_expected']}/{f['of']} | {fb} | {f['met']}/{f['of']} | {f['delay_s']} | {knock} |")
    approved = sum(r["checks"]["no_interventions"]["approved"] for r in rows)
    lines += ["", f"Clean flights: {approved} commands approved as they stood over the seeds, none modified, "
                  "refused or replaced.", "",
              f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {header['seeds_passed']} of {len(rows)} seeds "
              "passed every check.", ""]
    problems = [f"seed {r['seed']}, {k}: {p}" for r in rows for k in CHECKS for p in r["checks"][k]["problems"]]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:50]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"guardian-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
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
