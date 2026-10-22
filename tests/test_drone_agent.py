#!/usr/bin/env python3
"""Tests for the agent loop: events, the minimal belief, validation, and the decision trace.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-06's loop is the thing Phases 5-12 study: what an agent notices, when it
thinks again, what it is allowed to do, and what it based each decision on.
These drive the loop with small scripted test policies -- the real rule-based
policy is step 4 -- and check each part: that it decides only when an event
fires, that each kind of event fires once at the right moment, that the
validation step refuses what it should and the agent asks again, that a new
decision replaces a running skill cleanly, that motion goes on while a
decision is being made, and that the trace holds what the agent knew BEFORE
each decision.
"""

import dataclasses
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.decision import Decision, DecisionKind  # noqa: E402
from agentic_uav.agents.drone_agent import MAX_REJECTIONS, DroneAgent  # noqa: E402
from agentic_uav.agents.validation import ground_track, validate  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.core.events import RAISED_IN_PHASE_5, Trigger  # noqa: E402
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.core.scenario import BatterySpec, TargetSpec  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
ONE = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:1],
                          targets=TargetSpec(2, "fixed", ((65.0, -25.0), (100.0, -60.0))))
UP = S.TakeOffCommand(altitude_m=10)
DOWN = S.LandCommand()


def run_agent(scenario, policy, max_s=300.0, world=None, prepare=None, **options):
    """Run one agent on the mock, on its own thread on the world's timeline."""
    world = world or MockWorld(declared=[v.id for v in scenario.vehicles])
    if prepare:
        prepare(world)
    sensors = mock_sensors(world, scenario, "Drone1")
    executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
    out = {}

    def body():
        with world.clock.participate():
            agent = DroneAgent(scenario.brief(), sensors, executor, policy, **options)
            agent.assign("test task")
            agent.run(max_s=max_s)
            out["agent"] = agent

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    executor.close()
    return out["agent"], world


class Script:
    """Fly a fixed list of skills, one per success; finish when done; give up on failure."""

    def __init__(self, *commands, on=None):
        self.commands = list(commands)
        self.on = on or {}
        self.calls = []

    def decide(self, belief, events):
        self.calls.append(tuple(e.trigger for e in events))
        for e in events:
            if e.trigger in self.on:
                return self.on[e.trigger](belief, e)
        triggers = {e.trigger for e in events}
        if triggers & {Trigger.SKILL_FAILED, Trigger.SKILL_ABORTED}:
            return Decision.finish(reason="a skill did not succeed")
        if triggers & {Trigger.TASK_ASSIGNED, Trigger.SKILL_SUCCEEDED} and self.commands:
            return Decision.start(self.commands.pop(0), objective="the script", reason="next in the script")
        if not self.commands and not belief.self_.airborne:
            return Decision.finish(reason="script done")
        return Decision.carry_on(reason="nothing to change")


def triggers_of(agent):
    return [tuple(e.trigger for e in entry.events) for entry in agent.trace]


