#!/usr/bin/env python3
"""Record the Phase 2 goldens: what the frozen baseline does, call for call.

    python tools/record_golden.py            # writes tests/golden/*.json
    python tools/record_golden.py --check    # compares instead, exits 1 on drift

Phase 2 refactors the agent into modules without changing what it does (AUV-03,
2.3). That needs "what it does" written down BEFORE anything moves, in a form
two versions of the code can be compared on. Three files:

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
* `runner.json` -- whole invocations of `scripts/run_missions.py` against the
  same fakes, added in Phase 2 step 5 before the runner moved: the protocol
  series flown in one simulator session (M01-M08, M09, M10, then a refused
  M01), plan-only, flag overrides, and every refusal and stop path. Per
  invocation: exit code, console, result rows, summary, agent-log records and
  the simulator calls. Model replies are the v6 block's, so no model runs.

`execution.json` and `planning.json` were recorded from the code at
`v0.1-open-loop-baseline`, `runner.json` from the code at step 4 (`5f9ac56`),
whose runner differs from the baseline's only in archiving `agentic_uav/` with
each code snapshot. Re-recording later is allowed only when a change of behaviour is deliberate, and that change then
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
sys.path[:0] = [os.path.join(ROOT, "baseline"), os.path.join(ROOT, "scripts"),
                os.path.join(ROOT, "tests")]

import open_loop_agent as agent  # noqa: E402
import airsim_fake  # noqa: E402
import run_missions as runner  # noqa: E402

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


# The block the runner golden replays: v6, the last full series flown before
# Phase 2 began, in its three protocol files (M01-M08, M09, M10).
RUNNER_REPLIES_FROM = sorted(glob.glob(os.path.join(
    ROOT, "phases", "phase-01-baseline-freeze", "results",
    "baseline_v1-llama3.3_70b-20261019-18*-v6-polled.jsonl")))
HOST = ["--ollama-host", "http://127.0.0.1:11435"]


def runner_replies() -> dict[str, str]:
    """Instruction -> the reply llama3.3:70b gave it in the v6 block."""
    assert len(RUNNER_REPLIES_FROM) == 3, RUNNER_REPLIES_FROM
    replies: dict[str, str] = {}
    for path in RUNNER_REPLIES_FROM:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                for d in json.loads(line)["per_drone"]:
                    # temperature 0: one instruction, one reply, across the block
                    assert replies.setdefault(d["instruction"], d["raw_output"]) == d["raw_output"]
    return replies


def runner_cases() -> list[dict]:
    """Whole runner invocations. Each case is one simulator session."""
    m02 = "hover for 3 seconds then land"
    m03 = "go up to 15 meters, fly forward for 5 seconds, then land"
    return [
        {"id": "plan-only:all-missions",
         "invocations": [{"argv": ["--plan-only"] + HOST}]},
        {"id": "flight:protocol-order-then-wrong-order",
         # M01-M08, M09, M10 as the protocol flies them, in one session; then
         # M01 again without a restart, which must be refused before takeoff.
         "invocations": [
             {"argv": ["--missions", "M01,M02,M03,M04,M05,M06,M07,M08",
                       "--block", "blockA"] + HOST},
             {"argv": ["--missions", "M09", "--block", "blockB-M09"] + HOST},
             {"argv": ["--missions", "M10", "--block", "blockC-M10"] + HOST},
             {"argv": ["--missions", "M01", "--repeats", "1"] + HOST}]},
        {"id": "flight:four-declared-M10",
         "world": {"declared": ["Drone1", "Drone2", "Drone3", "Drone4"]},
         "invocations": [{"argv": ["--missions", "M10", "--repeats", "1"] + HOST,
                          "settings_vehicles": 4}]},
        {"id": "flight:rejected-plan-and-dead-endpoint",
         "invocations": [{"argv": ["--missions", "M01,M02,M03", "--repeats", "1"] + HOST,
                          "reply_overrides": {m02: "this is not json",
                                              m03: airsim_fake.RunnerOllama.UNREACHABLE}}]},
        {"id": "flight:land-stuck",
         # M03, not M04: v6's M04 plan ends with fly_to z: 0, which is already
         # on the ground, so its land has nothing left to descend.
         "world": {"stuck_land": ["Drone1"]},
         "invocations": [{"argv": ["--missions", "M03", "--repeats", "1"] + HOST}]},
        {"id": "flight:drone-appears-mid-series",
         "world": {"intrude_on_reset": {"2": "Drone2"}},
         "invocations": [{"argv": ["--missions", "M01,M02", "--repeats", "1"] + HOST}]},
        {"id": "plan-only:overrides",
         "invocations": [{"argv": ["--plan-only", "--missions", "m05, M10", "--repeats", "1",
                                   "--model", "llama3.2:3b", "--option", "num_ctx=4096",
                                   "--option", "temperature=0.5", "--option", "stop=END",
                                   "--block", "label"] + HOST,
                          "server_version": None}]},
        {"id": "refused:model-not-served",
         "invocations": [{"argv": ["--plan-only", "--missions", "M01"] + HOST,
                          "models": ["llama3.2:3b"]}]},
        {"id": "refused:endpoint-unreachable",
         "invocations": [{"argv": ["--missions", "M01"] + HOST, "listing_fails": True}]},
        {"id": "refused:bad-arguments",
         "invocations": [{"argv": ["--plan-only", "--missions", "M5,M01"] + HOST},
                         {"argv": ["--plan-only", "--option", "num_ctx"] + HOST}]},
    ]


def fly_chat_cases() -> list[dict]:
    """Scripted sandbox sessions: every command, both divergences from the study."""
    m01 = "fly forward for 5 seconds"
    m02 = "hover for 3 seconds then land"
    m04 = "fly forward for 5 seconds then return home and land"
    m09 = ["go up to 25 meters, fly forward for 6 seconds, then return home and land",
           "go up to 12 meters, fly right for 5 seconds, hover for 2 seconds, then land"]
    m10 = ["go up to 30 meters, fly forward for 5 seconds, then land",
           "go up to 24 meters, fly right for 5 seconds, then land",
           "go up to 18 meters, fly backward for 5 seconds, then land",
           "go up to 12 meters, fly left for 5 seconds, then land"]
    return [
        {"id": "sandbox:one-drone-every-command",
         "reply_overrides": {"do a barrel roll": "this is not json"},
         "inputs": ["1", "", ":help",
                    m01, "y",                 # no land step: left hovering
                    ":status",
                    m04, "y", "y",            # still up: land it first, then fly
                    m01, "n",                 # planned, not flown
                    ":plans", ":again", "y",
                    ":land", ":land",         # the second finds nothing flying
                    ":speed 8", ":speed", ":speed fast", ":speed 50",
                    m02, "y",                 # planned against the 8 m/s prompt
                    ":auto", "do a barrel roll",
                    ":reset", ":bogus", ":quit"]},
        {"id": "sandbox:startup-speed-and-more-drones",
         "inputs": ["0", "7", "2", "abc", "50", "8.5",
                    m09[0], m09[1], "y",
                    ":drones 4",
                    m10[0], m10[1], "", m10[3], "y",    # blank repeats the drone above
                    ":drones 1"]},                      # fewer drones than the scene holds
        {"id": "sandbox:end-of-input", "inputs": ["1", ""]},
        {"id": "sandbox:endpoint-not-serving-the-model",
         "models": ["llama3.2:3b"], "inputs": []},
    ]


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


def run_runner_case(case: dict, replies: dict[str, str]) -> list[dict]:
    return airsim_fake.run_scenario(agent, runner, case, replies)


def load_fly_chat():
    """tools/fly_chat.py as a module (tools/ is not a package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fly_chat", os.path.join(ROOT, "tools", "fly_chat.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_fly_chat_case(case: dict, replies: dict[str, str], fly_chat=None) -> dict:
    ollama = airsim_fake.RunnerOllama(dict(replies, **case.get("reply_overrides", {})),
                                      case.get("models", airsim_fake.DEFAULT_MODELS))
    return airsim_fake.run_fly_chat(agent, fly_chat or load_fly_chat(), case["inputs"],
                                    airsim_fake.FakeWorld(), ollama)


def build(only: set[str] | None = None) -> dict[str, dict]:
    """The goldens named in `only` (all three by default)."""
    meta = {
        "recorded_from": _commit(),
        "agent_sha256": agent.file_digest(agent.__file__),
        "note": "Phase 2 characterisation goldens. See tools/record_golden.py.",
    }
    built = {}
    want = only or {"execution.json", "planning.json", "runner.json", "fly_chat.json"}
    if want & {"execution.json", "planning.json"}:
        rows = recorded_rows()
        if "execution.json" in want:
            built["execution.json"] = {"meta": meta, "cases": [
                {**c, "result": run_execution(c)} for c in execution_cases(rows)]}
        if "planning.json" in want:
            built["planning.json"] = {"meta": meta, "cases": [
                {**c, "result": run_planning(c)} for c in planning_cases(rows)]}
    if "runner.json" in want:
        replies = runner_replies()
        built["runner.json"] = {
            "meta": dict(meta, runner_sha256=agent.file_digest(runner.__file__),
                         replies_from=[os.path.basename(p) for p in RUNNER_REPLIES_FROM]),
            "replies": replies,
            "cases": [{**c, "result": run_runner_case(c, replies)} for c in runner_cases()]}
    if "fly_chat.json" in want:
        replies = runner_replies()
        built["fly_chat.json"] = {
            "meta": dict(meta, replies_from=[os.path.basename(p) for p in RUNNER_REPLIES_FROM]),
            "replies": replies,
            "cases": [{**c, "result": run_fly_chat_case(c, replies)} for c in fly_chat_cases()]}
    return built


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
    parser.add_argument("--only", action="append", metavar="NAME",
                        choices=["execution.json", "planning.json", "runner.json",
                                 "fly_chat.json"],
                        help="record or check just this golden, repeatable. A "
                             "golden added later is recorded alone, so the "
                             "earlier ones keep the code they were recorded from")
    args = parser.parse_args()

    built = build(set(args.only) if args.only else None)
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
