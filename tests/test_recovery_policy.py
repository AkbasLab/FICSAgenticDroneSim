#!/usr/bin/env python3
"""Tests for agentic_uav.agents.recovery_policy and the team flown with a drone stopped (Phase 9, step 3).

    python -m unittest discover tests

WHY THESE EXIST
---------------
The thesis in one flight: a drone is stopped, and the rest carry on with no
new human command. These fly it on the mock -- every message delivered -- and
pin each part: no false alarm when nobody stops (a drone that landed and
said "done" is not a failure); every survivor's ladder climbing at its
thresholds when one is stopped, and no live drone ever suspected; the
stopped drone's task returning and a reserve taking it; the mission met; the
team lowering its ambition when the task cannot be redone in time; a stop
being only a stop; and the policy's own reasoning case by case.
"""

import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.decision import DecisionKind  # noqa: E402
from agentic_uav.agents.recovery_policy import RecoveryPolicy  # noqa: E402
from agentic_uav.coordination.contract_net import ContractNet  # noqa: E402
from agentic_uav.coordination.health import Health  # noqa: E402
from agentic_uav.coordination.roles import Role  # noqa: E402
from agentic_uav.coordination.tasks import TaskStatus, tasks_from_brief  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.core.team import TeamReport  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
BRIEF = TEAM.brief()
CONFIG = load_allocation()
HEALTH = load_recovery()
ALL = ["search S1", "search S2", "search S3", "search S4"]


def ladder(run, drone):
    return [(t["at"], t["teammate"], t["after"]) for t in run.policies[drone]["health"]["log"]]


def roles(run, drone):
    return [(c["at"], c["after"]) for c in run.policies[drone]["roles"]["log"]]


class NoStopTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_recovery_on_mock(TEAM, CONFIG, HEALTH, "no stop")

    def test_met_with_the_work_divided_as_in_phase_8(self):
        self.assertTrue(self.flight.met, self.flight.team.report.summary())
        self.assertEqual(self.flight.searched, {"Drone1": ["search S3"], "Drone2": ["search S4"],
                                                "Drone3": ["search S1"], "Drone4": ["search S2"]})
        self.assertEqual(self.flight.stopped, {})

    def test_no_false_alarm(self):
        for d in self.flight.policies:
            self.assertEqual(ladder(self.flight, d), [], d)

    def test_a_drone_that_finished_is_shown_finished_not_failed(self):
        finished = {m for p in self.flight.policies.values() for m in p["health"]["finished"]}
        self.assertTrue(finished)
        for p in self.flight.policies.values():
            self.assertNotIn("failed", p["health"]["states"].values())

    def test_each_scout_then_a_reserve_and_no_relay(self):
        for d in self.flight.policies:
            self.assertEqual([r for _, r in roles(self.flight, d)], ["scout", "reserve"], d)

    def test_reserves_wait_for_the_team_at_a_cost(self):
        # Phase 8 sent a finished drone home at once (188.0 s); a reserve waits for the team.
        self.assertGreater(self.flight.team.report.completion_s, 188.0)


class StopTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_recovery_on_mock(TEAM, CONFIG, HEALTH, "Drone1 stopped", {"Drone1": 60.0})

    def test_the_mission_continues_and_is_met(self):
        self.assertEqual(self.flight.stopped, {"Drone1": 60.0})
        self.assertTrue(self.flight.met, self.flight.team.report.summary())
        self.assertFalse(self.flight.team.finished["Drone1"])
        self.assertEqual(self.flight.survivors, ["Drone2", "Drone3", "Drone4"])

    def test_met_needs_every_survivor_to_end_its_part(self):
        team = dataclasses.replace(self.flight.team, finished={**self.flight.team.finished, "Drone3": False})
        self.assertFalse(dataclasses.replace(self.flight, team=team).met)

    def test_every_survivor_detects_it_at_the_thresholds(self):
        for d in self.flight.survivors:
            self.assertEqual(ladder(self.flight, d), [(63.5, "Drone1", "suspected"), (70.5, "Drone1", "unreachable"),
                                                      (90.5, "Drone1", "failed")], d)

    def test_its_task_returns_and_a_reserve_takes_it(self):
        self.assertEqual(sorted(t for ts in self.flight.searched.values() for t in ts), ALL)
        self.assertEqual(self.flight.searched["Drone4"], ["search S2", "search S3"])
        self.assertEqual(roles(self.flight, "Drone4")[:3], [(1.0, "scout"), (118.5, "reserve"), (119.6, "scout")])
        for d in self.flight.survivors:
            t = next(t for t in self.flight.policies[d]["net"]["book"]["tasks"] if t["task_id"] == "search S3")
            self.assertEqual((t["status"], t["assigned_agent"], t["version"]), ("complete", "Drone4", 2), d)
            self.assertTrue(any("Drone1's lease ran out" in e["why"] for e in self.flight.policies[d]["net"]["book_log"]))

    def test_no_new_command_after_the_start(self):
        for d, trace in self.flight.team.traces.items():
            told = [e.detail for entry in trace for e in entry.events if e.trigger is Trigger.TASK_ASSIGNED]
            self.assertEqual(told, [{"task": "team mission", "team": True}], d)

    def test_role_changes_are_announced(self):
        sent = {d.message.message_id: d.message for d in self.flight.team.deliveries}.values()
        changes = sorted((m.sender_id, m.payload["role"]) for m in sent if m.message_type is MessageType.ROLE_CHANGE)
        self.assertIn(("Drone4", "scout"), changes)
        self.assertIn(("Drone4", "reserve"), changes)
        heard = {r["from"] for r in self.flight.policies["Drone2"]["heard_roles"]}
        self.assertLessEqual({"Drone3", "Drone4"}, heard)

    def test_a_stop_is_only_a_stop(self):
        trace = self.flight.team.traces["Drone1"]
        self.assertLessEqual(trace[-1].at, 60.0)                           # it decided nothing after
        self.assertEqual(self.flight.team.skills["Drone1"][-1][1], "aborted")   # its skill stopped
        path = self.flight.team.trajectories["Drone1"]
        here, end = path.position_at(61.0), path.position_at(path.end)
        self.assertAlmostEqual(here[0], end[0], places=3)                  # and it held where it was
        self.assertAlmostEqual(here[1], end[1], places=3)
        self.assertTrue(here[2] > 5.0)


class ReprioritizationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        short = dataclasses.replace(TEAM, mission=dataclasses.replace(TEAM.mission, deadline_s=250.0))
        cls.flight = fly_recovery_on_mock(short, CONFIG, HEALTH, "stopped, deadline 250 s", {"Drone1": 60.0})

    def test_the_task_that_cannot_be_redone_is_abandoned_in_every_book(self):
        for d in self.flight.survivors:
            (a,) = self.flight.policies[d]["net"]["abandoned"]
            self.assertEqual(a["task_id"], "search S3", d)
            self.assertIn("no drone could still do it", a["why"])

    def test_nobody_chases_it_and_every_survivor_ends_its_part(self):
        self.assertNotIn("search S3", [t for ts in self.flight.searched.values() for t in ts])
        self.assertTrue(all(self.flight.team.finished[d] for d in self.flight.survivors))
        self.assertLessEqual(self.flight.team.report.until - self.flight.team.start, 250.0)

    def test_the_result_is_partial_and_said_so(self):
        report = self.flight.team.report
        self.assertFalse(report.success)
        c1 = next(c for c in report.criteria if c.id == "C1")
        self.assertFalse(c1.passed)
        self.assertIn("S3 0.", c1.detail)


# ------------------------------------------------------------ the policy's reasoning

def belief(x=40.0, y=-10.0, at=100.0, battery=100.0):
    b = BeliefState.start(BRIEF, "Drone1", Observation(at, x, y, 12.0, True, battery, (), True, None, 0, None))
    b.self_.home = (0.0, 0.0)
    return b


