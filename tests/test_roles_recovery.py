"""Phase 9 tests. FICS's own build hit three real bugs here, all really one
issue (lease duration vs. skill duration) - these tests lock in the fixes
designed around them from the start: self-view survives lease expiry
(claimed_by), others'-view respects it (held_by), and health detection
short-circuits the lease entirely (release_if_failed). The integration test
is the actual exit criterion: kill one drone mid-mission, the survivors
detect it and finish all 4 sectors anyway.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief_schema import Provenance, TeammateRecord
from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.roles import HealthMonitor, HealthState
from fics_drone.coordination.tasks import TaskBoard, TaskStatus
from fics_drone.experiments.team_runner import run_team_with_faults
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


def _teammate(age_s: float, now: float, confidence: float = 1.0) -> TeammateRecord:
    return TeammateRecord(name="Drone2", last_known_position=(0.0, 0.0, 0.0),
                           provenance=Provenance(timestamp=now - age_s, source="heartbeat",
                                                  base_confidence=confidence))


class TestHealthMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = HealthMonitor(heartbeat_interval_s=10.0)

    def test_never_heard_from_is_healthy_not_failed(self):
        """A peer we've never heard from at all is unknown, not evidence of
        failure - it might just not have sent its first heartbeat yet."""
        self.assertEqual(self.monitor.classify(None, now=0.0), HealthState.HEALTHY)

    def test_fresh_contact_is_healthy(self):
        record = _teammate(age_s=1.0, now=10.0)
        self.assertEqual(self.monitor.classify(record, now=10.0), HealthState.HEALTHY)

    def test_single_missed_heartbeat_is_still_healthy(self):
        """One missed message is an ordinary comms gap, not suspicion - a
        team that declares failure on one missed heartbeat would pull
        sectors off healthy drones constantly."""
        record = _teammate(age_s=11.0, now=11.0)  # just over 1 interval
        self.assertEqual(self.monitor.classify(record, now=11.0), HealthState.HEALTHY)

    def test_several_missed_heartbeats_is_suspected(self):
        record = _teammate(age_s=25.0, now=25.0)  # 2.5 intervals
        self.assertEqual(self.monitor.classify(record, now=25.0), HealthState.SUSPECTED)

    def test_many_missed_heartbeats_is_unreachable(self):
        record = _teammate(age_s=50.0, now=50.0)  # 5 intervals
        self.assertEqual(self.monitor.classify(record, now=50.0), HealthState.UNREACHABLE)

    def test_prolonged_silence_is_failed(self):
        record = _teammate(age_s=90.0, now=90.0)  # 9 intervals
        self.assertEqual(self.monitor.classify(record, now=90.0), HealthState.FAILED)


class TestTaskBoardLeaseSemantics(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO_PATH)
        self.board = TaskBoard(self.scenario)
        self.task_id = "search_A"

    def test_claimed_by_ignores_lease_expiry(self):
        """FICS's bug #1: a drone must trust its own claim even if the lease
        clock is running low - it knows it's still mid-sweep."""
        self.board.apply_claim(self.task_id, "Drone1", bid=1.0, version=1, now=0.0, lease_s=5.0)
        # well past the 5s lease
        self.assertIn(self.task_id, self.board.claimed_by("Drone1"))

    def test_held_by_respects_lease_expiry(self):
        """Others'-view: the SAME claim, now judged by an outside agent -
        here the lease matters, on purpose."""
        self.board.apply_claim(self.task_id, "Drone1", bid=1.0, version=1, now=0.0, lease_s=5.0)
        self.assertEqual(self.board.held_by(self.task_id, now=3.0), "Drone1")  # still valid
        self.assertIsNone(self.board.held_by(self.task_id, now=10.0))  # lapsed

    def test_release_if_failed_short_circuits_the_lease(self):
        """FICS's bug #3: don't make the team wait out a 300s lease for a
        drone everyone already knows is gone."""
        self.board.apply_claim(self.task_id, "Drone1", bid=1.0, version=1, now=0.0, lease_s=300.0)
        self.assertEqual(self.board.held_by(self.task_id, now=1.0), "Drone1")  # lease nowhere near up
        released = self.board.release_if_failed(self.task_id, "Drone1")
        self.assertTrue(released)
        self.assertIsNone(self.board.held_by(self.task_id, now=1.0))  # available immediately

    def test_release_if_failed_does_nothing_for_the_wrong_agent(self):
        self.board.apply_claim(self.task_id, "Drone1", bid=1.0, version=1, now=0.0, lease_s=300.0)
        released = self.board.release_if_failed(self.task_id, "Drone2")
        self.assertFalse(released)
        self.assertEqual(self.board.tasks[self.task_id].status, TaskStatus.CLAIMED)

    def test_release_keeps_the_lamport_version_counting_up(self):
        """version is NOT reset on release - a later re-claim at a lower
        version could otherwise lose to a stale message still in flight
        referencing the old, higher version."""
        self.board.apply_claim(self.task_id, "Drone1", bid=1.0, version=5, now=0.0, lease_s=300.0)
        self.board.release_if_failed(self.task_id, "Drone1")
        self.assertEqual(self.board.next_version(self.task_id), 6)


