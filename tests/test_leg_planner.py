"""A leg planner (NavRL, or a stand-in here) flies approved legs inside the mission stack.

The planner itself is replaced by small stand-ins so the tests need no torch: what is tested is the plumbing, that the
mock can fly on velocity commands, that the leg skill arrives, stops on the zone monitor and times out like
go_to_waypoint, and that an agent with a leg planner still flies a whole mission with the guardian in the loop.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.control.leg_planner_skill import fly_leg_with_planner
from fics_drone.core.scenario import load_scenario
from fics_drone.core.skill_result import SkillStatus
from fics_drone.experiments.experiment_config import ExperimentConfig, apply_zones
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


class StraightPlanner:
    """Heads straight for the goal at a fixed speed, ignores zones."""
    def __init__(self, speed=8.0):
        self.speed, self.legs, self.seen_rects = speed, [], []

    def begin_leg(self, start_xy, goal_xy):
        self.legs.append((tuple(start_xy), tuple(goal_xy)))
        return self

    def velocity(self, pos_xy, goal_xy, zone_rects):
        self.seen_rects.append(list(zone_rects))
        dx, dy = goal_xy[0] - pos_xy[0], goal_xy[1] - pos_xy[1]
        d = math.hypot(dx, dy) or 1.0
        return dx / d * self.speed, dy / d * self.speed


class TestMockVelocityMode(unittest.TestCase):
    def test_moves_at_the_commanded_velocity_then_hovers(self):
        import time
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 0.0))
        adapter.start_velocity(10.0, 0.0, 0.0)
        time.sleep(0.5)
        x, y, z = adapter.get_position()
        self.assertAlmostEqual(x, 5.0, delta=1.0)
        self.assertAlmostEqual(adapter.get_speed(), 10.0)
        adapter.start_hover()
        stopped_at = adapter.get_position()
        time.sleep(0.2)
        self.assertEqual(adapter.get_position(), stopped_at)
        self.assertEqual(adapter.get_speed(), 0.0)

    def test_a_move_command_after_a_velocity_command_takes_over(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 0.0), speed_mps=50.0)
        adapter.start_velocity(1.0, 0.0, 0.0)
        adapter.start_move_to(0.0, 10.0, 0.0)
        import time
        time.sleep(0.5)
        self.assertAlmostEqual(adapter.get_position()[1], 10.0, delta=0.01)


class TestLegSkill(unittest.TestCase):
    def test_arrives_and_reports_success(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        planner = StraightPlanner(speed=10.0)
        result = fly_leg_with_planner(adapter, 10.0, 0.0, 12.0, planner, lambda: [], timeout_s=10.0)
        self.assertEqual(result.status, SkillStatus.SUCCESS, result.error)
        self.assertLess(math.dist(adapter.get_position(), (10.0, 0.0, 12.0)), 1.5)
        self.assertEqual(planner.legs[0][1], (10.0, 0.0))

    def test_world_coordinates_include_the_spawn_offset(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        planner = StraightPlanner(speed=10.0)
        fly_leg_with_planner(adapter, 6.0, 0.0, 12.0, planner, lambda: [], offset_xy=(0.0, 20.0), timeout_s=10.0)
        self.assertEqual(planner.legs[0], ((0.0, 20.0), (6.0, 20.0)))

    def test_the_planner_is_shown_the_zones_given(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        planner = StraightPlanner(speed=10.0)
        fly_leg_with_planner(adapter, 6.0, 0.0, 12.0, planner, lambda: [(1.0, 2.0, 3.0, 4.0)], timeout_s=10.0)
        self.assertEqual(planner.seen_rects[0], [(1.0, 2.0, 3.0, 4.0)])

    def test_the_zone_monitor_stops_the_leg(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        result = fly_leg_with_planner(adapter, 40.0, 0.0, 12.0, StraightPlanner(speed=10.0), lambda: [],
                                      timeout_s=10.0, interrupt=lambda pos: pos[0] > 5.0)
        self.assertEqual(result.status, SkillStatus.INTERRUPTED)
        self.assertEqual(adapter.get_speed(), 0.0)

    def test_gives_up_after_the_timeout(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        result = fly_leg_with_planner(adapter, 100.0, 0.0, 12.0, StraightPlanner(speed=1.0), lambda: [], timeout_s=0.6)
        self.assertEqual(result.status, SkillStatus.TIMEOUT)

    def test_a_climb_with_no_horizontal_distance_never_asks_the_planner(self):
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 0.0))
        planner = StraightPlanner(speed=10.0)
        result = fly_leg_with_planner(adapter, 0.0, 0.0, 4.0, planner, lambda: [], timeout_s=10.0)
        self.assertEqual(result.status, SkillStatus.SUCCESS, result.error)
        self.assertEqual(planner.seen_rects, [])

    def test_a_non_finite_velocity_holds_position(self):
        class NotANumber(StraightPlanner):
            def velocity(self, *a):
                return float("nan"), float("nan")
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        result = fly_leg_with_planner(adapter, 10.0, 0.0, 12.0, NotANumber(), lambda: [], timeout_s=0.8)
        self.assertEqual(result.status, SkillStatus.TIMEOUT)
        self.assertEqual(adapter.get_position(), (0.0, 0.0, 12.0))

    def test_a_planner_that_raises_is_a_failed_leg_not_a_crash(self):
        class Broken(StraightPlanner):
            def velocity(self, *a):
                raise RuntimeError("policy failed")
        adapter = KinematicMockVehicleAdapter("D", start_position=(0.0, 0.0, 12.0))
        result = fly_leg_with_planner(adapter, 10.0, 0.0, 12.0, Broken(), lambda: [], timeout_s=5.0)
        self.assertEqual(result.status, SkillStatus.FAILED)
        self.assertIn("policy failed", result.error)


class TestOnePlannerSharedByTwoDrones(unittest.TestCase):
    def test_each_leg_keeps_its_own_state(self):
        """Found with the real NavRL planner: a planner object shared by four drones stored the current leg direction,
        so each drone steered with another drone's."""
        class _Dir:
            def __init__(self, dx, dy):
                self.dx, self.dy = dx, dy

            def velocity(self, pos_xy, goal_xy, zone_rects):
                d = math.hypot(self.dx, self.dy) or 1.0
                return self.dx / d * 5.0, self.dy / d * 5.0

        class Stateful:
            def begin_leg(self, start_xy, goal_xy):
                return _Dir(goal_xy[0] - start_xy[0], goal_xy[1] - start_xy[1])

        planner = Stateful()
        east = planner.begin_leg((0.0, 0.0), (10.0, 0.0))
        north = planner.begin_leg((0.0, 0.0), (0.0, 10.0))
        self.assertEqual(east.velocity(None, None, []), (5.0, 0.0))
        self.assertEqual(north.velocity(None, None, []), (0.0, 5.0))


