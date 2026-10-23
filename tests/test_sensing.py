#!/usr/bin/env python3
"""Tests for sensing: what a drone can know in flight, and the boundary around it.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 5's agent decides from sensor readings alone, so the readings must be
right at every instant -- including mid-skill, which is when an event-driven
agent reads them -- and must agree with what the evaluator will later say
about the same instant. And the readings must be ALL the agent gets: AUV-06
6.2 makes the truth/belief boundary the one mistake that silently invalidates
the study, so it is enforced here, by walking what the agent is handed and
by reading the agent package's imports.
"""

import ast
import dataclasses
import math
import os
import sys
import threading
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.models import Position  # noqa: E402
from agentic_uav.core.scenario import TargetSpec  # noqa: E402
from agentic_uav.core.sensing import Sensors  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.simulator.mission_world import Connectivity, battery, detections, place_targets  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import mock_trajectories  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
ONE = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:1],
                          targets=TargetSpec(2, "fixed", ((65.0, -5.0), (100.0, -60.0))))
TWO = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:2],
                          targets=TargetSpec(2, "fixed", ((65.0, -5.0), (100.0, -60.0))))


def fly_and_read(scenario, commands, every=0.5, drones=("Drone1",)):
    """Fly Drone1 through `commands` while a second thread reads its sensors every `every` s.

    Both threads share the world's simulated clock, so each reading is taken
    mid-flight at a known instant, as an agent watching a skill would take it.
    """
    world = MockWorld(declared=list(drones))
    sensors = mock_sensors(world, scenario, "Drone1")
    done = threading.Event()
    readings = []
    start = threading.Barrier(2)

    def fly():
        with world.clock.participate():
            start.wait()
            runner = S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock)
            for c in commands:
                assert runner.run(c).ok
            done.set()

    def read():
        with world.clock.participate():
            start.wait()
            while not done.is_set():
                world.clock.sleep(every)
                readings.append((sensors.now(), sensors.own_state(), sensors.battery(),
                                 sensors.sightings(), sensors.base_link()))

    threads = [threading.Thread(target=fly), threading.Thread(target=read)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return world, sensors, readings


class InFlightReadingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.world, cls.sensors, cls.readings = fly_and_read(ONE, (
            S.TakeOffCommand(altitude_m=10), S.GoToWaypointCommand(Waypoint(8, -20, 10)),
            S.GoToWaypointCommand(Waypoint(80, -5, 10)), S.GoToWaypointCommand(Waypoint(100, -50, 10))))
        cls.path = mock_trajectories(cls.world, ["Drone1"])["Drone1"]

    def test_readings_were_taken_mid_skill(self):
        moving = [r for r in self.readings if r[1].airborne and 0 < r[1].x < 80 and r[1].y > -20]
        self.assertGreater(len(moving), 10)

    def test_position_is_where_the_flight_was_at_that_instant(self):
        for t, state, *_ in self.readings:
            with self.subTest(t=t):
                x, y, h = self.path.position_at(t)
                self.assertAlmostEqual(state.x, x, places=6)
                self.assertAlmostEqual(state.y, y, places=6)
                self.assertAlmostEqual(state.altitude_m, h, places=6)
                self.assertEqual(state.t, t)

    def test_battery_agrees_with_the_evaluator_at_every_instant(self):
        for t, _, level, *_ in self.readings:
            with self.subTest(t=t):
                self.assertAlmostEqual(level, battery(self.path, ONE.battery, 0.0, t).remaining, places=9)
        levels = [r[2] for r in self.readings]
        self.assertEqual(levels, sorted(levels, reverse=True))          # it only falls

    def test_a_sighting_appears_when_it_is_made_and_not_before(self):
        (t1,) = [d for d in detections([self.path], place_targets(ONE), ONE.detection, 0.0, 1e9)
                 if d.target == "T1"]
        for t, _, _, seen, _ in self.readings:
            with self.subTest(t=t):
                labels = [s.label for s in seen]
                self.assertEqual("T1" in labels, t >= t1.detected_at)
        last = self.readings[-1][3]
        self.assertEqual([(s.label, s.x, s.y) for s in last][:1], [("T1", 65.0, -5.0)])

    def test_nothing_about_targets_not_yet_seen(self):
        # T2 at (100, -60) is passed only at the very end, if at all; before
        # the last leg nothing reveals it exists.
        before_last_leg = [r for r in self.readings if r[1].y > -10]
        self.assertTrue(all("T2" not in [s.label for s in r[3]] for r in before_last_leg))

    def test_the_link_agrees_with_the_evaluator(self):
        radio = Connectivity([self.path], (ONE.base.x, ONE.base.y), ONE.network.communication_range_m,
                             0.0, self.readings[-1][0])
        for t, *_, linked in self.readings:
            with self.subTest(t=t):
                self.assertEqual(linked, radio.connected_at("Drone1", t))
        self.assertIn(False, [r[4] for r in self.readings])            # (100, -50) is out of range
        self.assertIn(True, [r[4] for r in self.readings])


class WhoSeesWhatTests(unittest.TestCase):

    def test_a_sighting_is_the_drones_own(self):
        world = MockWorld(declared=["Drone1", "Drone2"])
        mine, theirs = mock_sensors(world, TWO, "Drone1"), mock_sensors(world, TWO, "Drone2")
        runner = S.SkillRunner(MockVehicleAdapter(world), "Drone2", world.clock)
        for c in (S.TakeOffCommand(altitude_m=10), S.GoToWaypointCommand(Waypoint(80, -5, 10))):
            self.assertTrue(runner.run(c).ok)
        self.assertEqual([s.label for s in theirs.sightings()], ["T1"])
        self.assertEqual(mine.sightings(), ())

    def test_the_base_is_reached_through_another_drone(self):
        # Canonical base (-8, 0), 100 m: Drone1 at 150 m out reaches it only through Drone2.
        world = MockWorld(declared=["Drone1", "Drone2"])
        scene = MockVehicleAdapter(world)
        sensors = mock_sensors(world, TWO, "Drone1")
        scene.place_vehicle("Drone1", Position(150.0, 0.0, 0.0))
        scene.place_vehicle("Drone2", Position(70.0, 0.0, 0.0))
        self.assertTrue(sensors.base_link())
        scene.place_vehicle("Drone2", Position(0.0, 60.0, 0.0))
        self.assertFalse(sensors.base_link())

    def test_only_the_scenarios_drones(self):
        world = MockWorld(declared=["Drone1"])
        with self.assertRaises(ValueError):
            mock_sensors(world, ONE, "Drone7")
        with self.assertRaises(ValueError):
            mock_sensors(world, TWO, "Drone1")                          # Drone2 is not in the world

    def test_counting_starts_when_asked(self):
        world = MockWorld(declared=["Drone1"])
        runner = S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock)
        self.assertTrue(runner.run(S.TakeOffCommand(altitude_m=10)).ok)
        later = mock_sensors(world, ONE, "Drone1")                       # from now
        self.assertEqual(later.battery(), 100.0)
        world.clock.sleep(10.0)
        self.assertAlmostEqual(later.battery(), 100.0 - 10.0 * ONE.battery.hover_drain_per_s)


