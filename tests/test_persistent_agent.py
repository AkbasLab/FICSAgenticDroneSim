"""Phase 5 tests. The policy (a pure function of belief+event) is tested in
isolation - fast, no adapter, no real time. Two slower integration tests run
the full agent against the kinematic mock to prove the whole loop actually
flies and lands.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.guardian import Guardian
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.search_policy import SearchAgentPolicy
from fics_drone.core.scenario import NoFlyZone, load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


class TestSearchPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = SearchAgentPolicy()

    def _belief(self, phase, position=(0, 0, 0), elapsed_s=0.0, battery_s=100.0,
                nav_retries=0, search_queue=None):
        b = Belief(self_state=SelfState(position=position, elapsed_s=elapsed_s, battery_s=battery_s,
                                         phase=phase, nav_retries=nav_retries),
                   mission=MissionBelief(sector_id="A", search_queue=search_queue or []))
        return b

    def test_task_assigned_leads_to_takeoff(self):
        b = self._belief("pre_takeoff")
        objective, phase = self.policy.decide(b, ReplanEvent.TASK_ASSIGNED)
        self.assertEqual(objective, Objective.TAKE_OFF)
        self.assertEqual(phase, "climbing")

    def test_critical_battery_forces_return_home_while_searching(self):
        b = self._belief("searching", elapsed_s=95.0, battery_s=100.0)  # 5% remaining < 12% critical
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(objective, Objective.RETURN_HOME)
        self.assertEqual(phase, "returning")

    def test_critical_battery_does_not_re_trigger_once_already_returning(self):
        b = self._belief("returning", elapsed_s=95.0, battery_s=100.0)
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(objective, Objective.LAND)  # proceeds normally, not stuck re-deciding RETURN_HOME

    def test_target_detected_leads_to_report_then_return_home(self):
        b = self._belief("searching")
        objective, phase = self.policy.decide(b, ReplanEvent.TARGET_DETECTED)
        self.assertEqual(objective, Objective.REPORT)
        b.phase = phase
        objective, phase = self.policy.decide(b, ReplanEvent.REPORT_SENT)
        self.assertEqual(objective, Objective.RETURN_HOME)

    def test_empty_search_queue_leads_to_listening_first(self):
        """Phase 7: an agent with nothing left to search lingers a few rounds
        for a late teammate broadcast before heading home, instead of
        leaving the instant its own work is done."""
        b = self._belief("searching", search_queue=[])
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(objective, Objective.LISTEN)
        self.assertEqual(phase, "listening")

    def test_listening_checks_for_orphans_after_enough_rounds(self):
        """Phase 9: listening exhausted now checks for a teammate's orphaned
        task before heading home, instead of going straight to RETURN_HOME."""
        b = self._belief("listening")
        b.self_state.listen_rounds = self.policy.listen_rounds
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(objective, Objective.CHECK_FOR_ORPHANS)
        self.assertEqual(phase, "checking_for_orphans")

    def test_check_for_orphans_with_nothing_found_returns_home(self):
        b = self._belief("checking_for_orphans")
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(objective, Objective.RETURN_HOME)
        self.assertEqual(phase, "returning")

    def test_check_for_orphans_finding_one_resumes_searching(self):
        b = self._belief("checking_for_orphans")
        objective, phase = self.policy.decide(b, ReplanEvent.NEW_TASK_ASSIGNED)
        self.assertEqual(objective, Objective.SEARCH_SECTOR)
        self.assertEqual(phase, "searching")

    def test_nav_retries_exceeded_aborts_to_return_home(self):
        b = self._belief("searching", nav_retries=SearchAgentPolicy().max_nav_retries)
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_FAILED)
        self.assertEqual(objective, Objective.RETURN_HOME)

    def test_nav_failure_under_retry_limit_tries_again(self):
        b = self._belief("searching", nav_retries=0)
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_FAILED)
        self.assertEqual(objective, Objective.SEARCH_SECTOR)
        self.assertEqual(phase, "searching")

    def test_returning_never_loops_forever_on_repeated_failure(self):
        """The real bug this caught live: retrying RETURN_HOME when the
        objective that just failed WAS RETURN_HOME degenerated into the
        policy returning the exact same (RETURN_HOME, "returning") forever,
        with no actual exit - 3 of 4 drones completed a real mission, the
        4th spun on this transition indefinitely with no error. Once
        retries are exhausted, the agent must land in place, never keep
        retrying the one thing that's already failing."""
        b = self._belief("returning", nav_retries=SearchAgentPolicy().max_nav_retries)
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_FAILED)
        self.assertEqual(objective, Objective.LAND)
        self.assertEqual(phase, "landing")

    def test_returning_retries_before_giving_up(self):
        b = self._belief("returning", nav_retries=0)
        objective, phase = self.policy.decide(b, ReplanEvent.SKILL_FAILED)
        self.assertEqual(objective, Objective.RETURN_HOME)
        self.assertEqual(phase, "returning")

    def test_guardian_blocked_leg_does_not_count_as_a_nav_retry(self):
        b = self._belief("searching", nav_retries=0)
        objective, phase = self.policy.decide(b, ReplanEvent.GUARDIAN_BLOCKED)
        self.assertEqual(objective, Objective.SEARCH_SECTOR)
        self.assertEqual(b.nav_retries, 0)  # policy itself never mutates belief


class TestGuardian(unittest.TestCase):
    def test_blocks_a_point_inside_a_no_fly_zone(self):
        zone = NoFlyZone(id="Z1", x_min=0, x_max=10, y_min=0, y_max=10)
        guardian = Guardian([zone])
        allowed, reason = guardian.check((5.0, 5.0, 8.0))
        self.assertFalse(allowed)
        self.assertIn("Z1", reason)

    def test_allows_a_clear_point(self):
        zone = NoFlyZone(id="Z1", x_min=0, x_max=10, y_min=0, y_max=10)
        guardian = Guardian([zone])
        allowed, reason = guardian.check((50.0, 50.0, 8.0))
        self.assertTrue(allowed)


class TestPersistentAgentIntegration(unittest.TestCase):
    def test_agent_finds_target_and_completes_in_sector_with_a_target(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.sector == "A")  # A has target T1
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=25.0)
        agent = PersistentAgent(adapter, scenario, "A", spec.spawn_offset, spec.battery_s)
        report = agent.run()

        self.assertEqual(report.target_found, "T1")
        self.assertEqual(report.trace[-1], "skill_succeeded->done")
        self.assertIn("target_detected->report", report.trace)
        self.assertIn("report_sent->return_home", report.trace)

    def test_agent_completes_without_a_target_in_sector_without_one(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.sector == "B")  # B has no target
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=25.0)
        agent = PersistentAgent(adapter, scenario, "B", spec.spawn_offset, spec.battery_s)
        report = agent.run()

        self.assertIsNone(report.target_found)
        self.assertEqual(report.trace[-1], "skill_succeeded->done")
        self.assertNotIn("target_detected->report", report.trace)


if __name__ == "__main__":
    unittest.main()