class TestFailureRecoveryIntegration(unittest.TestCase):
    def test_killed_drones_sector_still_gets_completed_by_a_survivor(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        bus = MessageBus()

        # kill_at_s=0.0 fires on the very first loop iteration, before TAKE_OFF -
        # deterministically "did nothing at all", not racing against how quickly
        # Drone2 might have genuinely finished its own sector first (found live:
        # at kill_at_s=5.0, Drone2 sometimes legitimately completed and reported
        # before the kill check next ran, since the kill is only checked between
        # loop iterations - a flaky test design, not a code bug).
        reports, agents, bus, assignment = run_team_with_faults(
            scenario, adapters, bus=bus, kill_name="Drone2", kill_at_s=0.0, heartbeat_interval_s=2.0)

        self.assertEqual(len(reports), 4)
        killed_trace = reports["Drone2"].trace
        self.assertTrue(killed_trace)
        self.assertIn("killed", killed_trace[-1])

        # The actual exit criterion: every sector still gets searched, even Drone2's -
        # checked against the UNION of completion status across every survivor's own
        # board, not one agent's alone, and not any agent's final sector_id. Each
        # agent's board is frozen at whatever it last observed before landing and
        # going quiet - the one that finishes first (Drone1 here, landing at ~9s) never
        # hears about completions broadcast later by agents still mid-mission, so no
        # single board is guaranteed complete on its own; the union across all of them is.
        completed_sector_ids = set()
        completed_by = set()
        for n in agents:
            if n == "Drone2":
                continue
            for t in agents[n].task_board.tasks.values():
                if t.status == TaskStatus.COMPLETE:
                    completed_sector_ids.add(t.sector_id)
                    completed_by.add(t.assignee)
        self.assertEqual(completed_sector_ids, {s.id for s in scenario.sectors})
        self.assertNotIn("Drone2", completed_by)  # never searched by the dead drone

    def test_killed_drone_never_sends_a_final_heartbeat_or_claim(self):
        """No flight, no sensing, no heartbeats, nobody told - a real crash
        looks like silence, not a graceful goodbye message. kill_at_s=0.0:
        dies before TAKE_OFF, so it should send nothing but its allocation
        bids/claim (which happen before PersistentAgent.run() even starts)."""
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        bus = MessageBus()

        run_team_with_faults(scenario, adapters, bus=bus, kill_name="Drone2", kill_at_s=0.0,
                              heartbeat_interval_s=2.0)

        sent_by_drone2 = [e for e in bus.log if e.sender == "Drone2"]
        self.assertTrue(all(e.type in ("task_bid", "task_claim") for e in sent_by_drone2))


if __name__ == "__main__":
    unittest.main()
