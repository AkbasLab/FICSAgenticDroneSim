#!/usr/bin/env python3
"""Tests for Phase 5's exit runs: the agent given only a task, and the checks that judge it.

    python -m unittest discover tests

WHY THESE EXIST
---------------
The exit criterion has three parts -- complete a task, without a preflight
list, recognising success and failure and deciding what next -- and each is
a check in `experiments/single_agent.py`. These make sure the checks pass on
the real runs and, as much, that each one FAILS when its part is missing: a
check that cannot fail shows nothing.
"""

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.agents.decision import Decision  # noqa: E402
from agentic_uav.agents.drone_agent import TraceEntry  # noqa: E402
from agentic_uav.agents.validation import Verdict  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402
from agentic_uav.experiments.single_agent import (  # noqa: E402
    EXIT_TASK,
    TROUBLES,
    Trouble,
    fly_agent_on_mock,
    trouble_runs,
    with_changes,
)

SINGLE = scenarios.load_scenario("search_single_001")


class ScenarioTests(unittest.TestCase):

    def test_it_is_the_canonical_mission_cut_to_one_drone_and_s3(self):
        canonical = scenarios.load_scenario("search_relay_001")
        self.assertEqual([v.id for v in SINGLE.vehicles], ["Drone1"])
        self.assertEqual([s.id for s in SINGLE.sectors], ["S3"])
        self.assertEqual(SINGLE.sectors[0], next(s for s in canonical.sectors if s.id == "S3"))
        for field in ("mission", "base", "network", "detection", "battery", "safety", "targets",
                      "restricted_zones", "random_seed"):
            with self.subTest(field=field):
                self.assertEqual(getattr(SINGLE, field), getattr(canonical, field))
        self.assertEqual(EXIT_TASK, "search S3")


class NominalTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_agent_on_mock(SINGLE)

    def test_the_task_is_completed(self):
        self.assertTrue(self.flight.met, self.flight.report.summary())
        self.assertTrue(self.flight.finished)
        self.assertEqual([s for s, _ in self.flight.skills],
                         ["TAKE_OFF", "FOLLOW_WAYPOINTS", "SEARCH_REGION", "FOLLOW_WAYPOINTS", "LAND"])
        self.assertTrue(all(status == "success" for _, status in self.flight.skills))

    def test_every_skill_was_chosen_as_it_went(self):
        self.assertTrue(self.flight.chosen_as_it_went())
        first = self.flight.trace[0]
        self.assertEqual([e.trigger for e in first.events], [Trigger.TASK_ASSIGNED])
        self.assertEqual(first.events[0].detail, {"task": "search S3"})

    def test_the_record_is_plain_data(self):
        row = json.loads(json.dumps(self.flight.as_json(), default=str))
        self.assertEqual(row["task"], "search S3")
        self.assertEqual(len(row["trace"]), len(self.flight.trace))
        self.assertIn("belief", row["trace"][0])

    def test_the_seeds_are_phase_4s(self):
        self.assertEqual(EXIT_SEEDS, tuple(range(1, 21)))


class TroubleTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.results = {t.name: (t, run, ok, problems) for t, run, ok, problems in trouble_runs(SINGLE)}

    def test_every_trouble_meets_its_check(self):
        self.assertEqual(len(self.results), len(TROUBLES))
        for name, (_, run, ok, problems) in self.results.items():
            with self.subTest(trouble=name):
                self.assertTrue(ok, problems)

    def test_the_troubles_are_what_they_say(self):
        _, once, _, _ = self.results["fault once"]
        self.assertEqual([st for s, st in once.skills if s == "FOLLOW_WAYPOINTS"][:2], ["failed", "success"])
        self.assertTrue(once.report.success)
        _, battery, _, _ = self.results["slow, short battery"]
        self.assertIn(("SEARCH_REGION", "aborted"), battery.skills)
        self.assertGreater(battery.report.facts.batteries[0].remaining, SINGLE.battery.reserve)
        _, late, _, _ = self.results["slow, short deadline"]
        self.assertLessEqual(late.report.until - late.report.start, 260.0)
        self.assertTrue(late.report.criterion("C6").passed)

    def test_a_check_fails_when_its_part_is_missing(self):
        # The same runs, held to expectations they do not meet.
        cases = [
            ("fault for good", dict(success=True), "should still have succeeded"),
            ("fault once", dict(gave_up="low battery"), "its reason should say"),
            ("too little battery", dict(skills=("TAKE_OFF", "FOLLOW_WAYPOINTS", "LAND")), "skills"),
        ]
        for name, change, words in cases:
            with self.subTest(trouble=name):
                trouble, run, _, _ = self.results[name]
                ok, problems = dataclasses.replace(trouble, **change).check(run)
                self.assertFalse(ok)
                self.assertTrue(any(words in p for p in problems), problems)

    def test_not_coming_home_safe_fails_the_check(self):
        # A real run that does not end safe: a 10 s deadline closes the
        # window while the drone is still in the air.
        cut_short = fly_agent_on_mock(with_changes(SINGLE, {"deadline_s": 10.0}), label="cut short")
        self.assertFalse(cut_short.report.criterion("C6").passed)
        ok, problems = Trouble("t", "w", "e").check(cut_short)
        self.assertFalse(ok)
        self.assertTrue(any("come home safe" in p for p in problems), problems)
        self.assertTrue(Trouble("t", "w", "e", safe=False).check(cut_short)[0])

    def test_with_changes(self):
        late = with_changes(SINGLE, {"deadline_s": 260.0})
        self.assertEqual(late.mission.deadline_s, 260.0)
        self.assertEqual(late.battery, SINGLE.battery)


class CheckLogicTests(unittest.TestCase):
    """The two trace checks, on traces built to break them."""

    def entry(self, events, decision):
        return TraceEntry(1.0, tuple(events), {}, decision, Verdict(True), "x")

    def test_a_start_with_no_event_is_a_preflight_list(self):
        run = fly_agent_on_mock(SINGLE)
        listed = dataclasses.replace(run, trace=run.trace + (self.entry((), Decision.start(S.LandCommand(), "land")),))
        self.assertTrue(run.chosen_as_it_went())
        self.assertFalse(listed.chosen_as_it_went())
        self.assertFalse(listed.met)

    def test_carrying_on_after_a_failure_is_not_deciding(self):
        run = fly_agent_on_mock(SINGLE)
        failed = Event(Trigger.SKILL_FAILED, 1.0, {"skill": "SEARCH_REGION", "status": "failed"})
        shrugged = dataclasses.replace(run, trace=run.trace + (self.entry((failed,), Decision.carry_on()),))
        self.assertTrue(run.decided_after_every_failure())
        self.assertFalse(shrugged.decided_after_every_failure())
        ok, problems = Trouble("t", "w", "e").check(shrugged)
        self.assertFalse(ok)
        self.assertIn("a failed skill was not followed by a decision", problems)

    def test_an_agent_that_never_finishes_fails_its_check(self):
        run = fly_agent_on_mock(SINGLE)
        ok, problems = Trouble("t", "w", "e").check(dataclasses.replace(run, finished=False))
        self.assertFalse(ok)
        self.assertIn("the agent never ended the task itself", problems)


class ScriptTests(unittest.TestCase):

    def test_one_seed_writes_its_record(self):
        import single_agent_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = single_agent_exit.main(["--seeds", "17", "--no-trouble", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            files = sorted(os.listdir(out))
            self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
            with open(os.path.join(out, files[0]), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            self.assertEqual([r["kind"] for r in rows], ["header", "nominal"])
            self.assertTrue(rows[0]["exit_criterion_met"])
            self.assertEqual(rows[1]["seed"], 17)
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
