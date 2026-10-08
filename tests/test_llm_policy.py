"""Phase 12 tests. None needs a model - ScriptedBackend is the fake. What is
being tested is everything that is NOT "the model is smart": that a model can
only choose from the offered menu, that every way it can fail still ends with
the aircraft flown correctly, that code (not the model) owns facts, and that
four agents over one backend stay four independent agents.
"""

import http.server
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, Provenance, SelfState, TeammateRecord
from fics_drone.agents.decision_schema import (DecisionRejected, REASON_CODES, RejectionKind,
                                               decision_json, parse_decision)
from fics_drone.agents.llm_backends import BackendError, BackendTimeout, ScriptedBackend
from fics_drone.agents.llm_policy import LLMAgentPolicy, make_policy_factory
from fics_drone.agents.llm_tools import BY_NAME
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.ollama_backend import DECISION_SCHEMA, ModelCard, OllamaBackend
from fics_drone.agents.search_policy import SearchAgentPolicy
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.coordination.tasks import TaskStatus
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.team_runner import run_team_with_faults
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")

LISTEN_JSON = decision_json("hold", "waiting_for_report")
HOME_JSON = decision_json("return_home", "my_work_is_done")
LEGAL = {"hold": {}, "return_home": {}}   # what the code offered, as parse_decision wants it


def _belief(phase="listening", listen_rounds=1, battery_s=100.0, elapsed_s=0.0):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 8.0), elapsed_s=elapsed_s, battery_s=battery_s),
               mission=MissionBelief(sector_id="A", search_queue=[]))
    b.phase = phase
    b.listen_rounds = listen_rounds
    return b


def _policy(*answers):
    return LLMAgentPolicy(ScriptedBackend(answers, respond=None))


class TestParseDecision(unittest.TestCase):
    def test_valid_decision_is_accepted(self):
        d = parse_decision(LISTEN_JSON, LEGAL)
        self.assertEqual(d.objective, Objective.LISTEN)

    def _kind(self, raw, legal=LEGAL):
        with self.assertRaises(DecisionRejected) as ctx:
            parse_decision(raw, legal)
        return ctx.exception.kind

    def test_prose_is_malformed_json(self):
        self.assertEqual(self._kind("Sure! I think the drone should go home."), RejectionKind.MALFORMED_JSON)

    def test_non_object_json_is_malformed(self):
        self.assertEqual(self._kind('["return_home"]'), RejectionKind.MALFORMED_JSON)

    def test_made_up_objective_is_rejected(self):
        self.assertEqual(self._kind(decision_json("deploy_countermeasures")),
                         RejectionKind.UNKNOWN_OBJECTIVE)

    def test_real_objective_that_is_not_offered_is_rejected(self):
        """take_off is a real Objective - but it is not on the menu at this moment."""
        self.assertEqual(self._kind(decision_json("take_off")),
                         RejectionKind.UNKNOWN_OBJECTIVE)

    def test_unknown_field_is_an_error_not_ignored(self):
        self.assertEqual(self._kind(decision_json("return_home", x=400, y=400)),
                         RejectionKind.BAD_FIELDS)

    def test_missing_field_is_rejected(self):
        self.assertEqual(self._kind('{"selected_tool": "return_home"}'), RejectionKind.BAD_FIELDS)

    def test_reason_code_outside_the_closed_list_is_rejected(self):
        self.assertEqual(self._kind(decision_json("return_home", "i_feel_like_it")),
                         RejectionKind.BAD_FIELDS)

    def test_the_model_cannot_carry_coordinates(self):
        """No field in the contract can hold a position at all."""
        self.assertNotIn("x", REASON_CODES)
        self.assertEqual(self._kind(decision_json("go_to_waypoint", "search_elsewhere", x=1, y=2)),
                         RejectionKind.UNKNOWN_OBJECTIVE)   # not on this menu, so it cannot be chosen


