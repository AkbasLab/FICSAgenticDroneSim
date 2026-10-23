#!/usr/bin/env python3
"""Tests for the rule-based policy: one drone, one search task, each step decided as it goes.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-06, 5.3 lists what the deterministic agent must do: accept a search task,
navigate to the sector, search it, report, return home, react to low battery,
recover from a failed navigation skill. Each is flown here on the mock, from
nothing but a task string, and judged by Phase 4's evaluator -- including the
runs meant to go wrong, where what is tested is that the agent noticed and
decided sensibly, with its reason in the trace.
"""

import dataclasses
import json
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.decision import DecisionKind  # noqa: E402
from agentic_uav.agents.drone_agent import DroneAgent  # noqa: E402
from agentic_uav.agents.rule_policy import MAX_RETRIES, RulePolicy, Stage, remaining_along  # noqa: E402
from agentic_uav.agents.validation import Verdict, validate  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.core.models import PrimitiveKind  # noqa: E402
from agentic_uav.core.scenario import BatterySpec  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.evaluation import evaluate  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import mock_trajectories  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

BASE = scenarios.load_scenario("search_relay_001")


def single(sector, **changes):
    """The canonical mission for one drone and one sector."""
    return dataclasses.replace(BASE, vehicles=BASE.vehicles[:1],
                               sectors=tuple(s for s in BASE.sectors if s.id == sector), **changes)


def fly(scenario, task, prepare=None, validator=validate):
    world = MockWorld(declared=["Drone1"])
    if prepare:
        prepare(world)
    executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
    out = {}

    def body():
        with world.clock.participate():
            agent = DroneAgent(scenario.brief(), mock_sensors(world, scenario, "Drone1"), executor,
                               RulePolicy(), validator=validator)
            agent.assign(task)
            agent.run(max_s=2000)
            out["agent"] = agent

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    executor.close()
    report = evaluate(scenario, mock_trajectories(world, ["Drone1"]), 0.0, world.clock.now(),
                      contacts=world.contacts())
    return out["agent"], report, world


def started(agent):
    return [e.decision.command.skill.value for e in agent.trace
            if e.decision.kind is DecisionKind.START and e.action.startswith(("started", "aborted"))]


def failing(report):
    return [c.id for c in report.criteria if not c.passed]


class NominalTests(unittest.TestCase):

    def test_given_only_a_task_it_completes_it(self):
        agent, report, _ = fly(single("S1"), "search S1")
        self.assertTrue(agent.finished)
        self.assertTrue(report.success, report.summary())
        self.assertEqual(started(agent), ["TAKE_OFF", "SEARCH_REGION", "FOLLOW_WAYPOINTS", "LAND"])
        # No preflight list: each skill was chosen in answer to the event before it.
        for entry in agent.trace:
            if entry.decision.kind is DecisionKind.START:
                triggers = {e.trigger for e in entry.events}
                self.assertTrue(triggers & {Trigger.TASK_ASSIGNED, Trigger.SKILL_SUCCEEDED}, entry.as_json())
        self.assertEqual(agent.belief.mission.progress["stage"], "done")
        self.assertEqual(agent.belief.local_map.searched_regions, [single("S1").sectors[0].region])

    def test_round_the_zone_out_of_range_and_reported_on_the_way_home(self):
        # S3 lies beyond R1 and beyond the base's 100 m radio.
        agent, report, _ = fly(single("S3"), "search S3")
        self.assertTrue(report.success, report.summary())
        self.assertEqual(started(agent), ["TAKE_OFF", "FOLLOW_WAYPOINTS", "SEARCH_REGION", "FOLLOW_WAYPOINTS", "LAND"])
        search_end = next(e.at for e in agent.trace if e.decision.objective == "return home and report")
        for r in report.facts.reports:
            self.assertGreater(r.reported_at, search_end)       # only once back in range
        self.assertEqual(report.criterion("C4").measured, 0)

    def test_deterministic(self):
        first, _, _ = fly(single("S1"), "search S1")
        second, _, _ = fly(single("S1"), "search S1")
        self.assertEqual(json.dumps([e.as_json() for e in first.trace], sort_keys=True, default=str),
                         json.dumps([e.as_json() for e in second.trace], sort_keys=True, default=str))

    def test_a_task_it_does_not_know(self):
        for task in ("patrol S9", "patrol S1", "search S9", "search"):
            with self.subTest(task=task):
                agent, _, world = fly(single("S1"), task)
                self.assertEqual(len(agent.trace), 1)
                self.assertIn("not a task this policy knows", agent.trace[0].decision.reason)
                self.assertFalse(mock_trajectories(world)["Drone1"].knots[-1].airborne)


