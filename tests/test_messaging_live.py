#!/usr/bin/env python3
"""Tests for Phase 7 step 6c: two talking agents flown live, and what it takes to fly them there.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also the live path whole, ~80 s in real time

WHY THESE EXIST
---------------
A live flight cannot run here, so the pieces are held on their own: the live
path refuses what it cannot fly; a live flight comes back as a run the mock's
checks apply to unchanged; and the script's live record says what it should
-- four checks for the flight, six for its mock twin, and a verdict that is
the flight's, never the exit's.

A flight built from a mock run stands in for a live one in the fast tests.
As in Phase 6 (tests/test_knowledge_live.py), such a stand-in cannot be asked
to pass "known exactly": its belief was sensed exactly while its truth is
rebuilt from polls. So the fast tests check that the verdict FOLLOWS the
checks, and the claim that a live flight passes is left to RealTimeTests,
which fly the whole path -- reset, Drone2 spawned at runtime, the poller,
the monitor, the bus on the poller's positions -- with the mock standing in
for AirSim.
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

from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.messaging import talking_checks  # noqa: E402
from agentic_uav.experiments.single_agent import (  # noqa: E402
    PAIR_TASKS,
    LiveTeamFlight,
    fly_agents_live,
    fly_agents_on_mock,
)
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import DEFAULT_POLL_HZ  # noqa: E402

LIVE = scenarios.load_scenario("search_relay_live_small")
G = MOCK_GROUND_Z
LIVE_CHECKS = ("met", "exchanged", "only_on_delivery", "known_exactly")


def live_like(run, hz=DEFAULT_POLL_HZ):
    """A LiveTeamFlight from a talking mock run, sampled as a poller would sample it."""
    period = 1.0 / hz
    samples = {}
    for drone, path in run.trajectories.items():
        rows, i = [], 0
        while path.start + i * period <= path.end + 1e-9:
            at = path.start + i * period
            x, y, alt = path.position_at(at)
            rows.append((at, x, y, G - alt))
            i += 1
        samples[drone] = rows
    return LiveTeamFlight(LIVE, dict(run.tasks), samples, {d: G for d in samples}, (), run.start,
                          run.report.until, hz, dict(run.traces), dict(run.finished), dict(run.skills),
                          run.deliveries, LIVE.network.communication_range_m,
                          {"added": ["Drone2"]}, {"samples": 0})


class LivePathTests(unittest.TestCase):

    def test_it_flies_only_one_task_per_pad(self):
        world = MockWorld(declared=("Drone1",), clock=RealClock())
        for tasks in ({"Drone1": "search S1"}, {**PAIR_TASKS, "Drone3": "search S3"}):
            with self.subTest(tasks=tasks), self.assertRaisesRegex(ValueError, "one task per drone"):
                fly_agents_live(LIVE, tasks, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world), RealClock())

    def test_it_refuses_pads_that_are_not_the_spawn_layout(self):
        # Live, drone i is spawned at (i x 4 m, 0): a pad elsewhere would take off from the wrong place.
        d1, d2 = LIVE.vehicles
        moved = dataclasses.replace(LIVE, vehicles=(d1, dataclasses.replace(d2, start_x=7.0)))
        world = MockWorld(declared=("Drone1",), clock=RealClock())
        with self.assertRaisesRegex(ValueError, "spawn layout"):
            fly_agents_live(moved, PAIR_TASKS, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                            RealClock())


class LiveTeamFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flown = fly_agents_on_mock(LIVE, PAIR_TASKS, "talking", messaging=True)
        cls.flight = live_like(cls.flown)

    def test_it_comes_back_as_a_run_the_checks_apply_to(self):
        run = self.flight.as_run("live")
        self.assertEqual((run.label, run.tasks, run.start), ("live", PAIR_TASKS, self.flown.start))
        self.assertEqual(run.traces, self.flown.traces)
        self.assertEqual(run.deliveries, self.flown.deliveries)
        self.assertEqual(run.report.observer, f"polled-{DEFAULT_POLL_HZ:g}Hz")
        checks = talking_checks(run, LIVE)
        self.assertEqual(sorted(checks), sorted(LIVE_CHECKS))
        for name in ("met", "exchanged", "only_on_delivery"):
            self.assertTrue(checks[name]["ok"], checks[name]["problems"][:3])

    def test_known_exactly_is_held_to_the_tolerance_it_is_given(self):
        # The stand-in's truth is rebuilt from polls, so at the mock's 1 cm it
        # cannot pass (see the module docstring); at a wide allowance it must.
        run = self.flight.as_run("live")
        self.assertFalse(talking_checks(run, LIVE)["known_exactly"]["ok"])
        wide = {"position_m": 5.0, "battery": 5.0, "why": "a test"}
        self.assertTrue(talking_checks(run, LIVE, wide)["known_exactly"]["ok"])

    def test_its_record(self):
        row = json.loads(json.dumps(self.flight.as_json(), default=str))
        self.assertEqual((row["kind"], row["scenario"], row["tasks"], row["range_m"]),
                         ("flight", "search_relay_live_small", PAIR_TASKS, 20.0))
        self.assertEqual(sorted(row["traces"]), ["Drone1", "Drone2"])
        self.assertEqual(sum(len(t) for t in row["traces"].values()), sum(len(t) for t in self.flown.traces.values()))
        self.assertEqual(row["samples"]["Drone1"][0][0], 0.0)              # times from the flight's start
        self.assertEqual(row["finished"], {"Drone1": True, "Drone2": True})


class ReportLiveTests(unittest.TestCase):
    """The script's live record and verdict, with a stand-in flight."""

    @classmethod
    def setUpClass(cls):
        cls.good = live_like(fly_agents_on_mock(LIVE, PAIR_TASKS, "talking", messaging=True))

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def report(self, flight):
        import messaging_exit
        args = SimpleNamespace(scenario="search_relay_live_small", poll_hz=None, out=self.out, block="t")
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.single_agent.fly_agents_live", return_value=flight), \
                redirect_stdout(buffer):
            code = messaging_exit.report_live(args, "2026-11-04T00:00:00", lambda: None, RealClock())
        jsonl = next(f for f in os.listdir(self.out) if f.endswith(".jsonl"))
        with open(os.path.join(self.out, jsonl), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        return code, rows, buffer.getvalue()

    def test_the_record(self):
        code, rows, text = self.report(self.good)
        header, flight = rows[0], rows[1]
        self.assertEqual((header["sim"], header["scenario"], header["tasks"], header["range_m"], header["delay_s"]),
                         ("airsim", "search_relay_live_small", PAIR_TASKS, 20.0, 0.1))
        self.assertEqual(sorted(header["checks"]), sorted(LIVE_CHECKS))
        self.assertNotIn("exit_criterion_met", header)                     # a live flight, not the exit
        self.assertEqual(header["poll"]["asked_hz"], DEFAULT_POLL_HZ)
        self.assertEqual((flight["kind"], flight["set"]), ("flight", "live"))
        self.assertEqual(sorted(flight["checks"]), sorted(LIVE_CHECKS))
        messages = [r for r in rows if r["kind"] == "message"]
        self.assertEqual(len(messages), len(self.good.deliveries))
        twin = rows[-1]
        self.assertEqual((twin["kind"], twin["set"]), ("twin", "mock_twin"))
        self.assertTrue(twin["checks"]["all"])                             # the twin is flown with all six
        self.assertTrue(header["mock_twin_all"])
        self.assertIn("| blocked_moves_nothing | - | yes |", text)
        self.assertNotIn("Exit criterion", text)

    def test_the_verdict_follows_the_four_checks(self):
        code, rows, text = self.report(self.good)
        ok = all(rows[1]["checks"][k]["ok"] for k in LIVE_CHECKS)
        self.assertEqual(rows[0]["live_flight_met"], ok)
        self.assertEqual(code, 0 if ok else 1)
        self.assertIn(f"**Live flight: {'MET' if ok else 'NOT MET'}**", text)

    def test_a_flight_that_did_not_finish_is_not_met(self):
        flight = dataclasses.replace(self.good, finished={"Drone1": True, "Drone2": False})
        code, rows, text = self.report(flight)
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["live_flight_met"])
        self.assertFalse(rows[0]["checks"]["met"])
        self.assertIn("**Live flight: NOT MET**", text)
        self.assertIn("failed: met", text)

    def test_a_flight_that_heard_nothing_is_not_met(self):
        flight = dataclasses.replace(self.good, deliveries=())
        code, rows, _ = self.report(flight)
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["checks"]["exchanged"])