class MockTrajectoryUntilNowTests(unittest.TestCase):

    def test_mid_move_the_present_is_a_knot_and_after_it_is_not_added(self):
        world = MockWorld(declared=["Drone1"])
        self.assertEqual(len(mock_trajectories(world, until_now=True)["Drone1"].knots),
                         len(mock_trajectories(world)["Drone1"].knots))
        world.clock.sleep(5.0)
        now = mock_trajectories(world, until_now=True)["Drone1"].knots[-1]
        self.assertEqual((now.t, now.airborne), (5.0, False))


class BoundaryTests(unittest.TestCase):
    """AUV-06 6.2: the agent holds only readings; nothing it holds leads to ground truth."""

    def test_the_bundle_is_functions_and_a_name(self):
        world = MockWorld(declared=["Drone1"])
        sensors = mock_sensors(world, ONE, "Drone1")
        self.assertIsInstance(sensors, Sensors)
        for f in dataclasses.fields(sensors):
            value = getattr(sensors, f.name)
            with self.subTest(field=f.name):
                if f.name == "drone":
                    self.assertIsInstance(value, str)
                else:
                    # A plain function: no __self__ to lead back to a world object.
                    self.assertIsInstance(value, types.FunctionType)
                    self.assertFalse(hasattr(value, "__self__"))
        self.assertFalse(any(not f.name.startswith("_") and f.name not in
                             {"drone", "now", "own_state", "battery", "sightings", "base_link"}
                             for f in dataclasses.fields(Sensors)))

    def test_core_sensing_needs_nothing_from_the_simulator(self):
        path = os.path.join(ROOT, "agentic_uav", "core", "sensing.py")
        self.assertEqual(boundary_violations(path, "agentic_uav.core"), [])

    def test_the_agents_package_reaches_no_ground_truth(self):
        folder = os.path.join(ROOT, "agentic_uav", "agents")
        modules = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".py")]
        self.assertIn(os.path.join(folder, "__init__.py"), modules)
        for path in modules:
            with self.subTest(module=os.path.basename(path)):
                self.assertEqual(boundary_violations(path, "agentic_uav.agents"), [])

    def test_the_check_would_catch_a_breach(self):
        # It must not pass vacuously: each way of breaking the rule is caught.
        import shutil
        import tempfile
        folder = tempfile.mkdtemp()
        try:
            for source in ("from agentic_uav.simulator.mission_world import mock_sensors\n",
                           "from ..simulator import sensing\n",
                           "from ..core.scenario import Scenario\n",
                           "import agentic_uav.experiments.evaluation\n",
                           "def f(s):\n    return s.random_seed\n"):
                path = os.path.join(folder, "breach.py")
                with open(path, "w", encoding="utf-8") as h:
                    h.write(source)
                with self.subTest(source=source.strip()):
                    self.assertNotEqual(boundary_violations(path, "agentic_uav.agents"), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


FORBIDDEN_MODULES = ("agentic_uav.simulator", "agentic_uav.experiments")
FORBIDDEN_NAMES = {"Scenario", "TargetSpec", "place_targets", "MockWorld", "random_seed"}


def boundary_violations(path, package):
    """Every way the module at `path`, in `package`, reaches past the boundary."""
    with open(path, encoding="utf-8") as h:
        tree = ast.parse(h.read(), path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [(a.name, None) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:                       # relative: resolve against the package
                parts = package.split(".")
                module = ".".join(parts[:len(parts) - node.level + 1] + ([module] if module else []))
            imported = [(module, a.name) for a in node.names]
        else:
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                found.append(f"names {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
                found.append(f"reads .{node.attr}")
            continue
        for module, name in imported:
            if any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES):
                found.append(f"imports {module}")
            if name in FORBIDDEN_NAMES:
                found.append(f"imports {name}")
    return found


if __name__ == "__main__":
    unittest.main()