class RecoveryTests(unittest.TestCase):

    def test_a_search_that_fails_once_is_tried_again(self):
        def once(world):
            world.faults.raise_times[("Drone1", PrimitiveKind.MOVE_TO_POSITION)] = 1
        agent, report, _ = fly(single("S1"), "search S1", once)
        self.assertTrue(report.success, report.summary())
        retry = [e for e in agent.trace if e.decision.reason.startswith("retry 1")]
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0].events[0].trigger, Trigger.SKILL_FAILED)
        self.assertEqual(retry[0].decision.command.skill.value, "SEARCH_REGION")

    def test_a_transit_that_fails_once_is_replanned_from_where_it_is(self):
        def once(world):
            world.faults.raise_times[("Drone1", PrimitiveKind.MOVE_TO_POSITION)] = 1
        agent, report, _ = fly(single("S3"), "search S3", once)
        self.assertTrue(report.success, report.summary())
        retry = [e for e in agent.trace if e.decision.reason.startswith("retry 1")]
        self.assertEqual(retry[0].decision.objective, "reach S3")

    def test_a_fault_that_does_not_clear_ends_in_landing_with_the_reason(self):
        def broken(world):
            world.faults.raise_on[("Drone1", PrimitiveKind.MOVE_TO_POSITION)] = "motor fault"
        agent, report, _ = fly(single("S1"), "search S1", broken)
        self.assertTrue(agent.finished)
        self.assertEqual(started(agent), ["TAKE_OFF"] + ["SEARCH_REGION"] * (MAX_RETRIES + 1) + ["LAND"])
        self.assertIn("gave up searching after 2 retries", agent.belief.mission.progress["gave_up"])
        self.assertEqual(failing(report), ["C1", "C2", "C3"])          # but home, landed, safe


class LowBatteryAndDeadlineTests(unittest.TestCase):

    def test_a_slow_drone_turns_back_while_it_still_can(self):
        # Half speed on a battery sized for full speed: the search is dropped
        # part-way, and the drone lands with its reserve intact.
        tight = single("S1", battery=BatterySpec(100.0, 0.3, 0.02, 20.0))
        def slow(world):
            world.faults.speed_factor["Drone1"] = 0.5
        agent, report, _ = fly(tight, "search S1", slow)
        turned = [e for e in agent.trace if e.decision.reason.startswith("low battery")]
        self.assertEqual(len(turned), 1)
        self.assertTrue(turned[0].action.startswith("aborted SEARCH_REGION"))
        self.assertTrue(report.criterion("C6").passed, report.criterion("C6").detail)
        self.assertGreater(report.facts.batteries[0].remaining, tight.battery.reserve)
        self.assertLess(report.coverage.fraction, 0.95)

    def test_a_slow_drone_is_costed_at_the_speed_it_makes_good(self):
        # Found in Phase 5 step 5: costing the way home at the planned 5 m/s,
        # a half-speed drone on S3 at 0.2 %/s turned back with 37.4 % and
        # landed on 18.0 %, under the reserve -- each metre at half speed
        # costs twice the hover drain. Costed at the speed it makes good, it
        # sees the shortfall early and lands well above.
        single_s3 = scenarios.load_scenario("search_single_001")
        tight = dataclasses.replace(single_s3, battery=BatterySpec(100.0, 0.2, 0.02, 20.0))
        def slow(world):
            world.faults.speed_factor["Drone1"] = 0.5
        agent, report, _ = fly(tight, "search S3", slow)
        self.assertIn("low battery", agent.belief.mission.progress["gave_up"])
        self.assertTrue(report.criterion("C6").passed, report.criterion("C6").detail)
        self.assertGreater(report.facts.batteries[0].remaining, tight.battery.reserve)
        # And at the planned speed the same battery finishes the task.
        _, nominal, _ = fly(tight, "search S3")
        self.assertTrue(nominal.success, nominal.summary())

    def test_a_slow_drone_turns_back_for_the_deadline_alone(self):
        # Plenty of battery, so no battery level is crossed: only the periodic
        # check can see that a half-speed drone will not finish in time.
        late = single("S1", mission=dataclasses.replace(BASE.mission, deadline_s=200.0))
        def slow(world):
            world.faults.speed_factor["Drone1"] = 0.5
        agent, report, _ = fly(late, "search S1", slow)
        turned = [e for e in agent.trace if e.decision.reason.startswith("short of time")]
        self.assertEqual(len(turned), 1)
        self.assertEqual(turned[0].events[0].trigger, Trigger.PERIODIC)
        self.assertTrue(turned[0].action.startswith("aborted SEARCH_REGION"))
        self.assertTrue(report.criterion("C6").passed, report.criterion("C6").detail)

    def test_a_search_that_cannot_be_finished_in_time_is_not_begun(self):
        short = single("S1", mission=dataclasses.replace(BASE.mission, deadline_s=100.0))
        agent, report, _ = fly(short, "search S1")
        self.assertEqual(started(agent), ["TAKE_OFF", "LAND"])
        self.assertIn("short of time", agent.belief.mission.progress["gave_up"])
        self.assertTrue(report.criterion("C6").passed)

    def test_not_enough_battery_to_start(self):
        weak = single("S1", battery=BatterySpec(100.0, 0.6, 0.02, 20.0))
        agent, _, _ = fly(weak, "search S1")
        self.assertEqual(started(agent), ["TAKE_OFF", "LAND"])
        self.assertIn("low battery", agent.belief.mission.progress["gave_up"])


