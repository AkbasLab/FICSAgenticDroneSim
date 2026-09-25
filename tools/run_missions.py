#!/usr/bin/env python3
"""Run a mission set against the baseline agent and score the plans.

This is the instrument for objective 1.3. Running the missions by hand is
possible but not reproducible: the point here is that the same command produces
the same series, and the raw evidence is written to disk rather than read off a
console.

    # planner only -- no simulator, no GPU, safe to run any time
    python tools/run_missions.py --plan-only

    # a subset, and a different model
    python tools/run_missions.py --plan-only --missions M05,M07 --model llama3.1:8b

    # single run per mission, for a quick look
    python tools/run_missions.py --plan-only --repeats 1

Outputs, both under phases/phase-01-baseline-freeze/results/:

    <set>-<model>-<timestamp>.jsonl   one record per run: plan, latency, score
    <set>-<model>-<timestamp>.md      the summary table, ready to paste

Flight runs (without --plan-only) need the simulator up and are **not**
automated end to end: multi-drone missions rewrite settings.json and require a
simulator restart, which a script should not be doing behind your back. The
runner tells you when it reaches one.

Scoring
-------
A plan is correct only if its action sequence matches `expected` exactly. Extra
steps are counted separately rather than partially credited, because "nearly
right" plans and correct plans fail differently in flight. Missions with
`scoreable = false` are run and logged but not scored.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
from typing import Any

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "baseline"))

DEFAULT_CONFIG = os.path.join(REPO, "configs", "missions", "baseline_v1.toml")
DEFAULT_OUT = os.path.join(REPO, "phases", "phase-01-baseline-freeze", "results")


def load_toml(path: str) -> dict[str, Any]:
    """Read a TOML file on either Python version in play.

    tomllib arrived in 3.11; this project runs 3.10, where the identical parser
    is installed as `tomli`. Trying the standard library first means the code
    keeps working unchanged after a Python upgrade.

    TOML is opened in BINARY mode -- both parsers require it, because they
    decode UTF-8 themselves rather than trusting the platform default.
    """
    try:
        import tomllib as toml_reader
    except ModuleNotFoundError:
        import tomli as toml_reader
    with open(path, "rb") as handle:
        return toml_reader.load(handle)


def score(actions: list[str], expected: list[str]) -> tuple[bool, int]:
    """Score one plan. Returns (correct, extra_steps).

    Exact sequence match, with no partial credit, because a plan that is nearly
    right fails differently in flight than one that is right: an extra
    `fly_straight` is a drone somewhere it should not be, not a small error.

    `extra_steps` is reported separately so the two failure modes -- inventing
    steps and dropping them -- stay distinguishable in the results, which is
    exactly the contrast M05 and M06 exist to probe.
    """
    return actions == expected, max(0, len(actions) - len(expected))


def run_one(agent, mission: dict[str, Any], model: str, attempt: int) -> dict[str, Any]:
    """Plan every drone's instruction for one mission, once.

    Returns one result record, which is appended verbatim to the JSONL output.
    The record keeps the raw model output alongside the score: a summary table
    answers "did it pass", and only the raw text answers "why did it fail".

    `agent` is the imported open_loop_agent module, passed in rather than
    imported here so the dependency is visible at the call site.
    """
    # Single- and multi-drone missions are shaped differently in the config:
    # `instruction`/`expected` for one drone, `instructions`/`expected_per_drone`
    # for several. Normalise both to lists so the loop below is uniform.
    drones = mission.get("drones", 1)
    if drones == 1:
        instructions = [mission["instruction"]]
        expectations = [mission.get("expected", [])]
    else:
        instructions = mission["instructions"]
        expectations = mission.get("expected_per_drone", [[]] * drones)

    per_drone = []
    for index, instruction in enumerate(instructions):
        # Vehicle names follow settings.json: Drone1, Drone2, … in config order.
        name = f"Drone{index + 1}"
        record = agent.plan_for(instruction, name, model)

        # Two logs on purpose. The agent's own runs/agent-log.jsonl is the raw
        # record of every planning call ever made, whatever ran it; the JSONL
        # this script writes is the scored experiment series. Neither replaces
        # the other.
        agent.log_record(record)

        # A rejected plan scores as incorrect rather than being skipped: a model
        # that emits unflyable plans has failed the mission, and dropping those
        # runs would quietly flatter the results.
        actions = [step["action"] for step in record.plan] if record.valid else []
        correct, extra = score(actions, expectations[index]) if record.valid else (False, 0)
        per_drone.append({
            "drone": name,
            "instruction": instruction,
            "valid": record.valid,
            "error": record.error,
            "actions": actions,
            "expected": expectations[index],
            "correct": correct,
            "extra_steps": extra,
            "plan_seconds": round(record.plan_seconds, 2),
            "normalised": record.normalised,
            "raw_output": record.raw_output,
        })

    # M08 has no correct answer, so it runs and is logged but never scored.
    scoreable = mission.get("scoreable", True)
    return {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mission": mission["id"],
        "category": mission.get("category", ""),
        "attempt": attempt,
        # Model and timestamp travel with every record: a results directory
        # accumulates series from different models, and a row that cannot say
        # which produced it is not evidence.
        "model": model,
        "drones": drones,
        "scoreable": scoreable,
        # A multi-drone mission passes only if EVERY drone's plan is right. One
        # correct plan out of four is a failed mission, not a partial success.
        "all_valid": all(d["valid"] for d in per_drone),
        "all_correct": scoreable and all(d["correct"] for d in per_drone),
        "plan_seconds": round(sum(d["plan_seconds"] for d in per_drone), 2),
        "per_drone": per_drone,
    }


def summarise(rows: list[dict[str, Any]], config: dict[str, Any], model: str) -> str:
    """Build the Markdown summary table from a set of result records.

    Written to disk beside the JSONL and printed to the console. The JSONL is
    the evidence; this is the thing a human reads and pastes into the phase
    record, so it stays small and quotes its own provenance.
    """
    # Group runs by mission so repeats collapse into one row with an x/N score.
    by_mission: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mission.setdefault(row["mission"], []).append(row)

    lines = [
        f"# {config['set']['name']} — {model}",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `tools/run_missions.py`.",
        "",
        "| Mission | Category | Valid | Correct | Extra steps | Latency (s) |",
        "|---|---|---|---|---|---|",
    ]

    latencies: list[float] = []
    correct_total = scoreable_total = 0

    for mission_id, runs in by_mission.items():
        attempts = len(runs)
        valid = sum(1 for r in runs if r["all_valid"])
        scoreable = runs[0]["scoreable"]
        correct = sum(1 for r in runs if r["all_correct"])
        extra = sum(d["extra_steps"] for r in runs for d in r["per_drone"])
        times = [r["plan_seconds"] for r in runs]
        latencies += times
        if scoreable:
            scoreable_total += attempts
            correct_total += correct
        lines.append(
            f"| {mission_id} | {runs[0]['category']} | {valid}/{attempts} | "
            f"{f'{correct}/{attempts}' if scoreable else '—'} | {extra} | "
            f"{statistics.mean(times):.1f} |"
        )

    lines += [
        "",
        f"**Scored runs correct: {correct_total}/{scoreable_total}**"
        f" · median latency {statistics.median(latencies):.1f}s"
        f" · slowest {max(latencies):.1f}s (first call of a session loads the model)",
        "",
        "Missions marked — are unscoreable by design; see the mission set for why.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--model", help="override the model in the config")
    parser.add_argument("--repeats", type=int, help="override the protocol's repeat count")
    parser.add_argument("--missions", help="comma-separated ids, e.g. M05,M07")
    parser.add_argument("--plan-only", action="store_true",
                        help="plan and score without flying (no simulator needed)")
    args = parser.parse_args()

    # The summary contains em dashes and middots. Files are written UTF-8
    # regardless; this stops a cp1252 console mangling the same text on screen.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    config = load_toml(args.config)
    # The config carries the protocol; flags override it for exploration. The
    # recorded model is whatever actually ran, not whatever the config says.
    model = args.model or config["protocol"]["model"]
    repeats = args.repeats or config["protocol"]["repeats"]

    missions = config["mission"]
    if args.missions:
        wanted = {m.strip().upper() for m in args.missions.split(",")}
        missions = [m for m in missions if m["id"].upper() in wanted]
        # Fail on a typo rather than silently running fewer missions than asked
        # for -- "M5" instead of "M05" would otherwise produce an empty series
        # that looks like a real one.
        missing = wanted - {m["id"].upper() for m in missions}
        if missing:
            sys.exit(f"no such mission(s): {', '.join(sorted(missing))}")
    if not missions:
        sys.exit("no missions selected")

    # Flight is refused rather than half-supported. See the module docstring:
    # multi-drone missions rewrite settings.json and need a simulator restart,
    # and a script that does that unprompted can invalidate the single-drone
    # runs sitting in the same results directory.
    if not args.plan_only:
        sys.exit(
            "Flight runs are not automated end to end.\n"
            "Multi-drone missions rewrite settings.json and need a simulator restart,\n"
            "which this script will not do behind your back. Use --plan-only here, and\n"
            "fly missions with:  python baseline/open_loop_agent.py --drones N ...\n"
        )

    # Imported here, not at module scope: the import pulls in the agent, which
    # pulls in ollama on first use. Keeping it late means --help and a bad
    # mission id fail instantly instead of after a model client loads.
    import open_loop_agent as agent

    print(f"set     : {config['set']['name']} v{config['set']['version']}")
    print(f"model   : {model}")
    print(f"missions: {len(missions)} × {repeats} repeats")
    print()

    rows = []
    for mission in missions:
        for attempt in range(1, repeats + 1):
            row = run_one(agent, mission, model, attempt)
            rows.append(row)
            mark = "ok " if row["all_correct"] else ("—  " if not row["scoreable"] else "MISS")
            actions = " ".join(row["per_drone"][0]["actions"]) or "(rejected)"
            print(f"  {row['mission']} {attempt}/{repeats}  {mark}  "
                  f"{row['plan_seconds']:5.1f}s  {actions}")

    os.makedirs(args.out, exist_ok=True)
    # Timestamped filenames, never overwritten: a second run is a second series,
    # not a correction of the first. Losing a run because it was rerun is the
    # kind of data loss nobody notices until the analysis disagrees with itself.
    # The colon in "llama3.2:3b" is illegal in a Windows filename, hence the
    # substitution.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"{config['set']['name']}-{model.replace(':', '_')}-{stamp}"

    jsonl_path = os.path.join(args.out, stem + ".jsonl")
    with io.open(jsonl_path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    md_path = os.path.join(args.out, stem + ".md")
    with io.open(md_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(summarise(rows, config, model))

    print()
    print(summarise(rows, config, model))
    print(f"raw     : {jsonl_path}")
    print(f"summary : {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
