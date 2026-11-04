#!/usr/bin/env python3
"""Tests for agentic_uav.agents.team_policy and the team flown with nobody told a sector (Phase 8, step 4).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Step 3 showed the contract-net on scripted messages. These fly it: four
agents on the mock, each told only the team mission, dividing the sectors by
their own bids and claims -- and each then flying its sector with Phase 5's
rule policy, unchanged. They check that the work is divided (each sector
once, all four), that nothing but the protocol divided it, that the
contested flight's conflicts are settled the same way every time, and the
policy's reactions one by one: nothing for it, a wait, a claim while
waiting, a search done, a shortfall that gives the task back.

THE NETWORK. These flights deliver every message (`range_m=None`): Phase 8's
exit is the protocol under perfect communication (decided 2026-11-04). The
canonical 100 m radio is flown once below, to keep visible what it does:
far-sector holders go silent, their leases run out mid-search, and sectors
are searched twice -- Phase 10's subject.
"""

import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.decision import DecisionKind  # noqa: E402
from agentic_uav.agents.drone_agent import TEAM_MISSION, DroneAgent  # noqa: E402
from agentic_uav.agents.rule_policy import Stage  # noqa: E402
from agentic_uav.agents.team_policy import TeamPolicy  # noqa: E402
from agentic_uav.coordination.bids import AllocationConfig, BidWeights  # noqa: E402
from agentic_uav.coordination.contract_net import ContractNet  # noqa: E402
from agentic_uav.coordination.tasks import TaskStatus, tasks_from_brief  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import contested, fly_team_on_mock, load_allocation  # noqa: E402
from agentic_uav.experiments.knowledge import Truth, knowledge_log  # noqa: E402
from agentic_uav.experiments.message_log import message_log  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.control.skills import SkillRunner  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
BRIEF = TEAM.brief()
CONFIG = load_allocation()
ALL = ["search S1", "search S2", "search S3", "search S4"]
DIVISION = {"Drone1": ["search S3"], "Drone2": ["search S4"], "Drone3": ["search S1"], "Drone4": ["search S2"]}


class DeliberatingFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_team_on_mock(TEAM, CONFIG, "deliberating", range_m=None)
        cls.team = cls.flight.team

    def test_the_mission_is_met_and_the_work_divided(self):
        self.assertTrue(self.flight.met, self.team.report.summary())
        self.assertEqual(self.flight.searched, DIVISION)
        self.assertEqual(sorted(sum(self.flight.searched.values(), [])), ALL)

    def test_nobody_was_told_a_sector(self):
        for d, trace in self.team.traces.items():
            told = [e for entry in trace for e in entry.events if e.trigger is Trigger.TASK_ASSIGNED]
            self.assertEqual([e.detail for e in told], [{"task": TEAM_MISSION, "team": True}], d)
            first = trace[0]
            self.assertEqual(first.decision.command.skill.value, "TAKE_OFF")

    def test_each_drone_flies_the_task_it_claimed(self):
        for d, net in self.flight.nets.items():
            (made,) = net["claims_made"]
            self.assertEqual([made["task_id"]], self.flight.searched[d])
            claimed = [e for entry in self.team.traces[d] for e in entry.events
                       if e.trigger is Trigger.MESSAGE and e.detail["allocation"] == "claimed"]
            self.assertEqual([e.detail["task"] for e in claimed], self.flight.searched[d])
            searched = [entry.decision for entry in self.team.traces[d]
                        if entry.decision.command is not None and entry.decision.command.skill.value == "SEARCH_REGION"]
            self.assertEqual([x.objective for x in searched], [f"search {self.flight.searched[d][0].split()[1]}"])

    def test_every_book_agrees_at_the_end(self):
        books = [{t["task_id"]: (t["status"], t["assigned_agent"]) for t in n["book"]["tasks"]}
                 for n in self.flight.nets.values()]
        self.assertTrue(all(b == books[0] for b in books))
        self.assertEqual(books[0], {t: ("complete", d) for d, ts in DIVISION.items() for t in ts})

    def test_no_conflict_and_no_lease_ran_out(self):
        for n in self.flight.nets.values():
            self.assertEqual(n["corrections"], [])
            self.assertFalse(any("lease ran out" in e["why"] for e in n["book_log"]))

    def test_the_task_messages_are_on_the_record(self):
        rows = message_log(self.team.deliveries, self.team.traces, self.team.start)
        kinds = {r["type"] for r in rows}
        self.assertLessEqual({"task_bid", "task_award", "task_accept", "task_complete"}, kinds)
        self.assertEqual({r["status"] for r in rows} - {"pending"}, {"delivered"})
        progress = [r for r in rows if r["type"] == "status_update" and r["sender"] == "Drone1"]
        self.assertTrue(progress)

    def test_every_decision_known_exactly(self):
        truth = Truth(TEAM, self.team.trajectories, self.team.start, self.team.report.until)
        entries = knowledge_log(self.team.traces, truth)
        self.assertTrue(all(e.ok for e in entries), [p for e in entries for p in e.problems][:5])

    def test_no_slower_than_the_hand_assignment(self):
        self.assertLessEqual(self.team.report.completion_s, 192.1)       # Phase 4's scripted, fixed assignment


class ContestedFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_team_on_mock(TEAM, contested(CONFIG), "contested", range_m=None)

    def test_the_same_division_after_the_conflict(self):
        self.assertTrue(self.flight.met)
        self.assertEqual(self.flight.searched, DIVISION)

    def test_every_book_logs_the_conflict_settled_by_the_rules(self):
        for d, n in self.flight.nets.items():
            self.assertEqual(sorted((c["task_id"], c["kept"], c["displaced"], c["rule"]) for c in n["corrections"]),
                             [("search S2", "Drone4", loser, "lowest valid bid") for loser in ("Drone1", "Drone2", "Drone3")],
                             d)

    def test_the_losers_claimed_again_and_flew_their_second_claim(self):
        for d in ("Drone1", "Drone2", "Drone3"):
            made = [c["task_id"] for c in self.flight.nets[d]["claims_made"]]
            self.assertEqual(made, ["search S2"] + DIVISION[d], d)

    def test_deterministic(self):
        again = fly_team_on_mock(TEAM, contested(CONFIG), "contested", range_m=None)
        self.assertEqual(again.nets, self.flight.nets)
        self.assertEqual({d: [(round(e.at, 6), e.decision.as_json()) for e in t] for d, t in again.team.traces.items()},
                         {d: [(round(e.at, 6), e.decision.as_json()) for e in t] for d, t in self.flight.team.traces.items()})


class HundredMetreRadioTests(unittest.TestCase):
    """The canonical 100 m radio, flown to keep its finding visible -- not part of Phase 8's exit."""

    def test_far_holders_lose_their_leases_and_sectors_are_searched_twice(self):
        run = fly_team_on_mock(TEAM, CONFIG, "100 m", range_m="scenario")
        expiries = sum("lease ran out" in e["why"] for n in run.nets.values() for e in n["book_log"])
        self.assertGreater(expiries, 0)
        self.assertGreater(len(sum(run.searched.values(), [])), 4)          # duplicate work
        self.assertEqual(sorted(set(sum(run.searched.values(), []))), ALL)


# ------------------------------------------------------- the policy, one reaction at a time

def belief_at(x=40.0, y=-10.0, airborne=True, battery=100.0, at=10.0):
    """Drone1's belief, out at (x, y) -- its home its pad, at the origin."""
    belief = BeliefState.start(BRIEF, "Drone1", Observation(at, x, y, 12.0 if airborne else 0.0, airborne, battery,
                                                            (), True, None, 0, None))
    belief.self_.home = (0.0, 0.0)
    return belief


def done(skill="TAKE_OFF", at=10.0):
    return (Event(Trigger.SKILL_SUCCEEDED, at, {"skill": skill, "status": "success"}),)


def news(what, at=10.0, **detail):
    return (Event(Trigger.MESSAGE, at, {"allocation": what, **detail}),)


def heard(net, kind, sender, payload, at=0.0, seq=1):
    return net.receive(new_message(kind, sender, BROADCAST, BRIEF.scenario_id, at, seq, payload), at)