class RefusalTests(unittest.TestCase):

    def test_outbound_work_refused_means_going_home(self):
        def no_searching(decision, belief):
            if decision.command is not None and decision.command.skill.value == "SEARCH_REGION":
                return Verdict(False, ("searching is not allowed today",))
            return Verdict(True)
        agent, _, _ = fly(single("S1"), "search S1", validator=no_searching)
        self.assertEqual(started(agent), ["TAKE_OFF", "LAND"])
        self.assertIn("searching is not allowed today", agent.belief.mission.progress["gave_up"])

    def test_the_way_home_refused_means_landing_where_it_is(self):
        def no_route_home(decision, belief):
            if decision.objective == "return home and report":
                return Verdict(False, ("not that way",))
            return Verdict(True)
        agent, report, world = fly(single("S1"), "search S1", validator=no_route_home)
        self.assertEqual(started(agent)[-1], "LAND")
        self.assertIn("the way home was refused", agent.belief.mission.progress["gave_up"])
        self.assertFalse(report.criterion("C6").passed)                 # landed out in the sector
        self.assertGreater(world.position("Drone1").x, 40.0)


class BranchTests(unittest.TestCase):
    """The give-up branches that a flight on the mock reaches only with contrived faults."""

    def setUp(self):
        self.brief = single("S1").brief()
        self.policy = RulePolicy()
        self.belief = BeliefState.start(self.brief, "Drone1",
                                        Observation(0.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        self.policy.decide(self.belief, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S1"}),))

    # Not named `fail`: that would shadow TestCase.fail, which every
    # assertEqual calls to report a failure -- the first version of this
    # class did exactly that, and every assertion in it passed regardless.
    def failed_event(self, skill):
        return (Event(Trigger.SKILL_FAILED, 1.0, {"skill": skill, "status": "failed", "message": "no"}),)

    def test_assertions_here_can_fail(self):
        with self.assertRaises(AssertionError):
            self.assertEqual(1, 2)

    def test_a_take_off_that_keeps_failing_ends_the_task(self):
        kinds = [self.policy.decide(self.belief, self.failed_event("TAKE_OFF")).kind for _ in range(MAX_RETRIES + 1)]
        self.assertEqual(kinds, [DecisionKind.START] * MAX_RETRIES + [DecisionKind.FINISH])
        self.assertIn("could not take off", self.policy.gave_up)

    def test_a_way_home_that_keeps_failing_ends_in_landing(self):
        self.policy.stage = Stage.GOING_HOME
        self.belief.self_.x, self.belief.self_.y = 60.0, -40.0
        decisions = [self.policy.decide(self.belief, self.failed_event("FOLLOW_WAYPOINTS"))
                     for _ in range(MAX_RETRIES + 1)]
        self.assertEqual([d.objective for d in decisions[:-1]], ["return home and report"] * MAX_RETRIES)
        self.assertEqual(decisions[-1].command.skill.value, "LAND")
        self.assertIn("could not get home", self.policy.gave_up)

    def test_a_landing_that_keeps_failing_ends_the_task_with_the_reason(self):
        self.policy.stage = Stage.LANDING
        kinds = [self.policy.decide(self.belief, self.failed_event("LAND")).kind for _ in range(MAX_RETRIES + 1)]
        self.assertEqual(kinds, [DecisionKind.START] * MAX_RETRIES + [DecisionKind.FINISH])
        self.assertIn("could not land", self.policy.gave_up)

    def test_retries_are_counted_per_stage(self):
        # Two failed transits use up the transit's retries; once it gets
        # there, a failed search must still get its own. S3: it has a transit
        # leg round R1 (S1's first lane is in a straight line).
        brief = single("S3").brief()
        self.belief = BeliefState.start(brief, "Drone1",
                                        Observation(0.0, 0, 0, 12, True, 100.0, (), True, None, 0, None))
        self.policy = RulePolicy()
        self.policy.decide(self.belief, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S3"}),))
        self.assertIs(self.policy.stage, Stage.TO_SECTOR)
        for _ in range(MAX_RETRIES):
            self.policy.decide(self.belief, self.failed_event("FOLLOW_WAYPOINTS"))
        self.policy.decide(self.belief, (Event(Trigger.SKILL_SUCCEEDED, 5.0, {"skill": "FOLLOW_WAYPOINTS"}),))
        self.assertIs(self.policy.stage, Stage.SEARCHING)
        retry = self.policy.decide(self.belief, self.failed_event("SEARCH_REGION"))
        self.assertEqual(retry.command.skill.value, "SEARCH_REGION")
        self.assertTrue(retry.reason.startswith("retry 1"))

    def test_the_speed_made_good_is_measured_and_never_above_the_plan(self):
        self.policy.stage = Stage.SEARCHING
        start = self.policy.lanes[0]
        self.policy.search_started_at, self.policy.search_path = 0.0, [start] + self.policy.lanes
        # Before MIN_SPEED_SAMPLE_S: the planned speed.
        self.belief.update(Observation(5.0, start[0] + 10.0, start[1], 12, True, 90.0, (), False, "SEARCH_REGION", 2, None))
        self.assertEqual(self.policy._speed_made_good(self.belief), self.policy.speed_mps)
        # 25 m along the first lane in 20 s: 1.25 m/s.
        self.belief.update(Observation(20.0, start[0] + 25.0, start[1], 12, True, 90.0, (), False, "SEARCH_REGION", 2, None))
        self.assertAlmostEqual(self.policy._speed_made_good(self.belief), 1.25)
        # 80 m in 10 s would be 8 m/s: held to the planned 5.
        self.belief.update(Observation(10.0, start[0] + 80.0, start[1], 12, True, 90.0, (), False, "SEARCH_REGION", 2, None))
        self.assertEqual(self.policy._speed_made_good(self.belief), self.policy.speed_mps)

    def test_the_estimate_counts_from_where_the_drone_is(self):
        # Near the end of S1's lanes with 30 %: the last lane and the way home
        # fit (about 6 %); the whole search would not (about 18 %).
        self.policy.stage = Stage.SEARCHING
        x, y = self.policy.lanes[-2]
        self.belief.update(Observation(60.0, x, y, 12.0, True, 30.0, (), False, "SEARCH_REGION", 2, None))
        self.assertIsNone(self.policy._shortfall(self.belief))
        self.belief.update(Observation(61.0, *self.policy.lanes[0], 12.0, True, 30.0, (), False, "SEARCH_REGION", 2, None))
        self.assertIn("low battery", self.policy._shortfall(self.belief))

    def test_sightings_and_the_link_change_nothing(self):
        self.policy.stage = Stage.SEARCHING
        for trigger in (Trigger.TARGET_DETECTED, Trigger.COMMS_CHANGED):
            with self.subTest(trigger=trigger):
                d = self.policy.decide(self.belief, (Event(trigger, 2.0, {}),))
                self.assertEqual(d.kind, DecisionKind.CONTINUE)


class AssumptionTests(unittest.TestCase):
    """Phase 6: the policy records what each decision rests on, and decides exactly as before."""

    def start(self, scenario, task="search S1", at=(0.0, 0.0), airborne=False):
        brief = scenario.brief()
        belief = BeliefState.start(brief, "Drone1", Observation(0.0, at[0], at[1], 12.0 if airborne else 0.0,
                                                                airborne, 100.0, (), True, None, 0, None))
        policy = RulePolicy()
        policy.decide(belief, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": task}),))
        return policy, belief

    def held(self, belief):
        return {k: (a.statement, a.evidence, a.confidence) for k, a in belief.assumptions.items()}

    def test_an_accepted_task_records_what_it_takes_from_the_brief(self):
        _, belief = self.start(single("S1"))
        held = self.held(belief)
        self.assertEqual(sorted(held), ["battery_model", "hazards", "reporting", "teammates"])
        self.assertEqual(held["battery_model"][1], "linear: 0.05 %/s aloft and 0.02 %/m moving, from the brief, uncalibrated")
        self.assertEqual(held["hazards"][1], "zones in the brief: R1; no hazard sensed")
        self.assertEqual(held["reporting"], ("what it sees reaches the base on the way home",
                                             "home is 8.0 m from the base, inside its 100 m radio", 0.8))
        self.assertEqual(held["teammates"], ("separation is not its concern: it flies alone",
                                             "no other drone on the brief's roster", 1.0))

    def test_a_home_beyond_the_radio_is_said_so(self):
        far = single("S1", network=dataclasses.replace(BASE.network, communication_range_m=5.0))
        _, belief = self.start(far)
        self.assertEqual(self.held(belief)["reporting"][:2], ("what it sees may never reach the base",
                                                              "home is 8.0 m from the base, beyond its 5 m radio"))

    def test_teammates_on_the_roster_unheard_then_heard(self):
        from agentic_uav.core.team import TeamReport
        policy, belief = self.start(BASE)                                  # four on the roster
        self.assertEqual(self.held(belief)["teammates"][1:], ("Drone2, Drone3, Drone4 on the roster, none heard", 0.5))
        belief.receive(TeamReport("Drone3", 0.5, "message"), now=1.0)
        belief.update(Observation(1.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        policy.decide(belief, (Event(Trigger.PERIODIC, 1.0),))
        self.assertEqual(self.held(belief)["teammates"][1], "current reports from Drone3; this policy does not plan around them")

    def test_a_task_it_does_not_know_assumes_nothing(self):
        _, belief = self.start(single("S1"), task="dance")
        self.assertEqual(belief.assumptions, {})

    def test_speed_planned_then_measured_capped_and_floored(self):
        policy, belief = self.start(single("S1"))
        policy._shortfall(belief)
        self.assertEqual(self.held(belief)["speed"],
                         ("the drone keeps making 5.00 m/s for the rest",
                          "the planned speed; not measured until the search is under way", 0.5))
        policy.stage = Stage.SEARCHING
        start = policy.lanes[0]
        policy.search_started_at, policy.search_path = 0.0, [start] + policy.lanes
        cases = [(5.0, 10.0, "the planned speed; the search is 5 s old, under the 10 s needed to measure it", 5.0, 0.5),
                 (20.0, 25.0, "made good 1.25 m/s over 20 s of search", 1.25, 0.9),
                 (10.0, 80.0, "made good 8.00 m/s over 10 s of search, capped at the planned 5", 5.0, 0.9),
                 (40.0, 4.0, "made good 0.10 m/s over 40 s of search, floored at 0.5", 0.5, 0.9)]
        for t, along, evidence, speed, confidence in cases:
            with self.subTest(t=t):
                belief.update(Observation(t, start[0] + along, start[1], 12, True, 90.0, (), False, "SEARCH_REGION", 2, None))
                policy._shortfall(belief)
                self.assertEqual(self.held(belief)["speed"],
                                 (f"the drone keeps making {speed:.2f} m/s for the rest", evidence, confidence))

    def test_fits_is_held_while_it_does_and_dropped_when_not(self):
        policy, belief = self.start(single("S1"))
        policy.stage = Stage.SEARCHING
        x, y = policy.lanes[-2]
        belief.update(Observation(60.0, x, y, 12.0, True, 30.0, (), False, "SEARCH_REGION", 2, None))
        self.assertIsNone(policy._shortfall(belief))
        statement, evidence, confidence = self.held(belief)["fits"]
        self.assertEqual(statement, "the battery and the time cover the rest of the task")
        self.assertIn("30.0 % (reserve 20 + 2)", evidence)
        self.assertEqual(confidence, 0.5)                    # no better than the speed it was costed at
        belief.update(Observation(61.0, *policy.lanes[0], 12.0, True, 30.0, (), False, "SEARCH_REGION", 2, None))
        self.assertIn("low battery", policy._shortfall(belief))
        self.assertNotIn("fits", belief.assumptions)

    def test_short_of_time_drops_fits_too(self):
        policy, belief = self.start(single("S1"))
        self.assertIsNone(policy._shortfall(belief))
        self.assertIn("fits", belief.assumptions)             # it fits, with 900 s to go
        belief.mission.deadline_at = 10.0                     # nowhere near enough
        self.assertIn("short of time", policy._shortfall(belief))
        self.assertNotIn("fits", belief.assumptions)

    def test_a_retry_is_assumed_and_let_go(self):
        policy, belief = self.start(single("S3"), task="search S3", airborne=True)
        self.assertIs(policy.stage, Stage.TO_SECTOR)
        failed = (Event(Trigger.SKILL_FAILED, 1.0, {"skill": "FOLLOW_WAYPOINTS", "status": "failed", "message": "no"}),)
        policy.decide(belief, failed)
        self.assertEqual(self.held(belief)["retry"],
                         ("the to_sector failure was passing: trying again from here",
                          "FOLLOW_WAYPOINTS failed: no; retry 1 of 2", 0.5))
        policy.decide(belief, (Event(Trigger.SKILL_SUCCEEDED, 5.0, {"skill": "FOLLOW_WAYPOINTS"}),))
        self.assertNotIn("retry", belief.assumptions)
        for _ in range(MAX_RETRIES):                          # the search fails, and is retried
            policy.decide(belief, (Event(Trigger.SKILL_FAILED, 6.0, {"skill": "SEARCH_REGION", "status": "failed"}),))
        self.assertIn("retry", belief.assumptions)
        policy.decide(belief, (Event(Trigger.SKILL_FAILED, 7.0, {"skill": "SEARCH_REGION", "status": "failed"}),))
        self.assertIn("gave up", policy.gave_up)
        self.assertNotIn("retry", belief.assumptions)          # given up: no longer assumed passing

    def test_an_unchanged_assumption_keeps_its_time(self):
        policy, belief = self.start(single("S1"))
        first = belief.assumptions["teammates"].at
        belief.update(Observation(30.0, 0, 0, 12, True, 99.0, (), True, None, 0, None))
        policy.decide(belief, (Event(Trigger.PERIODIC, 30.0),))
        self.assertEqual(belief.assumptions["teammates"].at, first)
        self.assertEqual(belief.snapshot()["assumptions"][-1]["age_s"], 30.0)

    def test_in_flight_the_trace_says_what_each_decision_rested_on(self):
        tight = single("S1", battery=BatterySpec(100.0, 0.3, 0.02, 20.0))
        def slow(world):
            world.faults.speed_factor["Drone1"] = 0.5
        agent, _, _ = fly(tight, "search S1", slow)
        turned = next(e for e in agent.trace if e.decision.reason.startswith("low battery"))
        held = {a["key"]: a for a in turned.belief["assumptions"]}      # what it held as it decided
        self.assertEqual(sorted(held), ["battery_model", "fits", "hazards", "reporting", "speed", "teammates"])
        self.assertTrue(held["speed"]["evidence"].startswith("made good 2.50 m/s"))
        after = {a["key"] for a in agent.trace[agent.trace.index(turned) + 1].belief["assumptions"]}
        self.assertNotIn("fits", after)                       # it no longer fits: let go


class RemainingAlongTests(unittest.TestCase):

    LANES = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]     # 25 m in all

    def test_where_the_drone_is_on_its_lanes(self):
        self.assertAlmostEqual(remaining_along(self.LANES, (0.0, 0.0)), 25.0)
        self.assertAlmostEqual(remaining_along(self.LANES, (4.0, 0.0)), 21.0)
        self.assertAlmostEqual(remaining_along(self.LANES, (10.0, 0.0)), 15.0)       # the corner: the later leg
        self.assertAlmostEqual(remaining_along(self.LANES, (5.0, 5.0)), 5.0)
        self.assertAlmostEqual(remaining_along(self.LANES, (0.0, 5.0)), 0.0)
        self.assertAlmostEqual(remaining_along(self.LANES, (4.0, 0.3)), 21.0)        # a little off the lane
        self.assertEqual(remaining_along([(1.0, 1.0)], (0.0, 0.0)), 0.0)


if __name__ == "__main__":
    unittest.main()
