"""Phase 11 tests. Every phase so far trusted the policy - this is the proof
that something else now catches it when a command shouldn't fly. The
catalogue coverage test is the real exit criterion: every one of 13 unsafe
commands is caught by its OWN intended check, not incidentally by another
one, which is what makes the catalogue a test of the checks rather than a
test of the envelope as a whole.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.safety_guardian import (
    Command, FallbackAction, GuardianOutcome, SafetyGuardian, SafetyLimits, Severity,
)
from fics_drone.agents.unsafe_injection import CATALOGUE, belief_for_case
from fics_drone.core.scenario import load_scenario

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


def _safe_belief():
    return Belief(self_state=SelfState(position=(10.0, 10.0, 8.0), elapsed_s=0.0, battery_s=100.0),
                   mission=MissionBelief(sector_id="A", search_queue=[]))


def _guardian():
    return SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)))


def _safe_command():
    return Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)


class TestCatalogueCoverage(unittest.TestCase):
    def test_every_unsafe_case_is_caught_by_its_own_intended_check(self):
        for case in CATALOGUE:
            guardian = _guardian()
            evaluation = guardian.evaluate(case.build(), belief_for_case(case.name))
            self.assertIn(case.expects_check, evaluation.failed_checks,
                           f"{case.name} was not caught by {case.expects_check}")

    def test_no_unsafe_command_is_ever_executed_unmodified(self):
        """APPROVE (the only outcome meaning "flown exactly as proposed") must
        never happen when any check failed."""
        for case in CATALOGUE:
            guardian = _guardian()
            evaluation = guardian.evaluate(case.build(), belief_for_case(case.name))
            if evaluation.outcome == GuardianOutcome.APPROVE:
                self.assertEqual(evaluation.failed_checks, [])


class TestCleanApproval(unittest.TestCase):
    def test_a_fully_safe_command_is_approved_unchanged(self):
        guardian = _guardian()
        evaluation = guardian.evaluate(_safe_command(), _safe_belief())
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE)
        self.assertEqual(evaluation.command, _safe_command())
        self.assertEqual(evaluation.failed_checks, [])


class TestNarrowing(unittest.TestCase):
    def test_altitude_below_floor_is_clamped_not_rejected(self):
        guardian = _guardian()
        cmd = Command(kind="fly", target=(10.0, 10.0, 1.0), speed_mps=5.0, timeout_s=30.0)
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE_WITH_MODIFICATION)
        self.assertEqual(evaluation.command.target[2], guardian.limits.altitude_floor_m)

    def test_excessive_speed_is_clamped_to_the_limit(self):
        guardian = _guardian()
        cmd = Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=999.0, timeout_s=30.0)
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE_WITH_MODIFICATION)
        self.assertEqual(evaluation.command.speed_mps, guardian.limits.max_speed_mps)

    def test_zero_timeout_is_clamped_up_to_the_minimum(self):
        guardian = _guardian()
        cmd = Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=0.0)
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE_WITH_MODIFICATION)
        self.assertEqual(evaluation.command.timeout_s, guardian.limits.min_timeout_s)

    def test_a_hard_violation_is_never_narrowed(self):
        guardian = _guardian()
        cmd = Command(kind="fly", target=(float("nan"), 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertEqual(evaluation.outcome, GuardianOutcome.REJECT_AND_REPLAN)


class TestPurposeScoping(unittest.TestCase):
    def test_battery_reserve_does_not_block_a_home_purpose_command(self):
        guardian = _guardian()
        belief = _safe_belief()
        belief.self_state.elapsed_s = 95.0  # 5% remaining, well under the 10% reserve
        cmd = Command(kind="fly", target=(0.0, 0.0, 8.0), speed_mps=5.0, timeout_s=30.0, purpose="home")
        evaluation = guardian.evaluate(cmd, belief)
        self.assertNotIn("battery_reserve", evaluation.failed_checks)

    def test_battery_reserve_blocks_the_same_shortage_for_a_mission_purpose_command(self):
        guardian = _guardian()
        belief = _safe_belief()
        belief.self_state.elapsed_s = 95.0
        cmd = Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0, purpose="mission")
        evaluation = guardian.evaluate(cmd, belief)
        self.assertIn("battery_reserve", evaluation.failed_checks)


class TestEscalation(unittest.TestCase):
    def test_three_consecutive_hard_rejections_escalate(self):
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=3, max_consecutive_interventions=99)
        belief = _safe_belief()
        bad = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        for _ in range(2):
            evaluation = guardian.evaluate(bad, belief)
            self.assertEqual(evaluation.outcome, GuardianOutcome.REJECT_AND_REPLAN)
        evaluation = guardian.evaluate(bad, belief)
        self.assertEqual(evaluation.outcome, GuardianOutcome.EXECUTE_SAFE_FALLBACK)

    def test_alternating_reject_and_narrow_still_escalates_via_interventions(self):
        """The evasion FICS's own build found: counting consecutive REJECTIONS
        alone lets a policy alternate reject/narrow forever and never trip it,
        since a narrowed command resets that counter. consecutive_interventions
        only resets on a clean APPROVE, so it still catches this."""
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=99, max_consecutive_interventions=5)
        belief = _safe_belief()
        reject_cmd = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        narrow_cmd = Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=999.0, timeout_s=30.0)
        outcomes = []
        for i in range(5):
            cmd = reject_cmd if i % 2 == 0 else narrow_cmd
            outcomes.append(guardian.evaluate(cmd, belief).outcome)
        self.assertEqual(outcomes[-1], GuardianOutcome.EXECUTE_SAFE_FALLBACK)
        self.assertNotIn(GuardianOutcome.REJECT_AND_REPLAN, [outcomes[-1]])

    def test_a_clean_approval_resets_both_counters(self):
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=3, max_consecutive_interventions=99)
        belief = _safe_belief()
        bad = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        guardian.evaluate(bad, belief)
        guardian.evaluate(bad, belief)
        guardian.evaluate(_safe_command(), belief)  # clean approval - resets
        self.assertEqual(guardian.consecutive_rejections, 0)
        evaluation = guardian.evaluate(bad, belief)
        self.assertEqual(evaluation.outcome, GuardianOutcome.REJECT_AND_REPLAN)  # not yet escalated again

    def test_escalation_fallback_is_return_home_when_not_already_home(self):
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=1, max_consecutive_interventions=99)
        belief = _safe_belief()  # position (10, 10, 8) - not home
        bad = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        evaluation = guardian.evaluate(bad, belief)
        self.assertEqual(evaluation.fallback, FallbackAction.RETURN_HOME)

    def test_escalation_fallback_is_land_when_already_home(self):
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=1, max_consecutive_interventions=99)
        belief = _safe_belief()
        belief.self_state.position = (0.0, 0.0, 8.0)  # already home
        bad = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        evaluation = guardian.evaluate(bad, belief)
        self.assertEqual(evaluation.fallback, FallbackAction.LAND_AT_SAFE_LOCATION)

    def test_once_escalated_the_guardian_ignores_the_next_proposal_entirely(self):
        """Sticky on purpose - a policy that's unsafe in a DIFFERENT way on its
        very next proposal must not undo the fallback already in progress."""
        guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)),
                                   max_consecutive_rejections=1, max_consecutive_interventions=99)
        belief = _safe_belief()
        bad = Command(kind="fly", target=(float("nan"), 0.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        guardian.evaluate(bad, belief)  # escalates -> RETURN_HOME
        belief.self_state.position = (0.0, 0.0, 8.0)  # the agent actually flew home
        evaluation = guardian.evaluate(_safe_command(), belief)  # a perfectly safe proposal now
        self.assertEqual(evaluation.outcome, GuardianOutcome.EXECUTE_SAFE_FALLBACK)
        self.assertEqual(evaluation.fallback, FallbackAction.LAND_AT_SAFE_LOCATION)


class TestConflictingCommands(unittest.TestCase):
    def test_a_second_evaluate_without_completing_the_first_is_rejected(self):
        guardian = _guardian()
        belief = _safe_belief()
        first = guardian.evaluate(_safe_command(), belief)
        self.assertEqual(first.outcome, GuardianOutcome.APPROVE)
        second = guardian.evaluate(_safe_command(), belief)
        self.assertIn("conflicting_commands", second.failed_checks)

    def test_command_completed_clears_the_in_flight_window(self):
        guardian = _guardian()
        belief = _safe_belief()
        guardian.evaluate(_safe_command(), belief)
        guardian.command_completed()
        second = guardian.evaluate(_safe_command(), belief)
        self.assertEqual(second.outcome, GuardianOutcome.APPROVE)


class TestDeterminism(unittest.TestCase):
    def test_same_command_and_belief_always_produce_the_same_verdict(self):
        belief = _safe_belief()
        cmd = Command(kind="fly", target=(5000.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        results = [_guardian().evaluate(cmd, belief).outcome for _ in range(20)]
        self.assertEqual(len(set(results)), 1)

    def test_never_holds_a_reference_to_scenario_ground_truth(self):
        """The guardian reads the command and the belief, never the scenario's
        own Target objects or any ground-truth structure - it must stay this
        way for it to remain policy-independent and attackable only through
        what it's actually handed."""
        from fics_drone.core.scenario import Target
        guardian = _guardian()
        for value in vars(guardian).values():
            self.assertNotIsInstance(value, Target)
        for value in vars(guardian.limits).values():
            if isinstance(value, list):
                for item in value:
                    self.assertNotIsInstance(item, Target)


