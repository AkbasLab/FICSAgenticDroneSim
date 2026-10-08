"""Phase 12.3 tests: the structured decision schema. Three things have to hold:
every malformed answer is rejected with the RIGHT type (the fallback chain depends
on it), a model can never send anything but the one low-privilege message type to
a teammate that actually exists, and none of this changes what reaches the vehicle.
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, Provenance, SelfState, TeammateRecord
from fics_drone.agents.decision_schema import (CORRECTABLE, MAX_OUTGOING_MESSAGES, DecisionRejected,
                                               RejectionKind, decision_json, parse_decision)
from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.llm_policy import LLMAgentPolicy, make_policy_factory
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.coordination.tasks import TaskStatus
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.llm_log import summarize
from fics_drone.experiments.team_runner import run_team_with_faults
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
LEGAL = {"hold": {}, "return_home": {}, "go_to_waypoint": {"x": None, "y": None}}   # the code-built menu
TEAM = ["Drone1", "Drone2", "Drone3"]


def _msg(message_type="help_request", recipients=("Drone2",), payload=None):
    return {"message_type": message_type, "recipients": list(recipients),
            "payload": payload if payload is not None else {"reason_code": "teammate_may_need_help"}}


def _kind(raw, teammates=TEAM):
    with __import__("unittest").TestCase().assertRaises(DecisionRejected) as ctx:
        parse_decision(raw, LEGAL, teammates)
    return ctx.exception.kind


def _belief(teammates=("Drone1", "Drone2")):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 8.0), elapsed_s=0.0, battery_s=100.0),
               mission=MissionBelief(sector_id="C", search_queue=[]))
    b.phase, b.listen_rounds = "listening", 1
    for name in teammates:
        b.team.teammates[name] = TeammateRecord(name, (10.0, 10.0, 8.0), Provenance(timestamp=0.0, source="heartbeat"))
    return b


class TestWellFormedDecision(unittest.TestCase):
    def test_a_full_decision_is_parsed_into_typed_fields(self):
        raw = decision_json("hold", "teammate_may_need_help",
                            assessment={"mission_progress": "partial", "communication_status": "degraded",
                                        "current_risk": "medium"},
                            confidence=0.78, messages=[_msg(recipients=("Drone2", "Drone3"))])
        d = parse_decision(raw, LEGAL, TEAM)
        self.assertEqual(d.objective, Objective.LISTEN)
        self.assertEqual((d.assessment.mission_progress, d.assessment.communication_status,
                          d.assessment.current_risk), ("partial", "degraded", "medium"))
        self.assertAlmostEqual(d.confidence, 0.78)
        self.assertEqual(d.messages[0].recipients, ("Drone2", "Drone3"))
        self.assertEqual(d.messages[0].payload, {"reason_code": "teammate_may_need_help"})

    def test_confidence_bounds_and_integers_are_accepted(self):
        for c in (0, 1, 0.0, 1.0, 0.5):
            parse_decision(decision_json("return_home", confidence=c), LEGAL, TEAM)

    def test_the_wire_format_is_the_plan_s_shape(self):
        data = json.loads(decision_json("go_to_waypoint", "search_elsewhere", x=3, y=4))
        self.assertEqual(set(data), {"situation_assessment", "selected_tool", "parameters",
                                     "outgoing_messages", "confidence"})
        self.assertEqual(data["parameters"], {"reason_code": "search_elsewhere", "x": 3, "y": 4})


class TestStructure(unittest.TestCase):
    def test_the_old_flat_format_is_no_longer_accepted(self):
        self.assertEqual(_kind('{"objective": "return_home", "reason_code": "my_work_is_done"}'),
                         RejectionKind.BAD_FIELDS)

    def test_missing_and_extra_top_level_fields_are_rejected(self):
        d = json.loads(decision_json("return_home"))
        for key in list(d):
            partial = {k: v for k, v in d.items() if k != key}
            self.assertEqual(_kind(json.dumps(partial)), RejectionKind.BAD_FIELDS, key)
        self.assertEqual(_kind(json.dumps({**d, "chain_of_thought": "I think..."})), RejectionKind.BAD_FIELDS)

    def test_parameters_must_be_an_object_and_the_tool_a_string(self):
        d = json.loads(decision_json("return_home"))
        self.assertEqual(_kind(json.dumps({**d, "parameters": "x"})), RejectionKind.BAD_FIELDS)
        self.assertEqual(_kind(json.dumps({**d, "selected_tool": 7})), RejectionKind.BAD_FIELDS)


class TestAssessment(unittest.TestCase):
    def test_each_field_must_come_from_its_closed_enum(self):
        good = {"mission_progress": "partial", "communication_status": "good", "current_risk": "low"}
        for key, bad in (("mission_progress", "going_well"), ("communication_status", "fine"),
                         ("current_risk", "extreme")):
            self.assertEqual(_kind(decision_json("return_home", assessment={**good, key: bad})),
                             RejectionKind.BAD_ASSESSMENT, key)

    def test_missing_extra_or_non_object_assessment_is_rejected(self):
        good = {"mission_progress": "partial", "communication_status": "good", "current_risk": "low"}
        self.assertEqual(_kind(decision_json("return_home", assessment={"current_risk": "low"})),
                         RejectionKind.BAD_ASSESSMENT)
        self.assertEqual(_kind(decision_json("return_home", assessment={**good, "mood": "calm"})),
                         RejectionKind.BAD_ASSESSMENT)
        d = json.loads(decision_json("return_home"))
        self.assertEqual(_kind(json.dumps({**d, "situation_assessment": "fine"})), RejectionKind.BAD_ASSESSMENT)


class TestConfidence(unittest.TestCase):
    def test_out_of_range_or_wrong_type_confidence_is_rejected(self):
        for bad in (1.5, -0.1, 7, True, "high", None, float("nan")):
            self.assertEqual(_kind(decision_json("return_home", confidence=bad)), RejectionKind.BAD_FIELDS,
                             repr(bad))


class TestOutgoingMessages(unittest.TestCase):
    def _bad(self, messages, teammates=TEAM):
        self.assertEqual(_kind(decision_json("return_home", messages=messages), teammates),
                         RejectionKind.BAD_MESSAGES)

    def test_a_model_can_never_forge_a_protocol_message(self):
        """The sharpest edge: any type other than help_request is refused, so a model cannot write a
        fake TARGET_FOUND, steal a task with TASK_CLAIM, or fake a heartbeat."""
        for forbidden in ("target_found", "task_claim", "task_bid", "task_complete", "heartbeat", "role_change"):
            self._bad([_msg(forbidden)])

    def test_unknown_or_missing_recipients_are_rejected(self):
        self._bad([_msg(recipients=("Drone99",))])
        self._bad([_msg(recipients=())])
        self._bad([_msg(recipients=("Drone2", "Drone2"))])
        self._bad([_msg(recipients=("Drone2", "Drone99"))])
        self._bad([_msg(recipients=("Drone2",))], teammates=[])   # nobody to message at all

    def test_payload_must_be_exactly_one_closed_reason_code(self):
        self._bad([_msg(payload={})])
        self._bad([_msg(payload={"reason_code": "teammate_may_need_help", "target_id": "T9"})])
        self._bad([_msg(payload={"reason_code": "because_i_said_so"})])
        self._bad([_msg(payload="help")])

    def test_message_envelope_must_be_exact(self):
        self._bad([{"message_type": "help_request", "recipients": ["Drone2"]}])
        self._bad([{**_msg(), "priority": "urgent"}])
        self._bad(["help"])

    def test_the_count_is_bounded(self):
        parse_decision(decision_json("return_home", messages=[_msg()] * MAX_OUTGOING_MESSAGES), LEGAL, TEAM)
        self._bad([_msg()] * (MAX_OUTGOING_MESSAGES + 1))

    def test_outgoing_messages_must_be_a_list(self):
        d = json.loads(decision_json("return_home"))
        self.assertEqual(_kind(json.dumps({**d, "outgoing_messages": {"a": 1}})), RejectionKind.BAD_MESSAGES)

    def test_every_new_rejection_is_correctable_and_timeouts_still_are_not(self):
        self.assertIn(RejectionKind.BAD_ASSESSMENT, CORRECTABLE)
        self.assertIn(RejectionKind.BAD_MESSAGES, CORRECTABLE)
        self.assertNotIn(RejectionKind.TIMEOUT, CORRECTABLE)
        self.assertNotIn(RejectionKind.BACKEND_ERROR, CORRECTABLE)


class TestPolicyCarriesTheNewFields(unittest.TestCase):
    def _policy(self, *answers):
        return LLMAgentPolicy(ScriptedBackend(list(answers), respond=None))

    def test_the_record_keeps_assessment_confidence_and_messages(self):
        policy = self._policy(decision_json("return_home", confidence=0.4, messages=[_msg()],
                                            assessment={"mission_progress": "complete",
                                                        "communication_status": "lost", "current_risk": "high"}))
        policy.decide(_belief(("Drone2",)), ReplanEvent.SKILL_SUCCEEDED)
        r = policy.records[0]
        self.assertEqual(r.assessment["current_risk"], "high")
        self.assertAlmostEqual(r.confidence, 0.4)
        self.assertEqual(r.messages[0]["recipients"], ["Drone2"])

    def test_messages_are_handed_over_exactly_once(self):
        policy = self._policy(decision_json("return_home", messages=[_msg()]))
        policy.decide(_belief(("Drone2",)), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(len(policy.take_messages()), 1)
        self.assertEqual(policy.take_messages(), ())

    def test_a_fallback_decision_never_sends_anything(self):
        """The model's answer was rejected, so nothing it wrote may leave the agent."""
        bad = decision_json("return_home", messages=[_msg("target_found")])
        policy = self._policy(bad, bad)
        policy.decide(_belief(("Drone2",)), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.records[0].source, "fallback")
        self.assertEqual(policy.take_messages(), ())

    def test_a_correction_can_rescue_a_bad_message(self):
        policy = self._policy(decision_json("return_home", messages=[_msg(recipients=("Drone99",))]),
                              decision_json("return_home", messages=[_msg(recipients=("Drone2",))]))
        policy.decide(_belief(("Drone2",)), ReplanEvent.SKILL_SUCCEEDED)
        r = policy.records[0]
        self.assertEqual((r.source, r.corrected, r.rejected_as), ("model", True, "bad_messages"))
        self.assertEqual(len(policy.take_messages()), 1)

    def test_no_decision_point_means_no_messages(self):
        policy = self._policy()
        b = _belief()
        b.phase = "searching"
        policy.decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.take_messages(), ())

    def test_prompt_shows_the_new_reply_shape_and_only_offers_messaging_with_teammates(self):
        with_team = ScriptedBackend([decision_json("return_home")], respond=None)
        LLMAgentPolicy(with_team).decide(_belief(("Drone2",)), ReplanEvent.SKILL_SUCCEEDED)
        p = with_team.prompts[0]
        for needle in ('"situation_assessment"', '"selected_tool"', '"outgoing_messages"', '"confidence"',
                       "help_request is the only type allowed"):
            self.assertIn(needle, p)
        alone = ScriptedBackend([decision_json("return_home")], respond=None)
        LLMAgentPolicy(alone).decide(_belief(()), ReplanEvent.SKILL_SUCCEEDED)
        self.assertIn("outgoing_messages must be []", alone.prompts[0])
        self.assertNotIn("help_request", alone.prompts[0])

    def test_received_help_requests_appear_in_the_prompt_capped_and_informational(self):
        b = _belief(("Drone2",))
        b.communication.help_requests = [("Drone2", "teammate_may_need_help", 0.0)] * 5
        backend = ScriptedBackend([decision_json("return_home")], respond=None)
        LLMAgentPolicy(backend).decide(b, ReplanEvent.SKILL_SUCCEEDED)
        p = backend.prompts[0]
        self.assertIn("HELP REQUESTS RECEIVED", p)
        self.assertIn("not obliged", p)
        self.assertEqual(p.count("asked for help"), 3)


