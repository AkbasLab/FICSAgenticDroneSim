#!/usr/bin/env python3
"""Tests for the message log, and how a decision is tied to the messages it rested on (AUV-07, 7.4).

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-07 asks the log for every message's fate and "whether the message
influenced a decision". That needs a chain with no gaps: a team record keeps
the message that made it; the belief notes which records the policy read
while deciding -- and not what the validation step read after; the agent
keeps those ids with the decision; and the log joins the bus's record to the
recipient's trace. Each link is held here, and the log's every column.
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
from agentic_uav.agents.decision import Decision  # noqa: E402
from agentic_uav.agents.drone_agent import DroneAgent  # noqa: E402
from agentic_uav.agents.rule_policy import RulePolicy  # noqa: E402
from agentic_uav.agents.validation import validate  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.core.team import TeamReport  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.message_log import message_log, summary  # noqa: E402
from agentic_uav.simulator.message_bus import MessageBus  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
PAIR = scenarios.load_scenario("search_pair_001")


def obs(at):
    return Observation(at, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None)


def heard(drone="Drone2", at=1.0, mid="Drone2#1", **kw):
    return TeamReport(drone, at, "message", position=(5.0, 5.0, 12.0), message_id=mid, **kw)


class RecordKeepsItsMessageTests(unittest.TestCase):

    def test_the_snapshot_names_the_message(self):
        belief = BeliefState.start(TEAM.brief(), "Drone1", obs(0.0))
        self.assertIsNone(TeamReport("Drone2", 0.0, "message").message_id)
        belief.receive(heard(), now=1.0)
        belief.update(obs(1.5))
        snap = belief.snapshot()["team"]
        self.assertEqual(snap["Drone2"]["message_id"], "Drone2#1")
        self.assertEqual(snap["Drone3"], "never heard")


class WhatThePolicyReadTests(unittest.TestCase):

    def setUp(self):
        self.belief = BeliefState.start(TEAM.brief(), "Drone1", obs(0.0))
        self.belief.receive(heard("Drone2", 1.0, "Drone2#1"), now=1.0)
        self.belief.receive(heard("Drone3", 1.0, "Drone3#4", ttl_s=0.5), now=1.0)      # expires at 1.5
        self.belief.receive(TeamReport("Drone4", 1.0, "base", position=(1.0, 1.0, 1.0)), now=1.0)   # no message
        self.belief.update(obs(2.0))

    def test_reading_through_the_accessors_is_noted(self):
        self.belief.start_reading()
        self.assertEqual(self.belief.read(), ())
        self.belief.current_teammates()
        self.assertEqual(self.belief.read(), ("Drone2#1",))          # Drone3 has expired; Drone4 came in no message
        self.belief.teammate("Drone3")                               # asked for by name, expired or not: read
        self.assertEqual(self.belief.read(), ("Drone2#1", "Drone3#4"))
        self.belief.teammate("Drone4")
        self.assertEqual(self.belief.read(), ("Drone2#1", "Drone3#4"))

    def test_each_decision_starts_afresh(self):
        self.belief.start_reading()
        self.belief.current_teammates()
        self.belief.start_reading()
        self.assertEqual(self.belief.read(), ())

    def test_the_rule_policy_reads_its_teammates(self):
        policy = RulePolicy()
        self.belief.start_reading()
        policy.decide(self.belief, (Event(Trigger.TASK_ASSIGNED, 2.0, {"task": "search S1"}),))
        self.assertEqual(self.belief.read(), ("Drone2#1",))
        self.assertIn("current reports from Drone2", self.belief.assumptions["teammates"].evidence)


class Reader:
    """A policy that reads one teammate's record, then flies a take-off and finishes."""

    def __init__(self, who="Drone2"):
        self.who, self.done = who, False

    def decide(self, belief, events):
        belief.teammate(self.who)
        if any(e.trigger is Trigger.TASK_ASSIGNED for e in events):
            return Decision.start(S.TakeOffCommand(altitude_m=10), "up", "test")
        self.done = True
        return Decision.finish(reason="done")


class ReadsOnce(Reader):
    """Reads its teammate on the first decision only."""

    def decide(self, belief, events):
        if any(e.trigger is Trigger.TASK_ASSIGNED for e in events):
            belief.teammate(self.who)
            return Decision.start(S.TakeOffCommand(altitude_m=10), "up", "test")
        return Decision.finish(reason="done")


