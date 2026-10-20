#!/usr/bin/env python3
"""Record the Phase 2 goldens: what the frozen baseline does, call for call.

    python tools/record_golden.py            # writes tests/golden/*.json
    python tools/record_golden.py --check    # compares instead, exits 1 on drift

Phase 2 refactors the agent into modules without changing what it does (AUV-03,
2.3). That needs "what it does" written down BEFORE anything moves, in a form
two versions of the code can be compared on. Two files:

* `execution.json` -- every distinct plan this project has ever flown, taken
  from the recorded results, flown through the real `fly_plans` against the
  recording fake in `tests/airsim_fake.py`. Per drone: the exact sequence of
  AirSim calls and arguments. Plus the outcome record each flight returns.
  Synthetic cases add the paths real flights rarely take: a `land` that does
  not descend, and leftover drones in the scene.
* `planning.json` -- every distinct model reply on record, replayed through the
  real `plan_for` with a scripted model. Per reply: the exact request sent
  (messages, schema, options, host) and the record produced. Synthetic replies
  add the error paths: unparseable JSON, an invalid plan, an unreachable
  endpoint.

Recorded from the code at `v0.1-open-loop-baseline`. Re-recording later is
allowed only when a change of behaviour is deliberate, and that change then
belongs in the phase record. `tests/test_golden.py` runs the comparison on
every test run.

A tool, not a script: it produces a test fixture, never a result.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "baseline"), os.path.join(ROOT, "tests")]

import open_loop_agent as agent  # noqa: E402
import airsim_fake  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden")


def recorded_rows() -> list[dict]:
    """Every scored row in every results file, in a stable order."""
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "phases", "*", "results", "*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if "per_drone" in row:
                    row["_source"] = os.path.basename(path)
                    rows.append(row)
    return rows


# ------------------------------------------------------------------ cases

def execution_cases(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        drones = row["per_drone"]
        if not row.get("all_valid") or not all(d.get("plan_steps") for d in drones):
            continue
        plans = {d["drone"]: d["plan_steps"] for d in drones}
        key = json.dumps(plans, sort_keys=True)
        if key not in seen:
            seen[key] = {"id": f"{row['mission']}#{len([c for c in seen.values() if c['mission'] == row['mission']]) + 1}",
                         "mission": row["mission"], "first_seen": row["_source"],
                         "plans": plans}
    cases = list(seen.values())

    m04 = next(c for c in cases if c["mission"] == "M04")
    m10 = next(c for c in cases if c["mission"] == "M10")
    cases += [
        {"id": "synthetic:land-stuck", "mission": "M04", "first_seen": "synthetic",
         "plans": m04["plans"], "stuck_land": ["Drone1"]},
        {"id": "synthetic:M10-Drone3-land-stuck", "mission": "M10", "first_seen": "synthetic",
         "plans": m10["plans"], "stuck_land": ["Drone3"]},
        {"id": "synthetic:leftover-drones", "mission": "M04", "first_seen": "synthetic",
         "plans": m04["plans"], "declared": ["Drone1", "Drone2", "Drone3", "Drone4"]},
    ]
    return cases


def planning_cases(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        protocol = row.get("protocol") or {}
        options = protocol.get("options") or dict(agent.OLLAMA_OPTIONS)
        for d in row["per_drone"]:
            case = {
                "instruction": d["instruction"],
                "drone": d["drone"],
                "model": row.get("model") or agent.MODEL,
                "endpoint": d.get("endpoint") or protocol.get("ollama_endpoint")
                            or "http://127.0.0.1:11434",
                "options": options,
                "reply": d.get("raw_output", ""),
            }
            key = json.dumps(case, sort_keys=True)
            if key not in seen:
                case["id"] = f"{row['mission']}/{d['drone']}#{len(seen) + 1}"
                case["first_seen"] = row["_source"]
                seen[key] = case
    cases = list(seen.values())

    base = {"instruction": "fly forward for 5 seconds", "drone": "Drone1",
            "model": "llama3.3:70b", "endpoint": "http://127.0.0.1:11435",
            "options": dict(agent.OLLAMA_OPTIONS), "first_seen": "synthetic"}
    synthetic = {
        "not-json": "this is not json",
        "unknown-action": '{"plan": [{"action": "teleport", "x": 1, "y": 2}]}',
        "duration-too-long": '{"plan": [{"action": "hover", "duration": 500}]}',
        "positive-z": '{"plan": [{"action": "set_altitude", "z": 30}, {"action": "land"}]}',
        "empty-plan": '{"plan": []}',
    }
    for name, reply in synthetic.items():
        cases.append(dict(base, id=f"synthetic:{name}", reply=reply))
    cases.append(dict(base, id="synthetic:unreachable", reply=None, raise_exc="ConnectionError"))
    return cases


# ------------------------------------------------------------------ running

def run_execution(case: dict) -> dict:
    return airsim_fake.run_flight(
        agent, case["plans"],
        declared=case.get("declared"),
        stuck_land=set(case.get("stuck_land", ())))


def run_planning(case: dict) -> dict:
    exc = None
    if case.get("raise_exc") == "ConnectionError":
        exc = ConnectionError("[WinError 10061] No connection could be made")
    return airsim_fake.run_planning(
        agent, case["instruction"], case["drone"], case["model"],
        case["endpoint"], case["options"], reply=case.get("reply"), raise_exc=exc)


def build() -> dict[str, dict]:
    rows = recorded_rows()
    execution = [{**c, "result": run_execution(c)} for c in execution_cases(rows)]
    planning = [{**c, "result": run_planning(c)} for c in planning_cases(rows)]
    meta = {
        "recorded_from": _commit(),
        "agent_sha256": agent.file_digest(agent.__file__),
        "note": "Phase 2 characterisation goldens. See tools/record_golden.py.",
    }
    return {"execution.json": {"meta": meta, "cases": execution},
            "planning.json": {"meta": meta, "cases": planning}}


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--always", "--dirty"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="compare against the stored goldens instead of writing")
    args = parser.parse_args()

    built = build()
    if args.check:
        drift = 0
        for name, data in built.items():
            with open(os.path.join(GOLDEN, name), encoding="utf-8") as handle:
                stored = json.load(handle)
            for want, got in zip(stored["cases"], data["cases"]):
                if want != got:
                    drift += 1
                    print(f"DRIFT {name} {want['id']}")
            if len(stored["cases"]) != len(data["cases"]):
                drift += 1
                print(f"DRIFT {name}: {len(stored['cases'])} cases stored, {len(data['cases'])} now")
        print("goldens match" if not drift else f"{drift} case(s) drifted")
        return 1 if drift else 0

    os.makedirs(GOLDEN, exist_ok=True)
    for name, data in built.items():
        with open(os.path.join(GOLDEN, name), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
            handle.write("\n")
        print(f"{name}: {len(data['cases'])} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
