#!/usr/bin/env python3
"""Phase 5's exit: one rule-based agent, told only "search S3", on the mock.

    python scripts/single_agent_exit.py                    # 20 seeds, then the five troubles
    python scripts/single_agent_exit.py --seeds 17 --block t

AUV-06's exit criterion: "one deterministic persistent agent completes a
search task without receiving a complete preflight action list, recognises
success or failure, and decides what to do next." `experiments/single_agent.py`
says how each part is shown; this script runs it and keeps the record.

Outputs, under phases/phase-05-persistent-agent/results/ by default:

    single-agent-exit-<stamp>[-<block>].jsonl   a header, one row per nominal seed, one per trouble
    single-agent-exit-<stamp>[-<block>].md      the tables and the verdict

Every row carries the full decision trace: each decision's time, the events
that caused it, the belief it was made on, the decision, the verdict and
what the agent did.

Exit code 0 only if every nominal seed met and every trouble met its check.
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
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402
from agentic_uav.experiments.single_agent import EXIT_TASK, exit_runs, trouble_runs  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-05-persistent-agent", "results")


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
    parser.add_argument("--scenario", default="search_single_001")
    parser.add_argument("--task", default=EXIT_TASK)
    parser.add_argument("--seeds", type=seeds_arg, default=EXIT_SEEDS)
    parser.add_argument("--no-trouble", action="store_true", help="the nominal seeds only")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    scenario = load_scenario(args.scenario)
    wall = time.perf_counter()
    runs = exit_runs(scenario, args.seeds, args.task)
    troubles = [] if args.no_trouble else trouble_runs(scenario, args.task)
    wall = time.perf_counter() - wall
    met = sum(r.met for r in runs)
    trouble_met = sum(ok for _, _, ok, _ in troubles)
    ok = met == len(runs) and trouble_met == len(troubles)

    header = {"kind": "header", "t": started, "sim": "mock", "scenario": scenario.scenario_id,
              "scenario_file": os.path.relpath(scenario_path(args.scenario), REPO).replace(os.sep, "/"),
              "task": args.task, "seeds": list(args.seeds), "nominal_met": met, "nominal_runs": len(runs),
              "troubles_met": trouble_met, "troubles": len(troubles), "exit_criterion_met": ok,
              "wall_s": round(wall, 2), "code": provenance()}
    rows = [header] + [{"kind": "nominal", **r.as_json()} for r in runs]
    rows += [{"kind": "trouble", "trouble": t.name, "what": t.what, "expect": t.expect, "check_met": good,
              "problems": problems, **run.as_json()} for t, run, good, problems in troubles]

    lines = [f"# Single-agent exit — {scenario.scenario_id}, mock", "",
             f"Run {started}, `scripts/single_agent_exit.py`, {wall:.1f} s wall. Agent: `agents/drone_agent.py` "
             f"with `agents/rule_policy.py`, told only `{args.task!r}`. Judge: `experiments/evaluation.py`.", "",
             "## Nominal: the task, on every seed", "",
             "| Seed | Met | Completion s | Coverage | Targets reported at s | Battery left % | Skills | Decisions |",
             "|---|---|---|---|---|---|---|---|"]
    for r in runs:
        rep = r.report
        reports = ", ".join(f"{t.id} {x.reported_at - rep.start:.1f}" if (x := rep.facts.first_report(t.id)) else f"{t.id} -"
                            for t in rep.facts.targets)
        lines.append(f"| {r.seed} | {'yes' if r.met else '**no**'} | "
                     f"{'-' if rep.completion_s is None else f'{rep.completion_s:.1f}'} | {rep.coverage.fraction:.4f} | "
                     f"{reports} | {rep.facts.batteries[0].remaining:.1f} | {' → '.join(s for s, _ in r.skills)} | "
                     f"{len(r.trace)} |")
    if troubles:
        lines += ["", "## Trouble: what went wrong, what the agent had to do, what it did", "",
                  "| Trouble | What | Expected | Skills (how each ended) | Its reason | Criteria failing | Check |",
                  "|---|---|---|---|---|---|---|"]
        for t, run, good, problems in troubles:
            failing = [c.id for c in run.report.criteria if not c.passed]
            lines.append(f"| {t.name} | {t.what} | {t.expect} | "
                         f"{', '.join(f'{s} {st}' for s, st in run.skills)} | {run.progress.get('gave_up', '-')} | "
                         f"{', '.join(failing) or '-'} | {'**met**' if good else 'NOT MET: ' + '; '.join(problems)} |")
    lines += ["", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {met} of {len(runs)} nominal seeds met "
                  f"(mission success, finished by the agent, every skill chosen as it went)"
                  + (f"; {trouble_met} of {len(troubles)} troubles met their checks." if troubles else "."), ""]
    summary = "\n".join(lines)

    os.makedirs(args.out, exist_ok=True)
    stem = f"single-agent-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        for row in rows:
            h.write(json.dumps(row, default=str) + "\n")
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary)
    print(summary)
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