class AgentKeepsWhatItReadTests(unittest.TestCase):

    def fly(self, policy, validator=validate):
        world = MockWorld(declared=["Drone1", "Drone2"])
        for v in PAIR.vehicles:
            MockVehicleAdapter(world).place_vehicle(v.id, S.Position(v.start_x, v.start_y, world.ground_z))
        executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
        out = {}

        def body():
            with world.clock.participate():
                agent = DroneAgent(PAIR.brief(), mock_sensors(world, PAIR, "Drone1"), executor, policy,
                                   validator=validator)
                agent.belief.receive(heard("Drone2", 0.0, "Drone2#7"), now=0.0)
                agent.assign("anything")
                agent.run(max_s=60.0)
                out["agent"] = agent

        thread = threading.Thread(target=body)
        thread.start()
        thread.join()
        executor.close()
        return out["agent"]

    def test_the_trace_keeps_the_ids_the_policy_read(self):
        agent = self.fly(Reader())
        self.assertEqual(agent.trace[0].read, ("Drone2#7",))
        self.assertEqual(json.loads(json.dumps(agent.trace[0].as_json()))["read"], ["Drone2#7"])

    def test_what_the_validation_step_reads_does_not_count(self):
        def nosy(decision, belief):
            belief.teammate("Drone2")                                 # read, but not by the policy
            return validate(decision, belief)
        agent = self.fly(Reader(), validator=nosy)
        first = agent.trace[0]
        self.assertEqual(first.read, ("Drone2#7",))                   # the policy's own read, and only that
        quiet = self.fly(Script(), validator=nosy)
        self.assertEqual(quiet.trace[0].read, ())

    def test_each_decision_keeps_only_its_own_reading(self):
        agent = self.fly(ReadsOnce())
        self.assertEqual([e.read for e in agent.trace], [("Drone2#7",), ()])

    def test_a_refused_decision_keeps_what_it_read(self):
        def never(decision, belief):
            from agentic_uav.agents.validation import Verdict
            return Verdict(False, ("test refusal",))
        agent = self.fly(Reader(), validator=never)
        refused = [e for e in agent.trace if e.action == "refused"]
        self.assertTrue(refused)
        self.assertTrue(all(e.read == ("Drone2#7",) for e in refused))


class Script:
    """Reads nothing: take off, then finish."""

    def decide(self, belief, events):
        if any(e.trigger is Trigger.TASK_ASSIGNED for e in events):
            return Decision.start(S.TakeOffCommand(altitude_m=10), "up", "test")
        return Decision.finish(reason="done")


DRONES = ("Drone1", "Drone2", "Drone3", "Drone4")


def beat(sender, seq, at, to=BROADCAST, ttl_s=None):
    return new_message(MessageType.HEARTBEAT, sender, to, "m", at, seq,
                       {"position": [0.0, 0.0, 10.0], "airborne": True, "battery": 90.0,
                        "task": None, "stage": None}, ttl_s=ttl_s)


