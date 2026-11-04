#!/usr/bin/env python3
"""Tests for Phase 8 step 6: the team dividing its mission, flown live, and what it takes to fly it there.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also the live path whole, ~80 s in real time

WHY THESE EXIST
---------------
A live flight cannot run here, so the pieces are held on their own: the live
path refuses pads it cannot fly; a live flight comes back as a run the exit's
checks apply to unchanged; and the script's live record says what it should
-- six checks for the flight, seven for its mock twin, a verdict that is the
flight's and never the exit's. As in Phase 7, a flight built from a mock run
stands in for a live one in the fast tests, and cannot be asked to pass
"known exactly" at the mock's 1 cm (its truth is rebuilt from polls); the
claim that a live flight passes is left to RealTimeTests, which fly the
whole path with the mock standing in for AirSim.
"""

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import (  # noqa: E402
    LiveAllocationFlight,
    fly_team_live,
    fly_team_on_mock,
    load_allocation,
)
from agentic_uav.experiments.allocation_exit import LIVE_CHECKS, live_checks  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from test_messaging_live import live_like  # noqa: E402

LIVE = scenarios.load_scenario("search_relay_live_small")
CONFIG = load_allocation()
WIDE = {"position_m": 5.0, "battery": 5.0, "why": "a test: the stand-in's truth is rebuilt from polls"}


def stand_in():
    run = fly_team_on_mock(LIVE, CONFIG, "deliberating", range_m=None)
    return LiveAllocationFlight(live_like(run.team), CONFIG, run.nets, run.searched)


class LivePathTests(unittest.TestCase):

    def test_it_refuses_pads_that_are_not_the_spawn_layout(self):
        d1, d2 = LIVE.vehicles
        moved = dataclasses.replace(LIVE, vehicles=(d1, dataclasses.replace(d2, start_x=7.0)))
        world = MockWorld(declared=("Drone1",), clock=RealClock())
        with self.assertRaisesRegex(ValueError, "spawn layout"):
            fly_team_live(moved, CONFIG, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world), RealClock())


class LiveFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.live = stand_in()

    def test_it_comes_back_as_a_run_the_checks_apply_to(self):
        run = self.live.as_run("live")
        self.assertEqual((run.team.label, run.config, run.searched), ("live", CONFIG, self.live.searched))
        checks = live_checks(run, LIVE, WIDE)
        self.assertEqual(sorted(k for k in checks if k != "all"), sorted(LIVE_CHECKS))
        for name in LIVE_CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:3])

    def test_a_live_claim_without_every_bid_fails_no_central_assignment(self):
        import copy
        nets = copy.deepcopy(self.live.nets)
        nets["Drone1"]["claims_made"][0]["heard"].pop("Drone2")
        checks = live_checks(dataclasses.replace(self.live, nets=nets).as_run(), LIVE, WIDE)
        self.assertFalse(checks["no_central_assignment"]["ok"])
        self.assertFalse(checks["all"])

    def test_the_pair_divides_both_sectors(self):
        self.assertEqual(sorted(t for ts in self.live.searched.values() for t in ts), ["search S1", "search S2"])
        self.assertTrue(all(len(ts) == 1 for ts in self.live.searched.values()))

    def test_its_record(self):
        row = json.loads(json.dumps(self.live.as_json(), default=str))
        self.assertEqual((row["kind"], row["scenario"]), ("flight", "search_relay_live_small"))
        self.assertEqual(row["config"], CONFIG.as_json())
        self.assertEqual(sorted(row["nets"]), ["Drone1", "Drone2"])
        self.assertEqual(row["searched"], self.live.searched)


class ReportLiveTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.good = stand_in()

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def report(self, flight):
        import allocation_exit
        args = SimpleNamespace(manifest="default", poll_hz=None, out=self.out, block="t")
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.allocation.fly_team_live", return_value=flight), \
                redirect_stdout(buffer):
            code = allocation_exit.report_live(args, "2026-11-04T00:00:00", lambda: None, RealClock())
        jsonl = next(f for f in os.listdir(self.out) if f.endswith(".jsonl"))
        with open(os.path.join(self.out, jsonl), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        return code, rows, buffer.getvalue()

    def test_the_record(self):
        code, rows, text = self.report(self.good)
        head, flight, twin = rows[0], rows[1], rows[-1]
        self.assertEqual((head["sim"], head["scenario"], head["manifest"], head["network"]),
                         ("airsim", "search_relay_live_small", "configs/allocation/default.toml",
                          "every message delivered (range unlimited)"))
        self.assertEqual(sorted(head["checks"]), sorted(LIVE_CHECKS))
        self.assertNotIn("exit_criterion_met", head)                          # a live flight, not the exit
        self.assertEqual((flight["kind"], flight["set"]), ("flight", "live"))
        self.assertGreater(len([r for r in rows if r["kind"] == "message"]), 20)
        self.assertEqual((twin["kind"], twin["set"]), ("twin", "mock_twin"))
        self.assertTrue(twin["checks"]["all"])                                # the twin flown with all seven
        self.assertTrue(head["mock_twin_all"])
        self.assertIn("| deterministic | - | yes |", text)
        self.assertNotIn("Exit criterion", text)

    def test_the_verdict_follows_the_six_checks(self):
        code, rows, text = self.report(self.good)
        ok = all(rows[1]["checks"][k]["ok"] for k in LIVE_CHECKS)
        self.assertEqual(rows[0]["live_flight_met"], ok)
        self.assertEqual(code, 0 if ok else 1)
        self.assertIn(f"**Live flight: {'MET' if ok else 'NOT MET'}**", text)

    def test_a_flight_that_did_not_finish_is_not_met(self):
        team = dataclasses.replace(self.good.flight, finished={"Drone1": True, "Drone2": False})
        code, rows, text = self.report(dataclasses.replace(self.good, flight=team))
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["checks"]["met"])
        self.assertIn("**Live flight: NOT MET**", text)
        self.assertIn("failed: met", text)


class CommandLineTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_live_options_are_for_a_live_run(self):
        import allocation_exit
        for argv in (["--port", "41451"], ["--poll-hz", "5"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                allocation_exit.main(argv + ["--out", self.out])
            self.assertEqual(raised.exception.code, 2)

    def test_live_goes_to_the_simulator(self):
        import allocation_exit
        with mock.patch.object(allocation_exit, "live", return_value=0) as live:
            self.assertEqual(allocation_exit.main(["--sim", "airsim", "--block", "x", "--out", self.out]), 0)
        self.assertEqual(live.call_args[0][0].block, "x")


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 80 s)")
class RealTimeTests(unittest.TestCase):

    def test_fly_team_live_on_the_mock_in_real_time(self):
        from agentic_uav.agents.rule_policy import RulePolicy
        from agentic_uav.experiments.knowledge import observed_poll_hz, poll_tolerance
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        with redirect_stdout(io.StringIO()):
            live = fly_team_live(LIVE, CONFIG, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world), clock)
        self.assertEqual(live.flight.layout["added"], ["Drone2"])
        self.assertEqual(live.flight.finished, {"Drone1": True, "Drone2": True})
        tol = poll_tolerance(LIVE, observed_poll_hz(live.flight.samples, live.flight.poll_hz)["hz"], RulePolicy().speed_mps)
        checks = live_checks(live.as_run(), LIVE, tol)
        for name in LIVE_CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:5])
        tops = {d: max(live.flight.grounds[d] - z for _, _, _, z in rows) for d, rows in live.flight.samples.items()}
        self.assertAlmostEqual(tops["Drone1"], 12.0, delta=0.5)
        self.assertAlmostEqual(tops["Drone2"], 16.0, delta=0.5)

    def test_the_script_live_on_the_mock_in_real_time(self):
        import allocation_exit
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        out = tempfile.mkdtemp()
        try:
            args = SimpleNamespace(manifest="default", poll_hz=None, out=out, block="rt")
            with redirect_stdout(io.StringIO()) as buffer:
                code = allocation_exit.report_live(args, "rt", lambda: MockVehicleAdapter(world), clock)
            self.assertEqual(code, 0, buffer.getvalue()[-2000:])
            self.assertIn("**Live flight: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