class TestDecisionOwnership(unittest.TestCase):
    """Code owns facts. The model owns exactly one judgment point."""

    def test_model_is_never_asked_outside_the_listening_phase(self):
        for phase in ("pre_takeoff", "climbing", "transit", "searching", "reporting",
                      "checking_for_orphans", "returning", "landing", "done"):
            backend = ScriptedBackend(respond=None)
            policy = LLMAgentPolicy(backend)
            policy.decide(_belief(phase=phase), ReplanEvent.SKILL_SUCCEEDED)
            self.assertEqual(backend.calls, 0, f"model was consulted in phase {phase}")

    def test_failed_skill_while_listening_is_a_fact_not_a_judgment(self):
        backend = ScriptedBackend(respond=None)
        LLMAgentPolicy(backend).decide(_belief(), ReplanEvent.SKILL_FAILED)
        self.assertEqual(backend.calls, 0)

    def test_low_battery_is_never_delegated(self):
        backend = ScriptedBackend(respond=None)
        policy = LLMAgentPolicy(backend)
        policy.decide(_belief(battery_s=100.0, elapsed_s=80.0), ReplanEvent.SKILL_SUCCEEDED)  # 20% left
        self.assertEqual(backend.calls, 0)

    def test_critical_battery_still_forces_return_home(self):
        policy = _policy()
        objective, phase = policy.decide(_belief(battery_s=100.0, elapsed_s=95.0), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual((objective, phase), (Objective.RETURN_HOME, "returning"))

    def test_model_cannot_linger_past_the_code_owned_cap(self):
        cap = SearchAgentPolicy().listen_rounds
        policy = _policy(LISTEN_JSON, LISTEN_JSON, HOME_JSON)   # asks to hold though the rounds are exhausted
        objective, _ = policy.decide(_belief(listen_rounds=cap), ReplanEvent.SKILL_SUCCEEDED)
        self.assertNotEqual(objective, Objective.LISTEN)

    def test_a_valid_model_choice_is_followed(self):
        policy = _policy(HOME_JSON)
        self.assertEqual(policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.RETURN_HOME, "returning"))
        self.assertEqual(policy.records[0].source, "model")
        self.assertEqual(policy.records[0].reason_code, "my_work_is_done")


class TestEveryFailureStillFliesTheAircraft(unittest.TestCase):
    """Fallback is the design: every way a model can fail ends in the
    deterministic policy's decision, and the event is recorded."""

    def _expect_fallback(self, *answers):
        deterministic = SearchAgentPolicy().decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        policy = _policy(*answers)
        result = policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(result, deterministic)
        self.assertEqual(policy.records[0].source, "fallback")
        return policy

    def test_prose_twice_falls_back(self):
        p = self._expect_fallback("go home pls", "I said go home")
        self.assertEqual(p.records[0].rejected_as, "malformed_json")

    def test_unknown_objective_twice_falls_back(self):
        bad = decision_json("land_on_the_moon")
        p = self._expect_fallback(bad, bad)
        self.assertEqual(p.records[0].rejected_as, "unknown_objective")

    def test_bad_fields_twice_falls_back(self):
        self._expect_fallback('{"selected_tool": "return_home"}', '{"selected_tool": "return_home"}')

    def test_timeout_falls_back_immediately_without_a_retry(self):
        backend = ScriptedBackend([BackendTimeout("hung")], respond=None)
        policy = LLMAgentPolicy(backend)
        deterministic = SearchAgentPolicy().decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED), deterministic)
        self.assertEqual(backend.calls, 1, "a timeout must not be retried - the drone is airborne")
        self.assertEqual(policy.records[0].rejected_as, "timeout")

    def test_backend_error_falls_back_immediately_without_a_retry(self):
        backend = ScriptedBackend([BackendError("server down")], respond=None)
        policy = LLMAgentPolicy(backend)
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(backend.calls, 1)
        self.assertEqual(policy.records[0].rejected_as, "backend_error")

    def test_one_correction_can_rescue_a_bad_first_answer(self):
        policy = _policy("not json", HOME_JSON)
        self.assertEqual(policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.RETURN_HOME, "returning"))
        record = policy.records[0]
        self.assertEqual((record.source, record.corrected, record.rejected_as),
                         ("model", True, "malformed_json"))

    def test_the_correction_prompt_names_the_specific_fault(self):
        backend = ScriptedBackend(["not json", HOME_JSON], respond=None)
        LLMAgentPolicy(backend).decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertIn("REJECTED", backend.prompts[1])
        self.assertNotIn("REJECTED", backend.prompts[0])

    def test_fallback_rate_counts_model_owned_decisions_only(self):
        policy = _policy("junk", "junk", HOME_JSON)
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)                # fallback
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)                # model
        policy.decide(_belief(phase="searching"), ReplanEvent.SKILL_SUCCEEDED)  # not model-owned: not counted
        self.assertEqual(len(policy.records), 2)
        self.assertAlmostEqual(policy.fallback_rate, 0.5)