class MessageLogTests(unittest.TestCase):

    def setUp(self):
        self.clock = SimClock(1000.0)                                 # a clock that does not start at 0
        at = {"Drone1": (0.0, 0.0, 10.0), "Drone2": (60.0, 0.0, 10.0), "Drone3": (0.0, 80.0, 10.0),
              "Drone4": (300.0, 0.0, 10.0)}
        self.bus = MessageBus(DRONES, self.clock, at.__getitem__, 100.0, mission_id="m")
        self.m1 = beat("Drone1", 1, 1000.0)
        self.bus.comms("Drone1").send(self.m1)                        # D2, D3 in range; D4 300 m out
        self.clock.sleep(0.5)
        self.bus.comms("Drone2").receive_available()                  # D2 reads it at 1000.5
        self.m2 = beat("Drone1", 2, 1000.5, to=("Drone3",), ttl_s=1.0)
        self.bus.comms("Drone1").send(self.m2)
        self.clock.sleep(2.0)
        self.bus.comms("Drone3").receive_available()                  # at 1002.5: m1 delivered, m2 expired
        self.m3 = beat("Drone1", 3, 1002.5, to=("Drone2",))
        self.bus.comms("Drone1").send(self.m3)                        # never read: pending at the end
        decision = lambda at, ids, read: {"at": at, "belief": {"team": {
            "Drone1": {"message_id": i} if i else "never heard" for i in ids}}, "read": read}
        self.traces = {
            "Drone2": [decision(1000.5, [None], []),                   # before it is in the belief
                       decision(1001.0, ["Drone1#1"], []),             # in the belief, not read
                       decision(1003.0, ["Drone1#1"], ["Drone1#1"]),   # read
                       decision(1004.0, ["Drone1#1"], ["Drone1#1"])],  # read again: the first time counts
            "Drone3": [decision(1002.5, ["Drone1#1"], ["Drone1#1"])],
        }
        self.rows = message_log(self.bus.deliveries(), self.traces, start=1000.0)

    def row(self, mid, recipient):
        return next(r for r in self.rows if r["message_id"] == mid and r["recipient"] == recipient)

    def test_every_column_auv_07_asks_for(self):
        r = self.row("Drone1#1", "Drone2")
        self.assertEqual(r, {"message_id": "Drone1#1", "type": "heartbeat", "sender": "Drone1", "recipient": "Drone2",
                             "created_s": 0.0, "sent_s": 0.0, "scheduled_s": 0.0, "delivered_s": 0.5,
                             "status": "delivered", "size_bytes": self.m1.size_bytes(), "expires_s": 3.0,
                             "distance_m": 60.0, "in_belief_at_s": 1.0, "read_by_policy_at_s": 3.0})

    def test_what_was_not_delivered_and_why(self):
        far = self.row("Drone1#1", "Drone4")
        self.assertEqual((far["status"], far["scheduled_s"], far["delivered_s"], far["distance_m"]),
                         ("out_of_range", None, None, 300.0))
        late = self.row("Drone1#2", "Drone3")
        self.assertEqual((late["status"], late["delivered_s"], late["expires_s"]), ("expired", None, 1.5))
        waiting = self.row("Drone1#3", "Drone2")
        self.assertEqual((waiting["status"], waiting["delivered_s"]), ("pending", None))

    def test_influence_at_two_levels(self):
        self.assertEqual((self.row("Drone1#1", "Drone3")["in_belief_at_s"],
                          self.row("Drone1#1", "Drone3")["read_by_policy_at_s"]), (2.5, 2.5))
        for mid, who in (("Drone1#1", "Drone4"), ("Drone1#2", "Drone3"), ("Drone1#3", "Drone2")):
            with self.subTest(message=mid, recipient=who):
                r = self.row(mid, who)
                self.assertEqual((r["in_belief_at_s"], r["read_by_policy_at_s"]), (None, None))

    def test_influence_is_the_recipients_own(self):
        # Drone2 read Drone1#1; that says nothing about Drone4, which never got it.
        self.assertIsNotNone(self.row("Drone1#1", "Drone2")["read_by_policy_at_s"])
        self.assertIsNone(self.row("Drone1#1", "Drone4")["read_by_policy_at_s"])

    def test_the_summary(self):
        s = summary(self.rows)
        self.assertEqual(s["deliveries"], 5)                       # the broadcast to three, and one each to two
        self.assertEqual(s["by_status"], {"delivered": 2, "expired": 1, "out_of_range": 1, "pending": 1})
        self.assertEqual(s["by_type"], {"heartbeat": 5})
        self.assertEqual(s["bytes_sent"], sum(r["size_bytes"] for r in self.rows))
        self.assertEqual(s["bytes_delivered"], 2 * self.m1.size_bytes())
        self.assertEqual((s["in_belief"], s["read_by_policy"]), (2, 2))

    def test_a_phase_6_snapshot_without_message_ids(self):
        # A team record from before Phase 7 has no message_id: nothing to
        # join, and nothing to break.
        old = {"Drone2": [{"at": 1001.0, "belief": {"team": {"Drone1": {"position": [0.0, 0.0, 10.0], "current": True}}}}]}
        rows = message_log(self.bus.deliveries(), old, start=1000.0)
        self.assertEqual({(r["in_belief_at_s"], r["read_by_policy_at_s"]) for r in rows}, {(None, None)})

    def test_trace_entries_or_their_json(self):
        class Entry:
            def __init__(self, row):
                self.row = row

            def as_json(self):
                return self.row
        objects = {d: [Entry(e) for e in t] for d, t in self.traces.items()}
        self.assertEqual(message_log(self.bus.deliveries(), objects, start=1000.0), self.rows)


if __name__ == "__main__":
    unittest.main()