class TestAgentWithLegPlanner(unittest.TestCase):
    def _agent(self, planner, scenario=None):
        scenario = scenario or load_scenario(SCENARIO_PATH)
        spec = scenario.drones[0]
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        return PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name=spec.name,
                               leg_planner=planner, leg_timeout_s=30.0), adapter

    def test_a_whole_solo_mission_is_flown_by_the_planner(self):
        planner = StraightPlanner(speed=15.0)
        agent, _ = self._agent(planner)
        report = agent.run()
        self.assertGreater(len(planner.legs), 3)                 # the sector legs went through the planner
        self.assertTrue(any(step == "skill_succeeded->done" or "done" in step for step in report.trace), report.trace)

    def test_active_zones_reach_the_planner_in_world_coordinates(self):
        scenario = apply_zones(load_scenario(SCENARIO_PATH), "appear", appear_s=0.0)   # on from the start
        planner = StraightPlanner(speed=15.0)
        agent, _ = self._agent(planner, scenario)
        agent.run()
        self.assertTrue(any((24.0, 40.0, 24.0, 40.0) in rects for rects in planner.seen_rects))

    def test_without_a_planner_nothing_changes(self):
        agent, _ = self._agent(None)
        self.assertIsNone(agent.leg_planner)


class TestConfig(unittest.TestCase):
    def test_leg_planner_choices(self):
        ExperimentConfig("x", leg_planner="navrl").validate()
        with self.assertRaises(ValueError):
            ExperimentConfig("x", leg_planner="bogus").validate()
        with self.assertRaises(ValueError):
            ExperimentConfig("x", leg_planner="navrl", policy="scripted").validate()

    def test_zone_speed_scale_slows_a_drifting_zone(self):
        base = load_scenario(SCENARIO_PATH)
        fast = [z for z in apply_zones(base, "drift").no_fly_zones if z.vx][0]
        slow = [z for z in apply_zones(base, "drift", zone_speed_scale=0.25).no_fly_zones if z.vx][0]
        self.assertAlmostEqual(slow.vx, fast.vx * 0.25)


if __name__ == "__main__":
    unittest.main()
