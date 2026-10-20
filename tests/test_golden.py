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
sys.path[:0] = [os.path.join(ROOT, "baseline"), os.path.join(ROOT, "tests")]

import open_loop_agent as agent  # noqa: E402  (path set above)
import airsim_fake  # noqa: E402

GOLDEN = os.path.join(ROOT, "tests", "golden")


def _load(name: str) -> list[dict]:
    with open(os.path.join(GOLDEN, name), encoding="utf-8") as handle:
        return json.load(handle)["cases"]


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