class TestSeparationAndLandingSite(unittest.TestCase):
    def test_a_waypoint_near_a_known_teammate_is_rejected(self):
        guardian = _guardian()
        belief = _safe_belief()
        from fics_drone.agents.belief_schema import Provenance, TeammateRecord
        belief.team.teammates["Drone2"] = TeammateRecord(
            name="Drone2", last_known_position=(10.0, 10.0, 8.0),
            provenance=Provenance(timestamp=0.0, source="heartbeat"))
        cmd = Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0, purpose="mission")
        evaluation = guardian.evaluate(cmd, belief)
        self.assertIn("separation", evaluation.failed_checks)

    def test_landing_inside_a_no_fly_zone_is_rejected(self):
        guardian = _guardian()
        cmd = Command(kind="land", target=(0.0, 50.0, 0.0))  # inside NFZ1
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertIn("landing_site", evaluation.failed_checks)

    def test_landing_outside_any_no_fly_zone_is_fine(self):
        guardian = _guardian()
        cmd = Command(kind="land", target=(10.0, 10.0, 0.0), timeout_s=30.0)
        evaluation = guardian.evaluate(cmd, _safe_belief())
        self.assertNotIn("landing_site", evaluation.failed_checks)


class TestGuardianLog(unittest.TestCase):
    def test_intervention_rate_counts_everything_that_is_not_a_clean_approve(self):
        from fics_drone.experiments.guardian_log import GuardianLog
        guardian = _guardian()
        belief = _safe_belief()
        log = GuardianLog()
        evaluation = guardian.evaluate(_safe_command(), belief)
        log.record(0, _safe_command(), evaluation)
        guardian.command_completed()
        bad = Command(kind="fly", target=(float("nan"), 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)
        evaluation = guardian.evaluate(bad, belief)
        log.record(1, bad, evaluation)
        self.assertEqual(log.intervention_rate, 0.5)

    def test_format_summary_includes_the_headline_counts(self):
        from fics_drone.experiments.guardian_log import GuardianLog
        guardian = _guardian()
        log = GuardianLog()
        evaluation = guardian.evaluate(_safe_command(), _safe_belief())
        log.record(0, _safe_command(), evaluation)
        summary = log.format_summary()
        self.assertIn("commands evaluated", summary)
        self.assertIn("approved unchanged", summary)


if __name__ == "__main__":
    unittest.main()
