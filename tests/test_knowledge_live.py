#!/usr/bin/env python3
"""Tests for Phase 6 step 6: the knowledge log of a live flight.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also a real 10 Hz poll, ~40 s

WHY THESE EXIST
---------------
A CarlaAir flight cannot run here, so the live knowledge log is held in
pieces. The tolerance it is checked within is derived from the poll rate and
the speed rather than chosen, and refuses nonsense. Widening it has not made
the check toothless: a belief further out than one poll still fails. The
script's record carries the tolerance it used, and the flight fails when the
agent does.

WHY THE FAST TESTS DO NOT CLAIM A STAND-IN FLIGHT PASSES
--------------------------------------------------------
Found while writing them. A LiveAgentFlight built from a mock run holds a
belief that was sensed EXACTLY, while `report_live` reconstructs its truth
through `trajectories_from_samples`, which calls a drone airborne only above
the poller's 3 m line. The knots agree to the metre; only the airborne flag
differs, over the first 3 m of the climb -- and because the battery model
charges nothing before lift-off, the reconstructed truth misses that
segment's 0.19 of hover and 0.24 of climb, a flat 0.43 for the rest of the
flight.

That is an artifact of standing in, not of the logger: in a real live flight
the belief comes from `polled_sensors`, which draws the same 3 m line, so
both sides agree. So the fast tests check the record's shape and arithmetic,
and the claim that a live flight passes is left to RealPollTests, which flies
the whole path against a real 10 Hz poll with the mock standing in for
AirSim. That is also the only place the one-poll lag appears, so it is the
only place the reason for the wider tolerance can be shown rather than
asserted.
"""

import copy
import dataclasses
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)              # Phase 5's live tests, for the live-sized scenario

from agentic_uav.agents.rule_policy import RulePolicy  # noqa: E402
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.experiments.knowledge import (  # noqa: E402
    TOLERANCE,
    Truth,
    entry_json,
    knowledge_entry,
    knowledge_log,
    observed_poll_hz,
    poll_tolerance,
    summary,
)
from agentic_uav.experiments.single_agent import (  # noqa: E402
    LiveAgentFlight,
    fly_agent_live,
    fly_agent_on_mock,
)
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import DEFAULT_POLL_HZ  # noqa: E402
from test_single_agent_live import LIVE, TASK  # noqa: E402

G = MOCK_GROUND_Z
SPEED = RulePolicy().speed_mps          # what the agent will actually ask for: not a guess


def live_like(flown, hz=DEFAULT_POLL_HZ):
    """A LiveAgentFlight from a mock run, sampled as a poller would sample it.

    The samples are taken at `hz` off the run's trajectory rather than being
    its knots, because the live allowance is now read FROM the samples: a
    flight whose samples were knots seconds apart would be checked within
    metres, which says nothing.

    Phase 5's `live_from_mock` starts the flight at CLOCK_ORIGIN, to keep the
    fact that a monotonic clock is never at zero, and leaves the run's trace
    on the mock clock -- harmless there, because nothing read both. The
    knowledge log reads the trace's times AND the flight's, so here they have
    to agree, as they do in a real flight where both come from one RealClock.

    See the module docstring for what this stand-in cannot be asked to show.
    """
    period = 1.0 / hz
    samples = {}
    for drone, path in flown.trajectories.items():
        rows, i = [], 0
        while path.start + i * period <= path.end + 1e-9:       # built, not accumulated
            at = path.start + i * period
            x, y, alt = path.position_at(at)
            rows.append((at, x, y, G - alt))
            i += 1
        samples[drone] = rows
    return LiveAgentFlight(LIVE, flown.task, samples, {d: G for d in samples}, (),
                           flown.report.start, flown.report.until, hz, flown.trace,
                           (), flown.finished, dict(flown.progress), flown.skills, ())


class PollToleranceTests(unittest.TestCase):

    def test_it_is_one_poll_of_flight(self):
        # 5 m/s at 10 Hz is 0.5 m; the battery that 0.5 m spends is
        # 0.5 * move_drain_per_m + hover_drain_per_s / hz.
        tol = poll_tolerance(LIVE, 10.0, 5.0)
        self.assertEqual(tol["position_m"], 0.5)
        self.assertAlmostEqual(tol["battery"], 0.5 * LIVE.battery.move_drain_per_m
                               + LIVE.battery.hover_drain_per_s / 10.0, places=9)
        self.assertEqual(tol["why"], "one poll of flight: 5 m/s across 0.1 s (10 Hz)")

    def test_a_slower_poll_allows_more(self):
        self.assertEqual(poll_tolerance(LIVE, 5.0, 5.0)["position_m"], 1.0)
        self.assertEqual(poll_tolerance(LIVE, 20.0, 5.0)["position_m"], 0.25)

    def test_the_live_run_uses_the_speed_the_agent_asks_for(self):
        self.assertEqual(poll_tolerance(LIVE, DEFAULT_POLL_HZ, SPEED),
                         poll_tolerance(LIVE, 10.0, 5.0))

    def test_it_is_wider_than_the_mocks_and_says_why(self):
        tol = poll_tolerance(LIVE, DEFAULT_POLL_HZ, SPEED)
        self.assertGreater(tol["position_m"], TOLERANCE["position_m"])
        self.assertGreater(tol["battery"], TOLERANCE["battery"])
        self.assertIn("one poll", tol["why"])

    def test_nonsense_is_refused_rather_than_quietly_huge(self):
        for hz, speed in ((0.0, 5.0), (-10.0, 5.0), (10.0, 0.0), (10.0, -5.0)):
            with self.subTest(hz=hz, speed=speed):
                with self.assertRaisesRegex(ValueError, "must both be positive"):
                    poll_tolerance(LIVE, hz, speed)


