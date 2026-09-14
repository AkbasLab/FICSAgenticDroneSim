"""Phase 11 tests: the independent runtime-safety guardian.

Structured as: each of the ten checks catches its own hazard; each outcome and
fallback behaves as specified; the log separates agent reliability from guardian
correction; and finally the exit criterion — deliberately unsafe commands from
both a rule policy and an LLM-style malformed plan never reach the vehicle.

A guardian nobody has attacked is an assumption, so most of this file is attack.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.belief_state import BeliefState
from agentic_uav.agents.objectives import SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.agents.safety_guardian import (
    FallbackAction, FlightPhase, GuardianOutcome, SafetyGuardian, SafetyLimits)
from agentic_uav.agents.search_policy import SearchAgentPolicy
from agentic_uav.agents.unsafe_injection import (
    UNSAFE_COMMANDS, InjectingPolicy, case)
from agentic_uav.control import skills as sk
from agentic_uav.core.models import Position3D
from agentic_uav.experiments.guardian_log import GuardianLog
from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")


def _scenario():
    return load_scenario(SCENARIO)


def _setup(battery=1.0, airborne=True, teammate_at=None, scenario=None):
    sc = scenario or _scenario()
    v = sc.vehicles[0]
    b = BeliefState(v.vehicle_id, v.start, battery_total_s=900.0)
    b.brief(sc)
    b.observe(Position3D(10.0, 10.0, -8.0), 900.0 * (1.0 - battery))
    b.airborne = airborne
    if teammate_at is not None:
        b.receive_teammate_report("Drone2", position=teammate_at,
                                  status="ok", sent_at=b.now)
    g = SafetyGuardian(limits=SafetyLimits.from_scenario(sc),
                       log=GuardianLog(v.vehicle_id))
    return g, b, sc


def _wp(x, y, z=-8.0, **kw):
    return sk.GoToWaypointCommand(waypoint=Position3D(x, y, z), **kw)


def _failed_names(decision):
    return {c.name for c in decision.failed}


# --- 11.1 the ten checks ---

def test_all_ten_checks_are_present():
    g, b, _ = _setup()
    names = {c.name for c in g.run_checks(_wp(20, 20), b)}
    names |= {c.name for c in g.run_checks(sk.LandCommand(), b)}
    required = {"altitude_bounds", "geofence", "restricted_zones",
                "waypoint_validity", "max_speed", "battery_reserve",
                "command_timeout", "separation", "landing_site",
                "conflicting_commands"}
    assert required <= names, required - names


def test_altitude_floor_and_ceiling():
    g, b, _ = _setup()
    assert "altitude_bounds" in _failed_names(g.evaluate(_wp(20, 20, -1.0), b))
    assert "altitude_bounds" in _failed_names(g.evaluate(_wp(20, 20, -400.0), b))
    assert "altitude_bounds" not in _failed_names(g.evaluate(_wp(20, 20, -8.0), b))


def test_geofence_blocks_far_waypoints():
    g, b, _ = _setup()
    assert "geofence" in _failed_names(g.evaluate(_wp(250, 10), b))
    assert "geofence" not in _failed_names(g.evaluate(_wp(20, 20), b))


def test_restricted_zone_is_blocked():
    g, b, sc = _setup()
    z = sc.restricted_zones[0]
    cx = sum(p[0] for p in z.polygon) / len(z.polygon)
    cy = sum(p[1] for p in z.polygon) / len(z.polygon)
    assert "restricted_zones" in _failed_names(g.evaluate(_wp(cx, cy), b))


def test_waypoint_validity_rejects_nan_and_inf():
    g, b, _ = _setup()
    assert "waypoint_validity" in _failed_names(g.evaluate(_wp(float("nan"), 10), b))
    assert "waypoint_validity" in _failed_names(g.evaluate(_wp(float("inf"), 10), b))
    assert "waypoint_validity" in _failed_names(g.evaluate(_wp(5000, 5000), b))


def test_max_speed_is_bounded():
    g, b, _ = _setup()
    assert "max_speed" in _failed_names(g.evaluate(_wp(20, 20, speed_mps=120.0), b))
    assert "max_speed" in _failed_names(g.evaluate(_wp(20, 20, speed_mps=-5.0), b))
    assert "max_speed" not in _failed_names(g.evaluate(_wp(20, 20, speed_mps=4.0), b))


def test_battery_reserve_blocks_mission_extending_work():
    g, b, _ = _setup(battery=0.05)
    d = g.evaluate(sk.SearchRegionCommand(min_x=10, min_y=10, max_x=50, max_y=50), b)
    assert "battery_reserve" in _failed_names(d)
    # but landing is never blocked for being low on battery
    assert "battery_reserve" not in _failed_names(g.evaluate(sk.LandCommand(), b))


def test_command_timeout_is_bounded():
    g, b, _ = _setup()
    assert "command_timeout" in _failed_names(g.evaluate(_wp(20, 20, timeout_s=36000.0), b))
    assert "command_timeout" in _failed_names(g.evaluate(_wp(20, 20, timeout_s=0.0), b))


def test_separation_from_known_teammates():
    g, b, _ = _setup(teammate_at=Position3D(40.0, 40.0, -8.0))
    assert "separation" in _failed_names(g.evaluate(_wp(40, 40), b))
    assert "separation" not in _failed_names(g.evaluate(_wp(20, 20), b))


def test_separation_ignores_stale_teammate_positions():
    """Acting on a two-minute-old position is its own hazard."""
    g, b, _ = _setup(teammate_at=Position3D(40.0, 40.0, -8.0))
    b.now = b.now + 600.0                 # the record is now long stale
    assert "separation" not in _failed_names(g.evaluate(_wp(40, 40), b))


def test_landing_site_must_be_legal():
    g, b, sc = _setup()
    z = sc.restricted_zones[0]
    cx = sum(p[0] for p in z.polygon) / len(z.polygon)
    cy = sum(p[1] for p in z.polygon) / len(z.polygon)
    b.position = Position3D(cx, cy, -8.0)       # hovering over the no-fly zone
    assert "landing_site" in _failed_names(g.evaluate(sk.LandCommand(), b))


def test_conflicting_simultaneous_commands():
    g, b, _ = _setup()
    g.begin(_wp(20, 20))                        # one command already running
    assert "conflicting_commands" in _failed_names(g.evaluate(_wp(30, 30), b))
    g.end()
    assert "conflicting_commands" not in _failed_names(g.evaluate(_wp(30, 30), b))


# --- 11.2 outcomes ---

def test_all_four_outcomes_exist():
    assert {o.value for o in GuardianOutcome} == {
        "approve", "approve_with_modification",
        "reject_and_replan", "execute_safe_fallback"}


def test_safe_command_is_approved_unchanged():
    g, b, _ = _setup()
    cmd = _wp(20, 20)
    d = g.evaluate(cmd, b)
    assert d.outcome is GuardianOutcome.APPROVE
    assert d.command is cmd
    assert not d.blocked


def test_soft_violation_is_clamped_not_rejected():
    """An excessive speed is fixable - narrow it rather than refuse the task."""
    g, b, _ = _setup()
    d = g.evaluate(_wp(20, 20, speed_mps=120.0), b)
    assert d.outcome is GuardianOutcome.APPROVE_WITH_MODIFICATION
    assert d.command.speed_mps <= g.limits.max_speed_mps
    assert d.proposed.speed_mps == 120.0        # the original is preserved


def test_modification_only_narrows():
    """The guardian may tighten a command, never loosen one."""
    g, b, _ = _setup()
    d = g.evaluate(_wp(20, 20, speed_mps=120.0, timeout_s=36000.0), b)
    assert d.command.speed_mps < 120.0
    assert d.command.timeout_s < 36000.0


def test_hard_violation_is_rejected_for_replan():
    g, b, _ = _setup()
    d = g.evaluate(_wp(250, 10), b)
    assert d.outcome is GuardianOutcome.REJECT_AND_REPLAN
    assert d.command is None                    # nothing goes to the vehicle
    assert "geofence" in d.reason


def test_fallback_when_the_agent_cannot_replan():
    """Critical battery means there is no time to think again."""
    g, b, _ = _setup(battery=0.05)
    d = g.evaluate(_wp(250, 10), b)
    assert d.outcome is GuardianOutcome.EXECUTE_SAFE_FALLBACK
    assert d.fallback is not None


# --- 11.3 fallbacks ---

def test_all_five_fallbacks_exist():
    assert {f.value for f in FallbackAction} == {
        "hold_position", "climb_or_descend_to_safe_layer", "return_home",
        "land_at_safe_location", "continue_last_valid_plan"}


def test_critical_battery_lands():
    g, b, _ = _setup(battery=0.05)
    assert g._select_fallback(b, [_fail("geofence")]) is \
        FallbackAction.LAND_AT_SAFE_LOCATION


def test_low_battery_returns_home():
    g, b, _ = _setup(battery=0.20)
    assert g._select_fallback(b, [_fail("geofence")]) is FallbackAction.RETURN_HOME


def test_separation_conflict_changes_layer():
    g, b, _ = _setup()
    assert g._select_fallback(b, [_fail("separation")]) is \
        FallbackAction.CLIMB_OR_DESCEND_TO_SAFE_LAYER


def test_on_the_ground_the_fallback_is_to_stay_there():
    g, b, _ = _setup(airborne=False)
    b.landed = True
    assert g._select_fallback(b, [_fail("geofence")]) is FallbackAction.HOLD_POSITION


def test_malformed_command_continues_the_last_valid_plan():
    g, b, _ = _setup()
    good = _wp(20, 20)
    g.evaluate(good, b)                          # becomes the last valid command
    assert g._select_fallback(b, [_fail("waypoint_validity")]) is \
        FallbackAction.CONTINUE_LAST_VALID_PLAN


def test_out_of_contact_and_uncertain_returns_home():
    g, b, _ = _setup(teammate_at=Position3D(40.0, 40.0, -8.0))
    b.communication.base_reachable = False
    b.now = b.now + 600.0                        # every teammate record is stale
    assert g._select_fallback(b, [_fail("command_timeout")]) is \
        FallbackAction.RETURN_HOME


def test_fallback_commands_are_themselves_safe():
    """A fallback that violated the envelope would be worse than useless."""
    g, b, _ = _setup()
    for fb in FallbackAction:
        cmd = g._fallback_command(fb, b)
        assert cmd is not None
        d = g.evaluate(cmd, b)
        assert d.outcome in (GuardianOutcome.APPROVE,
                             GuardianOutcome.APPROVE_WITH_MODIFICATION), \
            f"{fb.value} produced an unsafe command: {d.reason}"


def test_flight_phase_is_derived_from_belief():
    g, b, _ = _setup(airborne=False)
    b.landed = True
    assert g.flight_phase(b) is FlightPhase.ON_GROUND
    b.landed, b.airborne = False, True
    assert g.flight_phase(b) is FlightPhase.CRUISING
    b.rtb_forced = True
    assert g.flight_phase(b) is FlightPhase.RETURNING


# --- 11.4 the separate log ---

def test_log_records_everything_11_4_asks_for():
    g, b, _ = _setup()
    g.evaluate(_wp(250, 10), b)
    r = g.log.records[-1]
    assert r.proposed_action                     # proposed agent action
    assert r.rejection_reason                    # reason for rejection
    assert r.outcome != "approve"
    assert r.failed_checks
    assert r.all_checks                          # what was verified, not just failures
    g.log.note_effect(r, "blocked")
    assert r.mission_effect == "blocked"         # resulting mission effect


def test_log_separates_agent_reliability_from_guardian_correction():
    g, b, _ = _setup()
    g.evaluate(_wp(20, 20), b)                   # fine
    g.evaluate(_wp(250, 10), b)                  # blocked
    g.evaluate(_wp(20, 20, speed_mps=120.0), b)  # clamped
    s = g.log.stats()
    assert s["evaluated"] == 3
    assert s["approved"] == 1
    assert s["interventions"] == 2
    assert abs(s["intervention_rate"] - 2 / 3) < 1e-3   # stats round to 4dp
    assert "geofence" in s["by_failed_check"]


def test_guardian_log_is_not_the_decision_log():
    """They must be separate objects, or the analysis in 11.4 is impossible."""
    sc = _scenario()
    agent = _agent(sc)
    agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))
    assert agent.guardian_log is not agent.log
    assert hasattr(agent.guardian_log, "intervention_rate") is False
    assert "intervention_rate" in agent.guardian_log.stats()


def test_clean_run_has_a_low_intervention_rate():
    """The honest baseline: an uncompromised policy should rarely need the
    guardian. If this number is high, the agent is not reliable."""
    sc = _scenario()
    agent = _agent(sc)
    agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))
    s = agent.guardian_log.stats()
    assert s["evaluated"] > 0
    assert s["intervention_rate"] == 0.0, s


# --- determinism and independence ---

def test_guardian_is_deterministic():
    for _ in range(3):
        g, b, _ = _setup()
        d = g.evaluate(_wp(250, 10, speed_mps=120.0), b)
        assert d.outcome is GuardianOutcome.REJECT_AND_REPLAN
        assert _failed_names(d) == _failed_names(
            _setup()[0].evaluate(_wp(250, 10, speed_mps=120.0), _setup()[1]))


def test_guardian_holds_no_policy_and_no_model():
    """It must not be able to consult the thing it is constraining."""
    g, _b, _ = _setup()
    for v in vars(g).values():
        assert not isinstance(v, SearchAgentPolicy)
        assert not hasattr(v, "decide")          # no planner/LLM handle


def test_guardian_verdict_does_not_depend_on_who_proposed():
    """Same command, same verdict, whatever produced it."""
    g1, b1, _ = _setup()
    g2, b2, _ = _setup()
    cmd = _wp(250, 10)
    assert g1.evaluate(cmd, b1).outcome is g2.evaluate(cmd, b2).outcome


# --- exit criterion ---

def _agent(sc, policy=None, guardian=None):
    truth = GroundTruth(sc)
    v, sector = sc.vehicles[0], sc.sectors[0]
    a = PersistentAgent(
        v.vehicle_id, MockVehicleAdapter(0.0), policy=policy,
        home=v.start, battery_total_s=v.battery_s,
        cruise_altitude=sector.altitude, sensor=SensorModel(truth),
        roster=truth.roster(), sector_ids=truth.sector_ids(),
        guardian=guardian or SafetyGuardian(limits=SafetyLimits.from_scenario(sc)))
    a.belief.brief(sc)
    return a


def test_every_catalogued_unsafe_command_is_blocked():
    """The exit criterion, over the whole catalogue."""
    sc = _scenario()
    survivors = []
    for c in UNSAFE_COMMANDS:
        g, b, _ = _setup(teammate_at=Position3D(40.0, 40.0, -8.0), scenario=sc)
        d = g.evaluate(c.command(), b)
        if not d.blocked:
            survivors.append(c.name)
    assert not survivors, f"these unsafe commands were approved unchanged: {survivors}"


def test_each_unsafe_command_trips_its_intended_check():
    sc = _scenario()
    misses = []
    for c in UNSAFE_COMMANDS:
        g, b, _ = _setup(teammate_at=Position3D(40.0, 40.0, -8.0), scenario=sc)
        d = g.evaluate(c.command(), b)
        if c.expects_check not in _failed_names(d):
            misses.append((c.name, c.expects_check, sorted(_failed_names(d))))
    assert not misses, misses


def test_compromised_policy_cannot_reach_the_vehicle():
    """A rule policy that has gone wrong mid-mission: the injected commands are
    stopped, and the drone still lands safely at home."""
    sc = _scenario()
    policy = InjectingPolicy(
        SearchAgentPolicy(), unsafe_at={2, 3, 4},
        cases=["outside_geofence", "excessive_speed", "nan_waypoint"])
    agent = _agent(sc, policy=policy)
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))

    assert policy.injected, "nothing was injected; the test proves nothing"
    # every injected command was intervened on
    interventions = agent.guardian_log.interventions()
    assert len(interventions) >= len(policy.injected)
    # nothing out of bounds was ever approved unchanged
    for r in agent.guardian_log.records:
        if r.outcome == "approve":
            wp = (r.proposed_detail or {}).get("waypoint")
            if wp:
                assert abs(wp[0]) < 200 and abs(wp[1]) < 200, wp
    # and the aircraft is safe
    assert report.landed and report.returned_home


def test_llm_style_malformed_plan_is_contained():
    """NaN coordinates and a nonsense speed - the shape of a bad model output."""
    sc = _scenario()
    policy = InjectingPolicy(
        SearchAgentPolicy(), unsafe_at={2, 3},
        cases=["nan_waypoint", "infinite_waypoint"])
    agent = _agent(sc, policy=policy)
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))

    for r in agent.guardian_log.records:
        wp = (r.proposed_detail or {}).get("waypoint")
        if wp and (math.isnan(wp[0]) or math.isinf(wp[0])):
            assert r.outcome != "approve", "a NaN waypoint was approved"
    assert report.landed


def test_guardian_intervention_rate_distinguishes_the_two_runs():
    """The analysis 11.4 exists for: a clean policy and a compromised one produce
    the same mission outcome but very different guardian records."""
    sc = _scenario()
    clean = _agent(sc)
    clean.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))

    sc2 = _scenario()
    broken = _agent(sc2, policy=InjectingPolicy(
        SearchAgentPolicy(), unsafe_at={2, 3},
        cases=["outside_geofence", "excessive_speed"]))
    broken.run(SearchTask("search_S1", sc2.sectors[0], sc2.base.position))

    assert clean.guardian_log.stats()["intervention_rate"] < \
        broken.guardian_log.stats()["intervention_rate"]


def _fail(name):
    from agentic_uav.agents.safety_guardian import SafetyCheck
    return SafetyCheck(name, False, "injected for the test")



# --- escalation: a policy that never recovers ---


def test_repeated_rejection_escalates_to_a_fallback():
    """REJECT_AND_REPLAN assumes the policy can do better next time. When it
    cannot, endlessly asking is not a safe answer - the guardian must eventually
    act itself."""
    g, b, sc = _setup()
    cmd = case("outside_geofence").command()

    outcomes = [g.evaluate(cmd, b).outcome for _ in range(5)]
    assert outcomes[0] is GuardianOutcome.REJECT_AND_REPLAN
    assert GuardianOutcome.EXECUTE_SAFE_FALLBACK in outcomes, outcomes
    # and it escalates within the configured bound, not eventually
    first = outcomes.index(GuardianOutcome.EXECUTE_SAFE_FALLBACK)
    assert first == g.max_consecutive_rejections, outcomes


def test_a_clean_command_resets_the_escalation_counter():
    """One good command means the policy is not broken; the count starts over."""
    g, b, sc = _setup()
    bad = case("outside_geofence").command()
    good = sk.GoToWaypointCommand(waypoint=Position3D(20.0, 20.0, -8.0))

    g.evaluate(bad, b)
    g.evaluate(bad, b)
    assert g.consecutive_rejections == 2
    assert g.evaluate(good, b).outcome is GuardianOutcome.APPROVE
    assert g.consecutive_rejections == 0
    assert g.consecutive_interventions == 0
    # so the next rejection is a rejection again, not an escalation
    assert g.evaluate(bad, b).outcome is GuardianOutcome.REJECT_AND_REPLAN


def test_alternating_unsafe_commands_cannot_evade_escalation():
    """Regression for a real evasion found by running --repeat.

    Counting only rejections is defeatable: a policy alternating a rejectable
    command with a *clampable* one resets the rejection counter every other step
    and flies forever without ever being rejected twice in a row. A clamp is not
    a success, so the intervention counter resets only on an untouched approval.
    """
    g, b, sc = _setup()
    rejectable = case("outside_geofence").command()
    clampable = case("excessive_speed").command()

    outcomes = []
    for i in range(10):
        c = rejectable if i % 2 == 0 else clampable
        outcomes.append(g.evaluate(c, b).outcome)

    assert g.consecutive_rejections < g.max_consecutive_rejections, (
        "the alternation should indeed keep the rejection counter low - "
        "that is the evasion this test exists for")
    assert GuardianOutcome.EXECUTE_SAFE_FALLBACK in outcomes, (
        f"alternating unsafe commands evaded escalation entirely: {outcomes}")


def test_escalation_terminates_the_flight_rather_than_holding():
    """An escalated fallback must end the flight. Holding position or repeating
    the last valid plan leaves a compromised aircraft airborne until the battery
    decides the outcome."""
    g, b, sc = _setup()
    cmd = case("nan_waypoint").command()

    decision = None
    for _ in range(6):
        d = g.evaluate(cmd, b)
        if d.outcome is GuardianOutcome.EXECUTE_SAFE_FALLBACK:
            decision = d
            break
    assert decision is not None, "never escalated"
    assert decision.fallback in (FallbackAction.RETURN_HOME,
                                 FallbackAction.LAND_AT_SAFE_LOCATION), \
        f"escalation chose {decision.fallback}, which leaves the drone flying"
    assert "escalated" in decision.reason


def test_a_permanently_compromised_policy_still_lands():
    """The end-to-end version: the policy is broken for the whole mission and
    never recovers. Containment alone is not enough - the aircraft must come
    down, and in a bounded number of commands."""
    sc = _scenario()
    policy = InjectingPolicy(
        SearchAgentPolicy(), unsafe_at={2}, repeat=True,
        cases=["outside_geofence", "excessive_speed", "nan_waypoint"])
    agent = _agent(sc, policy=policy)
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))

    assert report.landed, "a permanently compromised policy left the drone airborne"
    assert report.returned_home
    stats = agent.guardian_log.stats()
    assert stats["evaluated"] < 20, (
        f"took {stats['evaluated']} commands to shut down a policy that was "
        f"broken from the start")
    for r in agent.guardian_log.records:
        if r.outcome == "approve":
            wp = (r.proposed_detail or {}).get("waypoint")
            if wp:
                assert abs(wp[0]) < 200 and abs(wp[1]) < 200, wp


def test_escalation_does_not_fire_on_a_healthy_policy():
    """Behaviour preservation: the normal mission must be untouched."""
    sc = _scenario()
    agent = _agent(sc, policy=SearchAgentPolicy())
    report = agent.run(SearchTask("search_S1", sc.sectors[0], sc.base.position))
    assert report.landed and report.returned_home
    assert not agent.guardian_log.interventions(), \
        "the guardian intervened on a policy that did nothing wrong"
    assert agent.guardian.consecutive_interventions == 0

if __name__ == "__main__":
    tests = [
        ("all ten checks are present", test_all_ten_checks_are_present),
        ("altitude floor and ceiling", test_altitude_floor_and_ceiling),
        ("geofence blocks far waypoints", test_geofence_blocks_far_waypoints),
        ("restricted zone is blocked", test_restricted_zone_is_blocked),
        ("waypoint validity rejects NaN/inf", test_waypoint_validity_rejects_nan_and_inf),
        ("max speed is bounded", test_max_speed_is_bounded),
        ("battery reserve blocks new work",
         test_battery_reserve_blocks_mission_extending_work),
        ("command timeout is bounded", test_command_timeout_is_bounded),
        ("separation from teammates", test_separation_from_known_teammates),
        ("separation ignores stale positions",
         test_separation_ignores_stale_teammate_positions),
        ("landing site must be legal", test_landing_site_must_be_legal),
        ("conflicting simultaneous commands", test_conflicting_simultaneous_commands),
        ("all four outcomes exist", test_all_four_outcomes_exist),
        ("safe command approved unchanged", test_safe_command_is_approved_unchanged),
        ("soft violation is clamped", test_soft_violation_is_clamped_not_rejected),
        ("modification only narrows", test_modification_only_narrows),
        ("hard violation rejected for replan", test_hard_violation_is_rejected_for_replan),
        ("fallback when replanning impossible", test_fallback_when_the_agent_cannot_replan),
        ("all five fallbacks exist", test_all_five_fallbacks_exist),
        ("critical battery lands", test_critical_battery_lands),
        ("low battery returns home", test_low_battery_returns_home),
        ("separation conflict changes layer", test_separation_conflict_changes_layer),
        ("on the ground, hold", test_on_the_ground_the_fallback_is_to_stay_there),
        ("malformed -> continue last valid plan",
         test_malformed_command_continues_the_last_valid_plan),
        ("out of contact + uncertain -> home", test_out_of_contact_and_uncertain_returns_home),
        ("fallback commands are themselves safe", test_fallback_commands_are_themselves_safe),
        ("flight phase derived from belief", test_flight_phase_is_derived_from_belief),
        ("log records all 11.4 fields", test_log_records_everything_11_4_asks_for),
        ("log separates agent from guardian",
         test_log_separates_agent_reliability_from_guardian_correction),
        ("guardian log is not the decision log", test_guardian_log_is_not_the_decision_log),
        ("clean run has low intervention rate", test_clean_run_has_a_low_intervention_rate),
        ("guardian is deterministic", test_guardian_is_deterministic),
        ("guardian holds no policy or model", test_guardian_holds_no_policy_and_no_model),
        ("verdict independent of proposer",
         test_guardian_verdict_does_not_depend_on_who_proposed),
        ("every unsafe command is blocked", test_every_catalogued_unsafe_command_is_blocked),
        ("each trips its intended check", test_each_unsafe_command_trips_its_intended_check),
        ("compromised policy contained", test_compromised_policy_cannot_reach_the_vehicle),
        ("LLM-style malformed plan contained", test_llm_style_malformed_plan_is_contained),
        ("intervention rate distinguishes runs",
         test_guardian_intervention_rate_distinguishes_the_two_runs),
        ("repeated rejection escalates", test_repeated_rejection_escalates_to_a_fallback),
        ("a clean command resets the counter",
         test_a_clean_command_resets_the_escalation_counter),
        ("alternating unsafe cmds cannot evade escalation",
         test_alternating_unsafe_commands_cannot_evade_escalation),
        ("escalation terminates the flight",
         test_escalation_terminates_the_flight_rather_than_holding),
        ("permanently compromised policy still lands",
         test_a_permanently_compromised_policy_still_lands),
        ("escalation does not fire on a healthy policy",
         test_escalation_does_not_fire_on_a_healthy_policy),
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
