"""Phase 7 tests. The blackout test is the strongest check per FICS's own
doc: rerun the real mission with a bus that delivers nothing and assert team
belief stays completely empty - proving belief updates only via delivered
messages, never a back channel."""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.protocols import Message, MessageType
from fics_drone.experiments.team_runner import run_team_threaded
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


class TestEnvelope(unittest.TestCase):
    def test_expires_at_is_created_plus_ttl(self):
        msg = Message(id=1, type=MessageType.TARGET_FOUND, sender="Drone1", recipients=None,
                       created_t=10.0, ttl_s=5.0, payload={})
        self.assertEqual(msg.expires_at(), 15.0)


class TestMessageBus(unittest.TestCase):
    def test_broadcast_reaches_everyone_but_the_sender(self):
        bus = MessageBus()
        for name in ("A", "B", "C"):
            bus.register(name)
        bus.send(MessageType.TARGET_FOUND, "A", {"target_id": "T1"})
        self.assertEqual(bus.receive_available("A"), [])
        self.assertEqual(len(bus.receive_available("B")), 1)
        self.assertEqual(len(bus.receive_available("C")), 1)

    def test_explicit_recipients_only_reach_those_named(self):
        bus = MessageBus()
        for name in ("A", "B", "C"):
            bus.register(name)
        bus.send(MessageType.HEARTBEAT, "A", {}, recipients=["B"])
        self.assertEqual(len(bus.receive_available("B")), 1)
        self.assertEqual(bus.receive_available("C"), [])

    def test_receive_available_drains_the_inbox(self):
        bus = MessageBus()
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.HEARTBEAT, "A", {})
        self.assertEqual(len(bus.receive_available("B")), 1)
        self.assertEqual(bus.receive_available("B"), [])  # already drained

    def test_blackout_delivers_nothing_and_logs_why(self):
        bus = MessageBus(drop_all=True)
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.TARGET_FOUND, "A", {"target_id": "T1"})
        self.assertEqual(bus.receive_available("B"), [])
        self.assertTrue(all(e.reason == "blackout" for e in bus.log))

    def test_log_records_sender_recipient_and_type(self):
        bus = MessageBus()
        bus.register("A")
        bus.register("B")
        bus.send(MessageType.TARGET_FOUND, "A", {"target_id": "T1"}, recipients=["B"])
        self.assertEqual(len(bus.log), 1)
        entry = bus.log[0]
        self.assertEqual(entry.sender, "A")
        self.assertEqual(entry.recipient, "B")
        self.assertEqual(entry.type, "target_found")
        self.assertTrue(entry.delivered)


class TestAgentLink(unittest.TestCase):
    def test_link_exposes_only_send_and_receive_available(self):
        bus = MessageBus()
        link = AgentLink(bus, "A")
        public_methods = {name for name, _ in inspect.getmembers(link, predicate=inspect.ismethod)
                           if not name.startswith("_")}
        self.assertEqual(public_methods, {"send", "receive_available"})

    def test_link_cannot_see_another_agents_inbox(self):
        bus = MessageBus()
        link_a = AgentLink(bus, "A")
        AgentLink(bus, "B")
        bus.send(MessageType.TARGET_FOUND, "B", {"target_id": "T1"})
        # A has no way to read B's inbox or the bus's internal state through its link
        self.assertFalse(hasattr(link_a, "inboxes"))
        self.assertFalse(hasattr(link_a, "peers"))


class TestTeamMissionIntegration(unittest.TestCase):
    def _run(self, blackout=False):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        bus = MessageBus(drop_all=blackout)
        reports, agents, bus = run_team_threaded(scenario, adapters, bus=bus)
        return scenario, reports, agents, bus

    def test_every_agent_completes_with_messaging_enabled(self):
        _, reports, _, _ = self._run()
        for name, report in reports.items():
            self.assertIsNotNone(report)  # ran to completion without raising

    def test_sector_without_its_own_target_learns_both_targets_second_hand(self):
        """The actual exit criterion: Drone2 (sector B) and Drone3 (sector C)
        have no target of their own, but should still end up knowing about
        BOTH T1 (Drone1/sector A) and T2 (Drone4/sector D) - recorded as
        second-hand, never as their own sensor reading."""
        _, _, agents, _ = self._run()
        for name in ("Drone2", "Drone3"):
            known = agents[name].belief.mission.targets_known
            self.assertIn("T1", known)
            self.assertIn("T2", known)
            self.assertEqual(known["T1"].source, "message")
            self.assertEqual(known["T2"].source, "message")

    def test_sector_with_its_own_target_knows_it_first_hand(self):
        _, _, agents, _ = self._run()
        sighting = agents["Drone1"].belief.mission.targets_known["T1"]
        self.assertEqual(sighting.source, "sensor")

    def test_blackout_leaves_other_sectors_with_no_second_hand_knowledge(self):
        """The strongest check: same mission, a bus that delivers nothing.
        Every agent still finds its OWN sector's target by sensing (Phase 6
        behavior, unaffected by messaging), but must never learn about a
        target outside its own sector without a delivered message."""
        _, _, agents, bus = self._run(blackout=True)
        self.assertTrue(bus.log)
        self.assertTrue(all(not e.delivered for e in bus.log))

        self.assertNotIn("T2", agents["Drone2"].belief.mission.targets_known)
        self.assertNotIn("T1", agents["Drone3"].belief.mission.targets_known)
        self.assertEqual(agents["Drone2"].belief.mission.targets_known, {})
        self.assertEqual(agents["Drone3"].belief.mission.targets_known, {})

        # the sectors that DO have a target still find it - by sensing, not messaging
        self.assertIn("T1", agents["Drone1"].belief.mission.targets_known)
        self.assertIn("T2", agents["Drone4"].belief.mission.targets_known)


if __name__ == "__main__":
    unittest.main()
