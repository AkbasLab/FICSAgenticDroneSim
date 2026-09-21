"""Phase 12: the LLM as a persistent agent policy.

None of these need Ollama, a GPU or an API key. The `ScriptedBackend` stands in
for the model, which makes every test here deterministic — an unusual and
deliberate property for a test suite covering an LLM system. What is being
tested is never "is the model smart". It is:

  * the model cannot do anything outside the tool set (12.2);
  * malformed, invalid or hostile output is caught and named (12.3);
  * the prompt stays bounded and excludes the raw log (12.4);
  * the numbers come from Python, not the model (12.5);
  * every failure path ends in the aircraft being flown correctly (12.6);
  * four agents over one model process stay four separate agents (12.1);
  * a run records exactly what produced it (12.7).
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents import context_builder, llm_tools, reasoning_tools
from agentic_uav.agents.belief_state import BeliefState
from agentic_uav.agents.decision_schema import (
    DecisionError, RejectionReason, parse_decision, response_schema)
from agentic_uav.agents.llm_backends import (
    BackendError, BackendTimeout, ModelCard, ScriptedBackend, call_with_timeout,
    make_backend)
from agentic_uav.agents.llm_policy import LLMAgentPolicy
from agentic_uav.agents.llm_tools import ParamError
from agentic_uav.agents.objectives import Objective, SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.agents.safety_guardian import (
    GuardianOutcome, SafetyGuardian, SafetyLimits)
from agentic_uav.agents.search_policy import SearchAgentPolicy
from agentic_uav.control import skills as sk
from agentic_uav.core.models import Position3D
from agentic_uav.experiments.llm_log import LLMDecisionLog, combined_stats
from agentic_uav.experiments.team_runner import build_allocating_team, run_team
from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")


# --- helpers ---


def _scenario():
    return load_scenario(SCENARIO)


def decision(tool="hold", params=None, progress="partial", comms="nominal",
             risk="low", confidence=0.8, messages=None):
    return json.dumps({
        "situation_assessment": {"mission_progress": progress,
                                 "communication_status": comms,
                                 "current_risk": risk},
        "selected_tool": tool, "parameters": params or {},
        "outgoing_messages": messages or [], "confidence": confidence})


def _belief(sc, airborne=True, battery=1.0, task=True, teammate_at=None):
    v, sector = sc.vehicles[0], sc.sectors[0]
    b = BeliefState(v.vehicle_id, v.start, battery_total_s=900.0)
    b.brief(sc)
    b.observe(Position3D(10.0, 10.0, -8.0), 900.0 * (1.0 - battery))
    b.airborne = airborne
    if task:
        b.assign_task(SearchTask("search_S1", sector, sc.base.position))
    if teammate_at is not None:
        b.receive_teammate_report("Drone2", position=teammate_at,
                                  status="ok", sent_at=b.now)
    return b


def _policy(sc, answers=None, default=None, **kw):
    backend = ScriptedBackend(answers=answers, default=default)
    kw.setdefault("timeout_s", None)
    return LLMAgentPolicy(backend, sc.vehicles[0].vehicle_id,
                          safety_limits=SafetyLimits.from_scenario(sc), **kw)


def _agent(sc, policy, guardian=None):
    truth = GroundTruth(sc)
    v, sector = sc.vehicles[0], sc.sectors[0]
    a = PersistentAgent(
        v.vehicle_id, MockVehicleAdapter(0.0), policy=policy, home=v.start,
        battery_total_s=v.battery_s, cruise_altitude=sector.altitude,
        sensor=SensorModel(truth), roster=truth.roster(),
        sector_ids=truth.sector_ids(),
        guardian=guardian or SafetyGuardian(limits=SafetyLimits.from_scenario(sc)))
    a.belief.brief(sc)
    return a


# --- 12.2 the tool set is closed ---


def test_every_documented_tool_exists():
    """The 15 tools the specification names, and nothing extra by accident."""
    required = {"accept_task", "decline_task", "compute_task_cost",
                "announce_task", "send_bid", "claim_task", "release_task",
                "change_role", "request_help", "report_target", "start_search",
                "go_to_waypoint", "act_as_relay", "return_home", "hold"}
    have = set(llm_tools.TOOL_NAMES)
    assert required <= have, f"missing tools: {required - have}"
    assert have == required, f"undeclared extra tools: {have - required}"


def test_an_invented_tool_is_refused():
    try:
        llm_tools.get("execute_python")
        raise AssertionError("an invented tool was accepted")
    except ParamError as e:
        assert "not an available tool" in str(e)
        assert "hold" in str(e), "the error should list the legal tools"


def test_unknown_parameters_are_refused_not_ignored():
    """Silently dropping an unexpected parameter executes a command the model
    did not intend."""
    try:
        llm_tools.get("hold").validate({"duration_s": 5.0, "altitude": -8.0})
        raise AssertionError("an unknown parameter was accepted")
    except ParamError as e:
        assert "altitude" in str(e)


def test_missing_required_parameter_is_refused():
    try:
        llm_tools.get("change_role").validate({"new_role": "relay"})
        raise AssertionError("missing reason_code was accepted")
    except ParamError as e:
        assert "reason_code" in str(e)


def test_parameters_outside_their_range_are_refused():
    for params in ({"x": 5000.0, "y": 0.0}, {"x": 0.0, "y": 0.0, "z": 40.0},
                   {"x": 0.0, "y": 0.0, "speed_mps": 99.0}):
        try:
            llm_tools.get("go_to_waypoint").validate(params)
            raise AssertionError(f"out-of-range parameters accepted: {params}")
        except ParamError:
            pass


def test_non_finite_parameters_are_refused():
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            llm_tools.get("go_to_waypoint").validate({"x": bad, "y": 0.0})
            raise AssertionError(f"{bad} accepted as a coordinate")
        except ParamError as e:
            assert "finite" in str(e)


def test_a_boolean_is_never_accepted_as_a_number():
    """True silently becoming 1.0 is how a nonsense altitude reaches a vehicle."""
    try:
        llm_tools.get("go_to_waypoint").validate({"x": True, "y": 0.0})
        raise AssertionError("a boolean was accepted as a coordinate")
    except ParamError as e:
        assert "boolean" in str(e)


def test_quoted_numbers_are_accepted():
    """Models routinely quote numbers; that is not an error worth a retry."""
    out = llm_tools.get("go_to_waypoint").validate({"x": "20.5", "y": "-3"})
    assert out["x"] == 20.5 and out["y"] == -3.0


def test_role_and_reason_codes_are_closed_vocabularies():
    try:
        llm_tools.get("change_role").validate(
            {"new_role": "supervisor", "reason_code": "BASE_LINK_LOST"})
        raise AssertionError("an invented role was accepted")
    except ParamError:
        pass
    try:
        llm_tools.get("change_role").validate(
            {"new_role": "relay", "reason_code": "I felt like it"})
        raise AssertionError("free-text reason accepted")
    except ParamError:
        pass


def test_every_tool_appears_in_the_prompt_catalogue():
    """A tool the model is never shown may as well not exist."""
    cat = llm_tools.catalogue()
    for name in llm_tools.TOOL_NAMES:
        assert name in cat, f"{name} is missing from the prompt catalogue"


# --- 12.3 the decision schema ---


def test_a_well_formed_decision_parses():
    d = parse_decision(decision("change_role",
                                {"new_role": "relay",
                                 "reason_code": "BASE_LINK_LOST"},
                                confidence=0.78))
    assert d.tool_name == "change_role"
    assert d.parameters["new_role"] == "relay"
    assert d.reason_code == "BASE_LINK_LOST"
    assert abs(d.confidence - 0.78) < 1e-9
    assert d.assessment.communication_status == "nominal"


def test_the_specification_example_parses_verbatim():
    """The exact object from the Phase 12.3 spec must be accepted as written."""
    d = parse_decision(json.dumps({
        "situation_assessment": {"mission_progress": "partial",
                                 "communication_status": "degraded",
                                 "current_risk": "medium"},
        "selected_tool": "change_role",
        "parameters": {"new_role": "relay", "reason_code": "BASE_LINK_LOST"},
        "outgoing_messages": [{"message_type": "ROLE_CHANGE",
                               "recipients": ["Drone2", "Drone3"],
                               "payload": {"new_role": "relay"}}],
        "confidence": 0.78}), known_peers={"Drone2", "Drone3"})
    assert d.tool_name == "change_role"
    assert len(d.outgoing) == 1
    assert d.outgoing[0].recipients == ("Drone2", "Drone3")


def _rejects(raw, reason, **kw):
    try:
        parse_decision(raw, **kw)
        raise AssertionError(f"accepted output that should be {reason}")
    except DecisionError as e:
        assert e.reason is reason, f"expected {reason}, got {e.reason}"
        assert e.hint, "a rejection must carry a usable repair hint"
        return e


def test_malformed_and_invalid_outputs_are_each_named():
    _rejects("I think we should search sector one", RejectionReason.MALFORMED_JSON)
    _rejects('{"situation_assessment": {', RejectionReason.MALFORMED_JSON)
    _rejects('["a", "list"]', RejectionReason.NOT_AN_OBJECT)
    _rejects("", RejectionReason.EMPTY_RESPONSE)
    _rejects(decision("deploy_countermeasures"), RejectionReason.UNKNOWN_TOOL)
    _rejects(decision("change_role", {"new_role": "relay"}),
             RejectionReason.BAD_PARAMETERS)
    _rejects(decision("hold", progress="going_great"),
             RejectionReason.BAD_ASSESSMENT)
    _rejects(decision("hold", confidence=7.0), RejectionReason.BAD_CONFIDENCE)
    _rejects(json.dumps({"situation_assessment":
                         {"mission_progress": "partial",
                          "communication_status": "nominal",
                          "current_risk": "low"},
                         "selected_tool": "hold", "parameters": {}}),
             RejectionReason.MISSING_FIELD)


def test_markdown_fences_are_tolerated():
    """Schema-constrained models still emit ```json. Not worth a retry."""
    d = parse_decision("```json\n" + decision("hold") + "\n```")
    assert d.tool_name == "hold"


def test_messages_to_nonexistent_drones_are_refused():
    """A hallucinated teammate would vanish into the bus and look like loss."""
    _rejects(decision("hold", messages=[{"message_type": "help_request",
                                         "recipients": ["Drone99"],
                                         "payload": {}}]),
             RejectionReason.BAD_MESSAGES, known_peers={"Drone1", "Drone2"})


def test_message_floods_are_refused():
    many = [{"message_type": "heartbeat", "recipients": ["Drone2"],
             "payload": {}}] * 20
    _rejects(decision("hold", messages=many), RejectionReason.BAD_MESSAGES,
             known_peers={"Drone2"})


def test_invented_message_types_are_refused():
    _rejects(decision("hold", messages=[{"message_type": "SELF_DESTRUCT",
                                         "recipients": ["Drone2"]}]),
             RejectionReason.BAD_MESSAGES, known_peers={"Drone2"})


def test_only_structural_faults_are_worth_a_correction():
    """A timeout cannot be corrected by explaining the problem to it."""
    assert RejectionReason.MALFORMED_JSON.correctable
    assert RejectionReason.UNKNOWN_TOOL.correctable
    assert not RejectionReason.TIMEOUT.correctable
    assert not RejectionReason.BACKEND_ERROR.correctable


def test_the_response_schema_covers_every_tool():
    """Constrained decoding must not exclude a legal tool."""
    schema = response_schema()
    enum = schema["properties"]["selected_tool"]["enum"]
    assert set(enum) == set(llm_tools.TOOL_NAMES)


# --- 12.4 bounded context ---


def test_the_prompt_contains_all_nine_required_sections():
    sc = _scenario()
    b = _belief(sc)
    ctx = context_builder.build(b, step=1, task=b.task,
                                safety_limits=SafetyLimits.from_scenario(sc))
    d = ctx.as_dict()
    for key in ("mission", "constraints", "role_and_task", "belief",
                "recent_messages", "communication", "last_skill_result",
                "unresolved_decisions"):
        assert key in d, f"the prompt is missing {key}"
    assert llm_tools.TOOL_NAMES[0] in ctx.to_prompt(), "tools are missing"


def test_the_prompt_excludes_the_raw_flight_log():
    """12.4: not the complete raw log, not every previous message.

    Checked structurally rather than by eyeballing the prompt: the context
    object must not carry a decision log or a full message history at all.
    """
    sc = _scenario()
    b = _belief(sc)
    for i in range(50):
        b.push_decision if False else None
    ctx = context_builder.build(b, step=1, task=b.task)
    blob = json.dumps(ctx.as_dict(), default=str).lower()
    for forbidden in ("decision_log", "flight_log", "full_history",
                      "all_messages", "transcript"):
        assert forbidden not in blob, f"the prompt carries {forbidden}"


def test_the_prompt_does_not_grow_without_bound():
    """Decision quality must not depend on how long the drone has been flying."""
    sc = _scenario()
    limits = SafetyLimits.from_scenario(sc)

    b = _belief(sc)
    small = context_builder.build(b, step=1, task=b.task,
                                  safety_limits=limits).size_chars()

    b2 = _belief(sc)
    for i in range(200):
        b2.receive_teammate_report(f"Drone{i % 4 + 2}",
                                   position=Position3D(i, i, -8.0),
                                   status="ok", sent_at=b2.now)
        b2.note_detections([f"T{i}"])
        b2.note_searched(f"S{i}", None)
    big = context_builder.build(b2, step=500, task=b2.task,
                                safety_limits=limits).size_chars()

    assert big < small * 3, (
        f"context grew from {small} to {big} chars over a long mission; "
        f"it must stay bounded")


def test_only_important_messages_reach_the_prompt():
    """Heartbeats already moved the belief; replaying them crowds out the
    messages that actually need a decision."""
    sc = _scenario()
    b = _belief(sc)

    class M:
        def __init__(self, t, sender="Drone2"):
            self.message_type = t
            self.sender_id = sender
            self.payload = {}
            self.sent_at_s = 0.0

    msgs = [M("heartbeat") for _ in range(30)] + [M("help_request")]
    rows = context_builder.recent_important(msgs, now=10.0)
    assert len(rows) <= context_builder.SUMMARY_LIMITS["recent_messages"]
    assert all(r["type"] != "heartbeat" for r in rows)
    assert any(r["type"] == "help_request" for r in rows)


def test_the_correction_prompt_names_the_actual_fault():
    """'Invalid, try again' mostly reproduces the same error."""
    p = context_builder.correction_prompt("selected_tool 'foo' is not a tool")
    assert "foo" in p
    assert "NOT executed" in p


# --- 12.5 deterministic calculation ---


def test_the_calculators_agree_with_plain_geometry():
    sc = _scenario()
    b = _belief(sc)                      # at (10, 10, -8)
    d = reasoning_tools.distance(b, (10.0, 40.0, -8.0))
    assert abs(d["horizontal_m"] - 30.0) < 1e-6
    assert abs(d["vertical_m"]) < 1e-6


def test_battery_sufficiency_always_includes_the_way_home():
    """Answering 'can I get there' and acting on it strands drones."""
    sc = _scenario()
    b = _belief(sc)
    out = reasoning_tools.battery_sufficient(b, to=(60.0, 60.0, -8.0))
    legs = [l["leg"] for l in out["legs"]]
    assert "return_home" in legs, "the return leg was not counted"
    assert out["required_with_margin_s"] > out["needed_s"]


def test_a_nearly_flat_battery_is_reported_insufficient():
    sc = _scenario()
    b = _belief(sc, battery=0.02)
    out = reasoning_tools.battery_sufficient(b, to=(80.0, 80.0, -8.0))
    assert not out["sufficient"]


def test_route_feasibility_matches_the_guardian():
    """The model can find out a waypoint is illegal before proposing it."""
    sc = _scenario()
    limits = SafetyLimits.from_scenario(sc)
    b = _belief(sc)
    guardian = SafetyGuardian(limits=limits)

    for point in ((250.0, 10.0, -8.0), (20.0, 20.0, -1.0), (20.0, 20.0, -8.0)):
        tool_says = reasoning_tools.route_feasible(b, point, limits=limits)
        cmd = sk.GoToWaypointCommand(waypoint=Position3D(*point))
        guardian_says = guardian.evaluate(cmd, b)
        approved = guardian_says.outcome is GuardianOutcome.APPROVE
        assert tool_says["feasible"] == approved, (
            f"{point}: the feasibility tool and the guardian disagree "
            f"({tool_says['reasons']} vs {guardian_says.reason})")


def test_task_cost_is_computed_not_chosen():
    """A model that picks its own bid wins everything by bidding zero."""
    sc = _scenario()
    from agentic_uav.coordination.tasks import tasks_from_scenario
    b = _belief(sc)
    task = tasks_from_scenario(sc, include_relay=False)[0]
    out = reasoning_tools.task_cost(b, task)
    assert "cost" in out and isinstance(out["cost"], float)
    assert "breakdown" in out and set("DBLCR") <= set(out["breakdown"])
    again = reasoning_tools.task_cost(b, task)
    assert out["cost"] == again["cost"], "the cost model is not deterministic"


def test_separation_risk_reports_staleness_alongside_distance():
    """'3 m away' and '3 m away as of 90 seconds ago' are different facts."""
    sc = _scenario()
    b = _belief(sc, teammate_at=Position3D(11.0, 10.0, -8.0))
    out = reasoning_tools.separation_risk(b, min_separation_m=3.0)
    assert out["conflict"] is True
    assert out["nearest"]["vehicle_id"] == "Drone2"
    assert "position_age_s" in out["nearest"]
    assert "believed" in out["note"]


def test_the_reasoning_tools_never_touch_ground_truth():
    """Phase 6's boundary must survive the model being given calculators."""
    import inspect
    src = inspect.getsource(reasoning_tools)
    for forbidden in ("GroundTruth", "true_position", "scenario.targets",
                      "NetworkModel"):
        assert forbidden not in src, (
            f"reasoning_tools references {forbidden}; agents must reason from "
            f"belief only")


def test_sweep_time_scales_with_the_area():
    sc = _scenario()
    small = reasoning_tools.sweep_time(sc.sectors[0], lane_spacing_m=8.0)
    dense = reasoning_tools.sweep_time(sc.sectors[0], lane_spacing_m=4.0)
    assert dense["seconds"] > small["seconds"]
    assert dense["lanes"] > small["lanes"]


# --- 12.6 timeout, correction, fallback ---


def test_a_good_decision_is_used():
    sc = _scenario()
    p = _policy(sc, default=decision("start_search"))
    b = _belief(sc)
    assert p.next_objective(b) is Objective.SEARCH_SECTOR
    assert not p.log.turns[-1].used_fallback


def test_one_correction_is_attempted_then_the_decision_is_used():
    """12.6.1: a model told precisely what was wrong usually fixes it."""
    sc = _scenario()
    p = _policy(sc, answers=[decision("nonexistent_tool"),
                             decision("start_search")])
    b = _belief(sc)
    objective = p.next_objective(b)
    turn = p.log.turns[-1]
    assert turn.corrected, "no correction was attempted"
    assert turn.attempts == 2
    assert not turn.used_fallback
    assert objective is Objective.SEARCH_SECTOR


def test_the_correction_prompt_is_actually_sent():
    sc = _scenario()
    backend = ScriptedBackend(answers=[decision("nope"), decision("hold")])
    p = LLMAgentPolicy(backend, "Drone1", timeout_s=None,
                       safety_limits=SafetyLimits.from_scenario(sc))
    p.next_objective(_belief(sc))
    assert len(backend.calls) == 2
    assert "rejected" in backend.calls[1]["user"].lower()
    assert "nope" in backend.calls[1]["user"]


def test_two_bad_answers_fall_through_to_the_deterministic_policy():
    """12.6.2. The aircraft is flown correctly regardless."""
    sc = _scenario()
    p = _policy(sc, answers=[decision("bad_tool"), decision("also_bad")])
    b = _belief(sc)
    objective = p.next_objective(b)
    turn = p.log.turns[-1]
    assert turn.used_fallback
    assert objective is SearchAgentPolicy().next_objective(b)


def test_a_timeout_falls_back_without_attempting_a_correction():
    """Retrying a hang costs another hang, on an airborne drone."""
    sc = _scenario()
    backend = ScriptedBackend(answers=[BackendTimeout("no answer")])
    p = LLMAgentPolicy(backend, "Drone1", timeout_s=None,
                       safety_limits=SafetyLimits.from_scenario(sc))
    p.next_objective(_belief(sc))
    turn = p.log.turns[-1]
    assert turn.used_fallback
    assert turn.rejection_reason == "timeout"
    assert not turn.corrected
    assert len(backend.calls) == 1, "a timeout must not be retried"


def test_a_dead_backend_falls_back():
    sc = _scenario()
    p = _policy(sc, answers=[BackendError("connection refused")])
    p.next_objective(_belief(sc))
    assert p.log.turns[-1].used_fallback


def test_an_unexpected_backend_exception_does_not_crash_the_agent():
    """A backend that raises something nobody anticipated must not take the
    aircraft down with it."""
    sc = _scenario()
    p = _policy(sc, answers=[ZeroDivisionError("something absurd")])
    objective = p.next_objective(_belief(sc))
    assert isinstance(objective, Objective)
    assert p.log.turns[-1].used_fallback


def test_the_wall_clock_timeout_is_enforced():
    import time

    class Slow:
        provider = "scripted"
        model = "slow"

        def card(self):
            return ModelCard("scripted", "slow")

        def complete(self, system, user, timeout_s=None, **_):
            time.sleep(1.5)
            return decision("hold")

    started = time.monotonic()
    try:
        call_with_timeout(Slow(), "s", "u", timeout_s=0.2)
        raise AssertionError("the timeout did not fire")
    except BackendTimeout:
        pass
    assert time.monotonic() - started < 1.2, "the call was not abandoned promptly"


def test_every_failure_mode_still_flies_the_aircraft():
    """The catalogue, end to end: whatever the model does, the drone comes home."""
    sc = _scenario()
    bad_answers = [
        "not json at all",
        '{"truncated": ',
        decision("invented_tool"),
        decision("change_role", {"new_role": "relay"}),
        decision("hold", progress="excellent"),
        decision("hold", confidence=-4.0),
        BackendTimeout("hang"),
        BackendError("refused"),
        "",
    ]
    for answer in bad_answers:
        p = _policy(sc, default=answer)
        agent = _agent(sc, p)
        report = agent.run(SearchTask("search_S1", sc.sectors[0],
                                      sc.base.position))
        assert report.landed, f"the drone did not land after: {answer!r}"
        assert report.returned_home, f"the drone did not come home after: {answer!r}"
        assert p.log.stats()["fallback_rate"] > 0.0


def test_safety_states_are_never_delegated_to_the_model():
    """Take-off, low battery and 'the mission is over' are facts, not judgements."""
    sc = _scenario()

    on_ground = _policy(sc, default=decision("start_search"))
    b = _belief(sc, airborne=False)
    assert on_ground.next_objective(b) is Objective.TAKE_OFF
    assert on_ground.log.turns[-1].fallback_cause == "not_airborne_yet"

    flat = _policy(sc, default=decision("start_search"))
    b2 = _belief(sc, battery=0.05)
    flat.next_objective(b2)
    assert flat.log.turns[-1].used_fallback
    assert "battery" in flat.log.turns[-1].fallback_cause


def test_a_finished_mission_does_not_loop_forever():
    """Regression. The model cannot infer 'we are done' from a context that only
    ever says 'you hold no task' - it asked to bid 117 times instead."""
    sc = _scenario()
    p = _policy(sc, default=decision("send_bid", {"task_id": "search_S1"}))
    b = _belief(sc, task=False)
    b.no_work_remaining = True
    objective = p.next_objective(b)
    assert objective in (Objective.RETURN_HOME, Objective.LAND)
    assert p.log.turns[-1].fallback_cause == "no_work_remaining"


def test_the_model_has_no_way_to_land_so_landing_is_deterministic():
    """Regression. The 15 permitted tools contain no landing action, so a model
    that has finished can only keep choosing `return_home`. It did exactly that
    60 times, hovering over its own pad, until the deterministic policy was
    given the terminal descent."""
    assert "land" not in llm_tools.TOOL_NAMES, \
        "if a land tool is ever added, revisit this rule"
    sc = _scenario()
    p = _policy(sc, default=decision("return_home", progress="complete"))
    b = _belief(sc)
    b.at_sector = True
    b.sector_searched = True             # the work is genuinely finished
    b.reported = True
    b.observe(b.home, 60.0)              # and the drone is over its own pad
    objective = p.next_objective(b)
    assert objective is Objective.LAND, f"got {objective}"
    assert p.log.turns[-1].fallback_cause == "landing_is_deterministic"


def test_a_single_agent_llm_mission_lands_without_an_allocator():
    """The team run sets no_work_remaining via the allocator; a solo agent has
    no allocator, so it must still reach the ground on its own."""
    sc = _scenario()
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from run_llm_agents import sensible_model
    p = _policy(sc, default=sensible_model)
    agent = _agent(sc, p)
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))
    assert report.landed and report.returned_home
    assert agent.steps < 30, f"took {agent.steps} steps to land"


def test_endless_coordination_is_bounded():
    """A policy that keeps coordinating without acquiring work is stuck, not
    thoughtful. The Phase 11 escalation lesson, applied to the policy layer."""
    sc = _scenario()
    p = _policy(sc, default=decision("send_bid", {"task_id": "search_S1"}))
    b = _belief(sc, task=False)
    outcomes = [p.next_objective(b) for _ in range(12)]
    assert any(t.fallback_cause == "coordination_not_converging"
               for t in p.log.turns), \
        f"the agent coordinated forever: {[o.value for o in outcomes]}"


# --- the model cannot get around the guardian ---


def test_a_valid_but_unsafe_command_is_still_stopped():
    """Perfect JSON, a real tool, a dangerous waypoint. Phase 11 still applies."""
    sc = _scenario()
    limits = SafetyLimits.from_scenario(sc)
    p = _policy(sc, default=decision("go_to_waypoint",
                                     {"x": 400.0, "y": 400.0, "z": -8.0}))
    b = _belief(sc)
    objective = p.next_objective(b)
    command = p.choose_skill(b, objective)
    verdict = SafetyGuardian(limits=limits).evaluate(command, b)
    assert verdict.outcome is not GuardianOutcome.APPROVE
    assert {"geofence", "waypoint_validity"} & {c.name for c in verdict.failed}


def test_an_unsafe_model_cannot_fly_the_drone_out_of_bounds():
    sc = _scenario()
    p = _policy(sc, default=decision("go_to_waypoint",
                                     {"x": 250.0, "y": 250.0, "z": -8.0}))
    agent = _agent(sc, p)
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))
    assert report.landed
    for rec in agent.guardian_log.records:
        if rec.outcome == "approve":
            wp = (rec.proposed_detail or {}).get("waypoint")
            if wp:
                assert abs(wp[0]) < 200 and abs(wp[1]) < 200, wp


def test_the_model_never_builds_the_sweep_itself():
    """`start_search` becomes the deterministic sweep, with the contract
    constants the executor expects - not a path the model wrote."""
    sc = _scenario()
    p = _policy(sc, default=decision("start_search"))
    b = _belief(sc)
    objective = p.next_objective(b)
    command = p.choose_skill(b, objective)
    assert isinstance(command, sk.SearchRegionCommand)
    reference = SearchAgentPolicy().choose_skill(b, Objective.SEARCH_SECTOR)
    assert command.lane_spacing_m == reference.lane_spacing_m
    assert command.speed_mps == reference.speed_mps


# --- 12.1 separate agents, shared model ---


def test_four_agents_share_one_backend_but_not_their_state():
    """The research property: separate agent state, not separate GPU copies."""
    sc = _scenario()
    backend = ScriptedBackend(default=decision("hold"))
    limits = SafetyLimits.from_scenario(sc)
    policies = {}

    def factory(vid, allocator):
        p = LLMAgentPolicy(backend, vid, safety_limits=limits,
                           allocator=allocator, timeout_s=None)
        policies[vid] = p
        return p

    agents, tasks, bus, truth = build_allocating_team(
        sc, lambda vid: MockVehicleAdapter(0.0), policy_factory=factory)

    assert len(policies) == 4
    assert len({id(p) for p in policies.values()}) == 4, "policies were shared"
    assert len({id(p.backend) for p in policies.values()}) == 1, \
        "the backend was not shared; 12.1 asks for one model process"
    assert len({id(p.log) for p in policies.values()}) == 4, "logs were shared"
    assert len({id(a.belief) for a in agents}) == 4, "beliefs were shared"
    assert len({id(p.memory) for p in policies.values()}) == 4, "memory was shared"


def test_one_agents_memory_does_not_leak_into_another():
    sc = _scenario()
    backend = ScriptedBackend(default=decision("hold"))
    limits = SafetyLimits.from_scenario(sc)
    a = LLMAgentPolicy(backend, "Drone1", safety_limits=limits, timeout_s=None)
    b_pol = LLMAgentPolicy(backend, "Drone2", safety_limits=limits, timeout_s=None)

    belief = _belief(sc)
    for _ in range(3):
        a.next_objective(belief)

    assert len(a.memory) == 3
    assert b_pol.memory == [], "one agent's memory reached another"
    assert a.log.turns and not b_pol.log.turns


def test_each_agent_is_prompted_about_itself():
    sc = _scenario()
    backend = ScriptedBackend(default=decision("hold"))
    limits = SafetyLimits.from_scenario(sc)
    for vid in ("Drone1", "Drone2"):
        p = LLMAgentPolicy(backend, vid, safety_limits=limits, timeout_s=None)
        belief = _belief(sc)
        belief.self_.vehicle_id = vid
        p.next_objective(belief)
    assert '"vehicle_id": "Drone1"' in backend.calls[0]["user"]
    assert '"vehicle_id": "Drone2"' in backend.calls[1]["user"]


def test_a_four_agent_llm_mission_completes():
    """The exit criterion: each drone uses its own persistent context to make
    mission-level decisions in flight, and everything still passes validation
    and runtime assurance."""
    sc = _scenario()
    limits = SafetyLimits.from_scenario(sc)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from run_llm_agents import sensible_model

    backend = ScriptedBackend(default=sensible_model)
    policies = {}

    def factory(vid, allocator):
        p = LLMAgentPolicy(backend, vid, safety_limits=limits,
                           allocator=allocator, timeout_s=None)
        policies[vid] = p
        return p

    agents, tasks, bus, truth = build_allocating_team(
        sc, lambda vid: MockVehicleAdapter(0.0), policy_factory=factory,
        guardian_factory=lambda vid: SafetyGuardian(limits=limits))
    report = run_team(agents, tasks, bus)

    assert len(report.sectors_searched) == len(sc.sectors), \
        f"only {report.sectors_searched} were searched"
    assert all(r.landed for r in report.agents.values()), "a drone did not land"

    stats = combined_stats([p.log for p in policies.values()])
    assert stats["turns"] > 0
    assert stats["fallback_rate"] < 0.9, \
        "almost every decision fell back; this is the rule agent in a costume"

    for a in agents:
        for rec in a.guardian_log.records:
            if rec.outcome == "approve":
                wp = (rec.proposed_detail or {}).get("waypoint")
                if wp:
                    assert abs(wp[0]) < 200 and abs(wp[1]) < 200


# --- 12.7 reproducibility ---


def test_a_floating_model_tag_is_not_accepted_as_pinned():
    """A method section that says 'Gemini' describes a system that no longer
    exists."""
    assert not ModelCard("gemini", "gemini-flash-latest").is_pinned
    assert not ModelCard("ollama", "llama3.1:latest").is_pinned
    assert ModelCard("ollama", "llama3.1:8b").is_pinned
    assert ModelCard("scripted", "scripted-v1").is_pinned


def test_an_unpinned_or_hot_model_warns():
    warnings = ModelCard("gemini", "gemini-flash-latest",
                         temperature=0.7).warnings()
    assert any("not pinned" in w for w in warnings)
    assert any("temperature" in w for w in warnings)


def test_temperature_defaults_to_zero():
    assert ModelCard("ollama", "llama3.1:8b").temperature == 0.0
    assert ModelCard("ollama", "llama3.1:8b").warnings() == []


def test_the_log_saves_every_prompt_and_output():
    import tempfile
    sc = _scenario()
    p = _policy(sc, default=decision("hold"))
    b = _belief(sc)
    p.next_objective(b)
    p.next_objective(b)

    with tempfile.TemporaryDirectory() as d:
        path = p.log.save(os.path.join(d, "Drone1.json"))
        saved = json.load(open(path))
    assert saved["model"]["provider"] == "scripted"
    assert len(saved["turns"]) == 2
    for t in saved["turns"]:
        assert t["system_prompt"], "a prompt was not saved"
        assert t["user_prompt"], "a prompt was not saved"
        assert t["raw_response"], "a model output was not saved"


def test_the_log_reports_the_numbers_a_paper_needs():
    sc = _scenario()
    p = _policy(sc, answers=[decision("hold"),
                             decision("bad"), decision("hold"),
                             BackendTimeout("x")],
                )
    b = _belief(sc)
    for _ in range(3):
        p.next_objective(b)
    s = p.log.stats()
    assert s["turns"] == 3
    assert 0.0 <= s["fallback_rate"] <= 1.0
    assert s["corrections"] == 1
    assert "tools_used" in s and "rejections" in s


def test_the_same_scripted_run_reproduces_exactly():
    """Determinism is what lets two architectures be compared under one seed."""
    sc = _scenario()
    outs = []
    for _ in range(2):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from run_llm_agents import sensible_model
        backend = ScriptedBackend(default=sensible_model)
        limits = SafetyLimits.from_scenario(sc)
        policies = {}

        def factory(vid, allocator):
            p = LLMAgentPolicy(backend, vid, safety_limits=limits,
                               allocator=allocator, timeout_s=None)
            policies[vid] = p
            return p

        agents, tasks, bus, truth = build_allocating_team(
            sc, lambda vid: MockVehicleAdapter(0.0), policy_factory=factory)
        run_team(agents, tasks, bus)
        outs.append([(vid, tuple(p.log.tools_used().items()))
                     for vid, p in sorted(policies.items())])
    assert outs[0] == outs[1], "two identical runs diverged"


def test_the_default_backend_needs_nothing_installed():
    """A reviewer with no Ollama and no API key must still be able to run this."""
    backend = make_backend("scripted")
    assert backend.card().provider == "scripted"
    assert backend.card().is_pinned


# --- runner ---

if __name__ == "__main__":
    tests = [
        # 12.2
        ("every documented tool exists", test_every_documented_tool_exists),
        ("an invented tool is refused", test_an_invented_tool_is_refused),
        ("unknown parameters refused", test_unknown_parameters_are_refused_not_ignored),
        ("missing required parameter refused", test_missing_required_parameter_is_refused),
        ("out-of-range parameters refused", test_parameters_outside_their_range_are_refused),
        ("non-finite parameters refused", test_non_finite_parameters_are_refused),
        ("bool is not a number", test_a_boolean_is_never_accepted_as_a_number),
        ("quoted numbers accepted", test_quoted_numbers_are_accepted),
        ("roles/reasons are closed vocabularies",
         test_role_and_reason_codes_are_closed_vocabularies),
        ("every tool is in the prompt", test_every_tool_appears_in_the_prompt_catalogue),
        # 12.3
        ("a well-formed decision parses", test_a_well_formed_decision_parses),
        ("the spec example parses verbatim",
         test_the_specification_example_parses_verbatim),
        ("bad outputs are each named", test_malformed_and_invalid_outputs_are_each_named),
        ("markdown fences tolerated", test_markdown_fences_are_tolerated),
        ("messages to unknown drones refused",
         test_messages_to_nonexistent_drones_are_refused),
        ("message floods refused", test_message_floods_are_refused),
        ("invented message types refused", test_invented_message_types_are_refused),
        ("only structural faults are correctable",
         test_only_structural_faults_are_worth_a_correction),
        ("schema covers every tool", test_the_response_schema_covers_every_tool),
        # 12.4
        ("prompt has all nine sections",
         test_the_prompt_contains_all_nine_required_sections),
        ("prompt excludes the raw log", test_the_prompt_excludes_the_raw_flight_log),
        ("prompt does not grow unbounded", test_the_prompt_does_not_grow_without_bound),
        ("only important messages included", test_only_important_messages_reach_the_prompt),
        ("correction names the fault", test_the_correction_prompt_names_the_actual_fault),
        # 12.5
        ("calculators agree with geometry", test_the_calculators_agree_with_plain_geometry),
        ("battery includes the way home",
         test_battery_sufficiency_always_includes_the_way_home),
        ("flat battery is insufficient", test_a_nearly_flat_battery_is_reported_insufficient),
        ("feasibility matches the guardian", test_route_feasibility_matches_the_guardian),
        ("task cost is computed not chosen", test_task_cost_is_computed_not_chosen),
        ("separation reports staleness",
         test_separation_risk_reports_staleness_alongside_distance),
        ("tools never touch ground truth", test_the_reasoning_tools_never_touch_ground_truth),
        ("sweep time scales with area", test_sweep_time_scales_with_the_area),
        # 12.6
        ("a good decision is used", test_a_good_decision_is_used),
        ("one correction then success",
         test_one_correction_is_attempted_then_the_decision_is_used),
        ("the correction prompt is sent", test_the_correction_prompt_is_actually_sent),
        ("two bad answers fall back",
         test_two_bad_answers_fall_through_to_the_deterministic_policy),
        ("a timeout is not retried",
         test_a_timeout_falls_back_without_attempting_a_correction),
        ("a dead backend falls back", test_a_dead_backend_falls_back),
        ("unexpected exception contained",
         test_an_unexpected_backend_exception_does_not_crash_the_agent),
        ("wall-clock timeout enforced", test_the_wall_clock_timeout_is_enforced),
        ("every failure mode still flies",
         test_every_failure_mode_still_flies_the_aircraft),
        ("safety states not delegated",
         test_safety_states_are_never_delegated_to_the_model),
        ("a finished mission does not loop",
         test_a_finished_mission_does_not_loop_forever),
        ("endless coordination is bounded", test_endless_coordination_is_bounded),
        ("no land tool -> deterministic landing",
         test_the_model_has_no_way_to_land_so_landing_is_deterministic),
        ("solo LLM mission lands",
         test_a_single_agent_llm_mission_lands_without_an_allocator),
        # guardian still holds
        ("valid but unsafe is stopped", test_a_valid_but_unsafe_command_is_still_stopped),
        ("unsafe model cannot leave bounds",
         test_an_unsafe_model_cannot_fly_the_drone_out_of_bounds),
        ("the model never builds the sweep", test_the_model_never_builds_the_sweep_itself),
        # 12.1
        ("shared backend, separate state",
         test_four_agents_share_one_backend_but_not_their_state),
        ("memory does not leak", test_one_agents_memory_does_not_leak_into_another),
        ("each agent is prompted about itself", test_each_agent_is_prompted_about_itself),
        ("4-agent LLM mission completes", test_a_four_agent_llm_mission_completes),
        # 12.7
        ("floating tags are not pinned",
         test_a_floating_model_tag_is_not_accepted_as_pinned),
        ("unpinned/hot models warn", test_an_unpinned_or_hot_model_warns),
        ("temperature defaults to zero", test_temperature_defaults_to_zero),
        ("prompts and outputs are saved", test_the_log_saves_every_prompt_and_output),
        ("log reports the paper's numbers", test_the_log_reports_the_numbers_a_paper_needs),
        ("scripted runs reproduce exactly", test_the_same_scripted_run_reproduces_exactly),
        ("default backend needs nothing", test_the_default_backend_needs_nothing_installed),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