class WiderButStillFailsTests(unittest.TestCase):
    """The live allowance is not a way of passing: a belief further out still fails."""

    @classmethod
    def setUpClass(cls):
        # Not `cls.run`: that shadows TestCase.run, and the suite dies calling it.
        cls.flown = fly_agent_on_mock(LIVE, TASK)
        cls.truth = Truth(LIVE, cls.flown.trajectories, cls.flown.report.start, cls.flown.report.until)
        cls.row = entry_json(next(e for e in cls.flown.trace if e.decision.reason == "at S1"))
        cls.tol = poll_tolerance(LIVE, DEFAULT_POLL_HZ, SPEED)

    def problems(self, change, tolerance):
        row = copy.deepcopy(self.row)
        change(row["belief"])
        return " ".join(knowledge_entry(row, "Drone1", self.truth, tolerance).problems)

    def nudged(self, metres):
        def change(b):
            b["self"]["position"][0] += metres
        return change

    def test_the_real_decision_passes_either_way(self):
        self.assertEqual(self.problems(lambda b: None, self.tol), "")
        self.assertEqual(self.problems(lambda b: None, None), "")

    def test_inside_one_poll_passes_live_and_fails_on_the_mock(self):
        inside = self.nudged(0.4)
        self.assertEqual(self.problems(inside, self.tol), "")
        self.assertIn("incorrect: believed position", self.problems(inside, None))

    def test_further_than_one_poll_still_fails(self):
        said = self.problems(self.nudged(0.6), self.tol)
        self.assertIn("incorrect: believed position", said)
        self.assertIn("past the 0.5 m allowed", said)

    def test_the_battery_moves_with_it(self):
        under = lambda b: b["self"].update(battery=b["self"]["battery"] - 0.01)   # noqa: E731
        over = lambda b: b["self"].update(battery=b["self"]["battery"] - 0.05)    # noqa: E731
        self.assertEqual(self.problems(under, self.tol), "")
        self.assertIn("past the 0.015 allowed", self.problems(over, self.tol))

    def test_the_other_two_checks_are_untouched_by_the_tolerance(self):
        self.assertIn("the team block is missing", self.problems(lambda b: b.pop("team"), self.tol))
        t = next(x for x in self.truth.targets if x.id == "T1")
        leak = lambda b: b["mission"]["progress"].update(hint=[round(t.x, 3), round(t.y, 3)])  # noqa: E731
        self.assertIn("leak:", self.problems(leak, self.tol))


