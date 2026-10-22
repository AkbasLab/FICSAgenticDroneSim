#!/usr/bin/env python3
"""Tests for Phase 5 step 6: the single agent flown live, and what it takes to fly it there.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also fly_agent_live, ~70 s in real time

WHY THESE EXIST
---------------
A live flight of the agent cannot run here, so each piece it needs is held
on its own: the live-sized scenario stays in the airspace already flown and
passes its mock gate; each skill flies on its own connection; a fault
injected in our code strikes the set number of times in the whole flight
and no more; readings built from the poller follow the same rules as the
mock's; a live flight is judged, saved and judged again the same; and the
script's live record says what it should. The whole live path runs on the
mock in real time when AUV_SLOW_TESTS is set.
"""

import dataclasses
import io
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.core.models import PrimitiveCommand, PrimitiveKind  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS  # noqa: E402
from agentic_uav.experiments.single_agent import (  # noqa: E402
    TROUBLES,
    LiveAgentFlight,
    exit_runs,
    fly_agent_live,
    fly_agent_on_mock,
)
from agentic_uav.simulator.fault_injection import FaultyAdapter, PassingFaults  # noqa: E402
from agentic_uav.simulator.mission_world import battery, detections, place_targets  # noqa: E402
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import trajectories_from_samples  # noqa: E402
from agentic_uav.simulator.sensing import polled_sensors  # noqa: E402

LIVE = scenarios.load_scenario("search_single_live_small")
TASK = "search S1"
G = MOCK_GROUND_Z
MOVE = PrimitiveKind.MOVE_TO_POSITION
ONCE = next(t for t in TROUBLES if t.name == "fault once")

CLOCK_ORIGIN = 1000.0         # a monotonic clock is never at 0 when a flight starts


def live_from_mock(run, faults_struck=()):
    """A LiveAgentFlight made from a mock run's exact trace, as a poller would have kept it."""
    t0 = CLOCK_ORIGIN
    samples = {d: [(t0 + k.t, k.x, k.y, G - k.altitude_m) for k in t.knots] for d, t in run.trajectories.items()}
    return LiveAgentFlight(LIVE, run.task, samples, {d: G for d in samples}, (), t0 + run.report.start,
                           t0 + run.report.until, 10.0, run.trace, (), run.finished, dict(run.progress),
                           run.skills, tuple(faults_struck))


class ScenarioTests(unittest.TestCase):

    def test_it_is_phase_4s_live_variant_cut_to_one_drone_and_s1(self):
        relay = scenarios.load_scenario("search_relay_live_small")
        self.assertEqual([v.id for v in LIVE.vehicles], ["Drone1"])
        self.assertEqual(LIVE.vehicles[0], relay.vehicle("Drone1"))
        self.assertEqual(LIVE.sectors, tuple(s for s in relay.sectors if s.id == "S1"))
        for field in ("mission", "base", "network", "detection", "battery", "safety", "restricted_zones",
                      "random_seed"):
            with self.subTest(field=field):
                self.assertEqual(getattr(LIVE, field), getattr(relay, field))
        self.assertEqual(LIVE.targets.min_spacing_m, 10.0)

    def test_the_flight_stays_in_the_airspace_flown(self):
        # Phase 4's Drone1 flew the lane at y = -18 from x = -8 to 20 live,
        # at most 26.9 m out; the agent's route round R1 stays inside that.
        run = fly_agent_on_mock(LIVE, TASK)
        knots = run.trajectories["Drone1"].knots
        self.assertGreaterEqual(min(k.x for k in knots), -8.0 - 1e-6)
        self.assertLessEqual(max(k.x for k in knots), 20.0 + 1e-6)
        self.assertLessEqual(max(abs(k.y) for k in knots), 18.0 + 1e-6)
        self.assertLess(max(math.hypot(k.x, k.y) for k in knots), 27.0)

    def test_the_mock_gate(self):
        runs = exit_runs(LIVE, EXIT_SEEDS, TASK)
        self.assertEqual([r.seed for r in runs if not r.met], [])
        once = fly_agent_on_mock(LIVE, TASK, ONCE.name, ONCE.prepare)
        ok, problems = ONCE.check(once)
        self.assertTrue(ok, problems)
        self.assertIn(("FOLLOW_WAYPOINTS", "failed"), once.skills)