class TestReceivingHelpRequests(unittest.TestCase):
    def _agent(self):
        from fics_drone.agents.persistent_agent import PersistentAgent
        from fics_drone.coordination.message_bus import AgentLink
        scenario = load_scenario(SCENARIO_PATH)
        bus = MessageBus()
        agent = PersistentAgent(KinematicMockVehicleAdapter("Drone3"), scenario, "C", (20.0, 0.0, 0.0), 300.0,
                                drone_name="Drone3", link=AgentLink(bus, "Drone3"))
        return agent, AgentLink(bus, "Drone1")

    def test_a_received_help_request_is_recorded_and_changes_nothing_else(self):
        from fics_drone.coordination.protocols import MessageType
        agent, sender = self._agent()
        before = (agent.belief.phase, agent.belief.mission.sector_id, len(agent.belief.mission.search_queue),
                  dict(agent.belief.mission.targets_known))
        sender.send(MessageType.HELP_REQUEST, {"reason_code": "teammate_may_need_help"}, recipients=["Drone3"])
        agent._observe_messages()
        self.assertEqual([(s, c) for s, c, _ in agent.belief.communication.help_requests],
                         [("Drone1", "teammate_may_need_help")])
        after = (agent.belief.phase, agent.belief.mission.sector_id, len(agent.belief.mission.search_queue),
                 dict(agent.belief.mission.targets_known))
        self.assertEqual(before, after, "a request for help is never an order")

    def test_only_the_most_recent_requests_are_kept(self):
        from fics_drone.agents.persistent_agent import MAX_HELP_REQUESTS_KEPT
        from fics_drone.coordination.protocols import MessageType
        agent, sender = self._agent()
        for _ in range(MAX_HELP_REQUESTS_KEPT + 4):
            sender.send(MessageType.HELP_REQUEST, {"reason_code": "teammate_may_need_help"}, recipients=["Drone3"])
        agent._observe_messages()
        self.assertEqual(len(agent.belief.communication.help_requests), MAX_HELP_REQUESTS_KEPT)