class ReasoningTests(unittest.TestCase):

    def policy(self):
        p = RecoveryPolicy(ContractNet("Drone1", tasks_from_brief(BRIEF), CONFIG), HEALTH)
        return p

    def started(self, b, at=100.0):
        p = self.policy()
        p.coordinate(b, [], at)                        # the detector and roles begin; it bids, claims nothing yet
        return p

    def test_nobody_can_only_when_no_drone_not_failed_could(self):
        b = belief(at=100.0)
        p = self.started(b)
        s3 = p.net.book.get("search S3")
        self.assertIsNone(p._nobody_can(b, s3))                               # plenty of time
        late = belief(at=100.0)
        late.mission.deadline_at = 100.0 + 60.0                              # a minute left: S3 takes longer
        p2 = self.started(late)
        self.assertIn("no drone could still do it", p2._nobody_can(late, s3))
        late.team.members["Drone2"] = None
        self.assertIn("no drone could still do it", p2._nobody_can(late, s3))

    def test_a_teammate_that_could_keeps_the_task(self):
        b = belief(battery=21.0)                                              # it cannot: too little battery
        p = self.started(b)
        b.receive(TeamReport("Drone2", 100.0, "message", position=(60.0, -20.0, 16.0), status="searching"), 100.0)
        self.assertIsNone(p._nobody_can(b, p.net.book.get("search S3")))     # but Drone2 could
        p.detector._state["Drone2"] = Health.FAILED
        self.assertIsNotNone(p._nobody_can(b, p.net.book.get("search S3")))  # not if it has failed

    def test_a_reserve_stays_while_teammates_work_and_it_could_help(self):
        b = belief()
        p = self.started(b)
        self.assertIsNone(p._still_useful(b))                                # nothing held by anyone
        claim = new_message(MessageType.TASK_AWARD, "Drone3", BROADCAST, BRIEF.scenario_id, 100.0, 1,
                            {"task_id": "search S1", "version": 1, "value": 100.0})
        p.net.receive(claim, 100.0)
        p.net.tick(100.5, lambda task: None)
        self.assertIn("teammates still at search S1", p._still_useful(b))
        d = p._nothing_open(b, "searched")
        self.assertEqual((d.command.skill.value, d.objective), ("HOLD_POSITION", "stand by as a reserve"))
        self.assertFalse(p.net.done)
        poor = belief(battery=21.0)
        self.assertIsNone(p._still_useful(poor))                             # could not help: home
        d = p._nothing_open(poor, "searched")
        self.assertEqual(d.objective, "return home and report")
        self.assertTrue(p.net.done)

    def test_a_relay_flies_half_way_to_the_silent_teammate_then_holds(self):
        b = belief(x=40.0, y=-10.0, at=100.0)
        p = self.started(b, at=80.0)                                         # watching since 80 s
        b.receive(TeamReport("Drone3", 85.0, "message", position=(152.0, -40.0, 20.0)), 85.0)
        b.links["Drone3"] = {"last_heard": 88.0}
        for m in ("Drone2", "Drone4"):
            b.links[m] = {"last_heard": 100.0}
        p.coordinate(b, [], 100.0)                                           # 12 s silent: unreachable
        self.assertEqual(p.detector.state("Drone3"), Health.UNREACHABLE)
        self.assertEqual(p.roles.role, Role.RELAY)
        d = p._go(b, "free")
        self.assertEqual(d.command.skill.value, "FOLLOW_WAYPOINTS")
        self.assertEqual(d.objective, "relay toward Drone3")
        self.assertIn("72.0, -20.0", d.reason)                               # half way from the base (-8, 0)
        there = belief(x=72.0, y=-20.0, at=101.0)
        there.team.members["Drone3"] = b.team.members["Drone3"]
        self.assertEqual(p._relay(there, "free").command.skill.value, "HOLD_POSITION")

    def test_the_belief_shows_the_ladder(self):
        b = belief()
        p = self.started(b)
        self.assertEqual(b.snapshot()["communication"]["teammate_health"],
                         {"Drone2": "healthy", "Drone3": "healthy", "Drone4": "healthy"})
        self.assertIsNotNone(p.as_json()["health"])

    def test_a_plain_task_is_still_phase_5s(self):
        p = self.policy()
        b = BeliefState.start(BRIEF, "Drone1", Observation(0.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        d = p.decide(b, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S3"}),))
        self.assertEqual((d.kind, d.command.skill.value, p.sector.id), (DecisionKind.START, "TAKE_OFF", "S3"))


if __name__ == "__main__":
    unittest.main()