class PolicyTests(unittest.TestCase):

    def policy(self, window=1.0):
        return TeamPolicy(ContractNet("Drone1", tasks_from_brief(BRIEF), AllocationConfig(BidWeights(), window, 2.0, 10.0)))

    def test_the_team_mission_takes_off_at_once(self):
        p = self.policy()
        d = p.decide(belief_at(0, 0, airborne=False, at=0.0),
                     (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": TEAM_MISSION, "team": True}),))
        self.assertEqual((d.kind, d.command.skill.value, p.stage), (DecisionKind.START, "TAKE_OFF", Stage.TAKING_OFF))

    def test_with_nothing_for_it_it_does_not_take_off(self):
        p = self.policy()
        b = belief_at(0, 0, airborne=False, battery=25.0, at=0.0)
        p.coordinate(b, [], 0.0)                                # bids nothing it could do: idle
        self.assertTrue(p.net.idle)
        d = p.decide(b, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": TEAM_MISSION, "team": True}),))
        self.assertEqual(d.kind, DecisionKind.FINISH)
        self.assertTrue(p.net.done)

    def test_airborne_with_no_task_it_holds_and_waits(self):
        p = self.policy()
        b = belief_at()
        p.coordinate(b, [], 10.0)                               # bids; the window has not passed
        p.stage = Stage.TAKING_OFF
        d = p.decide(b, done())
        self.assertEqual(d.command.skill.value, "HOLD_POSITION")
        self.assertTrue(p.waiting)
        self.assertEqual(b.mission.progress["stage"], "waiting")

    def test_a_claim_while_waiting_sends_it_to_the_sector(self):
        p = self.policy()
        b = belief_at()
        p.coordinate(b, [], 10.0)
        p.stage = Stage.TAKING_OFF
        p.decide(b, done())
        p.coordinate(b, [], 11.0)                               # the window has passed: it claims
        self.assertIsNotNone(p.net.holding)
        events = tuple(p.news())
        self.assertEqual([e.detail["allocation"] for e in events], ["claimed"])
        d = p.decide(b, events)
        self.assertIn(d.command.skill.value, ("FOLLOW_WAYPOINTS", "SEARCH_REGION"))
        self.assertFalse(p.waiting)
        self.assertEqual(b.self_.current_task, p.net.holding)

    def test_searched_with_nothing_left_it_completes_and_goes_home(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)                               # claims its best at once
        mine = p.net.holding
        for seq, t in enumerate(x for x in ALL if x != mine):
            heard(p.net, MessageType.TASK_COMPLETE, f"Drone{seq + 5}", {"task_id": t, "version": 1}, 10.0, seq + 1)
        p._take(b)
        p.stage = Stage.SEARCHING
        d = p.decide(b, done("SEARCH_REGION"))
        self.assertEqual(d.objective, "return home and report")
        self.assertIn("nothing left", d.reason)
        outs = p.drain()
        self.assertEqual([(o.kind, o.payload["task_id"]) for o in outs], [(MessageType.TASK_COMPLETE, mine)])
        self.assertEqual(p.completed, [mine])
        self.assertTrue(p.net.done)
        self.assertEqual(p.net.book.get(mine).status, TaskStatus.COMPLETE)

    def test_searched_with_work_left_it_waits_to_bid(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)
        p._take(b)
        p.stage = Stage.SEARCHING
        d = p.decide(b, done("SEARCH_REGION"))
        self.assertEqual(d.command.skill.value, "HOLD_POSITION")
        self.assertTrue(p.waiting)
        self.assertFalse(p.net.done)

    def test_a_shortfall_gives_the_task_back(self):
        p = self.policy(window=0.0)
        b = belief_at(battery=24.0)
        p.coordinate(belief_at(), [], 10.0)                     # claimed while the battery was full
        mine = p.net.holding
        p._take(b)
        p.stage = Stage.SEARCHING
        p.search_started_at = 10.0
        p.search_path = [(40.0, -10.0)] + p.lanes
        d = p.decide(b, (Event(Trigger.PERIODIC, 10.0),))
        self.assertEqual(d.objective, "return home and report")
        self.assertIn("low battery", d.reason)
        (out,) = p.drain()
        self.assertEqual((out.kind, out.payload["task_id"]), (MessageType.TASK_RELEASE, mine))
        self.assertEqual(p.net.book.get(mine).version, 2)
        self.assertTrue(p.net.done)

    def test_a_task_lost_in_flight_means_a_wait(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)
        mine = p.net.holding
        p.stage = Stage.TAKING_OFF
        p.decide(b, done())                                      # off to its sector
        heard(p.net, MessageType.TASK_AWARD, "Drone0", {"task_id": mine, "version": 1, "value": 0.5}, 10.5, 1)
        p.coordinate(b, [], 11.0)                                # settled: Drone0's lower bid wins
        self.assertNotEqual(p.net.holding, mine)
        d = p.decide(b, tuple(p.news()))
        self.assertIn(d.command.skill.value, ("HOLD_POSITION", "FOLLOW_WAYPOINTS", "SEARCH_REGION"))
        self.assertNotEqual(b.self_.current_task, mine)

    def test_a_second_task_is_costed_as_a_trip_out_to_it(self):
        # Waiting after its first search, it takes S3: the estimate runs from here to S3's lanes and through them.
        import math
        from agentic_uav.control.routing import length, route
        from agentic_uav.control.scripted import ZONE_CLEARANCE_M
        p = self.policy(window=0.0)
        b = belief_at(60.0, -40.0)
        for seq, t in enumerate(x for x in ALL if x != "search S3"):
            heard(p.net, MessageType.TASK_COMPLETE, f"Drone{seq + 5}", {"task_id": t, "version": 1}, 10.0, seq + 1)
        p.stage, p.waiting = Stage.SEARCHING, True
        p.coordinate(b, [], 10.0)                               # claims S3, the only task left
        self.assertEqual(p.net.holding, "search S3")
        p.decide(b, done("HOLD_POSITION"))
        zones = [z.polygon for z in BRIEF.restricted_zones]
        ahead = math.dist((60.0, -40.0), p.lanes[0]) + length(p.lanes)
        home = length(route(p.lanes[-1], (0.0, 0.0), zones, ZONE_CLEARANCE_M))
        self.assertIn(f"for {ahead + home:.0f} m", b.assumptions["fits"].evidence)

    def test_nothing_left_sends_a_waiting_drone_home_at_once(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)
        p._take(b)
        p.stage = Stage.SEARCHING
        p.decide(b, done("SEARCH_REGION"))                      # its task done; others still open: it waits
        self.assertTrue(p.waiting)
        p.news()
        for seq, t in enumerate(x for x in ALL if p.net.book.get(x).status is TaskStatus.OPEN):
            heard(p.net, MessageType.TASK_AWARD, f"Drone{seq + 5}", {"task_id": t, "version": 1, "value": 1.0}, 10.5, seq + 1)
        p.coordinate(b, [], 11.0)                               # all taken by others: nothing left for it
        events = tuple(p.news())
        self.assertIn("nothing left", [e.detail["allocation"] for e in events])
        d = p.decide(b, events)
        self.assertEqual(d.objective, "return home and report")
        self.assertIn("nothing left for it", d.reason)

    def test_a_drone_that_lost_its_task_is_not_costed_on_lanes_it_no_longer_has(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)
        mine = p.net.holding
        p.stage = Stage.TAKING_OFF
        p.decide(b, done())
        heard(p.net, MessageType.TASK_AWARD, "Drone0", {"task_id": mine, "version": 1, "value": 0.5}, 10.5, 1)
        p.coordinate(b, [], 11.0)
        p.decide(b, tuple(p.news()))
        if not p.waiting:                                       # it may have claimed another; make it wait
            p.waiting, p.task_id, p.lanes = True, None, []
        d = p.decide(b, (Event(Trigger.PERIODIC, 20.0),))       # no lanes: no estimate, no going home for it
        self.assertNotEqual(d.objective, "return home and report")

    def test_progress_is_how_far_along_its_lanes(self):
        p = self.policy(window=0.0)
        b = belief_at()
        p.coordinate(b, [], 10.0)
        p._take(b)
        self.assertEqual(p._progress(b), 0.0)                   # not yet searching
        p.stage = Stage.SEARCHING
        start, end = p.lanes[0], p.lanes[-1]
        self.assertAlmostEqual(p._progress(belief_at(*start)), 0.0, places=2)
        self.assertAlmostEqual(p._progress(belief_at(*end)), 1.0, places=2)
        mid = p.lanes[len(p.lanes) // 2]
        self.assertTrue(0.2 < p._progress(belief_at(*mid)) < 0.8)

    def test_a_plain_task_is_phase_5s(self):
        p = self.policy()
        d = p.decide(belief_at(0, 0, airborne=False, at=0.0),
                     (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S3"}),))
        self.assertEqual((d.command.skill.value, p.sector.id), ("TAKE_OFF", "S3"))


class AgentWiringTests(unittest.TestCase):

    def test_the_team_mission_needs_a_coordinator_and_a_coordinator_needs_comms(self):
        world = MockWorld(declared=["Drone1"])
        executor = ActionExecutor(SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
        sensors = mock_sensors(world, dataclasses.replace(TEAM, vehicles=TEAM.vehicles[:1]), "Drone1")
        policy = TeamPolicy(ContractNet("Drone1", tasks_from_brief(BRIEF), CONFIG))
        with self.assertRaises(ValueError):
            DroneAgent(BRIEF, sensors, executor, policy, coordinator=policy)
        with self.assertRaises(ValueError):
            DroneAgent(BRIEF, sensors, executor, policy).assign_team()


if __name__ == "__main__":
    unittest.main()