class LifecycleTests(unittest.TestCase):

    def test_a_task_then_one_decision_per_skill_ending(self):
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, -20, 10)), S.ReturnHomeCommand(), DOWN)
        agent, _ = run_agent(ONE, policy, periodic_s=1e6)
        self.assertTrue(agent.finished)
        self.assertEqual(triggers_of(agent), [(Trigger.TASK_ASSIGNED,)] + [(Trigger.SKILL_SUCCEEDED,)] * 4)
        self.assertEqual([e.action.split(" #")[0] for e in agent.trace],
                         ["started TAKE_OFF", "started GO_TO_WAYPOINT", "started RETURN_HOME", "started LAND",
                          "finished"])
        # It looked every tick but thought five times.
        self.assertGreater(agent.observations, 40)
        self.assertEqual(len(policy.calls), 5)

    def test_the_periodic_check_when_nothing_happens(self):
        policy = Script(UP, S.HoldPositionCommand(25.0), DOWN)
        agent, _ = run_agent(ONE, policy, periodic_s=10.0)
        periodic = [entry.at for entry in agent.trace if entry.events[0].trigger is Trigger.PERIODIC]
        self.assertEqual(len(periodic), 2)                          # within a 25 s hold, every 10 s
        self.assertAlmostEqual(periodic[1] - periodic[0], 10.0, places=6)

    def test_the_periodic_check_only_when_nothing_else_is_news(self):
        # Legs of about 4 s with a 3 s periodic check: every ending is news on
        # its own, and the periodic check never rides along with it.
        legs = [S.GoToWaypointCommand(Waypoint(0, -20 * k, 10)) for k in (1, 2, 3)]
        policy = Script(UP, *legs, S.ReturnHomeCommand(), DOWN)
        agent, _ = run_agent(ONE, policy, periodic_s=3.0)
        for triggers in triggers_of(agent):
            if Trigger.PERIODIC in triggers:
                self.assertEqual(triggers, (Trigger.PERIODIC,))
        self.assertIn((Trigger.PERIODIC,), triggers_of(agent))

    def test_the_trace_holds_what_it_knew_before_deciding(self):
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, -20, 10)), DOWN)
        agent, _ = run_agent(ONE, policy, periodic_s=1e6, max_s=60)
        first, second = agent.trace[0], agent.trace[1]
        self.assertIsNone(first.belief["mission"]["objective"])      # set BY that decision, not before it
        self.assertEqual(second.belief["mission"]["objective"], "the script")
        self.assertFalse(first.belief["self"]["airborne"])
        self.assertTrue(second.belief["self"]["airborne"])
        self.assertEqual(first.belief["self"]["current_task"], "test task")


class EventTests(unittest.TestCase):

    def test_a_sighting_is_news_once_and_can_stop_a_skill(self):
        # Out along y = -25 past T1 at (65, -25): the agent stops the leg when it sees it.
        stop = {Trigger.TARGET_DETECTED: lambda b, e: Decision.abort(reason=f"saw {e.detail['label']}")}
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, -25, 10)),
                        S.GoToWaypointCommand(Waypoint(150, -25, 10)), on=stop)
        agent, world = run_agent(ONE, policy, periodic_s=1e6, max_s=120)
        sightings = [e for entry in agent.trace for e in entry.events if e.trigger is Trigger.TARGET_DETECTED]
        self.assertEqual([e.detail["label"] for e in sightings], ["T1"])
        stopped = [entry for entry in agent.trace if entry.action == "aborted the running skill"]
        self.assertEqual(len(stopped), 1)
        self.assertLess(world.position("Drone1").x, 80.0)            # well short of x = 150
        self.assertIn((Trigger.SKILL_ABORTED,), triggers_of(agent))

    def test_battery_levels_are_news_as_they_are_crossed(self):
        hungry = dataclasses.replace(ONE, battery=BatterySpec(100.0, 1.0, 0.02, 20.0))   # 1 % a second
        policy = Script(UP, S.HoldPositionCommand(60.0), DOWN)
        agent, _ = run_agent(hungry, policy, periodic_s=1e6, battery_levels=(80.0, 50.0))
        levels = [e.detail["level"] for entry in agent.trace for e in entry.events
                  if e.trigger is Trigger.BATTERY_THRESHOLD]
        self.assertEqual(levels, [80.0, 50.0])

    def test_losing_and_regaining_the_base_is_news(self):
        # The base is (-8, 0) with a 100 m radio: out to x = 120 and back.
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, 20, 10)), S.GoToWaypointCommand(Waypoint(120, 20, 10)),
                        S.GoToWaypointCommand(Waypoint(0, 20, 10)))
        agent, _ = run_agent(ONE, policy, periodic_s=1e6, max_s=200)
        links = [e.detail["base_link"] for entry in agent.trace for e in entry.events
                 if e.trigger is Trigger.COMMS_CHANGED]
        self.assertEqual(links, [False, True])

    def test_an_abort_during_take_offs_settle_is_reported_as_success(self):
        # Found while testing: TAKE_OFF waits 3 s for the drone to settle with
        # a plain sleep. An abort asked for then is not seen, and the skill
        # ends in success -- the drone is already holding at height. Pinned
        # here so a change to it is a decision, not an accident.
        stop = {Trigger.PERIODIC: lambda b, e: Decision.abort(reason="stop")}
        policy = Script(UP, on=stop)
        agent, _ = run_agent(ONE, policy, periodic_s=5.0, max_s=10)       # 5 s: inside the settle
        endings = [e for entry in agent.trace for e in entry.events
                   if e.trigger in (Trigger.SKILL_SUCCEEDED, Trigger.SKILL_ABORTED)]
        self.assertEqual([(e.trigger, e.detail["skill"]) for e in endings],
                         [(Trigger.SKILL_SUCCEEDED, "TAKE_OFF")])
        self.assertTrue(agent.executor.history()[0].abort_requested)

    def test_a_failed_skill_is_news_with_its_reason(self):
        def stuck(world):
            from agentic_uav.core.models import PrimitiveKind
            world.faults.raise_on[("Drone1", PrimitiveKind.MOVE_TO_POSITION)] = "motor fault"
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, -20, 10)))
        agent, _ = run_agent(ONE, policy, periodic_s=1e6, prepare=stuck, max_s=60)
        failed = [e for entry in agent.trace for e in entry.events if e.trigger is Trigger.SKILL_FAILED]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].detail["error_code"], "SIMULATOR_ERROR")
        self.assertIn("motor fault", failed[0].detail["message"])

    def test_which_triggers_phase_5_raises(self):
        self.assertNotIn(Trigger.MESSAGE, RAISED_IN_PHASE_5)
        self.assertNotIn(Trigger.TEAMMATE_FAILED, RAISED_IN_PHASE_5)
        self.assertEqual(len(RAISED_IN_PHASE_5), len(Trigger) - 2)


