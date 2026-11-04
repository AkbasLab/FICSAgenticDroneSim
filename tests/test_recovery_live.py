#!/usr/bin/env python3
"""Tests for Phase 9 step 5: a drone stopped mid-search, flown live, and what it takes to fly it there.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also the live path whole, ~70 s each in real time

WHY THESE EXIST
---------------
A live flight cannot run here, so the pieces are held on their own: the live
path refuses pads it cannot fly and a stop for a drone it does not fly; a live
flight comes back as a run the exit's checks apply to unchanged, the stopped
drone told to the judge; and the script's live record says what it should --
seven checks for the flight, eight for its mock twin, a verdict that is the
flight's and never the exit's. As in Phases 7 and 8, a flight built from a
mock run stands in for a live one in the fast tests; the claim that a live
flight passes is left to RealTimeTests, which fly the whole path with the mock
standing in for AirSim.
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
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.recovery import (  # noqa: E402
    LiveRecoveryFlight,
    fly_recovery_live,
    fly_recovery_on_mock,
    load_recovery,
)
from agentic_uav.experiments.recovery_exit import LIVE_CHECKS, LIVE_STOP_AT_S, live_checks  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from test_messaging_live import live_like  # noqa: E402

LIVE = scenarios.load_scenario("search_relay_live_small")
CONFIG = load_allocation()
HEALTH = load_recovery()
STOP = {"Drone2": LIVE_STOP_AT_S}
WIDE = {"position_m": 5.0, "battery": 5.0, "why": "a test: the stand-in's truth is rebuilt from polls"}


def stand_in():
    run = fly_recovery_on_mock(LIVE, CONFIG, HEALTH, "Drone2 stopped", STOP)
    return LiveRecoveryFlight(live_like(run.team), CONFIG, HEALTH, run.stopped, run.policies, run.searched)


class LivePathTests(unittest.TestCase):

    def test_it_refuses_pads_that_are_not_the_spawn_layout(self):
        d1, d2 = LIVE.vehicles
        moved = dataclasses.replace(LIVE, vehicles=(d1, dataclasses.replace(d2, start_x=7.0)))
        world = MockWorld(declared=("Drone1",), clock=RealClock())
        with self.assertRaisesRegex(ValueError, "spawn layout"):
            fly_recovery_live(moved, CONFIG, HEALTH, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                              RealClock(), STOP)

    def test_it_refuses_to_stop_a_drone_it_does_not_fly(self):
        world = MockWorld(declared=("Drone1",), clock=RealClock())
        with self.assertRaisesRegex(ValueError, r"not on .*Drone7"):
            fly_recovery_live(LIVE, CONFIG, HEALTH, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                              RealClock(), {"Drone7": 17.0})


class LiveFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.live = stand_in()

    def test_it_comes_back_as_a_run_the_checks_apply_to(self):
        run = self.live.as_run("live")
        self.assertEqual((run.team.label, run.config, run.health), ("live", CONFIG, HEALTH))
        self.assertEqual((run.stopped, run.survivors), (self.live.stopped, ["Drone1"]))
        checks = live_checks(run, LIVE, WIDE)
        self.assertEqual(sorted(k for k in checks if k != "all"), sorted(LIVE_CHECKS))
        self.assertNotIn("deterministic", checks)                       # one flight cannot be held to it
        for name in LIVE_CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:3])
        self.assertTrue(checks["all"])

    def test_the_stopped_drone_is_told_to_the_judge(self):
        # Told it was stopped, the judge does not hold the stopped drone to ending its part.
        self.assertTrue(self.live.as_run().met)
        told_nothing = dataclasses.replace(self.live, stopped={})
        self.assertFalse(told_nothing.as_run().met)

    def test_a_survivor_that_never_noticed_fails_detected(self):
        policies = copy.deepcopy(self.live.policies)
        policies["Drone1"]["health"]["log"] = []
        checks = live_checks(dataclasses.replace(self.live, policies=policies).as_run(), LIVE, WIDE)
        self.assertFalse(checks["detected"]["ok"])
        self.assertFalse(checks["all"])

    def test_a_flight_in_which_nobody_was_stopped_fails_detected(self):
        # A stop set after the mission ended stops nobody; such a flight must not pass for one that detected a stop.
        checks = live_checks(dataclasses.replace(self.live, stopped={}).as_run(), LIVE, WIDE)
        self.assertIn("nobody was stopped", " ".join(checks["detected"]["problems"]))
        self.assertFalse(checks["all"])

    def checked(self, change):
        policies = copy.deepcopy(self.live.policies)
        change(policies["Drone1"])
        return live_checks(dataclasses.replace(self.live, policies=policies).as_run(), LIVE, WIDE)

    def test_a_ladder_late_by_less_than_two_ticks_passes_and_by_more_fails(self):
        # Live, a tick is the real clock's: the ladder may read late by up to two of them, and no more.
        def late(by):
            def change(p):
                first = p["health"]["log"][0]
                first["silence_s"] = HEALTH.suspected_s + by
            return change
        self.assertTrue(self.checked(late(0.9))["detected"]["ok"])
        self.assertFalse(self.checked(late(1.1))["detected"]["ok"])

    def test_a_role_change_off_its_cause_by_less_than_two_ticks_passes_and_by_more_fails(self):
        # The survivor's last change, back to reserve, follows its detector calling the stopped drone failed;
        # the role and its announcement stay as flown, the cause is moved.
        self.assertEqual(self.live.policies["Drone1"]["roles"]["log"][-1]["after"], "reserve")

        def off(by):
            def change(p):
                failed = next(t for t in p["health"]["log"] if t["after"] == "failed")
                failed["at"] -= by
            return change
        self.assertTrue(self.checked(off(0.9))["roles_from_interactions"]["ok"])
        self.assertFalse(self.checked(off(1.1))["roles_from_interactions"]["ok"])
        self.assertFalse(self.checked(off(5.0))["roles_from_interactions"]["ok"])

    def test_the_survivor_takes_the_stopped_drones_sector(self):
        self.assertEqual(sorted(self.live.searched["Drone1"]), ["search S1", "search S2"])
        self.assertEqual(self.live.searched["Drone2"], [])
        taken = live_checks(self.live.as_run(), LIVE, WIDE)["reassigned"]["reassignments"]
        self.assertEqual([(x["stopped"], x["task"], x["taken_by"]) for x in taken], [("Drone2", "search S1", "Drone1")])

    def test_its_record(self):
        row = json.loads(json.dumps(self.live.as_json(), default=str))
        self.assertEqual((row["kind"], row["scenario"]), ("flight", "search_relay_live_small"))
        self.assertEqual((row["allocation"], row["health"]), (CONFIG.as_json(), HEALTH.as_json()))
        self.assertEqual(sorted(row["policies"]), ["Drone1", "Drone2"])
        self.assertEqual((row["stopped"], row["searched"]), (self.live.stopped, self.live.searched))


class ReportLiveTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.good = stand_in()

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def report(self, flight):
        import recovery_exit
        args = SimpleNamespace(poll_hz=None, out=self.out, block="t")
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.recovery.fly_recovery_live", return_value=flight) as fly, \
                redirect_stdout(buffer):
            code = recovery_exit.report_live(args, "2026-11-04T00:00:00", lambda: None, RealClock())
        self.assertEqual(fly.call_args[0][6], STOP)
        jsonl = next(f for f in os.listdir(self.out) if f.endswith(".jsonl"))
        with open(os.path.join(self.out, jsonl), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        return code, rows, buffer.getvalue()

    def test_the_record(self):
        code, rows, text = self.report(self.good)
        head, flight, twin = rows[0], rows[1], rows[-1]
        self.assertEqual((head["sim"], head["scenario"], head["recovery_manifest"], head["network"]),
                         ("airsim", "search_relay_live_small", "configs/recovery/default.toml",
                          "every message delivered (range unlimited)"))
        self.assertEqual((head["stop"], head["stopped_at"]), (STOP, self.good.stopped))
        self.assertEqual(sorted(head["checks"]), sorted(LIVE_CHECKS))
        self.assertNotIn("exit_criterion_met", head)                          # a live flight, not the exit
        self.assertEqual((flight["kind"], flight["set"]), ("flight", "live"))
        self.assertGreater(len([r for r in rows if r["kind"] == "message"]), 20)
        self.assertEqual((twin["kind"], twin["set"]), ("twin", "mock_twin"))
        self.assertEqual(sorted(twin["searched"]), ["Drone1 stopped", "Drone2 stopped", "no stop"])
        self.assertEqual(twin["stopped"], {"no stop": {}, "Drone1 stopped": {"Drone1": LIVE_STOP_AT_S},
                                           "Drone2 stopped": {"Drone2": LIVE_STOP_AT_S}})   # stopped mid-search, at 17 s
        self.assertTrue(twin["checks"]["all"])                                # the twin flown with all eight
        self.assertTrue(head["mock_twin_all"])
        self.assertIn("| deterministic | - | yes |", text)
        self.assertIn("| Survivor's roles | Drone1: ", text)
        self.assertNotIn("Exit criterion", text)

    def test_the_verdict_follows_the_seven_checks(self):
        code, rows, text = self.report(self.good)
        ok = all(rows[1]["checks"][k]["ok"] for k in LIVE_CHECKS)
        self.assertEqual(rows[0]["live_flight_met"], ok)
        self.assertEqual(code, 0 if ok else 1)
        self.assertIn(f"**Live flight: {'MET' if ok else 'NOT MET'}**", text)

    def test_a_survivor_that_did_not_finish_is_not_met(self):
        team = dataclasses.replace(self.good.flight, finished={"Drone1": False, "Drone2": False})
        code, rows, text = self.report(dataclasses.replace(self.good, flight=team))
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["checks"]["continued"])
        self.assertIn("**Live flight: NOT MET**", text)
        self.assertIn("continued", text.split("failed:")[1])


class CommandLineTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_live_options_are_for_a_live_run(self):
        import recovery_exit
        for argv in (["--port", "41451"], ["--poll-hz", "5"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                recovery_exit.main(argv + ["--out", self.out])
            self.assertEqual(raised.exception.code, 2)

    def test_live_goes_to_the_simulator(self):
        import recovery_exit
        with mock.patch.object(recovery_exit, "live", return_value=0) as live:
            self.assertEqual(recovery_exit.main(["--sim", "airsim", "--block", "x", "--out", self.out]), 0)
        self.assertEqual(live.call_args[0][0].block, "x")


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 70 s each)")
class RealTimeTests(unittest.TestCase):

    def test_fly_recovery_live_on_the_mock_in_real_time(self):
        from agentic_uav.agents.rule_policy import RulePolicy
        from agentic_uav.experiments.knowledge import observed_poll_hz, poll_tolerance
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        with redirect_stdout(io.StringIO()):
            live = fly_recovery_live(LIVE, CONFIG, HEALTH, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                                     clock, STOP)
        self.assertEqual(live.flight.layout["added"], ["Drone2"])
        self.assertEqual(sorted(live.stopped), ["Drone2"])
        self.assertAlmostEqual(live.stopped["Drone2"], LIVE_STOP_AT_S, delta=1.0)
        self.assertEqual(live.flight.finished, {"Drone1": True, "Drone2": False})
        self.assertEqual(sorted(live.searched["Drone1"]), ["search S1", "search S2"])
        tol = poll_tolerance(LIVE, observed_poll_hz(live.flight.samples, live.flight.poll_hz)["hz"], RulePolicy().speed_mps)
        checks = live_checks(live.as_run(), LIVE, tol)
        for name in LIVE_CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:5])
        ladder = [t["after"] for t in live.policies["Drone1"]["health"]["log"]]
        self.assertEqual(ladder, ["suspected", "unreachable", "failed"])
        # Stopped, it holds where it was: its skill aborted, it does not fly on.
        self.assertEqual(live.flight.skills["Drone2"][-1][1], "aborted")
        after = [(x, y) for t, x, y, _ in live.flight.samples["Drone2"] if t > live.flight.start + live.stopped["Drone2"] + 2.0]
        self.assertGreater(len(after), 20)
        self.assertLess(max(math.dist(after[0], p) for p in after), 0.5)
        tops = {d: max(live.flight.grounds[d] - z for _, _, _, z in rows) for d, rows in live.flight.samples.items()}
        self.assertAlmostEqual(tops["Drone1"], 12.0, delta=0.5)
        self.assertAlmostEqual(tops["Drone2"], 16.0, delta=0.5)

    def test_the_script_live_on_the_mock_in_real_time(self):
        import recovery_exit
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        out = tempfile.mkdtemp()
        try:
            args = SimpleNamespace(poll_hz=None, out=out, block="rt")
            with redirect_stdout(io.StringIO()) as buffer:
                code = recovery_exit.report_live(args, "rt", lambda: MockVehicleAdapter(world), clock)
            self.assertEqual(code, 0, buffer.getvalue()[-2000:])
            self.assertIn("**Live flight: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