class _Recording:
    """An adapter that records the primitives it was sent."""

    def __init__(self):
        self.sent = []
        self.name = "recording"

    def execute_primitive(self, vehicle_id, command):
        self.sent.append((vehicle_id, command.kind))
        return "done"


class FaultInjectionTests(unittest.TestCase):

    def setUp(self):
        self.faults = PassingFaults({("Drone1", MOVE): 2})
        self.inner = _Recording()
        self.adapter = FaultyAdapter(self.inner, self.faults)
        self.move = PrimitiveCommand.move_to_position(0, 0, G - 3, 5.0)

    def test_fails_the_set_number_of_times_then_passes_through(self):
        for left in (1, 0):
            with self.assertRaisesRegex(RuntimeError, f"injected passing fault on move_to_position \\({left} more"):
                self.adapter.execute_primitive("Drone1", self.move)
        self.assertEqual(self.inner.sent, [])                        # nothing refused reached the simulator
        self.assertEqual(self.adapter.execute_primitive("Drone1", self.move), "done")
        self.assertEqual(self.inner.sent, [("Drone1", MOVE)])
        self.assertEqual(self.faults.struck, [("Drone1", "move_to_position")] * 2)

    def test_only_the_chosen_drone_and_primitive(self):
        hover = PrimitiveCommand.hover()
        self.assertEqual(self.adapter.execute_primitive("Drone1", hover), "done")
        self.assertEqual(self.adapter.execute_primitive("Drone2", self.move), "done")
        self.assertEqual(self.faults.left("Drone1", MOVE), 2)

    def test_counted_across_every_connection_of_the_flight(self):
        other = FaultyAdapter(_Recording(), self.faults)
        with self.assertRaises(RuntimeError):
            self.adapter.execute_primitive("Drone1", self.move)
        with self.assertRaises(RuntimeError):
            other.execute_primitive("Drone1", self.move)
        self.assertEqual(other.execute_primitive("Drone1", self.move), "done")

    def test_strikes_exactly_as_often_from_many_threads(self):
        faults = PassingFaults({("Drone1", MOVE): 50})
        taken = []

        def worker():
            taken.extend(faults.take("Drone1", MOVE) for _ in range(100))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(taken), 50)
        self.assertEqual(len(faults.struck), 50)

    def test_everything_else_is_the_adapters_own(self):
        self.assertEqual(self.adapter.name, "recording")


class ExecutorConnectTests(unittest.TestCase):

    def test_each_skill_flies_on_a_connection_of_its_own(self):
        world = MockWorld()
        opened = []

        def connect():
            opened.append(MockVehicleAdapter(world))
            return opened[-1]

        executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock), connect=connect)
        out = []

        def agent():
            with world.clock.participate():
                for command in (S.TakeOffCommand(altitude_m=10), S.GoToWaypointCommand(Waypoint(10, 0, 10))):
                    executor.start(command)
                    out.append(executor.wait().result)

        thread = threading.Thread(target=agent)
        thread.start()
        thread.join()
        executor.close()
        self.assertTrue(all(r.ok for r in out), out)
        self.assertEqual(len(opened), 2)
        self.assertIs(executor.runner.vehicle, opened[-1])


class _Observer:
    """What polled_sensors reads of a PollingObserver: its drones, its clock, its samples."""

    def __init__(self, samples, now):
        self.drones = tuple(samples)
        self._samples = samples
        self.clock = SimpleNamespace(now=lambda: self.now)
        self.now = now

    def samples(self):
        return {d: list(rows) for d, rows in self._samples.items()}


