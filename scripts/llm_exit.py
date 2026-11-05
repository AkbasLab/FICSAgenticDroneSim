#!/usr/bin/env python3
"""Phase 12's exit: each drone decides with its own LLM context, every action still guarded.

    python scripts/llm_exit.py --ollama-host http://127.0.0.1:11435          # seeds 1-5, the pinned model
    python scripts/llm_exit.py --echo --seeds 17 --block t                   # the echo model: no server, a dry run

AUV-12's exit criterion: "Each drone uses a distinct persistent agent context to make mission-level decisions
during flight, while every action still passes through structured validation and runtime assurance." How each
part is shown is in `experiments/llm_exit.py`: the canonical four, Phase 9's team as protocol and procedure,
the pinned model deciding, the guardian and keep-out on; each seed with no stop and with Drone1 stopped at
60 s, every reply recorded and each flight flown again offline from its record. Checked: distinct contexts,
the model decides, everything guarded, each flight replays exactly; and over the run, the model frozen -- the
server held the pinned digest (configs/llm/default.toml) before the first flight and after the last.

Outputs, under phases/phase-12-llm-agent-policy/results/ by default:

    llm-exit-<stamp>[-<block>].jsonl   a header (manifest, digests, verdict, findings); per seed the checks and
                                       findings; per flight every drone's LLM log (contexts, replies) and every
                                       guardian record; and the recorded replies, to replay any flight again
    llm-exit-<stamp>[-<block>].md      the checks, the findings, the verdict

Exit code 0 only if every check passed on every flight.
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

from agentic_uav.coordination.keepout import parse_keepout  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.llm import llm_path, load_llm, preflight  # noqa: E402
from agentic_uav.experiments.llm_exit import CHECKS, exit_checks, findings, llm_flights  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-12-llm-agent-policy", "results")
KEEPOUT = os.path.join(REPO, "configs", "keepout", "default.toml")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=seeds_arg, default=(1, 2, 3, 4, 5))
    parser.add_argument("--ollama-host")
    parser.add_argument("--echo", action="store_true", help="the echo model, no server: a dry run, never of record")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL")
    args = parser.parse_args(argv)
    if args.echo == bool(args.ollama_host):
        parser.error("give --ollama-host (the pinned model) or --echo (a dry run), not both")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    config = load_llm()
    before: list[str] = []
    if args.echo:
        from agentic_uav.planners.llm_ask import EchoAsk
        ask, model = EchoAsk(), "echo"
    else:
        before = preflight(config, args.ollama_host)
        if before:
            print("NOT FLOWN: " + "; ".join(before))
            return 2
        from agentic_uav.planners.llm_ask import OllamaAsk
        ask, model = OllamaAsk(config.model, args.ollama_host, config.options, config.timeout_s), config.model
    fly = {"guardian": load_guardian(), "keep_out": parse_keepout(load_toml(KEEPOUT), KEEPOUT)}
    scenario = load_scenario(SCENARIO)
    alloc, health = load_allocation(), load_recovery()
    wall = time.perf_counter()
    rows, extra = [], []
    for seed in args.seeds:
        flights = llm_flights(scenario, seed, alloc, health, ask, fly)
        checks = exit_checks(flights)
        found = findings(flights)
        rows.append({"kind": "seed", "seed": seed, "checks": checks, "findings": found})
        for label, f in flights.items():
            extra.append({"kind": "flight", "seed": seed, "flight": label, "llm": f["logs"],
                          "guardians": f["run"].guardians, "executed": f["run"].executed,
                          "records": f["records"]})
        print(f"seed {seed}: " + ", ".join(f"{k} {'yes' if checks[k]['ok'] else 'NO'}" for k in CHECKS)
              + " | " + "; ".join(f"{label}: met {x['met']}, {x['model_decisions']} model decisions, "
                                  f"{x['decisions'].get('fallback', 0)} fallbacks" for label, x in found.items()),
              flush=True)
    wall = time.perf_counter() - wall
    after = [] if args.echo else preflight(config, args.ollama_host)
    frozen = {"ok": not args.echo and not before and not after, "before": before, "after": after}
    ok = all(r["checks"]["all"] for r in rows) and (frozen["ok"] or args.echo)

    header = {"kind": "header", "t": started, "model": model, "endpoint": args.ollama_host or "echo",
              "manifest": os.path.relpath(llm_path(), REPO), "llm": config.as_json(), "model_frozen": frozen,
              "keep_out": fly["keep_out"].as_json(), "guardian": fly["guardian"].as_json(),
              "seeds": list(args.seeds), "seeds_passed": sum(r["checks"]["all"] for r in rows),
              "exit_criterion_met": ok and not args.echo, "dry_run": args.echo, "wall_s": round(wall, 1),
              "code": provenance()}
    lines = [f"# LLM exit — {scenario.scenario_id}, mock, {model}", "",
             f"Run {started}, `scripts/llm_exit.py`, {wall:.0f} s wall"
             + (" -- **a dry run with the echo model, never of record**" if args.echo else
                f", the pinned model `{config.model}` at `{config.digest[:12]}` via {args.ollama_host}")
             + ". The canonical four with the guardian and the keep-out; each seed with no stop and with Drone1 "
               "stopped at 60 s; every flight flown again offline from its recorded replies.", "",
             "| Seed | " + " | ".join(CHECKS) + " |", "|---|" + "---|" * len(CHECKS)]
    for r in rows:
        lines.append(f"| {r['seed']} | " + " | ".join("yes" if r["checks"][k]["ok"] else "**no**" for k in CHECKS) + " |")
    lines += ["", f"Model frozen: {'yes' if frozen['ok'] else ('-- (dry run)' if args.echo else '**no**')}"
                  + ("" if args.echo else f" -- the server held `{config.digest[:12]}` before the first flight and "
                                          "after the last."), "",
              "**Findings** (not pass conditions):", "",
              "| Seed, flight | Met | Ended s | Model decisions (agreed with the rule) | Fallbacks | Corrected "
              "| Guardian interventions | Tools chosen | Model p50 s |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for label, x in r["findings"].items():
            inter = ", ".join(f"{k} {v}" for k, v in x["interventions"].items()) or "none"
            lines.append(f"| {r['seed']}, {label} | {'yes' if x['met'] else 'no'} | {x['completion_s']} "
                         f"| {x['model_decisions']} ({x['agreed']}) | {x['decisions'].get('fallback', 0)} "
                         f"| {x['decisions'].get('corrected', 0)} | {inter} "
                         f"| {', '.join(f'{k} {v}' for k, v in x['tools'].items())} | {x['latency_p50_s']} |")
    verdict = "DRY RUN" if args.echo else ("MET" if ok else "NOT MET")
    lines += ["", f"**Exit criterion: {verdict}** — {header['seeds_passed']} of {len(rows)} seeds passed every check.", ""]
    problems = [f"seed {r['seed']}, {k}: {p}" for r in rows for k in CHECKS for p in r["checks"][k]["problems"]]
    problems += [f"model frozen: {p}" for p in before + after]
    if problems:
        lines += ["Problems:", ""] + [f"* {p}" for p in problems[:40]] + [""]

    os.makedirs(args.out, exist_ok=True)
    stem = f"llm-exit-{time.strftime('%Y%m%d-%H%M%S')}" + (f"-{args.block}" if args.block else "")
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
