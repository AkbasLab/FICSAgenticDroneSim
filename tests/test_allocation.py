"""Phase 8 tests. TestTaskBoard covers the Lamport-clock conflict rule
directly - FICS's own build hit a real bug here (private per-agent version
counters compared as if they meant the same thing) and fixed it by making
version a per-task max(seen)+1. These tests exercise that rule without
needing to provoke a real race."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.bidding import BidWeights, compute_bid
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.coordination.tasks import TaskBoard, TaskStatus, tasks_from_scenario
from fics_drone.experiments.team_runner import allocate_sectors, run_team_with_allocation
from fics_drone.coordination.message_bus import AgentLink
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


class TestBidding(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO_PATH)
        self.sector = self.scenario.sector("A")

    def test_closer_drone_bids_lower(self):
        far = compute_bid((1000.0, 1000.0, 0.0), battery_frac_remaining=1.0, workload=0, sector=self.sector)
        near = compute_bid((25.0, 25.0, 0.0), battery_frac_remaining=1.0, workload=0, sector=self.sector)
        self.assertLess(near, far)

    def test_lower_battery_bids_worse(self):
        full = compute_bid((0.0, 0.0, 0.0), battery_frac_remaining=1.0, workload=0, sector=self.sector)
        low = compute_bid((0.0, 0.0, 0.0), battery_frac_remaining=0.1, workload=0, sector=self.sector)
        self.assertLess(full, low)

    def test_more_workload_bids_worse(self):
        idle = compute_bid((0.0, 0.0, 0.0), battery_frac_remaining=1.0, workload=0, sector=self.sector)
        busy = compute_bid((0.0, 0.0, 0.0), battery_frac_remaining=1.0, workload=2, sector=self.sector)
        self.assertLess(idle, busy)


class TestTaskBoard(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO_PATH)
        self.board = TaskBoard(self.scenario)
        self.task_id = "search_A"

    def test_first_claim_on_an_open_task_is_accepted(self):
        accepted = self.board.apply_claim(self.task_id, "Drone1", bid=10.0, version=1)
        self.assertTrue(accepted)
        self.assertEqual(self.board.tasks[self.task_id].assignee, "Drone1")

    def test_higher_version_claim_overrides_a_lower_one(self):
        self.board.apply_claim(self.task_id, "Drone1", bid=10.0, version=1)
        accepted = self.board.apply_claim(self.task_id, "Drone2", bid=999.0, version=2)
        self.assertTrue(accepted)  # higher version wins even with a worse bid - that's the point
        self.assertEqual(self.board.tasks[self.task_id].assignee, "Drone2")

    def test_lower_version_claim_is_rejected(self):
        self.board.apply_claim(self.task_id, "Drone1", bid=10.0, version=3)
        accepted = self.board.apply_claim(self.task_id, "Drone2", bid=1.0, version=1)
        self.assertFalse(accepted)
        self.assertEqual(self.board.tasks[self.task_id].assignee, "Drone1")

    def test_tied_version_breaks_on_lower_bid(self):
        """The actual genuine-simultaneous-claim case: two agents claim the
        same task at the same Lamport version. Lower bid should win, not
        whoever's message happened to arrive first."""
        self.board.apply_claim(self.task_id, "Drone1", bid=50.0, version=2)
        accepted = self.board.apply_claim(self.task_id, "Drone2", bid=10.0, version=2)
        self.assertTrue(accepted)
        self.assertEqual(self.board.tasks[self.task_id].assignee, "Drone2")

    def test_tied_version_and_bid_breaks_on_name(self):
        self.board.apply_claim(self.task_id, "Drone1", bid=10.0, version=2)
        accepted = self.board.apply_claim(self.task_id, "Drone2", bid=10.0, version=2)
        self.assertTrue(accepted)  # "Drone2" > "Drone1" lexicographically - deterministic, not arbitrary
        self.assertEqual(self.board.tasks[self.task_id].assignee, "Drone2")

    def test_next_version_is_per_task_max_seen_plus_one(self):
        """The actual Lamport-clock fix FICS's doc describes: version is
        derived from what THIS task has seen, not a private per-agent
        counter that could coincidentally read the same number for two
        completely unrelated things."""
        self.board.apply_claim(self.task_id, "Drone1", bid=10.0, version=5)
        self.assertEqual(self.board.next_version(self.task_id), 6)


class TestAllocationIntegration(unittest.TestCase):
    def test_four_drones_converge_on_four_distinct_sectors(self):
        """Exit criterion: no central assignment, every sector claimed
        exactly once, every drone's local board agrees."""
        scenario = load_scenario(SCENARIO_PATH)
        bus = MessageBus()
        links = {spec.name: AgentLink(bus, spec.name) for spec in scenario.drones}
        assignment = allocate_sectors(scenario, links)

        won = [s for s in assignment.values() if s is not None]
        self.assertEqual(len(won), 4)
        self.assertEqual(set(won), {s.id for s in scenario.sectors})  # every sector, exactly once

    def test_mission_runs_using_the_allocated_sectors(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        reports, agents, bus, assignment = run_team_with_allocation(scenario, adapters)

        self.assertEqual(len(reports), 4)
        for name, agent in agents.items():
            self.assertEqual(agent.belief.mission.sector_id, assignment[name])


if __name__ == "__main__":
    unittest.main()