class TestBoundedPrompt(unittest.TestCase):
    def test_prompt_does_not_grow_with_mission_length(self):
        def prompt_len(elapsed):
            backend = ScriptedBackend([HOME_JSON], respond=None)
            b = _belief(elapsed_s=elapsed, battery_s=10000.0)  # big budget: stay above the low-battery cutoff
            LLMAgentPolicy(backend).decide(b, ReplanEvent.SKILL_SUCCEEDED)
            return len(backend.prompts[0])
        self.assertLess(prompt_len(200.0), prompt_len(3.0) * 1.1)

    def test_teammates_shown_are_capped(self):
        backend = ScriptedBackend([HOME_JSON], respond=None)
        b = _belief()
        for i in range(50):
            b.team.teammates[f"D{i}"] = TeammateRecord(f"D{i}", None, Provenance(timestamp=0.0, source="x"))
        LLMAgentPolicy(backend).decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertLess(backend.prompts[0].count("last heard"), 9)

    def test_prompt_only_offers_legal_options(self):
        backend = ScriptedBackend([HOME_JSON], respond=None)
        cap = SearchAgentPolicy().listen_rounds
        LLMAgentPolicy(backend).decide(_belief(listen_rounds=cap), ReplanEvent.SKILL_SUCCEEDED)
        self.assertNotIn("- hold:", backend.prompts[0])
        self.assertIn("- return_home:", backend.prompts[0])


