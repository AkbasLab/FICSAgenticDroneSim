#!/usr/bin/env python3
"""Tests for the guardian wired into the agent loop and the team flight (Phase 11, step 3).

    python -m unittest discover -s tests -p test_guardian_agent.py

WHY THESE EXIST
---------------
The guardian's checks are tested on their own in test_guardian.py. These test
what happens when an agent flies with one: that each outcome changes what the
agent DOES -- the modified command flies, a refusal is asked again with
GUARD_REJECTED, the fallback flies on the loop's last ask -- and that the
trace says so; that the guardian's log is its own; and that a team flight with
a guardian and nothing unsafe in it is, knot for knot, the flight without one.
A guardian that changed a clean flight would make every comparison with
Phases 5-10 meaningless.
"""

import dataclasses
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.decision import Decision  # noqa: E402
from agentic_uav.agents.drone_agent import MAX_REJECTIONS, DroneAgent  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.events import Trigger  # noqa: E402
from agentic_uav.core.scenario import TargetSpec  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.network_exit import canonical  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.safety import guardian as g  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
ONE = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:1],
                          targets=TargetSpec(2, "fixed", ((65.0, -25.0), (100.0, -60.0))))
LIMITS = g.parse_limits(load_toml(os.path.join(ROOT, "configs", "guardian", "default.toml")))


def same_flight(a, b):
    """Deliveries, the drones' records, every decision's time and action, every trajectory knot."""
    return (canonical(a) == canonical(b) and a.policies == b.policies
            and [(d, e.at, e.action) for d, t in a.team.traces.items() for e in t]
            == [(d, e.at, e.action) for d, t in b.team.traces.items() for e in t]
            and {d: list(t.knots) for d, t in a.team.trajectories.items()}
            == {d: list(t.knots) for d, t in b.team.trajectories.items()})


def run_guarded(policy, max_s=120.0, guarded=True, **options):
    world = MockWorld(declared=["Drone1"])
    sensors = mock_sensors(world, ONE, "Drone1")
    executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
    brief = ONE.brief()
    out = {}

    def body():
        with world.clock.participate():
            if guarded:
                guardian = g.Guardian(brief, "Drone1", LIMITS, executor.handle(), 12.0)
                agent = DroneAgent(brief, sensors, guardian.handle(), policy, validator=guardian.review, **options)
                guardian.attach(agent.belief)
                out["guardian"] = guardian
            else:
                agent = DroneAgent(brief, sensors, executor, policy, **options)
            agent.assign("test task")
            agent.run(max_s=max_s)
            out["agent"] = agent

    thread = threading.Thread(target=body)
    thread.start()
    thread.join()
    executor.close()
    return out["agent"], out.get("guardian"), executor


class Script:
    """Each decision the next in a list; FINISH when it runs out on the ground."""

    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.asked = []

    def decide(self, belief, events):
        self.asked.append(tuple(e.trigger for e in events))
        if self.decisions and (Trigger.TASK_ASSIGNED in self.asked[-1] or Trigger.SKILL_SUCCEEDED in self.asked[-1]
                               or Trigger.GUARD_REJECTED in self.asked[-1]):
            return self.decisions.pop(0)
        if not belief.self_.airborne:
            return Decision.finish(reason="done")
        return Decision.carry_on(reason="nothing to change")


def start(cmd):
    return Decision.start(cmd, "test", "scripted")


