#!/usr/bin/env python3
"""The Phase 2 regression test: the agent still does exactly what it did.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 2 moves every AirSim call behind a `VehicleAdapter` and every planning
call behind a `MissionPlanner`. Its exit criterion is that the baseline runs
through the new structure "without changing their expected behaviour" (AUV-03).
These tests are that criterion made checkable without a simulator or a model.

`tests/golden/` was recorded from `v0.1-open-loop-baseline` by
`tools/record_golden.py`, before any code moved:

* execution -- every distinct plan ever flown in this project, plus a stuck
  landing and leftover drones, through `fly_plans` against the recording fake.
  Compared: each drone's exact AirSim call sequence, and the outcome records.
* planning -- every distinct model reply on record, plus the error paths,
  through `plan_for` with a scripted model. Compared: the exact request sent,
  and the plan record produced.
* runner -- whole `scripts/run_missions.py` invocations, recorded in step 5
  before the runner moved: the protocol series in one simulator session,
  plan-only, overrides, every refusal and the mid-series stop. Compared: exit
  code, console, result rows, summary, agent-log records, the code snapshot's
  shape and every simulator call.
* fly_chat -- scripted `tools/fly_chat.py` sessions, recorded in step 5
  before the sandbox moved: every command, both of its deliberate departures
  from the study (the prompt addendum and hovering), more drones, fewer
  drones, a dead endpoint. Compared: console, every request the model
  received, every simulator call.

A failure here means behaviour changed. If the change is deliberate, re-record
with `python tools/record_golden.py` and say why in the phase record. Never
re-record to make a refactor pass.

Each case replays from the inputs stored in the golden itself, so the result
files can move or grow without disturbing these tests.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "baseline"), os.path.join(ROOT, "scripts"),
                os.path.join(ROOT, "tests")]

import open_loop_agent as agent  # noqa: E402  (path set above)
import airsim_fake  # noqa: E402
import run_missions as runner  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden")


def _load(name: str, part: str = "cases"):
    with open(os.path.join(GOLDEN, name), encoding="utf-8") as handle:
        return json.load(handle)[part]


def _first_difference(want, got, path="result"):
    """Where two JSON values first differ, for a readable failure message."""
    if type(want) is not type(got):
        return f"{path}: {want!r} != {got!r}"
    if isinstance(want, dict):
        for key in sorted(set(want) | set(got)):
            if key not in want or key not in got:
                return f"{path}.{key}: present in only one"
            found = _first_difference(want[key], got[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(want, list):
        for i, (a, b) in enumerate(zip(want, got)):
            found = _first_difference(a, b, f"{path}[{i}]")
            if found:
                return found
        if len(want) != len(got):
            return f"{path}: {len(want)} items != {len(got)}"
        return None
    return None if want == got else f"{path}: {want!r} != {got!r}"


class ExecutionGoldenTests(unittest.TestCase):
    """Every recorded plan flies with the same AirSim calls and outcomes."""

    def test_every_case(self):
        cases = _load("execution.json")
        self.assertGreaterEqual(len(cases), 16)
        for case in cases:
            with self.subTest(case=case["id"]):
                got = airsim_fake.run_flight(
                    agent, case["plans"],
                    declared=case.get("declared"),
                    stuck_land=set(case.get("stuck_land", ())))
                got = json.loads(json.dumps(got))          # same types as the file
                self.assertIsNone(_first_difference(case["result"], got),
                                  _first_difference(case["result"], got))


class PlanningGoldenTests(unittest.TestCase):
    """Every recorded reply makes the same request and the same plan record."""

    def test_every_case(self):
        cases = _load("planning.json")
        self.assertGreaterEqual(len(cases), 44)
        for case in cases:
            with self.subTest(case=case["id"]):
                exc = None
                if case.get("raise_exc") == "ConnectionError":
                    exc = ConnectionError("[WinError 10061] No connection could be made")
                got = airsim_fake.run_planning(
                    agent, case["instruction"], case["drone"], case["model"],
                    case["endpoint"], case["options"], reply=case.get("reply"),
                    raise_exc=exc)
                got = json.loads(json.dumps(got))
                self.assertIsNone(_first_difference(case["result"], got),
                                  _first_difference(case["result"], got))


class RunnerGoldenTests(unittest.TestCase):
    """Every recorded runner invocation prints, writes and flies the same."""

    def test_every_case(self):
        cases = _load("runner.json")
        replies = _load("runner.json", "replies")
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case=case["id"]):
                got = json.loads(json.dumps(
                    airsim_fake.run_scenario(agent, runner, case, replies)))
                self.assertIsNone(_first_difference(case["result"], got),
                                  _first_difference(case["result"], got))


class FlyChatGoldenTests(unittest.TestCase):
    """Every recorded sandbox session prints, asks and flies the same."""

    def test_every_case(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import record_golden
        cases = _load("fly_chat.json")
        replies = _load("fly_chat.json", "replies")
        self.assertGreaterEqual(len(cases), 4)
        fly_chat = record_golden.load_fly_chat()
        for case in cases:
            with self.subTest(case=case["id"]):
                got = json.loads(json.dumps(
                    record_golden.run_fly_chat_case(case, replies, fly_chat)))
                self.assertIsNone(_first_difference(case["result"], got),
                                  _first_difference(case["result"], got))


class HarnessSanityTests(unittest.TestCase):
    """The goldens are only as good as the fake. Pin what they must contain."""

    def test_every_mission_is_covered(self):
        missions = {c["mission"] for c in _load("execution.json")}
        self.assertEqual(missions, {f"M{i:02d}" for i in range(1, 11)})

    def test_the_failure_paths_are_covered(self):
        ids = {c["id"] for c in _load("execution.json")}
        self.assertIn("synthetic:land-stuck", ids)
        self.assertIn("synthetic:leftover-drones", ids)
        planning = {c["id"] for c in _load("planning.json")}
        for name in ("not-json", "unknown-action", "unreachable", "positive-z"):
            self.assertIn(f"synthetic:{name}", planning)

    def test_the_runner_paths_are_covered(self):
        results = {c["id"]: c["result"] for c in _load("runner.json")}
        series = results["flight:protocol-order-then-wrong-order"]
        self.assertEqual([r["exit"] for r in series], [0, 0, 0, 1])
        self.assertEqual([len(r["rows"]) for r in series[:3]], [24, 3, 3])
        self.assertIn("REFUSING TO RUN", series[3]["stderr"])
        self.assertTrue(any(l.startswith("STOPPED at M02")
                            for l in results["flight:drone-appears-mid-series"][0]["stderr"]))
        stuck = results["flight:land-stuck"][0]["rows"][0]["execution"]
        self.assertFalse(stuck["completed"])
        dead = results["flight:rejected-plan-and-dead-endpoint"][0]
        self.assertEqual([r["transport_error"] for r in dead["rows"]], [False, False, True])
        self.assertTrue(all(r[0]["snapshot"] is None or r[0]["snapshot"]["package_complete"]
                            for r in results.values()))

    def test_a_changed_call_is_caught(self):
        # Prove the comparison can fail: alter one argument of one recorded
        # call and the difference must be reported, not absorbed.
        case = _load("execution.json")[0]
        altered = json.loads(json.dumps(case["result"]))
        drone = next(k for k in altered["calls"] if k != "main")
        altered["calls"][drone][-3][1] = ["changed"]
        self.assertIsNotNone(_first_difference(case["result"], altered))


if __name__ == "__main__":
    unittest.main()