class ScriptRecordTests(unittest.TestCase):
    """What the live record holds. Not whether a stand-in flight passes: see the module docstring."""

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

    def report(self, flight):
        import knowledge_exit
        args = SimpleNamespace(scenario=knowledge_exit.LIVE_SCENARIO, task=knowledge_exit.LIVE_TASK,
                               out=self.out, block="t", poll_hz=None)
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.single_agent.fly_agent_live", return_value=flight), \
                redirect_stdout(buffer):
            code = knowledge_exit.report_live(args, "now", lambda: None, RealClock())
        (jsonl,) = [f for f in os.listdir(self.out) if f.endswith(".jsonl")]
        with open(os.path.join(self.out, jsonl), encoding="utf-8") as h:
            return code, [json.loads(line) for line in h], buffer.getvalue()

    def test_every_decision_is_recorded_beside_the_mocks(self):
        _, rows, text = self.report(live_like(fly_agent_on_mock(LIVE, TASK)))
        header = rows[0]
        self.assertTrue(header["met"], header)                 # the agent met its task
        self.assertEqual(header["scenario"], "search_single_live_small")
        self.assertEqual(header["scenario_file"], "configs/scenarios/search_single_live_small.toml")
        self.assertEqual(header["task"], "search S1")
        self.assertEqual(header["drone"], "Drone1")
        kinds = [(r["kind"], r.get("set")) for r in rows]
        self.assertEqual(kinds[0], ("header", None))
        self.assertEqual(kinds[1], ("flight", "live"))
        self.assertEqual(sum(1 for k, s in kinds if (k, s) == ("decision", "live")), header["decisions"])
        self.assertEqual(sum(1 for k, s in kinds if (k, s) == ("flight", "mock_twin")), 1)
        self.assertGreater(sum(1 for k, s in kinds if (k, s) == ("decision", "mock_twin")), 0)
        self.assertIn("| Decisions |", text)

    def test_the_verdict_counts_the_decisions_it_logged(self):
        _, rows, _ = self.report(live_like(fly_agent_on_mock(LIVE, TASK)))
        live = [r for r in rows if (r["kind"], r.get("set")) == ("decision", "live")]
        header = rows[0]
        self.assertEqual(header["decisions"], len(live))
        self.assertEqual(header["decisions_passed"], sum(r["checks"]["ok"] for r in live))
        self.assertEqual(header["exit_criterion_met"],
                         header["met"] and header["decisions_passed"] == header["decisions"])

    def test_the_tolerance_it_was_checked_within_is_in_the_record(self):
        _, rows, text = self.report(live_like(fly_agent_on_mock(LIVE, TASK)))
        header = rows[0]
        self.assertEqual(header["poll_hz"], DEFAULT_POLL_HZ)
        self.assertEqual(header["speed_mps"], SPEED)
        self.assertEqual(header["tolerance"], poll_tolerance(LIVE, DEFAULT_POLL_HZ, SPEED))
        self.assertEqual(header["mock_tolerance"], TOLERANCE)
        self.assertIn("within **0.5 m**", text)
        self.assertIn("one poll of flight: 5 m/s across", text)

    def test_a_flight_that_does_not_meet_its_task_is_not_met(self):
        flight = dataclasses.replace(live_like(fly_agent_on_mock(LIVE, TASK)), finished=False)
        code, rows, text = self.report(flight)
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["met"])
        self.assertFalse(rows[0]["exit_criterion_met"])
        self.assertIn("**NOT MET**", text)
        self.assertIn("did not meet its task", text)

    def test_the_live_only_flags_are_refused_on_the_mock(self):
        import knowledge_exit
        for argv in (["--poll-hz", "5"], ["--scenario", "search_single_001"], ["--task", "search S3"]):
            with self.subTest(argv=argv):
                with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()), \
                        self.assertRaises(SystemExit) as raised:
                    knowledge_exit.main(argv + ["--out", self.out])
                self.assertEqual(raised.exception.code, 2)


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 40 s)")
class RealPollTests(unittest.TestCase):
    """The live path whole, against a real 10 Hz poll, with the mock standing in for AirSim."""

    @classmethod
    def setUpClass(cls):
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        cls.flight = fly_agent_live(LIVE, TASK, MockVehicleAdapter(world),
                                    lambda: MockVehicleAdapter(world), clock)
        cls.truth = Truth(LIVE, cls.flight.trajectories(), cls.flight.start, cls.flight.end)
        cls.polled = observed_poll_hz(cls.flight.samples, cls.flight.poll_hz)
        cls.tol = poll_tolerance(LIVE, cls.polled["hz"], SPEED)

    def offsets(self):
        """How far each believed position stood from the interpolated truth."""
        out = []
        for entry in self.flight.trace:
            row = entry_json(entry)
            me = row["belief"].get("self", {})
            if "position" in me:
                out.append(math.dist(me["position"], self.truth.position("Drone1", row["at"])))
        return out

    def test_the_log_passes_within_one_poll(self):
        self.assertTrue(self.flight.as_run("real time").met)
        s = summary(knowledge_log({"Drone1": self.flight.trace}, self.truth, self.tol))
        self.assertGreater(s["decisions"], 5)
        self.assertEqual(s["ok"], s["decisions"], s["problems"][:5])

    def test_and_the_lag_is_real_rather_than_assumed(self):
        # If this ever passes at the mock's allowance, the wider tolerance is
        # not needed and poll_tolerance should go. It is here to say so.
        worst = max(self.offsets())
        self.assertGreater(worst, TOLERANCE["position_m"])
        self.assertLessEqual(worst, self.tol["position_m"])

    def test_the_poller_keeps_less_than_it_is_asked_for(self):
        # Why the allowance is the observed gap and not the nominal one: a
        # decision was measured 0.550 m out, past the 0.5 m that 10 Hz allows.
        self.assertLess(self.polled["hz"], self.polled["asked_hz"])
        self.assertGreater(self.polled["worst_gap_s"], 1.0 / self.polled["asked_hz"])
        self.assertGreaterEqual(self.polled["worst_gap_s"], self.polled["median_gap_s"])
        self.assertGreater(self.tol["position_m"], poll_tolerance(LIVE, self.polled["asked_hz"],
                                                                  SPEED)["position_m"])

    def test_the_script_writes_a_met_record_of_it(self):
        import knowledge_exit
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        args = SimpleNamespace(scenario=knowledge_exit.LIVE_SCENARIO, task=knowledge_exit.LIVE_TASK,
                               out=out, block="realpoll", poll_hz=None)
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.single_agent.fly_agent_live", return_value=self.flight), \
                redirect_stdout(buffer):
            code = knowledge_exit.report_live(args, "now", lambda: None, RealClock())
        self.assertEqual(code, 0, buffer.getvalue()[-2000:])
        self.assertIn("**MET**", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
