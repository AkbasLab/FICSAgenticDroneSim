#!/usr/bin/env python3
"""Tests for agents that talk: heartbeats, status, what they take in, and what they estimate of the link.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 7's exit is that four agents exchange heartbeats and status while
flying and that their team beliefs update ONLY when messages are delivered.
These fly the canonical four on the mock with messaging on, and hold the
parts: a heartbeat a second and a status after each decision, numbered in one
sequence; every teammate record in every decision traced to a message that
was delivered to that drone before the decision; nothing out of range ever
believed; the link estimated from what was heard alone. And that talking
changes no decision -- in Phase 7 messages inform, they do not steer.
"""

import json
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import CONNECTED_WINDOW_S, BeliefState, Observation  # noqa: E402
from agentic_uav.agents.drone_agent import DroneAgent  # noqa: E402
from agentic_uav.agents.rule_policy import RulePolicy  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.action_executor import ActionExecutor  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.message_log import message_log, summary  # noqa: E402
from agentic_uav.experiments.single_agent import TEAM_TASKS, fly_agents_on_mock  # noqa: E402
from agentic_uav.simulator.message_bus import MessageBus  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.sensing import mock_sensors  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
PAIR = scenarios.load_scenario("search_pair_001")


def sent_by(rows, sender):
    """One row per message sent by `sender` (a broadcast has a row per recipient)."""
    first = {}
    for r in rows:
        if r["sender"] == sender:
            first.setdefault(r["message_id"], r)
    return sorted(first.values(), key=lambda r: int(r["message_id"].split("#")[1]))


class FourTalkingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.on = fly_agents_on_mock(TEAM, TEAM_TASKS, messaging=True)
        cls.off = fly_agents_on_mock(TEAM, TEAM_TASKS)
        cls.rows = message_log(cls.on.deliveries, cls.on.traces, cls.on.start)

    def test_they_complete_their_tasks(self):
        self.assertTrue(self.on.met, self.on.report.summary())

    def test_talking_changes_no_decision(self):
        # Plan, recommendation 4: heartbeats and status raise no event.
        for drone in TEAM_TASKS:
            with self.subTest(drone=drone):
                self.assertEqual([(e.at, e.decision.as_json(), e.verdict, e.action) for e in self.on.traces[drone]],
                                 [(e.at, e.decision.as_json(), e.verdict, e.action) for e in self.off.traces[drone]])
        self.assertEqual(self.on.report.as_json(), self.off.report.as_json())

    def test_a_heartbeat_a_second_and_a_status_after_each_decision(self):
        for drone in TEAM_TASKS:
            with self.subTest(drone=drone):
                mine = sent_by(self.rows, drone)
                beats = [r["created_s"] for r in mine if r["type"] == "heartbeat"]
                self.assertEqual({round(b - a, 6) for a, b in zip(beats, beats[1:])}, {1.0})
                decided_at = sorted({round(e.at - self.on.start, 3) for e in self.on.traces[drone]})
                status_at = [r["created_s"] for r in mine if r["type"] == "status_update"]
                self.assertEqual(status_at, decided_at)

    def test_numbered_in_one_sequence_from_one(self):
        for drone in TEAM_TASKS:
            seqs = [int(r["message_id"].split("#")[1]) for r in sent_by(self.rows, drone)]
            self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_team_beliefs_update_only_on_delivery(self):
        # The exit's real test: every teammate record in every decision came
        # in a message delivered to THAT drone, at or before the decision.
        delivered = {(r["recipient"], r["message_id"]): r["delivered_s"] for r in self.rows if r["status"] == "delivered"}
        created = {r["message_id"]: r["created_s"] for r in self.rows}
        checked = 0
        for drone, trace in self.on.traces.items():
            for e in trace:
                at = round(e.at - self.on.start, 3)
                for member, record in e.belief["team"].items():
                    if record == "never heard":
                        continue
                    checked += 1
                    key = (drone, record["message_id"])
                    self.assertIn(key, delivered, f"{drone} believed {key[1]} without delivery")
                    self.assertLessEqual(delivered[key], at)
                    self.assertEqual(record["message_id"].split("#")[0], member)
                    # What the record says is the message's: the teammate's
                    # task, and an age counted from when it was SENT.
                    self.assertEqual(record["task"], TEAM_TASKS[member])
                    self.assertAlmostEqual(record["age_s"], at - created[record["message_id"]], places=6)
        self.assertGreater(checked, 100)

    def test_nothing_out_of_range_is_ever_believed(self):
        never = {(r["recipient"], r["message_id"]) for r in self.rows if r["status"] != "delivered"}
        self.assertTrue(any(r["status"] == "out_of_range" for r in self.rows))
        for r in self.rows:
            if (r["recipient"], r["message_id"]) in never:
                self.assertIsNone(r["in_belief_at_s"])
                self.assertIsNone(r["read_by_policy_at_s"])

    def test_a_teammate_out_of_range_goes_stale(self):
        stale = [(d, m) for d, t in self.on.traces.items() for e in t
                 for m, rec in e.belief["team"].items() if isinstance(rec, dict) and not rec["current"]]
        self.assertTrue(stale)                     # heard once, then out of range long enough to expire

    def test_the_policy_reads_what_it_believes(self):
        s = summary(self.rows)
        self.assertGreater(s["read_by_policy"], 0)
        self.assertLessEqual(s["read_by_policy"], s["in_belief"])
        self.assertLessEqual(s["in_belief"], s["by_status"]["delivered"])

    def test_the_link_estimated_from_what_was_heard(self):
        for drone, trace in self.on.traces.items():
            for e in trace:
                c = e.belief["communication"]
                if c["estimated_latency_s"] == "unknown":
                    continue
                # Read at the next tick: a message is half a second old when taken in.
                self.assertEqual(c["estimated_latency_s"], 0.5)
                at = round(e.at - self.on.start, 3)
                heard = {r["sender"] for r in self.rows if r["recipient"] == drone and r["status"] == "delivered"
                         and at - CONNECTED_WINDOW_S <= r["delivered_s"] <= at}
                self.assertEqual(set(c["connected_peers"]), heard)
        losses = [e.belief["communication"]["recent_loss_rate"] for t in self.on.traces.values() for e in t]
        self.assertTrue(any(isinstance(x, float) and x > 0 for x in losses))        # out-of-range gaps

    def test_deterministic(self):
        again = fly_agents_on_mock(TEAM, TEAM_TASKS, messaging=True)
        self.assertEqual(message_log(again.deliveries, again.traces, again.start), self.rows)
        for drone in TEAM_TASKS:
            self.assertEqual([e.belief for e in again.traces[drone]], [e.belief for e in self.on.traces[drone]])


