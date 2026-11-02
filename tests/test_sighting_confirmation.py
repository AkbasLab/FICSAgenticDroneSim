"""GMB: a sighting that a no-fly zone cut short is kept as a pending confirmation, shared with the team as a
sighting (never a find), and confirmed later by the best-placed drone once the zone has cleared. Mock-only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import (
    MissionBelief, PendingConfirmation, Provenance, SelfState, TargetSighting, TeammateRecord,
)
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.search_policy import SearchAgentPolicy
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.protocols import MessageType
from fics_drone.core.scenario import NoFlyZone, load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
T1 = (30.0, 30.0, 8.0)


def _agent(zones, name="Drone1", link=None, speed=15.0):
    scenario = load_scenario(SCENARIO_PATH)
    scenario.no_fly_zones = list(zones)
    spec = next(d for d in scenario.drones if d.name == name)
    return PersistentAgent(KinematicMockVehicleAdapter(spec.name, speed_mps=speed), scenario, spec.sector,
                           spec.spawn_offset, spec.battery_s, drone_name=spec.name, link=link)


def _belief(phase, confirm=None):
    b = Belief(self_state=SelfState(position=(0, 0, 0), elapsed_s=0.0, battery_s=1000.0, phase=phase),
               mission=MissionBelief(sector_id="A", search_queue=[]))
    b.mission.confirm_target_id = confirm
    return b


class TestPolicyTransitions(unittest.TestCase):
    def setUp(self):
        self.policy = SearchAgentPolicy()

    def test_reporting_with_nothing_to_confirm_goes_home_as_before(self):
        self.assertEqual(self.policy.decide(_belief("reporting"), ReplanEvent.REPORT_SENT),
                         (Objective.RETURN_HOME, "returning"))

    def test_reporting_with_a_blocked_sighting_to_confirm_goes_to_confirm(self):
        self.assertEqual(self.policy.decide(_belief("reporting", "T1"), ReplanEvent.REPORT_SENT),
                         (Objective.CONFIRM_TARGET, "confirming"))

    def test_confirming_keeps_confirming_until_nothing_is_left_then_goes_home(self):
        self.assertEqual(self.policy.decide(_belief("confirming", "T1"), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.CONFIRM_TARGET, "confirming"))
        self.assertEqual(self.policy.decide(_belief("confirming"), ReplanEvent.REPORT_SENT),
                         (Objective.RETURN_HOME, "returning"))

    def test_a_finished_drone_with_a_sighting_to_confirm_does_not_go_straight_home(self):
        self.assertEqual(self.policy.decide(_belief("checking_for_orphans", "T1"), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.CONFIRM_TARGET, "confirming"))
        self.assertEqual(self.policy.decide(_belief("checking_for_orphans"), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.RETURN_HOME, "returning"))


class TestZoneClearTime(unittest.TestCase):
    def test_a_zone_that_expires_gives_a_clear_time_just_after_it(self):
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=5.0, active_until_s=12.0)])
        self.assertAlmostEqual(agent._zone_clear_time(T1), 12.5, places=3)  # last covered 11.5 s, +1 s margin

    def test_a_zone_that_never_expires_is_never_clear(self):
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=5.0)])
        self.assertIsNone(agent._zone_clear_time(T1))

    def test_a_static_zone_over_the_point_is_never_clear(self):
        self.assertIsNone(_agent([NoFlyZone("S", 24, 40, 24, 40)])._zone_clear_time(T1))

    def test_a_zone_elsewhere_means_clear_now(self):
        self.assertEqual(_agent([NoFlyZone("Z", -10, 10, 45, 60, active_from_s=5.0, active_until_s=12.0)])
                         ._zone_clear_time(T1), 0.0)

    def test_a_drifting_zone_clears_once_it_has_moved_past(self):
        zone = NoFlyZone("D", 38, 46, 28, 36, active_from_s=3.0, vx=-2.5)
        clear_at = _agent([zone])._zone_clear_time(T1)
        self.assertIsNotNone(clear_at)
        self.assertFalse(zone.contains(30.0, 30.0, clear_at))
        self.assertTrue(zone.contains(30.0, 30.0, clear_at - 1.6))  # was still on top of it just before


class TestMessagesAndPending(unittest.TestCase):
    def _pair(self):
        bus = MessageBus()
        sender, receiver_link = AgentLink(bus, "Drone1"), AgentLink(bus, "Drone2")
        receiver = _agent([], name="Drone2", link=receiver_link)
        return sender, receiver

    def test_a_sighting_message_becomes_pending_and_is_not_a_find(self):
        sender, receiver = self._pair()
        sender.send(MessageType.TARGET_SIGHTED, {"target_id": "T1", "world_position": T1})
        receiver._observe_messages()
        self.assertIn("T1", receiver.belief.mission.pending_confirmations)
        self.assertEqual(receiver.belief.mission.pending_confirmations["T1"].reporter, "Drone1")
        self.assertIsNone(receiver.belief.target_found)

    def test_a_later_find_clears_the_pending_confirmation(self):
        sender, receiver = self._pair()
        sender.send(MessageType.TARGET_SIGHTED, {"target_id": "T1", "world_position": T1})
        sender.send(MessageType.TARGET_FOUND, {"target_id": "T1", "world_position": T1})
        receiver._observe_messages()
        self.assertNotIn("T1", receiver.belief.mission.pending_confirmations)
        self.assertEqual(receiver.belief.target_found, "T1")

    def test_a_sighting_of_something_already_confirmed_is_ignored(self):
        sender, receiver = self._pair()
        receiver.belief.mission.targets_known["T1"] = TargetSighting("T1", (0, 0, 0), 0.0, confirmed=True)
        sender.send(MessageType.TARGET_SIGHTED, {"target_id": "T1", "world_position": T1})
        receiver._observe_messages()
        self.assertEqual(receiver.belief.mission.pending_confirmations, {})


class TestWhoGoes(unittest.TestCase):
    def _agent_at(self, local_position):
        agent = _agent([], name="Drone3")  # spawns at world (20, 0)
        agent.belief.position = local_position
        agent.belief.self_state.elapsed_s = 10.0
        return agent

    def _teammate(self, agent, name, world_xy, heard_at):
        agent.belief.team.teammates[name] = TeammateRecord(
            name, (world_xy[0], world_xy[1], 8.0), Provenance(timestamp=heard_at, source="heartbeat"))

    def test_the_nearest_fresh_drone_goes(self):
        agent = self._agent_at((0.0, 0.0, 8.0))          # world (20, 0): far from T1
        self._teammate(agent, "Drone1", (34.0, 28.0), heard_at=9.0)
        pending = PendingConfirmation("T1", T1, 5.0, "Drone1")
        self.assertEqual(agent._best_confirmer(pending), "Drone1")

    def test_a_stale_teammate_is_not_a_candidate(self):
        agent = self._agent_at((0.0, 0.0, 8.0))
        self._teammate(agent, "Drone1", (34.0, 28.0), heard_at=0.0)   # 10 s old, past the freshness limit
        pending = PendingConfirmation("T1", T1, 5.0, "Drone1")
        self.assertEqual(agent._best_confirmer(pending), "Drone3")

    def test_a_tie_goes_to_the_lower_name(self):
        agent = self._agent_at((10.0, 30.0, 8.0))        # world (30, 30): exactly on T1
        self._teammate(agent, "Drone1", (30.0, 30.0), heard_at=10.0)
        pending = PendingConfirmation("T1", T1, 5.0, "Drone1")
        self.assertEqual(agent._best_confirmer(pending), "Drone1")


class TestRefreshConfirmation(unittest.TestCase):
    def _with_pending(self, zones, **kw):
        agent = _agent(zones, **kw)
        agent.belief.mission.pending_confirmations["T1"] = PendingConfirmation("T1", T1, 5.0, "Drone1")
        return agent

    def test_a_zone_that_clears_soon_makes_it_mine(self):
        agent = self._with_pending([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=12.0)])
        agent._refresh_confirmation()
        self.assertEqual(agent.belief.mission.confirm_target_id, "T1")

    def test_a_zone_that_never_clears_means_nothing_to_attempt(self):
        agent = self._with_pending([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1)])
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)

    def test_waiting_longer_than_the_limit_is_not_attempted(self):
        agent = self._with_pending([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=90.0)])
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)

    def test_out_of_attempts_means_nothing_to_attempt(self):
        agent = self._with_pending([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=12.0)])
        agent.belief.mission.pending_confirmations["T1"].attempts = 3
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)

    def test_a_relay_does_not_confirm(self):
        agent = self._with_pending([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=12.0)])
        agent.belief.self_state.role = "relay"
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)


class TestEndToEnd(unittest.TestCase):
    """The case the baseline exposed: a zone switches on over T1 while the drone is dwelling on it."""

    def test_a_zone_that_expires_lets_the_same_drone_confirm_the_target_later(self):
        # Drone1 reaches T1 around 4.8 s at 15 m/s; the zone is on from 5 s to 12 s
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=5.0, active_until_s=12.0)])
        report = agent.run()
        self.assertTrue(any(step.startswith("sighting_blocked(T1") for step in report.trace), report.trace)
        self.assertIn("sighting_confirmed(T1)", report.trace)
        self.assertEqual(report.target_found, "T1")
        x, y, _ = agent.belief.position
        self.assertLess((x * x + y * y) ** 0.5, 5.0, f"ended away from home: {agent.belief.position}")

    def test_a_zone_that_never_expires_leaves_the_sighting_unconfirmed_and_the_drone_goes_home(self):
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=5.0)])
        report = agent.run()
        self.assertTrue(any(step.startswith("sighting_blocked(T1, clears=never") for step in report.trace), report.trace)
        self.assertNotIn("sighting_confirmed(T1)", report.trace)
        self.assertIsNone(report.target_found)
        x, y, _ = agent.belief.position
        self.assertLess((x * x + y * y) ** 0.5, 5.0)


class TestStandoffWait(unittest.TestCase):
    """The drifting-zone case: waiting where I stand lets the zone sweep over me again and again."""

    DRIFT = dict(x_min=38, x_max=46, y_min=28, y_max=36, active_from_s=3.0, vx=-2.5)

    def _pending(self, agent):
        agent.belief.mission.pending_confirmations["T1"] = PendingConfirmation("T1", T1, 5.0, "Drone1")
        return agent.belief.mission.pending_confirmations["T1"]

    def test_a_safe_spot_is_kept(self):
        agent = _agent([NoFlyZone("Z", -10, 10, 45, 60, active_from_s=5.0, active_until_s=12.0)])
        agent.belief.position = (30.0, 30.0, 8.0)  # Drone1 spawns at the origin: local = world
        spot = agent._standoff_point(self._pending(agent), 4.0, 12.0)
        self.assertAlmostEqual(spot[0], 30.0)
        self.assertAlmostEqual(spot[1], 30.0)

    def test_a_drifting_zone_moves_the_wait_off_its_path(self):
        zone = NoFlyZone("D", **self.DRIFT)
        agent = _agent([zone])
        agent.belief.position = (34.0, 29.6, 8.0)  # right in the zone path
        spot = agent._standoff_point(self._pending(agent), 4.0, 10.2)
        self.assertIsNotNone(spot)
        t = 4.0
        while t <= 10.2:
            x0, x1, y0, y1 = zone.bounds_at(t)
            self.assertFalse(x0 - 8 <= spot[0] <= x1 + 8 and y0 - 8 <= spot[1] <= y1 + 8, (t, spot))
            t += 0.5

    def test_no_clear_spot_means_hold(self):
        agent = _agent([NoFlyZone("Big", -500, 500, -500, 500, active_from_s=0.1, active_until_s=12.0)])
        self.assertIsNone(agent._standoff_point(self._pending(agent), 4.0, 12.0))

    def test_end_to_end_a_drifting_zone_confirms_the_target_with_few_zone_entries(self):
        agent = _agent([NoFlyZone("D", **self.DRIFT)])
        report = agent.run()
        self.assertEqual(report.target_found, "T1", report.trace)
        entries = [s for s in report.trace if s.startswith("guardian_escalated(exit_zone")]
        self.assertLessEqual(len(entries), 2, report.trace)


if __name__ == "__main__":
    unittest.main()
