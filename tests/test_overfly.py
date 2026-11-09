"""NavRL steers only sideways at one height, so the agent supplies the vertical part: when a leg is blocked by trees it can
climb above the tallest blocker, cross, and come down. Mock-only."""

import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents import persistent_agent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.core.obstacles import BoxKeepOut, TreeObstacle
from fics_drone.core.scenario import load_scenario
from fics_drone.planners.overfly import detour_cost_s, overfly_altitude, overfly_cost_s
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


def tree(x, y, top, r=1.2, bottom=2.0):
    return TreeObstacle(x=x, y=y, z_bottom=bottom, z_top=top, trunk_r=r, crown_r=r, crown_from_frac=1.0)


class OverflyAltitudeTests(unittest.TestCase):
    def test_goes_just_above_the_tallest_blocker(self):
        z = overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 14), tree(20, 0, 20)], margin=0.5)
        self.assertEqual(z, 23.0)

    def test_a_tree_off_the_line_does_not_raise_it(self):
        z = overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 14), tree(20, 12, 25)], margin=0.5)
        self.assertEqual(z, 17.0)

    def test_another_trees_top_does_not_give_a_height_that_only_just_clears_the_blocker(self):
        # a 17.1 m tree off to the side makes 20.1 m a candidate; the 20 m tree on the line needs 23 m
        z = overfly_altitude((0, 0, 12), (0, -64, 12), [tree(0, -27, 20, r=2.0), tree(30, 0, 17.1)], margin=0.5)
        self.assertEqual(z, 23.0)

    def test_too_tall_gives_none(self):
        self.assertIsNone(overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 40)], margin=0.5, max_extra=15.0))

    def test_zero_limit_switches_it_off(self):
        self.assertIsNone(overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 14)], margin=0.5, max_extra=0.0))

    def test_a_zone_cannot_be_flown_over(self):
        self.assertIsNone(overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 14), BoxKeepOut(15, 20, -3, 3)], margin=0.5))

    def test_a_teammate_column_cannot_be_flown_over(self):
        mate = TreeObstacle(x=15, y=0, z_bottom=-1000.0, z_top=1000.0, trunk_r=6.5, crown_r=6.5, crown_from_frac=1.0)
        self.assertIsNone(overfly_altitude((0, 0, 8), (30, 0, 8), [tree(10, 0, 14), mate], margin=0.5))

    def test_a_climb_through_a_wide_crown_is_refused(self):
        # a tall tree beside the start whose crown (above 16 m) reaches over it: the straight climb would pass through the crown
        t = TreeObstacle(x=3.0, y=0.0, z_bottom=2.0, z_top=25.0, trunk_r=1.0, crown_r=5.0, crown_from_frac=0.6)
        self.assertIsNone(overfly_altitude((0, 0, 8), (30, 0, 8), [t, tree(15, 0, 14)], margin=0.5, max_extra=20.0))

    def test_cost_helpers(self):
        self.assertEqual(overfly_cost_s((0, 0, 8), (30, 0, 8), 23.0, 1.0), 30.0)
        self.assertAlmostEqual(detour_cost_s((0, 0, 8), [(15, 20, 8)], (30, 0, 8), 2.0), (2 * 25.0 - 30.0) / 2.0)


class AgentOverflyTests(unittest.TestCase):
    def _agent(self, trees):
        scenario = load_scenario(SCENARIO_PATH)
        scenario.obstacles = list(trees)
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name=spec.name)
        agent.belief.position = (0.0, 0.0, 8.0)
        return agent, adapter

    def test_with_no_way_round_the_aircraft_flies_over_and_lands_on_the_target_height(self):
        trees = [tree(15, 0, 20)]
        agent, adapter = self._agent(trees)
        agent.scenario.search_routes = [object()]           # the street branch, whose planner is patched below to find no way
        with mock.patch.object(persistent_agent, "plan_around", return_value=None):
            trace = []
            event = agent._guarded_fly((30.0, 0.0, 8.0), trace)
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("flew_over_tree", trace)
        self.assertNotIn("no_way_round", trace)
        self.assertLess(math.dist(adapter.get_position(), (30.0, 0.0, 8.0)), 1.5)

    def test_the_overfly_never_enters_the_tree(self):
        import threading
        import time
        t = tree(15, 0, 20)
        agent, adapter = self._agent([t])
        agent.scenario.search_routes = [object()]
        inside, stop = [], threading.Event()

        def watch():
            while not stop.is_set():
                x, y, z = adapter.get_position()
                if t.blocks_point(x, y, z, margin=0.0):
                    inside.append((x, y, z))
                time.sleep(0.005)

        threading.Thread(target=watch, daemon=True).start()
        with mock.patch.object(persistent_agent, "plan_around", return_value=None):
            agent._guarded_fly((30.0, 0.0, 8.0), [])
        stop.set()
        self.assertEqual(inside, [])

    def test_switched_off_it_is_blocked_as_before(self):
        agent, adapter = self._agent([tree(15, 0, 20)])
        agent.scenario.search_routes = [object()]
        trace = []
        with mock.patch.object(persistent_agent, "plan_around", return_value=None), \
                mock.patch.object(persistent_agent, "OVERFLY_MAX_EXTRA_M", 0.0):
            event = agent._guarded_fly((30.0, 0.0, 8.0), trace)
        self.assertEqual(event.value, "guardian_blocked")
        self.assertIn("no_way_round", trace)

    def test_a_cheap_detour_is_preferred_to_a_climb(self):
        agent, adapter = self._agent([tree(15, 0, 20)])
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 8.0), trace)
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("flew_round_tree", trace)
        self.assertNotIn("flew_over_tree", trace)

    def test_a_tree_too_tall_to_cross_is_still_flown_round(self):
        agent, adapter = self._agent([tree(15, 0, 60)])
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 8.0), trace)
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("flew_round_tree", trace)


if __name__ == "__main__":
    unittest.main()