class UnlimitedRangeTests(unittest.TestCase):

    def test_no_gaps_when_nothing_is_out_of_range(self):
        run = fly_agents_on_mock(TEAM, TEAM_TASKS, messaging=True, range_m=None)
        rows = message_log(run.deliveries, run.traces, run.start)
        self.assertNotIn("out_of_range", summary(rows)["by_status"])
        losses = {e.belief["communication"]["recent_loss_rate"] for t in run.traces.values() for e in t}
        self.assertEqual(losses - {"unknown"}, {0.0})


class NotListeningTests(unittest.TestCase):

    def test_without_comms_the_link_stays_unknown(self):
        run = fly_agents_on_mock(PAIR)
        for trace in run.traces.values():
            for e in trace:
                c = e.belief["communication"]
                self.assertEqual((c["estimated_latency_s"], c["recent_loss_rate"], c["connected_peers"]),
                                 ("unknown", "unknown", "unknown"))
        self.assertEqual(run.deliveries, ())


class HeardTests(unittest.TestCase):
    """The link estimates, from arrivals alone."""

    def setUp(self):
        self.belief = BeliefState.start(TEAM.brief(), "Drone1",
                                        Observation(0.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        self.belief.listening = True

    def test_gaps_are_misses_and_late_ones_are_not_new(self):
        for seq, t in ((1, 0.0), (2, 1.0), (5, 4.0), (3, 2.0)):      # 3 and 4 missed; 3 turns up late
            self.belief.heard("Drone2", seq, t, t + 0.5)
        link = self.belief.links["Drone2"]
        self.assertEqual((link["last_seq"], link["received"], link["missed"]), (5, 4, 2))
        self.assertAlmostEqual(self.belief.communication.recent_loss_rate, 2 / 6)
        self.assertEqual(self.belief.communication.estimated_latency_s, 0.5)

    def test_connected_means_heard_lately(self):
        self.belief.heard("Drone2", 1, 0.0, 0.5)
        self.belief.heard("Drone3", 1, 2.0, 2.5)
        self.belief.update(Observation(4.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))
        self.assertEqual(self.belief.communication.connected_peers, ("Drone3",))     # Drone2 last heard 3.5 s ago
        self.assertEqual(self.belief.snapshot()["communication"]["connected_peers"], ["Drone3"])

    def test_latency_is_the_mean_of_the_last_ten(self):
        for seq in range(1, 13):
            self.belief.heard("Drone2", seq, float(seq), seq + (2.0 if seq <= 2 else 0.5))
        self.assertEqual(self.belief.communication.estimated_latency_s, 0.5)       # the two slow ones fell out

    def test_not_listening_estimates_nothing(self):
        self.belief.listening = False
        self.belief.heard("Drone2", 1, 0.0, 0.5)
        self.assertIsNone(self.belief.communication.estimated_latency_s)
        self.assertIsNone(self.belief.communication.connected_peers)


class AgentHandleTests(unittest.TestCase):

    def agent_with_comms(self, comms_for="Drone1"):
        world = MockWorld(declared=["Drone1", "Drone2"])
        bus = MessageBus(["Drone1", "Drone2"], world.clock, lambda d: (0.0, 0.0, 0.0), 100.0)
        executor = ActionExecutor(S.SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
        out = {}

        def body():
            with world.clock.participate():
                try:
                    out["agent"] = DroneAgent(PAIR.brief(), mock_sensors(world, PAIR, "Drone1"), executor,
                                              RulePolicy(), comms=bus.comms(comms_for))
                except ValueError as exc:
                    out["error"] = exc

        thread = threading.Thread(target=body)
        thread.start()
        thread.join()
        executor.close()
        return out

    def test_an_agent_holding_comms_reaches_no_bus(self):
        from test_sensing import ground_truth_reached
        agent = self.agent_with_comms()["agent"]
        self.assertEqual(ground_truth_reached(agent), [])
        self.assertTrue(agent.belief.listening)

    def test_it_will_not_take_another_drones_comms(self):
        out = self.agent_with_comms(comms_for="Drone2")
        self.assertIn("Drone1's agent was handed Drone2's comms", str(out["error"]))


if __name__ == "__main__":
    unittest.main()
