"""GMB: confirm_target, the model's say in who confirms a sighting a no-fly zone cut short. Code builds the
menu (only sightings this drone could legally go confirm), the model may pick one even when the code's pick is a
teammate, and every flight still goes through the guardian. Mock-only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, PendingConfirmation, Provenance, SelfState, TeammateRecord
from fics_drone.agents.context_builder import build_prompt
from fics_drone.agents.decision_schema import DecisionRejected, RejectionKind, decision_json, parse_decision
from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.llm_policy import LLMAgentPolicy
from fics_drone.agents.llm_tools import BY_NAME, MAX_MODEL_ACTIONS, offered_tools
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.protocols import MessageType
from fics_drone.core.scenario import NoFlyZone, load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
T1 = (30.0, 30.0, 8.0)
ROW = ("T1", (30.0, 30.0), 4.0, "Drone1", "Drone2")   # (target, xy, seconds until the zone clears, reporter, code's pick)


def _belief(view=(), actions=0, role="scout"):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 8.0), elapsed_s=0.0, battery_s=300.0),
               mission=MissionBelief(sector_id="C", search_queue=[]))
    b.phase, b.listen_rounds = "listening", 1
    b.self_state.role, b.self_state.model_actions = role, actions
    b.mission.confirm_view = list(view)
    return b


def _agent(zones, name="Drone3", bus=None, policy=None):
    scenario = load_scenario(SCENARIO_PATH)
    scenario.no_fly_zones = list(zones)
    spec = next(d for d in scenario.drones if d.name == name)
    link = AgentLink(bus, name) if bus else None
    return PersistentAgent(KinematicMockVehicleAdapter(spec.name, speed_mps=15.0), scenario, spec.sector,
                           spec.spawn_offset, spec.battery_s, drone_name=spec.name, link=link, policy=policy)


def _pending(agent, reporter="Drone1"):
    agent.belief.mission.pending_confirmations["T1"] = PendingConfirmation("T1", T1, 0.0, reporter)


def _fresh_teammate(agent, name, world_xy):
    agent.belief.self_state.elapsed_s = 10.0
    agent.belief.team.teammates[name] = TeammateRecord(
        name, (world_xy[0], world_xy[1], 8.0), Provenance(timestamp=10.0, source="heartbeat"))


class TestTheTool(unittest.TestCase):
    def test_it_is_a_free_flight_tool_that_maps_to_confirming(self):
        tool = BY_NAME["confirm_target"]
        self.assertTrue(tool.free)
        self.assertEqual(tool.objective, Objective.CONFIRM_TARGET)
        self.assertEqual(tool.params, ("target_id",))

    def test_it_is_offered_only_while_the_code_says_a_sighting_is_legal_to_confirm(self):
        self.assertNotIn("confirm_target", offered_tools(_belief(), listen_cap=3))
        self.assertEqual(offered_tools(_belief([ROW]), listen_cap=3)["confirm_target"]["target_id"], ("T1",))

    def test_it_stays_on_the_menu_when_the_action_cap_is_spent(self):
        offered = offered_tools(_belief([ROW], actions=MAX_MODEL_ACTIONS), listen_cap=3)
        self.assertEqual(set(offered), {"return_home", "confirm_target"})

    def test_a_target_that_was_not_offered_is_rejected_and_the_valid_one_is_named(self):
        offered = {"confirm_target": {"target_id": ("T1",)}, "return_home": {}}
        ok = parse_decision(decision_json("confirm_target", params={"target_id": "T1"}), offered, [])
        self.assertEqual((ok.tool, ok.args, ok.objective), ("confirm_target", {"target_id": "T1"}, Objective.CONFIRM_TARGET))
        with self.assertRaises(DecisionRejected) as ctx:
            parse_decision(decision_json("confirm_target", params={"target_id": "T9"}), offered, [])
        self.assertEqual(ctx.exception.kind, RejectionKind.BAD_FIELDS)
        self.assertIn("T1", ctx.exception.detail)

    def test_the_prompt_shows_the_waiting_sighting_and_the_codes_pick(self):
        belief = _belief([ROW])
        prompt = build_prompt(belief, ReplanEvent.SKILL_SUCCEEDED, offered_tools(belief, listen_cap=3), 3)
        self.assertIn("SIGHTINGS WAITING FOR CONFIRMATION", prompt)
        self.assertIn("T1 at world (30, 30), seen by Drone1", prompt)
        self.assertIn("clears in about 4s", prompt)
        self.assertIn("the code would send: Drone2", prompt)
        self.assertIn("- confirm_target:", prompt)

    def test_the_prompt_has_no_such_section_when_nothing_is_waiting(self):
        belief = _belief()
        prompt = build_prompt(belief, ReplanEvent.SKILL_SUCCEEDED, offered_tools(belief, listen_cap=3), 3)
        self.assertNotIn("SIGHTINGS WAITING", prompt)
        self.assertNotIn("confirm_target", prompt)


class TestTheViewAndTheOverride(unittest.TestCase):
    ZONE = NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=8.0)

    def _setup(self):
        agent = _agent([self.ZONE])
        _pending(agent)
        _fresh_teammate(agent, "Drone1", (38.0, 30.0))    # Drone1 is much nearer than Drone3, so the code sends Drone1
        return agent

    def test_the_view_lists_a_sighting_the_code_would_send_a_teammate_to_but_it_is_not_mine(self):
        agent = self._setup()
        agent._refresh_confirmation()
        self.assertEqual([(r[0], r[3], r[4]) for r in agent.belief.mission.confirm_view], [("T1", "Drone1", "Drone1")])
        self.assertIsNone(agent.belief.mission.confirm_target_id)

    def test_a_model_choice_makes_it_mine_and_survives_the_next_refresh(self):
        agent = self._setup()
        agent._refresh_confirmation()
        trace = []
        agent._pending_action = ("confirm_target", {"target_id": "T1", "reason_code": "my_work_is_done"})
        agent._apply_model_confirm_choice(trace)
        self.assertEqual(agent.belief.mission.confirm_target_id, "T1")
        self.assertIn("model_confirms(T1)", trace)
        agent._refresh_confirmation()                      # the next step recomputes from scratch
        self.assertEqual(agent.belief.mission.confirm_target_id, "T1")

    def test_other_tools_do_not_touch_the_override(self):
        agent = self._setup()
        agent._pending_action = ("return_home", {"reason_code": "my_work_is_done"})
        agent._apply_model_confirm_choice([])
        self.assertIsNone(agent.belief.mission.confirm_override_id)

    def test_the_override_ends_when_the_sighting_stops_being_legal(self):
        agent = self._setup()
        agent.belief.mission.confirm_override_id = "T1"
        agent.belief.mission.pending_confirmations["T1"].attempts = 3
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)
        self.assertIsNone(agent.belief.mission.confirm_override_id)

    def test_a_relay_has_no_view_and_so_no_tool(self):
        agent = self._setup()
        agent.belief.self_state.role = "relay"
        agent._refresh_confirmation()
        self.assertEqual(agent.belief.mission.confirm_view, [])
        self.assertNotIn("confirm_target", offered_tools(agent.belief, listen_cap=3))

    def test_a_zone_that_never_clears_means_nothing_is_offered(self):
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1)])
        _pending(agent)
        agent._refresh_confirmation()
        self.assertEqual(agent.belief.mission.confirm_view, [])


class TestWithAModelInThePolicySlot(unittest.TestCase):
    def test_the_model_policy_exposes_the_battery_rule_the_agent_reads(self):
        policy = LLMAgentPolicy(ScriptedBackend())
        self.assertEqual(policy.low_battery_frac, policy.fallback.low_battery_frac)

    def test_the_agent_refreshes_the_view_with_a_model_policy_without_crashing(self):
        agent = _agent([NoFlyZone("Z", 24, 40, 24, 40, active_from_s=0.1, active_until_s=8.0)],
                       policy=LLMAgentPolicy(ScriptedBackend()))
        _pending(agent)
        agent._refresh_confirmation()
        self.assertEqual(len(agent.belief.mission.confirm_view), 1)

    def test_choosing_confirm_target_moves_the_agent_to_confirming(self):
        answer = decision_json("confirm_target", params={"target_id": "T1"})
        policy = LLMAgentPolicy(ScriptedBackend([answer]))
        agent = _agent([], policy=policy)
        _pending(agent)
        agent.belief.phase = "listening"
        agent.belief.listen_rounds = 1
        agent._refresh_confirmation()
        self.assertEqual(policy.decide(agent.belief, ReplanEvent.SKILL_SUCCEEDED), (Objective.CONFIRM_TARGET, "confirming"))
        self.assertEqual(policy.take_action()[0], "confirm_target")

    def test_the_model_policy_does_not_decide_while_already_confirming(self):
        policy = LLMAgentPolicy(ScriptedBackend())
        agent = _agent([], policy=policy)
        _pending(agent)
        agent.belief.phase = "confirming"
        agent._refresh_confirmation()
        agent.belief.mission.confirm_target_id = "T1"
        self.assertEqual(policy.decide(agent.belief, ReplanEvent.SKILL_SUCCEEDED), (Objective.CONFIRM_TARGET, "confirming"))
        self.assertEqual(policy.records, [])               # deterministic: no model call was made


class TestEndToEnd(unittest.TestCase):
    def test_a_model_override_goes_and_confirms_a_target_the_code_gave_to_a_teammate(self):
        bus = MessageBus()
        agent = _agent([], name="Drone3", bus=bus)
        peer = _agent([], name="Drone1", bus=bus)
        _pending(agent)
        _fresh_teammate(agent, "Drone1", (38.0, 30.0))
        agent._refresh_confirmation()
        self.assertIsNone(agent.belief.mission.confirm_target_id)        # code says: Drone1's job
        agent._pending_action = ("confirm_target", {"target_id": "T1", "reason_code": "my_work_is_done"})
        agent._apply_model_confirm_choice([])
        trace = []
        event = agent._confirm_target(trace)
        self.assertEqual(event, ReplanEvent.REPORT_SENT, trace)
        self.assertIn("sighting_confirmed(T1)", trace)
        self.assertNotIn("T1", agent.belief.mission.pending_confirmations)
        found = [m for m in peer.link.receive_available() if m.type == MessageType.TARGET_FOUND]
        self.assertEqual([m.payload["target_id"] for m in found], ["T1"])


if __name__ == "__main__":
    unittest.main()