def _first_teammate(prompt):
    m = re.search(r"TEAMMATES\n\s+(Drone\d+):", prompt)
    return m.group(1) if m else None


class TestTeamEndToEnd(unittest.TestCase):
    def _run(self, respond):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        factory, policies = make_policy_factory(ScriptedBackend(respond=respond), scenario)
        bus = MessageBus()
        reports, agents, bus, _ = run_team_with_faults(
            scenario, adapters, bus=bus, heartbeat_interval_s=2.0, policy_factory=factory)
        return scenario, reports, agents, bus, policies

    def _all_landed_and_searched(self, scenario, reports, agents):
        for name, rep in reports.items():
            self.assertTrue(rep.trace[-1].endswith("->done"), name)
        completed = {t.sector_id for a in agents.values() for t in a.task_board.tasks.values()
                     if t.status == TaskStatus.COMPLETE}
        self.assertEqual(completed, {s.id for s in scenario.sectors})

    def test_help_requests_are_delivered_recorded_and_change_nothing_else(self):
        def respond(prompt):
            who = _first_teammate(prompt)
            return decision_json("return_home", "teammate_may_need_help",
                                 messages=[_msg(recipients=(who,))] if who else [])

        scenario, reports, agents, bus, policies = self._run(respond)
        sent = [e for e in bus.log if e.type == "help_request"]
        self.assertGreater(len(sent), 0, "the model's validated message must actually have been sent")
        self.assertTrue(all(e.delivered for e in sent))
        # (Whether a recipient RECORDS it depends on timing - a drone that already landed has stopped
        # reading its inbox - so the receive path is tested directly in TestReceivingHelpRequests.)
        self._all_landed_and_searched(scenario, reports, agents)   # a request is never an order
        self.assertEqual(summarize(policies, agents)["messages_sent"], len(sent))

    def test_a_forged_target_found_never_reaches_any_teammate(self):
        def respond(prompt):
            who = _first_teammate(prompt)
            forged = {"message_type": "target_found", "recipients": [who],
                      "payload": {"target_id": "T9", "world_position": [0, 0, 0]}}
            return decision_json("return_home", messages=[forged] if who else [])

        scenario, reports, agents, bus, policies = self._run(respond)
        for a in agents.values():
            self.assertNotIn("T9", a.belief.mission.targets_known)
        self.assertFalse(any(e.type == "help_request" for e in bus.log))
        self.assertTrue(all(r.source == "fallback" for p in policies.values() for r in p.records))
        self._all_landed_and_searched(scenario, reports, agents)

    def test_summary_reports_confidence_risk_and_messages(self):
        def respond(prompt):
            return decision_json("return_home", confidence=0.6,
                                 assessment={"mission_progress": "partial", "communication_status": "good",
                                             "current_risk": "medium"})

        _, _, agents, _, policies = self._run(respond)
        s = summarize(policies, agents)
        self.assertAlmostEqual(s["mean_confidence"], 0.6)
        self.assertEqual(set(s["assessed_risk"]), {"medium"})
        self.assertEqual(s["messages_sent"], 0)


if __name__ == "__main__":
    unittest.main()