class ReplaceTests(unittest.TestCase):

    def test_a_new_skill_replaces_the_running_one_without_false_news(self):
        # On the first periodic check during a long leg, turn back: the leg
        # is aborted to make way, and that abort is not reported as news.
        turn = {Trigger.PERIODIC: lambda b, e: Decision.start(S.ReturnHomeCommand(), "go home", "changed mind")}
        policy = Script(UP, S.GoToWaypointCommand(Waypoint(0, -100, 10)), on=turn)
        agent, _ = run_agent(ONE, policy, periodic_s=5.0, max_s=40)
        replaced = [entry.action for entry in agent.trace if entry.action.startswith("aborted GO_TO_WAYPOINT")]
        self.assertEqual(len(replaced), 1)
        self.assertIn("then started RETURN_HOME", replaced[0])
        self.assertNotIn((Trigger.SKILL_ABORTED,), triggers_of(agent))


class ValidationTests(unittest.TestCase):

    def test_a_refusal_is_news_and_the_agent_asks_again(self):
        through, round_ = Waypoint(50, 0, 10), Waypoint(8, -20, 10)        # (0,0) -> (50,0) crosses R1

        class Stubborn(Script):
            def decide(self, belief, events):
                self.calls.append(tuple(e.trigger for e in events))
                if Trigger.GUARD_REJECTED in {e.trigger for e in events}:
                    return Decision.start(S.GoToWaypointCommand(round_), "round R1", "the guard said no")
                if Trigger.TASK_ASSIGNED in {e.trigger for e in events}:
                    return Decision.start(UP, "up")
                if any(e.trigger is Trigger.SKILL_SUCCEEDED and e.detail["skill"] == "TAKE_OFF" for e in events):
                    return Decision.start(S.GoToWaypointCommand(through), "straight", "shortest")
                return Decision.finish()

        agent, _ = run_agent(ONE, Stubborn(), periodic_s=1e6, max_s=60)
        refused = [entry for entry in agent.trace if entry.action == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertIn("restricted zone R1", refused[0].verdict.reasons[0])
        accepted = agent.trace[agent.trace.index(refused[0]) + 1]
        self.assertIn(Trigger.GUARD_REJECTED, [e.trigger for e in accepted.events])
        self.assertTrue(accepted.action.startswith("started GO_TO_WAYPOINT"))

    def test_refused_every_time_it_holds(self):
        class Hopeless(Script):
            def decide(self, belief, events):
                if Trigger.TASK_ASSIGNED in {e.trigger for e in events}:
                    return Decision.start(UP, "up")
                if Trigger.SKILL_SUCCEEDED in {e.trigger for e in events}:
                    return Decision.start(S.GoToWaypointCommand(Waypoint(50, 0, 10)), "straight")
                if Trigger.GUARD_REJECTED in {e.trigger for e in events}:
                    return Decision.start(S.GoToWaypointCommand(Waypoint(50, 0, 10)), "straight, again")
                return Decision.finish()

        agent, _ = run_agent(ONE, Hopeless(), periodic_s=1e6, max_s=20)
        refusals = [entry for entry in agent.trace if entry.action == "refused"]
        self.assertEqual(len(refusals), MAX_REJECTIONS + 1)
        self.assertEqual(agent.trace[-1].action, "nothing to hold")

    def test_refused_every_time_while_flying_it_stops_and_holds(self):
        # Mid-leg, a periodic re-think that only ever proposes a path through
        # R1: refused each time, so the agent stops the leg and holds.
        through = S.GoToWaypointCommand(Waypoint(50, 0, 10))

        class Insists(Script):
            def decide(self, belief, events):
                triggers = {e.trigger for e in events}
                if Trigger.TASK_ASSIGNED in triggers:
                    return Decision.start(UP, "up")
                if Trigger.SKILL_SUCCEEDED in triggers:
                    return Decision.start(S.GoToWaypointCommand(Waypoint(0, -100, 10)), "out")
                on_the_leg = belief.self_.current_skill == "GO_TO_WAYPOINT"
                if on_the_leg and triggers & {Trigger.PERIODIC, Trigger.GUARD_REJECTED}:
                    return Decision.start(through, "straight through")
                if Trigger.PERIODIC in triggers:
                    return Decision.carry_on()
                return Decision.finish(reason=str(triggers))

        agent, world = run_agent(ONE, Insists(), periodic_s=5.0, max_s=30)
        held = [entry for entry in agent.trace if entry.action == "held after repeated refusals"]
        self.assertEqual(len(held), 1)
        self.assertIn((Trigger.SKILL_ABORTED,), triggers_of(agent))
        self.assertGreater(world.position("Drone1").y, -100.0 + 50.0)       # stopped well short

    def test_the_way_home_is_never_refused(self):
        # 150 m out with 21 %: going home costs about 4.5 %, ending under the
        # 20 % reserve -- the rule that would refuse an outbound leg. Home and
        # landing are allowed regardless: refusing them would be worse.
        out_there = self._belief(battery=100.0, x=0.0, y=0.0)           # home is the pad
        out_there.update(Observation(60.0, 0.0, -150.0, 10.0, True, 21.0, (), False, None, 2, "success"))
        self.assertEqual(out_there.self_.home, (0.0, 0.0))
        route_home = S.FollowWaypointsCommand((Waypoint(0, -75, 10), Waypoint(0, 0, 10)))
        for command in (S.ReturnHomeCommand(), S.LandCommand(), S.HoldPositionCommand(5.0), route_home):
            with self.subTest(skill=command.skill.value):
                self.assertTrue(validate(Decision.start(command, "home"), out_there).ok)
        self.assertFalse(validate(Decision.start(S.GoToWaypointCommand(Waypoint(0, -10, 10)), "back"),
                                  out_there).ok)

    def test_the_way_home_is_still_kept_out_of_zones(self):
        # The battery rule waives the way home; the zone rule never does.
        # From (50, 0), straight home to the pad crosses R1.
        beyond = self._belief(battery=100.0, x=0.0, y=0.0)
        beyond.update(Observation(30.0, 50.0, 0.0, 10.0, True, 90.0, (), True, None, 2, "success"))
        verdict = validate(Decision.start(S.ReturnHomeCommand(), "home"), beyond)
        self.assertFalse(verdict.ok)
        self.assertIn("restricted zone R1", verdict.reasons[0])
        self.assertTrue(validate(Decision.start(S.LandCommand(), "down"), beyond).ok)
        self.assertEqual(ground_track(S.ReturnHomeCommand(), (50.0, 0.0), (0.0, 0.0)), [(50.0, 0.0), (0.0, 0.0)])

    def test_the_battery_rule_and_the_way_home(self):
        # 150 m out along -y (clear of R1) and 150 m back: 300 m and 60 s at
        # 5 m/s, 6 % + 3 % = 9 %. From 25 % that leaves 16 %, under the 20 % reserve.
        agent_belief = self._belief(battery=25.0, x=0.0, y=0.0)
        far = Decision.start(S.GoToWaypointCommand(Waypoint(0, -150, 10)), "far")
        verdict = validate(far, agent_belief)
        self.assertFalse(verdict.ok)
        self.assertEqual(len(verdict.reasons), 1)
        self.assertIn("about 9.0 % to fly this and home", verdict.reasons[0])
        self.assertTrue(validate(Decision.start(S.ReturnHomeCommand(), "home"), agent_belief).ok)
        self.assertTrue(validate(Decision.start(S.GoToWaypointCommand(Waypoint(0, -10, 10)), "near"),
                                 self._belief(battery=90.0, x=0.0, y=0.0)).ok)

    def test_a_search_is_checked_along_its_lanes(self):
        # A region whose lawnmower passes over R1.
        over = S.SearchRegionCommand(region=Region(10.0, -10.0, 40.0, 10.0), altitude_m=10, spacing_m=10)
        track = ground_track(over, (0.0, 0.0))
        self.assertEqual(track[0], (0.0, 0.0))
        self.assertGreater(len(track), 3)
        self.assertFalse(validate(Decision.start(over, "search"), self._belief(90.0, 0.0, 0.0)).ok)

    def test_decisions_are_well_formed(self):
        with self.assertRaises(ValueError):
            Decision(DecisionKind.START)
        with self.assertRaises(ValueError):
            Decision(DecisionKind.FINISH, command=UP)

    @staticmethod
    def _belief(battery, x, y):
        obs = Observation(0.0, x, y, 10.0, True, battery, (), True, None, 0, None)
        return BeliefState.start(ONE.brief(), "Drone1", obs)


class BeliefTests(unittest.TestCase):

    def test_reported_once_the_base_is_in_reach(self):
        from agentic_uav.core.sensing import Sighting
        brief = ONE.brief()
        seen = (Sighting("T1", 65.0, -25.0, 3.0),)
        belief = BeliefState.start(brief, "Drone1", Observation(0.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        changes = belief.update(Observation(4.0, 150, 0, 10, True, 99.0, seen, False, "GO_TO_WAYPOINT", 2, None))
        self.assertEqual(changes["new_sightings"], ["T1"])
        self.assertEqual(changes["base_link"], False)
        self.assertEqual(belief.local_map.reported_targets, set())
        belief.update(Observation(9.0, 40, 0, 10, True, 98.0, seen, True, None, 2, "success"))
        self.assertEqual(belief.local_map.reported_targets, {"T1"})
        self.assertAlmostEqual(belief.time_left, brief.mission.deadline_s - 9.0)


class RealTimeTests(unittest.TestCase):

    def test_motion_goes_on_while_the_agent_thinks(self):
        # AUV-06, 5.2: low-level motion must never depend on decision time.
        # In real time, a policy that takes 0.3 s to decide during a leg:
        # the drone keeps flying meanwhile.
        clock = RealClock()
        world = MockWorld(declared=["Drone1"], clock=clock)
        adapter = MockVehicleAdapter(world)
        adapter.take_control("Drone1")
        adapter.execute_primitive("Drone1", S.PrimitiveCommand.move_to_position(0, 0, world.ground_z - 5, 20.0))
        runner = S.SkillRunner(adapter, "Drone1", clock, ground_z=world.ground_z)
        executor = ActionExecutor(runner)
        moved = {}

        class Slow:
            def decide(self, belief, events):
                triggers = {e.trigger for e in events}
                if Trigger.TASK_ASSIGNED in triggers:
                    return Decision.start(S.GoToWaypointCommand(Waypoint(0, -12, 5), speed_mps=10.0), "out")
                if Trigger.PERIODIC in triggers and "x" not in moved:
                    before = adapter.get_pose("Drone1").y
                    time.sleep(0.3)                                    # thinking
                    moved["x"] = before - adapter.get_pose("Drone1").y
                    return Decision.carry_on()
                return Decision.finish()

        agent = DroneAgent(ONE.brief(), mock_sensors(world, ONE, "Drone1"), executor, Slow(),
                           tick_s=0.05, periodic_s=0.2)
        agent.assign("out")
        agent.run(max_s=2.0)
        executor.close()
        self.assertGreater(moved["x"], 2.0)                            # ~3 m at 10 m/s while it thought


if __name__ == "__main__":
    unittest.main()