class TestFourAgentsOneBackend(unittest.TestCase):
    def test_four_llm_agents_complete_the_mission_and_land(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        backend = ScriptedBackend()   # default_script: one shared model process
        policies = {}

        def factory(name):
            policies[name] = LLMAgentPolicy(backend)
            return policies[name]

        reports, agents, _, _ = run_team_with_faults(
            scenario, adapters, bus=MessageBus(), heartbeat_interval_s=2.0, policy_factory=factory)

        self.assertEqual(len(reports), 4)
        self.assertEqual(len({id(p) for p in policies.values()}), 4, "four distinct policy objects")
        self.assertGreater(backend.calls, 0, "the model must actually have been consulted")
        for name, report in reports.items():
            self.assertTrue(report.trace[-1].endswith("->done"), f"{name} did not finish cleanly: {report.trace[-3:]}")
            self.assertIn("land", " ".join(report.trace), f"{name} never landed")

        completed = set()
        for agent in agents.values():
            for t in agent.task_board.tasks.values():
                if t.status == TaskStatus.COMPLETE:
                    completed.add(t.sector_id)
        self.assertEqual(completed, {s.id for s in scenario.sectors})

    def test_each_agent_keeps_its_own_history(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        backend = ScriptedBackend()
        policies = {}

        def factory(name):
            policies[name] = LLMAgentPolicy(backend)
            return policies[name]

        run_team_with_faults(scenario, adapters, bus=MessageBus(), heartbeat_interval_s=2.0,
                             policy_factory=factory)
        self.assertEqual(sum(len(p.records) for p in policies.values()), backend.calls)
        for p in policies.values():
            self.assertTrue(all(r.source in ("model", "fallback") for r in p.records))

    def test_model_failures_never_stop_the_team_finishing(self):
        """Every model call times out - the whole team flies on deterministic fallback."""
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        backend = ScriptedBackend(respond=lambda prompt: (_ for _ in ()).throw(BackendTimeout("hung")))
        policies = {}

        def factory(name):
            policies[name] = LLMAgentPolicy(backend)
            return policies[name]

        reports, _, _, _ = run_team_with_faults(
            scenario, adapters, bus=MessageBus(), heartbeat_interval_s=2.0, policy_factory=factory)
        for name, report in reports.items():
            self.assertTrue(report.trace[-1].endswith("->done"), name)
        self.assertTrue(all(p.fallback_rate == 1.0 for p in policies.values() if p.records))


WAYPOINT_LEGAL = {**LEGAL, "go_to_waypoint": {"x": None, "y": None}}


def _wp(x, y):
    return decision_json("go_to_waypoint", "search_elsewhere", x=x, y=y)


class TestWaypointContract(unittest.TestCase):
    def test_valid_waypoint_is_parsed_as_world_xy(self):
        d = parse_decision(_wp(12, -3.5), WAYPOINT_LEGAL)
        self.assertEqual((d.objective, d.waypoint), (Objective.GO_TO_WAYPOINT, (12.0, -3.5)))

    def _kind(self, raw):
        with self.assertRaises(DecisionRejected) as ctx:
            parse_decision(raw, WAYPOINT_LEGAL)
        return ctx.exception.kind

    def test_boolean_is_never_accepted_as_a_number(self):
        self.assertEqual(self._kind(_wp(True, 0)), RejectionKind.BAD_FIELDS)

    def test_string_coordinate_is_rejected(self):
        self.assertEqual(self._kind(_wp("north", 0)), RejectionKind.BAD_FIELDS)

    def test_missing_coordinate_is_rejected(self):
        raw = json.dumps({**json.loads(_wp(5, 6)),
                          "parameters": {"reason_code": "search_elsewhere", "x": 5}})
        self.assertEqual(self._kind(raw), RejectionKind.BAD_FIELDS)

    def test_coordinates_on_any_other_objective_are_rejected(self):
        raw = decision_json("return_home", x=5, y=5)
        self.assertEqual(self._kind(raw), RejectionKind.BAD_FIELDS)

    def test_schema_does_not_judge_whether_a_point_is_safe(self):
        """A no-fly-zone point, a far-away point and NaN are all well-formed. Judging them is
        the guardian's job alone - a schema that pre-filtered them would hide them from it."""
        for x, y in ((0, 50), (5000, 0), (float("nan"), 0)):
            parse_decision(_wp(x, y), WAYPOINT_LEGAL)

    def test_waypoint_is_only_offered_while_rounds_remain(self):
        cap = SearchAgentPolicy().listen_rounds
        for rounds, offered in ((1, True), (cap, False)):
            backend = ScriptedBackend([HOME_JSON], respond=None)
            LLMAgentPolicy(backend).decide(_belief(listen_rounds=rounds), ReplanEvent.SKILL_SUCCEEDED)
            self.assertEqual("- go_to_waypoint:" in backend.prompts[0], offered)

    def test_waypoints_can_be_switched_off(self):
        backend = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(backend, waypoints_enabled=False).decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertNotIn("go_to_waypoint", backend.prompts[0])

    def test_coordinates_are_handed_over_exactly_once(self):
        policy = _policy(_wp(30, 30))
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.take_waypoint(), (30.0, 30.0))
        self.assertIsNone(policy.take_waypoint())


class RecordingMock(KinematicMockVehicleAdapter):
    """Remembers every position the vehicle was ever commanded toward."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.commanded = []

    def start_move_to(self, x, y, z):
        self.commanded.append((x, y, z))
        return super().start_move_to(x, y, z)


NFZ1 = (-10.0, 10.0, 45.0, 60.0)   # x_min, x_max, y_min, y_max (world)


def _fly_solo(answers):
    """Drone3 alone on sector C (no target there, so it reaches the model's decision point)."""
    scenario = load_scenario(SCENARIO_PATH)
    adapter = RecordingMock("Drone3", speed_mps=25.0)
    policy = LLMAgentPolicy(ScriptedBackend(answers, respond=None), sectors=scenario.sectors,
                            spawn_offset=(20.0, 0.0, 0.0))
    agent = PersistentAgent(adapter, scenario, "C", (20.0, 0.0, 0.0), 300.0, policy=policy, drone_name="Drone3")
    report = agent.run()
    return report, agent, adapter, policy


class TestUnsafeButValidModelOutput(unittest.TestCase):
    """The Phase 11 payoff: a perfectly well-formed decision naming a real option can still
    be unsafe. Validation accepts it; the guardian, one layer down, stops it before it
    reaches the vehicle - and the drone still finishes and lands."""

    UNSAFE = {
        "inside_no_fly_zone": (0, 50),
        "outside_geofence": (5000, 0),
        "beyond_max_distance": (1000, 0),
        "not_a_number": (float("nan"), 0),
    }

    def test_every_unsafe_waypoint_is_blocked_before_the_vehicle_and_the_drone_lands(self):
        for label, (x, y) in self.UNSAFE.items():
            with self.subTest(case=label):
                report, agent, adapter, policy = _fly_solo([_wp(x, y)] + [HOME_JSON] * 3)
                self.assertEqual(policy.records[0].objective, Objective.GO_TO_WAYPOINT,
                                 "validation must ACCEPT it - it is well-formed")
                self.assertTrue(any("guardian_blocked" in t for t in report.trace), report.trace)
                self.assertTrue(any(e.outcome == "reject_and_replan" for e in agent.guardian_log.entries))
                for cx, cy, _ in adapter.commanded:        # local frame -> world
                    wx, wy = cx + 20.0, cy
                    self.assertFalse(NFZ1[0] <= wx <= NFZ1[1] and NFZ1[2] <= wy <= NFZ1[3])
                    self.assertTrue(abs(wx) < 200 and abs(wy) < 200, f"vehicle was sent to ({wx}, {wy})")
                self.assertTrue(report.trace[-1].endswith("->done"))
                self.assertIn("land", " ".join(report.trace))

    def test_a_blocked_waypoint_still_consumes_a_round_so_it_cannot_loop(self):
        cap = SearchAgentPolicy().listen_rounds
        report, agent, _, policy = _fly_solo([_wp(0, 50)] * 20)   # the model keeps asking, forever
        self.assertLessEqual(sum(1 for r in policy.records if r.objective == Objective.GO_TO_WAYPOINT), cap)
        self.assertTrue(report.trace[-1].endswith("->done"))

    def test_a_safe_waypoint_is_flown_and_sensed(self):
        # a point inside sector C (world x 20..40, y -40..-20)
        report, agent, adapter, _ = _fly_solo([_wp(30, -30)] + [HOME_JSON] * 3)
        self.assertFalse(any("guardian_blocked" in t for t in report.trace), report.trace)
        self.assertTrue(any(abs(cx + 20.0 - 30) < 1 and abs(cy + 30) < 1 for cx, cy, _ in adapter.commanded))
        self.assertTrue(report.trace[-1].endswith("->done"))

    def test_model_never_chooses_altitude(self):
        _, _, adapter, _ = _fly_solo([_wp(30, -30)] + [HOME_JSON] * 3)
        zs = {round(z, 3) for _, _, z in adapter.commanded}
        self.assertEqual(len(zs), 1, f"every command used one code-owned altitude, got {zs}")

    def test_fallback_after_a_blocked_waypoint_is_the_deterministic_policy(self):
        report, _, _, policy = _fly_solo([_wp(0, 50), "junk", "junk"])
        self.assertTrue(report.trace[-1].endswith("->done"))
        self.assertIn("fallback", [r.source for r in policy.records])

    def test_four_agents_with_a_waypointing_model_still_all_land(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        backend = ScriptedBackend(respond=lambda prompt: _wp(0, 50) if "- go_to_waypoint:" in prompt else HOME_JSON)
        factory, policies = make_policy_factory(backend, scenario)
        reports, agents, _, _ = run_team_with_faults(
            scenario, adapters, bus=MessageBus(), heartbeat_interval_s=2.0, policy_factory=factory)
        for name, report in reports.items():
            self.assertTrue(report.trace[-1].endswith("->done"), name)
        blocked = sum(1 for a in agents.values() for e in a.guardian_log.entries if e.outcome == "reject_and_replan")
        self.assertGreater(blocked, 0, "the guardian must actually have been exercised by model output")


class _FakeOllama(http.server.BaseHTTPRequestHandler):
    """Minimal stand-in for the Ollama HTTP API, so the real transport code is tested with no model."""
    mode = "ok"            # ok | hang | garbage | no_response_field
    seen_bodies = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "llama3.1:8b", "digest": "46e0c10c039eabcdef"}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        type(self).seen_bodies.append(json.loads(self.rfile.read(length)))
        if self.mode == "hang":
            time.sleep(3)
            return
        self.send_response(200)
        self.end_headers()
        if self.mode == "garbage":
            self.wfile.write(b"<html>not json</html>")
        elif self.mode == "no_response_field":
            self.wfile.write(json.dumps({"done": True}).encode())
        else:
            self.wfile.write(json.dumps({"response": HOME_JSON}).encode())


class TestOllamaBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
        cls.host = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _FakeOllama.mode = "ok"
        _FakeOllama.seen_bodies = []

    def test_request_is_greedy_seeded_and_schema_constrained(self):
        backend = OllamaBackend("llama3.1:8b", host=self.host)
        self.assertEqual(backend.complete("hi", 5.0), HOME_JSON)
        body = _FakeOllama.seen_bodies[-1]
        self.assertEqual(body["options"]["temperature"], 0.0)
        self.assertEqual(body["options"]["seed"], 17)
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"], DECISION_SCHEMA)

    def test_schema_agrees_with_the_validator_contract(self):
        from fics_drone.agents.decision_schema import (COMMUNICATION_STATUS, CURRENT_RISK, MISSION_PROGRESS,
                                                       TOP_KEYS)
        props = DECISION_SCHEMA["properties"]
        self.assertEqual(set(props), TOP_KEYS)
        self.assertEqual(set(DECISION_SCHEMA["required"]), TOP_KEYS)
        self.assertFalse(DECISION_SCHEMA["additionalProperties"])
        self.assertEqual(set(props["parameters"]["properties"]["reason_code"]["enum"]), set(REASON_CODES))
        self.assertEqual(set(props["selected_tool"]["enum"]), set(BY_NAME))   # exactly the fifteen tools
        a = props["situation_assessment"]["properties"]
        self.assertEqual((set(a["mission_progress"]["enum"]), set(a["communication_status"]["enum"]),
                          set(a["current_risk"]["enum"])),
                         (set(MISSION_PROGRESS), set(COMMUNICATION_STATUS), set(CURRENT_RISK)))
        # the decoder can only ever name the one message type a model is allowed to author
        item = props["outgoing_messages"]["items"]["properties"]
        self.assertEqual(item["message_type"]["enum"], ["help_request"])

    def test_card_records_the_digest_and_is_pinned(self):
        card = OllamaBackend("llama3.1:8b", host=self.host).card()
        self.assertEqual(card.digest, "46e0c10c039e")
        self.assertTrue(card.is_pinned)
        self.assertEqual(card.warnings(), [])

    def test_a_floating_tag_is_never_certified_as_pinned(self):
        self.assertFalse(ModelCard("ollama", "llama3.1:latest", "abc", 0.0, 17).is_pinned)
        self.assertFalse(ModelCard("ollama", "llama3.1", "abc", 0.0, 17).is_pinned)
        self.assertFalse(ModelCard("ollama", "llama3.1:8b", None, 0.0, 17).is_pinned)

    def test_nonzero_temperature_is_flagged(self):
        card = ModelCard("ollama", "llama3.1:8b", "abc", 0.7, 17)
        self.assertTrue(any("temperature" in w for w in card.warnings()))

    def test_a_hung_server_is_a_timeout(self):
        _FakeOllama.mode = "hang"
        with self.assertRaises(BackendTimeout):
            OllamaBackend("llama3.1:8b", host=self.host).complete("hi", 0.5)

    def test_unreachable_server_is_a_backend_error_not_a_crash(self):
        import socket
        with socket.socket() as s:                 # a port that was just free, so it is refused at once
            s.bind(("127.0.0.1", 0))
            dead_port = s.getsockname()[1]
        # Windows can take ~2s to report a refused local connection, so it may surface as either;
        # both are non-correctable and lead to the same immediate, un-retried fallback.
        with self.assertRaises((BackendError, BackendTimeout)):
            OllamaBackend("llama3.1:8b", host=f"http://127.0.0.1:{dead_port}").complete("hi", 5.0)

    def test_garbage_and_missing_fields_are_backend_errors(self):
        for mode in ("garbage", "no_response_field"):
            _FakeOllama.mode = mode
            with self.assertRaises(BackendError):
                OllamaBackend("llama3.1:8b", host=self.host).complete("hi", 5.0)

    def test_real_transport_failures_still_fly_the_aircraft(self):
        """End to end through the policy: a hung model falls back to the deterministic policy."""
        _FakeOllama.mode = "hang"
        policy = LLMAgentPolicy(OllamaBackend("llama3.1:8b", host=self.host), timeout_s=0.5)
        deterministic = SearchAgentPolicy().decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED), deterministic)
        self.assertEqual(policy.records[0].rejected_as, "timeout")