class OutcomeInTheLoopTests(unittest.TestCase):
    def test_a_modified_command_is_what_flies(self):
        policy = Script(start(S.TakeOffCommand(altitude_m=60.0, speed_mps=15.0)), start(S.LandCommand()))
        agent, guardian, executor = run_guarded(policy, periodic_s=1e6)
        flown = executor.history()[0].command
        self.assertEqual((flown.altitude_m, flown.speed_mps), (40.0, 8.0))
        first = agent.trace[0]
        self.assertTrue(first.action.startswith("modified by the guardian: started TAKE_OFF"))
        self.assertEqual(first.decision.command.altitude_m, 60.0)            # what was proposed, as proposed
        j = first.as_json()["verdict"]
        self.assertEqual((j["outcome"], j["fallback"]), (g.MODIFY, None))
        self.assertEqual(j["replacement"]["command"]["altitude_m"], 40.0)
        self.assertEqual([e["outcome"] for e in guardian.log], [g.MODIFY])
        self.assertTrue(agent.finished)

    def test_a_refusal_is_asked_again_and_the_guardian_holds_on_the_last_ask(self):
        zone = start(S.GoToWaypointCommand(Waypoint(25.0, 0.0, 12.0)))
        policy = Script(start(S.TakeOffCommand(altitude_m=12.0)), *[zone] * (MAX_REJECTIONS + 1),
                        start(S.LandCommand()))
        agent, guardian, executor = run_guarded(policy, periodic_s=1e6)
        actions = [e.action.split(" #")[0] for e in agent.trace]
        self.assertEqual(actions[:5], ["started TAKE_OFF"] + ["refused"] * MAX_REJECTIONS +
                         ["guardian fallback HOLD_POSITION: started HOLD_POSITION"])
        self.assertEqual(sum(Trigger.GUARD_REJECTED in a for a in policy.asked), MAX_REJECTIONS)
        self.assertEqual([e["outcome"] for e in guardian.log], [g.REJECT] * MAX_REJECTIONS + [g.FALLBACK])
        skills = [x.command.skill for x in executor.history()]
        self.assertNotIn(S.SkillName.GO_TO_WAYPOINT, skills)
        self.assertEqual(skills[:2], [S.SkillName.TAKE_OFF, S.SkillName.HOLD_POSITION])
        self.assertEqual(agent.trace[4].as_json()["verdict"]["fallback"], g.HOLD_POSITION)

    def test_without_a_guardian_the_trace_is_phase_5s(self):
        policy = Script(start(S.TakeOffCommand(altitude_m=12.0)), start(S.LandCommand()))
        agent, _, _ = run_guarded(policy, guarded=False, periodic_s=1e6)
        self.assertEqual(set(agent.trace[0].as_json()["verdict"]), {"ok", "reasons"})

    def test_an_approved_flight_is_logged_nowhere_and_counted(self):
        policy = Script(start(S.TakeOffCommand(altitude_m=12.0)),
                        start(S.GoToWaypointCommand(Waypoint(0.0, -20.0, 12.0))), start(S.ReturnHomeCommand()),
                        start(S.LandCommand()))
        agent, guardian, _ = run_guarded(policy, periodic_s=1e6)
        self.assertTrue(agent.finished)
        self.assertEqual(guardian.log, [])
        self.assertEqual(guardian.approved, 5)                  # four starts and the finish
        self.assertTrue(all(set(e.as_json()["verdict"]) == {"ok", "reasons"} for e in agent.trace))


class TeamFlightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sc = dataclasses.replace(CANONICAL, random_seed=3)
        cfg, health = load_allocation(), load_recovery()
        cls.plain = fly_recovery_on_mock(sc, cfg, health, "no stop")
        cls.guarded = fly_recovery_on_mock(sc, cfg, health, "no stop", guardian=LIMITS)

    def test_a_clean_guarded_flight_is_the_flight_without_a_guardian(self):
        self.assertTrue(same_flight(self.guarded, self.plain))
        self.assertTrue(self.guarded.met)

    def test_each_drone_has_its_own_guardian_at_its_own_layer_and_nothing_to_log(self):
        self.assertEqual(self.plain.guardians, {})
        self.assertEqual({d: x["layer_m"] for d, x in self.guarded.guardians.items()},
                         {"Drone1": 12.0, "Drone2": 16.0, "Drone3": 20.0, "Drone4": 24.0})
        self.assertTrue(all(x["log"] == [] and x["approved"] > 0 for x in self.guarded.guardians.values()))

    def test_every_skill_started_is_recorded_with_its_command(self):
        for d, ran in self.guarded.executed.items():
            self.assertEqual([(x["skill"]) for x in ran], [s for s, _ in self.guarded.team.skills[d]])
            self.assertTrue(all(x["started_at"] >= self.guarded.team.start for x in ran))
        self.assertEqual(self.guarded.executed["Drone1"][0]["command"]["altitude_m"], 12.0)


if __name__ == "__main__":
    unittest.main()
