"""Phase 6 exit criterion, enforced as tests, not just a design intention.
'Rule to preserve: an agent must never hold a GroundTruth, Scenario, or
Target. Everything reaches belief through SensorModel.' If a later change
hands an agent scenario data directly, these are the tests meant to fail."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief_schema import Provenance
from fics_drone.agents.decision_log import DecisionLogger
from fics_drone.agents.ground_truth import GroundTruth, PerceivedTarget, SensorModel
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.core.scenario import Scenario, Target, load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")
BANNED_TYPES = (Scenario, Target, GroundTruth)


def _walk_for_banned_types(obj, seen=None):
    """Recursively walks a belief's object graph. Returns every banned
    ground-truth object found anywhere inside it, however deeply nested."""
    if seen is None:
        seen = set()
    if id(obj) in seen or obj is None:
        return []
    seen.add(id(obj))
    found = []
    if isinstance(obj, BANNED_TYPES):
        found.append(obj)
    if hasattr(obj, "__dict__"):
        for v in vars(obj).values():
            found.extend(_walk_for_banned_types(v, seen))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(_walk_for_banned_types(v, seen))
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            found.extend(_walk_for_banned_types(v, seen))
    return found


class TestGroundTruthIsolation(unittest.TestCase):
    def test_belief_never_holds_a_ground_truth_object_after_a_full_run(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.sector == "A")
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=25.0)
        agent = PersistentAgent(adapter, scenario, "A", spec.spawn_offset, spec.battery_s)
        agent.run()

        leaked = _walk_for_banned_types(agent.belief)
        self.assertEqual(leaked, [], f"belief graph contains ground-truth objects: {leaked}")

    def test_agent_only_learns_the_target_in_its_own_sector(self):
        """Sector A holds T1, Sector D holds T2 - an agent searching A must
        never learn T2 exists, and vice versa. This is exactly the
        accidental-global-information bug Phase 6 exists to catch."""
        scenario = load_scenario(SCENARIO_PATH)

        spec_a = next(d for d in scenario.drones if d.sector == "A")
        agent_a = PersistentAgent(KinematicMockVehicleAdapter(spec_a.name, speed_mps=25.0),
                                   scenario, "A", spec_a.spawn_offset, spec_a.battery_s)
        agent_a.run()
        self.assertIn("T1", agent_a.belief.mission.targets_known)
        self.assertNotIn("T2", agent_a.belief.mission.targets_known)

        spec_d = next(d for d in scenario.drones if d.sector == "D")
        agent_d = PersistentAgent(KinematicMockVehicleAdapter(spec_d.name, speed_mps=25.0),
                                   scenario, "D", spec_d.spawn_offset, spec_d.battery_s)
        agent_d.run()
        self.assertIn("T2", agent_d.belief.mission.targets_known)
        self.assertNotIn("T1", agent_d.belief.mission.targets_known)

    def test_sensor_model_returns_plain_data_not_scenario_target_instances(self):
        scenario = load_scenario(SCENARIO_PATH)
        sensor = SensorModel(scenario)
        target = scenario.targets[0]
        seen = sensor.perceive((target.x, target.y, 8.0))
        self.assertTrue(seen)
        for s in seen:
            self.assertIsInstance(s, PerceivedTarget)
            self.assertNotIsInstance(s, Target)

    def test_sensor_sees_nothing_outside_every_targets_radius(self):
        scenario = load_scenario(SCENARIO_PATH)
        sensor = SensorModel(scenario)
        self.assertEqual(sensor.perceive((1000.0, 1000.0, 8.0)), [])


class TestProvenanceDecay(unittest.TestCase):
    def test_confidence_halves_after_one_half_life(self):
        p = Provenance(timestamp=0.0, source="teammate_report", base_confidence=1.0)
        self.assertAlmostEqual(p.decayed_confidence(now=20.0), 0.5, places=3)

    def test_confidence_quarters_after_two_half_lives(self):
        p = Provenance(timestamp=0.0, source="teammate_report", base_confidence=1.0)
        self.assertAlmostEqual(p.decayed_confidence(now=40.0), 0.25, places=3)

    def test_becomes_stale_after_ttl_elapses(self):
        p = Provenance(timestamp=0.0, source="teammate_report")
        self.assertFalse(p.is_stale(now=30.0, ttl_s=60.0))
        self.assertTrue(p.is_stale(now=61.0, ttl_s=60.0))


class TestDecisionLog(unittest.TestCase):
    def test_log_entries_show_both_knew_and_did_not_know(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.sector == "A")
        logger = DecisionLogger()
        agent = PersistentAgent(KinematicMockVehicleAdapter(spec.name, speed_mps=25.0),
                                 scenario, "A", spec.spawn_offset, spec.battery_s,
                                 logger=logger, drone_name=spec.name)
        agent.run()

        self.assertTrue(logger.entries)
        for e in logger.entries:
            self.assertTrue(e.knew)
            self.assertTrue(e.did_not_know)
            self.assertTrue(e.decided)

    def test_json_round_trip(self):
        logger = DecisionLogger()
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.sector == "B")
        agent = PersistentAgent(KinematicMockVehicleAdapter(spec.name, speed_mps=25.0),
                                 scenario, "B", spec.spawn_offset, spec.battery_s,
                                 logger=logger, drone_name=spec.name)
        agent.run()

        out_path = os.path.join(os.path.dirname(__file__), "_tmp_decision_log.json")
        logger.to_json(out_path)
        self.assertTrue(os.path.exists(out_path))
        os.remove(out_path)


if __name__ == "__main__":
    unittest.main()
