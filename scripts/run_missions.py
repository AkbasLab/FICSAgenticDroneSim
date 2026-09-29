#!/usr/bin/env python3
"""Run a mission set against the baseline agent and score the plans.

This is the instrument for objective 1.3. Running the missions by hand is
possible but not reproducible: the point here is that the same command produces
the same series, and the raw evidence is written to disk rather than read off a
console.

    # planner only -- no simulator, no GPU, safe to run any time
    python scripts/run_missions.py --plan-only

    # a subset, and a different model
    python scripts/run_missions.py --plan-only --missions M05,M07 --model llama3.1:8b

    # single run per mission, for a quick look
    python scripts/run_missions.py --plan-only --repeats 1

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


def snapshot_code(agent, out_dir: str, stem: str, config_path: str) -> dict[str, Any]:
    """Archive the exact code and config this series ran, beside its data.

    A git SHA identifies code only if the tree was clean, and in practice runs
    are flown from uncommitted work -- most of this project's flights were. So
    the actual files are copied into `<stem>-code/` next to the JSONL, and the
    manifest records digests, the commit, and whether the tree was dirty.

    One snapshot per series, not per run: every run in a series is flown by the
    same code, and the per-row digests prove it. Three small text files against
    two dozen runs is the right trade.

    This is `AUV-14` §14.2 (experiment manifest) arriving early, because the
    question "which agent produced this number" is already live.
    """
    import shutil

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sources = {
        "open_loop_agent.py": os.path.join(repo, "baseline", "open_loop_agent.py"),
        "run_missions.py": os.path.abspath(__file__),
        os.path.basename(config_path): os.path.abspath(config_path),
    }

    folder = os.path.join(out_dir, stem + "-code")
    os.makedirs(folder, exist_ok=True)
    digests = {}
    for name, source in sources.items():
        shutil.copy2(source, os.path.join(folder, name))
        digests[name] = agent.file_digest(source)

    manifest = dict(agent.provenance(), files=digests, snapshot=os.path.basename(folder))
    with io.open(os.path.join(folder, "manifest.json"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")
    return manifest


def current_roster(agent) -> list[str]:
    """The vehicles in settings.json right now.

    Read rather than assumed: the file is what the *running* simulator loaded
    at startup, and a mismatch is the difference between a flight and a pile of
    "vehicle not found" errors.
    """
    import json as _json
    path = os.path.join(agent.documents_dir(), "AirSim", "settings.json")
    try:
        with io.open(path, encoding="utf-8-sig") as handle:
            return list(_json.load(handle).get("Vehicles", {}))
    except (OSError, ValueError):
        return []


def describe(row: dict[str, Any], attempt: int, repeats: int) -> str:
    """One line per run for the console, readable while a set is flying."""
    mark = "ok  " if row["all_correct"] else ("--  " if not row["scoreable"] else "MISS")
    actions = " ".join(row["per_drone"][0]["actions"]) or "(rejected)"
    line = (f"{row['mission']} {attempt}/{repeats}  {mark}  "
            f"plan {row['plan_seconds']:5.1f}s  {actions}")

    execution = row.get("execution")
    if not execution:
        return line
    if not execution.get("flown"):
        return line + f"  | not flown: {execution.get('reason')}"

    flight = max((o["flight_seconds"] for o in execution["outcomes"]), default=0)
    line += f"  | flew {flight:.0f}s {'complete' if execution['completed'] else 'INCOMPLETE'}"
    if execution["collision"]:
        line += "  COLLISION"
    separation = execution.get("separation") or {}
    if separation.get("measured"):
        line += f"  min sep {separation['min_separation_m']}m"
    return line


def fly_one(agent, client, mission: dict[str, Any], model: str, attempt: int,
            protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    """Plan and FLY one mission, once. Same record as run_one plus `execution`.

    The order is deliberate:

    1. **Reset the world**, so every repeat starts from the same pose. Without
       it each run begins where the last ended -- ground height drifted from
       29.25 to 27.27 across runs in practice, which would make three
       "repeats" three different experiments.
    2. **Plan before anything arms**, so a rejected plan costs no flight time.
    3. **Fly through the agent's own `fly_plans`**, not a copy, so a scored run
       and a hand-flown run are the same procedure.
    """
    row = run_one(agent, mission, model, attempt, protocol)   # plan and score first

    if not row["all_valid"]:
        row["execution"] = {"flown": False, "reason": "plan rejected"}
        return row

    agent.reset_world(client)

    records = [
        agent.PlanRecord(
            drone=drone["drone"],
            instruction=drone["instruction"],
            raw_output=drone["raw_output"],
            plan=drone["plan_steps"],
            plan_seconds=drone["plan_seconds"],
            valid=True,
            model=model,
        )
        for drone in row["per_drone"]
    ]

    outcomes, separation = agent.fly_plans(client, records)
    agent.log_execution(outcomes, separation)

    row["execution"] = {
        "flown": True,
        "completed": all(o["completed"] for o in outcomes),
        # A collision only counts if it is new this flight AND not the ground:
        # every landing registers terrain contact, so counting that would make
        # the metric meaningless.
        "collision": any(
            o.get("collision", {}).get("has_collided")
            and o["collision"].get("new_this_flight")
            and not o["collision"].get("is_ground")
            for o in outcomes
        ),
        "ground_contact": any(o.get("collision", {}).get("is_ground") for o in outcomes),
        "separation": separation,
        "outcomes": outcomes,
    }
    return row


def run_one(agent, mission: dict[str, Any], model: str, attempt: int,
            protocol: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if record.valid and mission.get("scoreable", True):
            correct, extra = score(actions, expectations[index])
        else:
            # An unscoreable mission has no expected sequence, so comparing
            # against an empty list would report every step as "extra" -- M08
            # showed 12 extra steps for three perfectly reasonable 4-step plans.
            # A rejected plan is likewise not scored, only recorded.
            correct, extra = False, 0
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
            # The validated steps with their parameters, not just action names:
            # a flight needs the durations and coordinates too.
            "plan_steps": record.plan if record.valid else None,
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
        # The conditions this run flew under, copied into the row rather than
        # left implicit in the config. A series can span several simulator
        # sessions and several days, and the config may be edited between them;
        # a row that cannot state its own conditions is not evidence.
        "protocol": protocol,
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
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/run_missions.py`.",
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
            f"{f'{correct}/{attempts}' if scoreable else '—'} | "
            f"{extra if scoreable else '—'} | "
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
    parser.add_argument("--pause", action="store_true",
                        help="wait for a keypress between runs, to watch each one")
    parser.add_argument("--block", metavar="LABEL",
                        help="short label for this session, e.g. blockB-M09. "
                             "Appears in every filename so a results folder "
                             "reads as a list of sessions rather than timestamps")
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

    # Imported here, not at module scope: the import pulls in the agent, which
    # pulls in ollama on first use. Keeping it late means --help and a bad
    # mission id fail instantly instead of after a model client loads.
    import open_loop_agent as agent

    client = None
    if not args.plan_only:
        # Mixed drone counts in one pass are fine now. Vehicles a mission needs
        # are spawned into the running simulator by ensure_vehicles(), so M09
        # (two drones) and M10 (four) can follow M01-M08 (one) without a
        # restart between them.
        #
        # This previously refused a mixed set and demanded a settings.json edit
        # plus a restart per block. That was wrong: simAddVehicle adds vehicles
        # to a running simulator, which was documented in this project's own
        # reference set the whole time.
        needed = sorted({m.get("drones", 1) for m in missions})
        count = max(needed)
        roster = current_roster(agent)
        print(f"roster  : {len(roster)} declared in settings.json; "
              f"missions need up to {count} "
              f"({'spawned at runtime as required' if count > len(roster) else 'sufficient'})")

        import airsim
        client = airsim.MultirotorClient(ip="127.0.0.1", port=41451)
        client.confirmConnection()

    mode = "planning only" if args.plan_only else f"FLYING, {count} drone(s)"
    print(f"set     : {config['set']['name']} v{config['set']['version']}")
    print(f"model   : {model}")
    print(f"missions: {len(missions)} × {repeats} repeats  ({mode})")
    print()

    os.makedirs(args.out, exist_ok=True)

    # ONE stem per invocation, fixed before the first run, timestamped so a
    # re-run never overwrites an earlier one.
    #
    # One file per block ON PURPOSE: M01-M08, M09 and M10 each need their own
    # simulator session for the roster, and keeping their logs separate means
    # each file is short enough to read. A merged log would be one long file
    # covering three sessions.
    #
    # An earlier version stamped the live file at the start and wrote a second
    # file at the end, producing two files holding the same 24 runs under
    # different names, with a summary matching only one of them.
    # The colon in "llama3.2:3b" is illegal in a Windows filename.
    # Naming convention, documented in results/README.md:
    #   <set>-<model>-<stamp>[-<block>].jsonl        the runs
    #   <set>-<model>-<stamp>[-<block>].md           the summary
    #   <set>-<model>-<stamp>[-<block>]-code/        the code that flew them
    #
    # The block label is optional but worth passing: a folder of timestamps
    # tells you when a session ran, not what it was.
    label = f"-{args.block}" if args.block else ""
    stem = (f"{config['set']['name']}-{model.replace(':', '_')}"
            f"-{time.strftime('%Y%m%d-%H%M%S')}{label}")
    live_path = os.path.join(args.out, stem + ".jsonl")

    # Archive the code and config that are about to fly, before anything flies.
    manifest = snapshot_code(agent, args.out, stem, args.config)
    print(f"code    : {manifest['commit']}"
          f"{' (dirty tree)' if manifest['dirty'] else ''}"
          f" -> {manifest['snapshot']}/")

    rows = []
    for mission in missions:
        for attempt in range(1, repeats + 1):
            # Each row carries the conditions it flew under. Blocks are flown in
            # separate sessions, possibly days apart, and the config may be
            # edited between them; a row that cannot state its own conditions is
            # not evidence.
            conditions = dict(config["protocol"], flown=not args.plan_only,
                              code=manifest)
            if args.plan_only:
                row = run_one(agent, mission, model, attempt, conditions)
            else:
                row = fly_one(agent, client, mission, model, attempt, conditions)
            rows.append(row)

            # Append as we go. A crash or a hung flight three hours into a set
            # must not cost the runs that already succeeded.
            with io.open(live_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row) + "\n")

            print("  " + describe(row, attempt, repeats))

            # Step-by-step: stop after each run so the simulator can be watched
            # and the result read before the next one starts.
            if args.pause and not (mission is missions[-1] and attempt == repeats):
                input("    [enter] next run  ")

    # The JSONL was written row by row as the runs completed; nothing more to
    # write here. The summary describes this block only, and sits beside its
    # own data with the same stem.
    md_path = os.path.join(args.out, stem + ".md")
    with io.open(md_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(summarise(rows, config, model))

    print()
    print(summarise(rows, config, model))
    print(f"raw     : {live_path}")
    print(f"summary : {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