class PolledSensorsTests(unittest.TestCase):

    def test_own_state_is_the_latest_poll(self):
        obs = _Observer({"Drone1": [(0.0, 0.0, 0.0, G), (1.0, 2.0, -3.0, G - 12.0)]}, 1.05)
        state = polled_sensors(obs, LIVE, "Drone1", {"Drone1": G}).own_state()
        self.assertEqual((state.t, state.x, state.y, state.altitude_m, state.airborne), (1.05, 2.0, -3.0, 12.0, True))

    def test_landed_below_the_pollers_line(self):
        # CarlaAir reports a landed drone about 1.17 m up: not airborne.
        obs = _Observer({"Drone1": [(0.0, 0.0, 0.0, G - 1.17)]}, 0.1)
        self.assertFalse(polled_sensors(obs, LIVE, "Drone1", {"Drone1": G}).own_state().airborne)

    def test_the_base_link_is_the_radio_range_now(self):
        # The base is at (-6, 0), its radio reaches 20 m.
        near = _Observer({"Drone1": [(0.0, 0.0, 0.0, G)]}, 0.0)
        far = _Observer({"Drone1": [(0.0, 0.0, 0.0, G), (9.0, 20.0, -18.0, G - 12.0)]}, 9.0)
        self.assertTrue(polled_sensors(near, LIVE, "Drone1", {"Drone1": G}).base_link())
        self.assertFalse(polled_sensors(far, LIVE, "Drone1", {"Drone1": G}).base_link())

    def test_battery_and_sightings_are_phase_4s_rules_on_the_polls(self):
        run = fly_agent_on_mock(LIVE, TASK)
        flight = live_from_mock(run)
        obs = _Observer(flight.samples, flight.end)
        sensors = polled_sensors(obs, LIVE, "Drone1", flight.grounds, start=flight.start)
        path = trajectories_from_samples(flight.samples, flight.grounds)["Drone1"]
        self.assertAlmostEqual(sensors.battery(),
                               battery(path, LIVE.battery, flight.start, flight.end).remaining, places=9)
        # What the evaluator will say of the same polls -- not of the mock's
        # exact trace: below the poller's 3 m line nothing counts as airborne.
        self.assertAlmostEqual(sensors.battery(), flight.judge().facts.batteries[0].remaining, places=9)
        seen = sensors.sightings()
        expected = detections([path], place_targets(LIVE), LIVE.detection, flight.start, flight.end)
        self.assertEqual([(s.label, s.at) for s in seen], [(d.target, d.detected_at) for d in expected])
        self.assertEqual(len(seen), LIVE.targets.count)                 # both found, as the mock found them

    def test_refused_before_the_first_poll(self):
        obs = _Observer({"Drone1": []}, 0.0)
        sensors = polled_sensors(obs, LIVE, "Drone1", {"Drone1": G})
        with self.assertRaisesRegex(RuntimeError, "no poll yet"):
            sensors.own_state()

    def test_only_observed_scenario_drones_with_a_ground(self):
        obs = _Observer({"Drone1": [(0.0, 0.0, 0.0, G)]}, 0.0)
        with self.assertRaisesRegex(ValueError, "not one of"):
            polled_sensors(obs, LIVE, "Drone2", {"Drone1": G})
        with self.assertRaisesRegex(ValueError, "no measured ground"):
            polled_sensors(obs, LIVE, "Drone1", {})


class LiveAgentFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mock_run = fly_agent_on_mock(LIVE, TASK)
        cls.flight = live_from_mock(cls.mock_run)

    def test_judged_like_the_mock(self):
        for seed in (1, 15, 17):
            with self.subTest(seed=seed):
                report = self.flight.judge(seed)
                self.assertTrue(report.success, report.summary())
                self.assertEqual(report.observer, "polled-10Hz")
                self.assertEqual(report.random_seed, seed)
        self.assertTrue(self.flight.as_run("live").met)

    def test_saved_and_judged_again_the_same(self):
        row = json.loads(json.dumps(self.flight.as_json(), default=str))
        self.assertEqual(row["samples"]["Drone1"][0][0], 0.0)           # times from the flight's start
        again = LiveAgentFlight.from_json(row, LIVE)
        self.assertEqual(again.trace_json, tuple(row["trace"]))
        self.assertEqual(again.as_json()["trace"], row["trace"])           # saved again, the trace is kept
        self.assertEqual(again.skills, self.flight.skills)
        for seed in EXIT_SEEDS:
            with self.subTest(seed=seed):
                a, b = self.flight.judge(seed), again.judge(seed)
                self.assertEqual(a.success, b.success)
                self.assertEqual([c.passed for c in a.criteria], [c.passed for c in b.criteria])
                self.assertAlmostEqual(a.coverage.fraction, b.coverage.fraction, places=3)

    def test_not_a_flight_of_this_scenario(self):
        row = self.flight.as_json()
        with self.assertRaisesRegex(ValueError, "not a flight"):
            LiveAgentFlight.from_json(dict(row, kind="seed"), LIVE)
        with self.assertRaisesRegex(ValueError, "not a flight"):
            LiveAgentFlight.from_json(row, scenarios.load_scenario("search_single_001"))

    def test_only_one_agent_flies_live(self):
        two = scenarios.load_scenario("search_relay_live_small")
        with self.assertRaisesRegex(ValueError, "one agent"):
            fly_agent_live(two, TASK, None, None, RealClock())


class ScriptLiveTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

    def report(self, flight, fault_once=False):
        import single_agent_exit
        args = SimpleNamespace(scenario=single_agent_exit.LIVE_SCENARIO, task=single_agent_exit.LIVE_TASK,
                               seeds=(1, 2, 17), out=self.out, block="t", fault_once=fault_once, poll_hz=None)
        buffer = io.StringIO()
        with mock.patch("agentic_uav.experiments.single_agent.fly_agent_live", return_value=flight), \
                redirect_stdout(buffer):
            code = single_agent_exit.report_live(args, LIVE, "now", lambda: None, RealClock())
        (jsonl,) = [f for f in os.listdir(self.out) if f.endswith(".jsonl")]
        with open(os.path.join(self.out, jsonl), encoding="utf-8") as h:
            return code, [json.loads(line) for line in h], buffer.getvalue()

    def test_a_nominal_flight_is_recorded_beside_its_mock_twin(self):
        code, rows, text = self.report(live_from_mock(fly_agent_on_mock(LIVE, TASK)))
        self.assertEqual(code, 0)
        self.assertEqual([r["kind"] for r in rows], ["header", "flight", "mock_twin", "seed", "seed", "seed"])
        self.assertTrue(rows[0]["met"])
        self.assertEqual(rows[0]["scenario_file"], "configs/scenarios/search_single_live_small.toml")
        self.assertEqual([r["seed"] for r in rows[3:]], [1, 2, 17])
        self.assertEqual([r["report"]["random_seed"] for r in rows[3:]], [1, 2, 17])
        self.assertIn("Seeds judged on this flight: 3 of 3 succeed.", text)
        self.assertIn("**MET**", text)

    def test_a_flight_that_fails_is_not_met(self):
        flight = dataclasses.replace(live_from_mock(fly_agent_on_mock(LIVE, TASK)), finished=False)
        code, rows, text = self.report(flight)
        self.assertEqual(code, 1)
        self.assertIn("finished False", rows[0]["problems"][0])
        self.assertIn("**NOT MET**", text)

    def test_fault_once_is_held_to_the_mocks_check(self):
        run = fly_agent_on_mock(LIVE, TASK, ONCE.name, ONCE.prepare)
        code, rows, text = self.report(live_from_mock(run, [("Drone1", "move_to_position")]), fault_once=True)
        self.assertEqual(code, 0, rows[0]["problems"])
        self.assertTrue(rows[0]["fault_once"])
        self.assertIn(["FOLLOW_WAYPOINTS", "failed"], rows[2]["skills"])          # the twin met the fault too
        self.assertIn("Drone1 move_to_position", text)

    def test_a_fault_once_flight_that_fails_its_check_is_not_met(self):
        run = fly_agent_on_mock(LIVE, TASK, ONCE.name, ONCE.prepare)
        flight = dataclasses.replace(live_from_mock(run), finished=False)
        code, rows, text = self.report(flight, fault_once=True)
        self.assertEqual(code, 1)
        self.assertIn("the agent never ended the task itself", rows[0]["problems"])

    def test_fault_once_is_for_a_live_run(self):
        import single_agent_exit
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            single_agent_exit.main(["--fault-once", "--out", self.out])
        self.assertEqual(raised.exception.code, 2)


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 70 s)")
class RealTimeAgentFlightTest(unittest.TestCase):

    def test_fly_agent_live_on_the_mock_in_real_time(self):
        # The live path whole -- reset, placement, rest, the poller, the
        # monitor, a connection per skill, the injected fault -- with the
        # mock standing in for AirSim.
        for fault_once in (False, True):
            with self.subTest(fault_once=fault_once):
                clock = RealClock()
                world = MockWorld(declared=("Drone1",), clock=clock)
                flight = fly_agent_live(LIVE, TASK, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world),
                                        clock, fault_once=fault_once)
                run = flight.as_run("real time")
                if fault_once:
                    self.assertEqual(flight.faults_struck, (("Drone1", "move_to_position"),))
                    self.assertTrue(*ONCE.check(run))
                else:
                    self.assertEqual(flight.faults_struck, ())
                    self.assertTrue(run.met, run.report.summary())
                self.assertEqual(flight.grounds, {"Drone1": G})
                self.assertGreater(len(flight.samples["Drone1"]), 200)
                self.assertTrue(all(flight.judge(s).success for s in EXIT_SEEDS))


if __name__ == "__main__":
    unittest.main()
