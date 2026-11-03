"""Separation looks at where teammates are going and at the route, and a blocked drone waits instead of giving up.

Found live on 2026-11-02: two drones sent to the same sector corner from different sides each passed the guardian
(it compared only the target with a teammate's last reported position) and met 0.5 m and 0.09 m apart.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, Provenance, SelfState, TeammateRecord
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.safety_guardian import Command, GuardianOutcome, SafetyGuardian, SafetyLimits
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.protocols import MessageType
from fics_drone.core.scenario import load_scenario
from fics_drone.agents.objectives import ReplanEvent
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


def _guardian():
    return SafetyGuardian(limits=SafetyLimits.from_scenario(load_scenario(SCENARIO_PATH)))


def _belief(t=10.0, mate=None):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 12.0), elapsed_s=t, battery_s=300.0),
               mission=MissionBelief(sector_id="A", search_queue=[]))
    if mate is not None:
        b.team.teammates["Drone1"] = mate
    return b


def _mate(position, heading_to=None, heard_at=10.0):
    return TeammateRecord(name="Drone1", last_known_position=position,
                          provenance=Provenance(timestamp=heard_at, source="heartbeat"), heading_to=heading_to)


def _fly(x, y):
    return Command(kind="fly", target=(x, y, 12.0), speed_mps=5.0, timeout_s=30.0, purpose="mission")


class TestSeparationLooksAhead(unittest.TestCase):
    def test_a_target_a_teammate_has_announced_is_refused(self):
        """Drone1 set off for the corner (20, 20); Drone2 asking for the same corner is refused while it is en route."""
        belief = _belief(mate=_mate((0.0, 0.0, 12.0), heading_to=(20.0, 20.0, 12.0)))
        evaluation = _guardian().evaluate(_fly(20.0, 20.0), belief, position_world=(0.0, 20.0, 12.0))
        self.assertEqual(evaluation.outcome, GuardianOutcome.REJECT_AND_REPLAN)
        self.assertEqual(evaluation.failed_checks, ["separation"])

    def test_an_old_announcement_stops_counting(self):
        belief = _belief(t=100.0, mate=_mate((0.0, 0.0, 12.0), heading_to=(20.0, 20.0, 12.0), heard_at=10.0))
        evaluation = _guardian().evaluate(_fly(20.0, 20.0), belief, position_world=(0.0, 20.0, 12.0))
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE)

    def test_a_route_that_passes_close_to_a_teammate_is_refused_though_the_target_is_far(self):
        belief = _belief(mate=_mate((10.0, 10.0, 12.0)))
        evaluation = _guardian().evaluate(_fly(30.0, 30.0), belief, position_world=(0.0, 0.0, 12.0))
        self.assertEqual(evaluation.failed_checks, ["separation"])
        self.assertIn("path", evaluation.reason)

    def test_a_route_that_keeps_clear_is_approved(self):
        belief = _belief(mate=_mate((10.0, 25.0, 12.0)))
        evaluation = _guardian().evaluate(_fly(30.0, 30.0), belief, position_world=(0.0, 0.0, 12.0))
        self.assertEqual(evaluation.outcome, GuardianOutcome.APPROVE)

    def test_without_the_aircrafts_own_position_only_the_target_is_checked(self):
        belief = _belief(mate=_mate((10.0, 10.0, 12.0)))
        self.assertEqual(_guardian().evaluate(_fly(30.0, 30.0), belief).outcome, GuardianOutcome.APPROVE)

    def test_going_home_is_never_blocked_by_a_teammate(self):
        belief = _belief(mate=_mate((10.0, 10.0, 12.0), heading_to=(0.0, 0.0, 12.0)))
        home = Command(kind="fly", target=(0.0, 0.0, 12.0), speed_mps=5.0, timeout_s=30.0, purpose="home")
        self.assertEqual(_guardian().evaluate(home, belief, position_world=(20.0, 20.0, 12.0)).outcome,
                         GuardianOutcome.APPROVE)


class TestWaitingOutAConflict(unittest.TestCase):
    def _agent(self, bus):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.name == "Drone2")
        return PersistentAgent(KinematicMockVehicleAdapter("Drone2", speed_mps=15.0), scenario, spec.sector,
                               spec.spawn_offset, spec.battery_s, drone_name="Drone2",
                               link=AgentLink(bus, "Drone2"))

    def test_a_blocked_drone_holds_until_the_teammate_has_moved_on_then_flies(self):
        bus = MessageBus()
        agent = self._agent(bus)
        mate_link = AgentLink(bus, "Drone1")
        # Drone2 is told Drone1 is heading for the corner it wants
        agent.belief.team.teammates["Drone1"] = _mate((0.0, 0.0, 12.0), heading_to=(-20.0, 20.0, 12.0), heard_at=0.0)
        trace = []

        def teammate_moves_on():
            time.sleep(1.0)
            mate_link.send(MessageType.HEARTBEAT, {"position": [-40.0, 40.0, 12.0], "battery_frac": 1.0,
                                                    "role": "scout"})

        threading.Thread(target=teammate_moves_on).start()
        started = time.monotonic()
        event = agent._guarded_fly((-20.0, 0.0, 12.0), trace)   # local to Drone2's spawn: world (-20, 20)
        self.assertEqual(event, ReplanEvent.SKILL_SUCCEEDED, trace)
        self.assertTrue(any(step.startswith("waited_for_separation") for step in trace), trace)
        self.assertLess(time.monotonic() - started, 15.0)
        self.assertEqual(agent.guardian.consecutive_rejections, 0)

    def test_a_teammate_that_never_moves_still_ends_in_a_plain_block_after_the_wait(self):
        import fics_drone.agents.persistent_agent as module
        bus = MessageBus()
        agent = self._agent(bus)
        agent.belief.team.teammates["Drone1"] = _mate((0.0, 0.0, 12.0), heading_to=(-20.0, 20.0, 12.0), heard_at=0.0)
        trace = []
        original = module.SEPARATION_WAIT_S
        module.SEPARATION_WAIT_S = 4.0
        try:
            event = agent._guarded_fly((-20.0, 0.0, 12.0), trace)
        finally:
            module.SEPARATION_WAIT_S = original
        self.assertEqual(event, ReplanEvent.GUARDIAN_BLOCKED, trace)
        self.assertTrue(any(step.startswith("waited_for_separation") for step in trace), trace)

    def test_a_solo_agent_never_waits(self):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.name == "Drone2")
        solo = PersistentAgent(KinematicMockVehicleAdapter("Drone2", speed_mps=15.0), scenario, spec.sector,
                               spec.spawn_offset, spec.battery_s, drone_name="Drone2")
        trace = []
        self.assertEqual(solo._guarded_fly((-20.0, 0.0, 12.0), trace), ReplanEvent.SKILL_SUCCEEDED, trace)
        self.assertFalse(any("waited" in step for step in trace))


if __name__ == "__main__":
    unittest.main()