class CommandLineTests(unittest.TestCase):
    # Every call writes to a scratch folder: were a refusal ever lost, the
    # flight it let through must not land in the phase's results.

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def refused(self, argv):
        import messaging_exit
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            messaging_exit.main(argv + ["--out", self.out])
        return raised.exception.code

    def test_live_flies_only_the_variant(self):
        self.assertEqual(self.refused(["--sim", "airsim", "--scenario", "search_relay_001"]), 2)

    def test_live_options_are_for_a_live_run(self):
        self.assertEqual(self.refused(["--port", "41451"]), 2)
        self.assertEqual(self.refused(["--poll-hz", "5"]), 2)

    def test_live_goes_to_the_simulator(self):
        import messaging_exit
        with mock.patch.object(messaging_exit, "live", return_value=0) as live:
            self.assertEqual(messaging_exit.main(["--sim", "airsim", "--block", "x", "--out", self.out]), 0)
        args = live.call_args[0][0]
        self.assertEqual((args.scenario, args.block), ("search_relay_live_small", "x"))


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 80 s)")
class RealTimeTests(unittest.TestCase):

    def test_fly_agents_live_on_the_mock_in_real_time(self):
        # The live path whole, with the mock standing in for AirSim.
        from agentic_uav.agents.rule_policy import RulePolicy
        from agentic_uav.experiments.knowledge import observed_poll_hz, poll_tolerance
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        with redirect_stdout(io.StringIO()):
            flight = fly_agents_live(LIVE, PAIR_TASKS, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                                     clock)
        self.assertEqual(flight.layout["added"], ["Drone2"])
        self.assertEqual(flight.grounds, {"Drone1": G, "Drone2": G})
        self.assertEqual(flight.finished, {"Drone1": True, "Drone2": True})
        self.assertGreater(min(len(v) for v in flight.samples.values()), 200)
        tol = poll_tolerance(LIVE, observed_poll_hz(flight.samples, flight.poll_hz)["hz"], RulePolicy().speed_mps)
        checks = talking_checks(flight.as_run("real time"), LIVE, tol)
        for name in LIVE_CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:5])
        # The bus judged range on the poller: heard near the pads, silent searching.
        status = {d.status for d in flight.deliveries}
        self.assertTrue({"delivered", "out_of_range"} <= status, status)
        # Each at its own height, as on the mock: 12 m and 16 m.
        tops = {d: max(G - z for _, _, _, z in rows) for d, rows in flight.samples.items()}
        self.assertAlmostEqual(tops["Drone1"], 12.0, delta=0.5)
        self.assertAlmostEqual(tops["Drone2"], 16.0, delta=0.5)

    def test_the_script_live_on_the_mock_in_real_time(self):
        import messaging_exit
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        out = tempfile.mkdtemp()
        try:
            args = SimpleNamespace(scenario="search_relay_live_small", poll_hz=None, out=out, block="rt")
            with redirect_stdout(io.StringIO()) as buffer:
                code = messaging_exit.report_live(args, "rt", lambda: MockVehicleAdapter(world), clock)
            self.assertEqual(code, 0, buffer.getvalue()[-2000:])
            self.assertIn("**Live flight: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
