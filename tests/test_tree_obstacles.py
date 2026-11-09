"""Trees as obstacles: the keep-out shape, the guardian check, and what a leg planner is shown.

Found live on 2026-11-03: the sim's palms have no collision, so drones (and the lidar) pass through them; the agent has to be
told where they are.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.safety_guardian import Command, GuardianOutcome, SafetyGuardian, SafetyLimits
from fics_drone.core.obstacles import TreeObstacle
from fics_drone.core.scenario import load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
PALM = TreeObstacle(x=29.4, y=22.0, z_bottom=1.8, z_top=25.8)     # crown from 16.2 m up


def _guardian(trees):
    scenario = load_scenario(SCENARIO_PATH)
    scenario.obstacles = list(trees)
    return SafetyGuardian(limits=SafetyLimits.from_scenario(scenario))


def _belief():
    return Belief(self_state=SelfState(position=(0.0, 0.0, 12.0), elapsed_s=1.0, battery_s=300.0),
                  mission=MissionBelief(sector_id="A", search_queue=[]))


def _fly(x, y, z=12.0):
    return Command(kind="fly", target=(x, y, z), speed_mps=5.0, timeout_s=30.0, purpose="mission")


class TestTreeShape(unittest.TestCase):
    def test_at_cruise_height_only_the_trunk_counts(self):
        self.assertTrue(PALM.blocks_point(29.4, 22.5, 12.0))
        self.assertFalse(PALM.blocks_point(31.5, 22.0, 12.0))          # 2.1 m from the trunk, below the crown

    def test_high_up_the_crown_counts(self):
        self.assertTrue(PALM.blocks_point(33.0, 22.0, 20.0))           # 3.6 m from the trunk, in the crown
        self.assertFalse(PALM.blocks_point(35.0, 22.0, 20.0))          # beyond the crown

    def test_above_and_below_the_tree_is_clear(self):
        self.assertFalse(PALM.blocks_point(29.4, 22.0, 30.0))
        self.assertFalse(PALM.blocks_point(29.4, 22.0, 0.5))

    def test_a_segment_through_the_trunk_is_blocked_and_one_beside_it_is_not(self):
        self.assertTrue(PALM.blocks_segment((20.0, 22.0, 12.0), (40.0, 22.0, 12.0)))
        self.assertFalse(PALM.blocks_segment((20.0, 25.0, 12.0), (40.0, 25.0, 12.0)))

    def test_a_segment_that_starts_inside_can_leave(self):
        self.assertFalse(PALM.blocks_segment((29.4, 22.5, 12.0), (29.4, 30.0, 12.0)))

    def test_the_rectangle_a_planner_sees_matches_the_height(self):
        self.assertEqual(tuple(round(v, 6) for v in PALM.rect_at(12.0)), (28.2, 30.6, 20.8, 23.2))
        self.assertEqual(tuple(round(v, 6) for v in PALM.rect_at(20.0)), (24.4, 34.4, 17.0, 27.0))
        self.assertIsNone(PALM.rect_at(40.0))

    def test_rects_hug_the_circle_for_a_planner_that_knows_only_rectangles(self):
        rects = PALM.rects_at(20.0)
        self.assertEqual(PALM.rects_at(40.0), [])
        inside = lambda x, y: any(a <= x <= b and c <= y <= d for a, b, c, d in rects)
        # the corner of the one-square form is outside the circle (radius 5 at this height) and is not covered
        self.assertFalse(inside(PALM.x + 4.6, PALM.y + 4.6))
        # the centre and a point just inside the circle's edge are covered
        self.assertTrue(inside(PALM.x, PALM.y))
        self.assertTrue(inside(PALM.x + 4.9, PALM.y))
        self.assertTrue(inside(PALM.x + 3.0, PALM.y + 3.5))


class TestGuardianRefusesTrees(unittest.TestCase):
    def test_a_target_in_the_trunk_is_refused(self):
        e = _guardian([PALM]).evaluate(_fly(29.4, 22.3), _belief())
        self.assertEqual(e.outcome, GuardianOutcome.REJECT_AND_REPLAN)
        self.assertEqual(e.failed_checks, ["obstacles"])

    def test_a_path_through_the_trunk_is_refused_when_the_position_is_known(self):
        g = _guardian([PALM])
        e = g.evaluate(_fly(40.0, 22.0), _belief(), position_world=(20.0, 22.0, 12.0))
        self.assertEqual(e.failed_checks, ["obstacles"])
        self.assertIn("passes through the tree", e.reason)

    def test_a_path_that_misses_the_tree_is_approved(self):
        e = _guardian([PALM]).evaluate(_fly(40.0, 26.0), _belief(), position_world=(20.0, 26.0, 12.0))
        self.assertEqual(e.outcome, GuardianOutcome.APPROVE)

    def test_a_high_leg_over_the_trunk_but_through_the_crown_is_refused(self):
        e = _guardian([PALM]).evaluate(_fly(40.0, 22.0, 20.0), _belief(), position_world=(20.0, 22.0, 20.0))
        self.assertEqual(e.failed_checks, ["obstacles"])

    def test_with_no_trees_nothing_changes(self):
        e = _guardian([]).evaluate(_fly(29.4, 22.3), _belief())
        self.assertEqual(e.outcome, GuardianOutcome.APPROVE)


class TestAgentWithTrees(unittest.TestCase):
    def _agent(self, trees, name="Drone1"):
        scenario = load_scenario(SCENARIO_PATH)
        scenario.obstacles = list(trees)
        spec = next(d for d in scenario.drones if d.name == name)
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        return PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s,
                               drone_name=spec.name), adapter

    def test_a_planner_is_shown_the_trunk_at_the_aircrafts_height(self):
        agent, adapter = self._agent([PALM])
        agent.belief.position = (15.0, 15.0, 12.0)
        rects = [tuple(round(v, 6) for v in r) for r in agent._active_zone_rects()]
        rects = [r for r in rects if r[0] > 20.0]
        box = (min(r[0] for r in rects), max(r[1] for r in rects), min(r[2] for r in rects), max(r[3] for r in rects))
        self.assertEqual(tuple(round(v, 6) for v in box), (28.2, 30.6, 20.8, 23.2))

    def test_a_planner_is_not_shown_a_tree_far_beyond_its_sensor(self):
        agent, adapter = self._agent([PALM])
        agent.belief.position = (-40.0, -40.0, 12.0)
        self.assertEqual([r for r in agent._active_zone_rects() if 20.0 < r[0] < 40.0 and 15.0 < r[2] < 30.0], [])

    def test_a_whole_mission_flies_without_ever_entering_the_trunk(self):
        agent, adapter = self._agent([PALM])
        inside = []
        import threading
        import time
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                x, y, z = adapter.get_position()
                if PALM.blocks_point(x, y, z, margin=0.0):
                    inside.append((x, y, z))
                time.sleep(0.01)

        threading.Thread(target=watch, daemon=True).start()
        report = agent.run()
        stop.set()
        self.assertEqual(inside, [])
        self.assertTrue(any("done" in step for step in report.trace), report.trace)


class TestSearchLanesAvoidTrees(unittest.TestCase):
    """With the palm's whole leaf footprint as a keep-out, the first lane of Sector A starts under it. The agent plans its
    lanes around it, so the guardian never refuses three legs in a row and ends the mission (found live 2026-11-03)."""

    BIG_PALM = TreeObstacle(x=29.45, y=22.02, z_bottom=1.8, z_top=25.75, trunk_r=1.5, crown_r=5.67, crown_from_frac=0.28)

    def _agent(self):
        scenario = load_scenario(SCENARIO_PATH)
        scenario.obstacles = [self.BIG_PALM]
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        return PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s,
                               drone_name=spec.name, cruise_height=12.0), spec

    def test_no_leg_of_the_planned_search_enters_or_crosses_the_keep_out(self):
        agent, spec = self._agent()
        pts = [(leg.point[0] + spec.spawn_offset[0], leg.point[1] + spec.spawn_offset[1], leg.point[2] + spec.spawn_offset[2])
               for leg in agent.belief.mission.search_queue]
        self.assertGreater(len(pts), 10)
        previous = (spec.spawn_offset[0], spec.spawn_offset[1], 12.0)
        for p in pts:
            self.assertFalse(self.BIG_PALM.blocks_point(*p, margin=0.5), p)
            self.assertFalse(self.BIG_PALM.blocks_segment(previous, p, margin=0.5), (previous, p))
            previous = p

    def test_with_no_trees_the_queue_is_untouched(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        plain = PersistentAgent(KinematicMockVehicleAdapter("Drone1"), scenario, spec.sector, spec.spawn_offset,
                                spec.battery_s, drone_name="Drone1", cruise_height=12.0)
        agent, _ = self._agent()
        self.assertGreater(len(agent.belief.mission.search_queue), len(plain.belief.mission.search_queue) - 12)

    def test_a_whole_mission_with_the_big_keep_out_finishes_and_is_never_refused_for_a_tree(self):
        agent, spec = self._agent()
        report = agent.run()
        refused = [e for e in agent.guardian_log.entries if "obstacles" in e.failed_checks]
        self.assertEqual(refused, [], [e.reason for e in refused])
        self.assertTrue(any("done" in step for step in report.trace), report.trace)
        self.assertNotIn("mission_terminated", " ".join(report.trace))


class TestSearchLegsInsideZones(unittest.TestCase):
    """A zone over several lane waypoints must not make the guardian refuse three legs in a row and end the mission (found at
    scale, 2026-11-03)."""

    def _agent(self, zone):
        scenario = load_scenario(SCENARIO_PATH)
        scenario.no_fly_zones = list(scenario.no_fly_zones) + [zone]
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        return PersistentAgent(KinematicMockVehicleAdapter("Drone1", speed_mps=15.0), scenario, spec.sector, spec.spawn_offset,
                               spec.battery_s, drone_name="Drone1"), spec

    def test_a_zone_that_is_on_for_good_drops_the_legs_inside_it_and_the_mission_still_finishes(self):
        from fics_drone.core.scenario import NoFlyZone
        agent, spec = self._agent(NoFlyZone("PERM", 20.0, 40.0, 20.0, 32.0, active_from_s=0.0))   # the lower half of sector A
        report = agent.run()
        refused = [e for e in agent.guardian_log.entries if "restricted_zones" in e.failed_checks]
        self.assertEqual(refused, [], [e.reason for e in refused])
        self.assertTrue(any(step.startswith("dropped_leg_in_PERM") for step in report.trace))
        self.assertTrue(any("done" in step for step in report.trace), report.trace)

    def test_a_zone_that_ends_defers_the_legs_and_they_are_flown_after_it_does(self):
        from fics_drone.core.scenario import NoFlyZone
        agent, spec = self._agent(NoFlyZone("TEMP", 20.0, 40.0, 20.0, 32.0, active_from_s=0.0, active_until_s=3.0))
        report = agent.run()
        refused = [e for e in agent.guardian_log.entries if "restricted_zones" in e.failed_checks]
        self.assertEqual(refused, [], [e.reason for e in refused])
        self.assertTrue(any(step == "deferred_leg_in_TEMP" for step in report.trace), report.trace)
        self.assertFalse(any(step.startswith("dropped_leg_in_TEMP") for step in report.trace), report.trace)
        self.assertTrue(any("done" in step for step in report.trace), report.trace)


class TestBoxKeepOut(unittest.TestCase):
    BOX = None

    @classmethod
    def setUpClass(cls):
        from fics_drone.core.obstacles import BoxKeepOut
        cls.BOX = BoxKeepOut(10.0, 20.0, 10.0, 20.0)

    def test_a_line_through_the_box_is_blocked_and_one_beside_it_is_not(self):
        self.assertTrue(self.BOX.blocks_segment((0.0, 15.0, 8.0), (30.0, 15.0, 8.0)))
        self.assertFalse(self.BOX.blocks_segment((0.0, 25.0, 8.0), (30.0, 25.0, 8.0)))

    def test_the_detour_goes_round_and_never_enters(self):
        path = self.BOX.detour_path((0.0, 15.0, 8.0), (30.0, 15.0, 8.0), margin=0.5)
        pts = [(0.0, 15.0)] + [(x, y) for x, y, _ in path] + [(30.0, 15.0)]
        for p, q in zip(pts, pts[1:]):
            for i in range(0, 41):
                x, y = p[0] + (q[0] - p[0]) * i / 40, p[1] + (q[1] - p[1]) * i / 40
                self.assertFalse(self.BOX.blocks_point(x, y, 0.0, margin=0.5), (p, q, x, y))
        self.assertTrue(all(z == 8.0 for _, _, z in path))


class TestEveryLegIsRoutedRound(unittest.TestCase):
    def _agent(self, name="Drone1", zone=None):
        scenario = load_scenario(SCENARIO_PATH)
        if zone is not None:
            scenario.no_fly_zones = list(scenario.no_fly_zones) + [zone]
        spec = next(d for d in scenario.drones if d.name == name)
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        return PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name=spec.name), adapter

    def test_the_guardians_fallback_home_is_the_aircrafts_own_spawn_point(self):
        agent, _ = self._agent("Drone2")                    # spawns at world (0, 20)
        belief = _belief()
        belief.self_state.position = (5.0, 5.0, 12.0)
        self.assertEqual(agent.guardian._home_world(belief)[:2], (0.0, 20.0))

    def test_a_zone_that_is_on_between_the_aircraft_and_its_target_is_flown_round_with_no_interrupt(self):
        from fics_drone.core.scenario import NoFlyZone
        zone = NoFlyZone("MID", 5.0, 15.0, -3.0, 3.0, active_from_s=0.0)          # on the way out of home to the east
        agent, adapter = self._agent(zone=zone)
        agent.belief.position = (0.0, 0.0, 8.0)
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 8.0), trace)
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("flew_round_tree", trace)
        self.assertNotIn("zone_interrupt", trace)
        self.assertLess(math.dist(adapter.get_position(), (30.0, 0.0, 8.0)), 1.5)

    def test_a_teammate_parked_on_the_way_is_flown_round(self):
        from fics_drone.agents.belief_schema import Provenance, TeammateRecord
        agent, adapter = self._agent()
        agent.belief.position = (0.0, 0.0, 8.0)
        agent.belief.team.teammates["Drone2"] = TeammateRecord(name="Drone2", last_known_position=(15.0, 0.5, 0.0),
                                                                provenance=Provenance(timestamp=0.0, source="heartbeat"))
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 8.0), trace, purpose="home")
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("flew_round_tree", trace)


if __name__ == "__main__":
    unittest.main()