class TestPromptCoordinateFormat(unittest.TestCase):
    def test_prompt_shows_the_coordinate_format_only_when_waypoints_are_offered(self):
        on = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(on).decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertIn('"x": <number>', on.prompts[0])
        off = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(off, waypoints_enabled=False).decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertNotIn('"x": <number>', off.prompts[0])


class TestBlockFeedback(unittest.TestCase):
    """The guardian's reason is shown to the model - informationally. It never gains authority."""

    def test_block_reason_is_shown_only_right_after_a_block(self):
        b = _belief()
        b.self_state.last_block_reason = "separation: (1.0, 20.0, 8.0) within 5.0m of Drone2"
        blocked = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(blocked).decide(b, ReplanEvent.GUARDIAN_BLOCKED)
        self.assertIn("within 5.0m of Drone2", blocked.prompts[0])
        calm = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(calm).decide(b, ReplanEvent.SKILL_SUCCEEDED)
        self.assertNotIn("blocked_by_the_safety_layer", calm.prompts[0])

    def test_no_reason_means_no_feedback_line(self):
        backend = ScriptedBackend([HOME_JSON], respond=None)
        LLMAgentPolicy(backend).decide(_belief(), ReplanEvent.GUARDIAN_BLOCKED)
        self.assertNotIn("blocked_by_the_safety_layer", backend.prompts[0])

    def test_agent_records_the_guardians_reason_and_the_next_prompt_carries_it(self):
        report, agent, _, policy = _fly_solo([_wp(0, 50), HOME_JSON, HOME_JSON, HOME_JSON])
        self.assertTrue(any("guardian_blocked" in t for t in report.trace))
        second_prompt = policy.records[1].prompts[0]
        self.assertIn("blocked_by_the_safety_layer", second_prompt)
        self.assertIn("restricted_zones", second_prompt)

    def test_reason_is_cleared_by_the_next_approved_flight(self):
        # blocked once, then a safe point inside sector C is approved and flown
        _, agent, _, _ = _fly_solo([_wp(0, 50), _wp(30, -30), HOME_JSON, HOME_JSON])
        self.assertIsNone(agent.belief.self_state.last_block_reason)

    def test_feedback_does_not_let_the_model_override_the_guardian(self):
        """Even a model told exactly why, and that keeps proposing it, is blocked every time."""
        report, agent, adapter, _ = _fly_solo([_wp(0, 50)] * 10)
        blocked = [e for e in agent.guardian_log.entries if e.outcome == "reject_and_replan"]
        self.assertGreater(len(blocked), 0)
        for cx, cy, _ in adapter.commanded:
            self.assertFalse(NFZ1[0] <= cx + 20.0 <= NFZ1[1] and NFZ1[2] <= cy <= NFZ1[3])
        self.assertTrue(report.trace[-1].endswith("->done"))


if __name__ == "__main__":
    unittest.main()
