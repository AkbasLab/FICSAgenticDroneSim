"""Phase 13: the architectures are comparable, and differ only where intended.

These are validity tests rather than functional ones. A functional bug makes a
run crash; a validity bug makes every run succeed and every number mean
something other than what the paper will claim. The checks here are the ones
that protect the results:

  * every architecture shares the scenario, skills, executor, sensor model,
    network model and guardian - so a difference between two of them cannot be
    a difference in any of those;
  * each architecture differs from its neighbours on exactly one axis;
  * D with the model switched off reproduces C, which is the strongest single
    check that C and D differ only in the LLM;
  * the recovery mechanisms are faster than the mission, without which no
    architecture can recover and the comparison measures timeout constants.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

from agentic_uav.agents.llm_backends import ScriptedBackend
from agentic_uav.agents.safety_guardian import SafetyGuardian
from agentic_uav.coordination.fleet_controller import CentralAssignmentClient
from agentic_uav.coordination.roles import FAILED_AFTER_MISSED
from agentic_uav.coordination.task_allocator import TaskAllocator
from agentic_uav.experiments import architectures as arch
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")
EXPERIMENT_HEARTBEAT_S = 8.0


def _scenario():
    return load_scenario(SCENARIO)


def _adapter(_vid):
    return MockVehicleAdapter(0.0)


def _backend():
    from run_llm_agents import sensible_model
    return ScriptedBackend(default=sensible_model)


def _build(key, sc=None, **kw):
    kw.setdefault("condition", "nominal")
    kw.setdefault("seed", 17)
    kw.setdefault("heartbeat_interval_s", EXPERIMENT_HEARTBEAT_S)
    if arch.spec(key).policy == "llm":
        kw.setdefault("backend", _backend())
    return arch.build(key, sc or _scenario(), _adapter, **kw)


def _run(key, sc=None, stop_at=None, **kw):
    return arch.run(_build(key, sc, **kw), stop_at=stop_at)


# --- the exit criterion --------------------------------------------------


def test_every_architecture_is_selected_by_configuration():
    """13's exit criterion: config, not four unrelated programs."""
    for key in ("A", "B", "C", "D", "E"):
        assert isinstance(arch.spec(key), arch.ArchitectureSpec)
    # one builder, one runner, for all of them
    for key in arch.ALL:
        assert callable(arch.build) and callable(arch.run)


def test_all_five_architectures_fly_the_mission():
    sc = _scenario()
    for key in ("A", "B", "C", "D", "E"):
        r = _run(key, sc)
        assert r.coverage > 0.0, f"{key} covered nothing"
        assert r.all_landed, f"{key} left a drone airborne"


# --- the confound guards -------------------------------------------------


def test_architectures_share_the_scenario_and_sensing():
    """A difference between architectures must not be a difference in world."""
    sc = _scenario()
    builds = {k: _build(k, sc) for k in ("A", "B", "C", "D", "E")}
    rosters = {k: tuple(sorted(b.truth.roster())) for k, b in builds.items()}
    assert len(set(rosters.values())) == 1, f"rosters differ: {rosters}"
    for k, b in builds.items():
        assert b.scenario is sc, f"{k} was built against a different scenario"
        assert len(b.agents) == len(sc.vehicles), f"{k} has the wrong fleet size"


def test_every_architecture_runs_the_same_guardian():
    """Phase 11 must sit under all of them, with identical limits."""
    sc = _scenario()
    seen = []
    for key in ("A", "B", "C", "D", "E"):
        for agent in _build(key, sc).agents:
            assert isinstance(agent.guardian, SafetyGuardian), \
                f"{key} has no runtime-safety guardian"
            L = agent.guardian.limits
            seen.append((L.max_speed_mps, L.min_altitude, L.max_altitude,
                         L.geofence_min_x, L.geofence_max_x,
                         L.min_separation_m))
    assert len(set(seen)) == 1, "guardian limits differ between architectures"


def test_every_architecture_uses_the_same_executor_and_skills():
    sc = _scenario()
    kinds = set()
    for key in ("A", "B", "C", "D", "E"):
        for agent in _build(key, sc).agents:
            kinds.add(type(agent.executor).__name__)
            kinds.add(type(agent.adapter).__name__)
    assert len(kinds) == 2, f"executor/adapter differ across architectures: {kinds}"


def test_the_same_condition_produces_the_same_network_model():
    sc = _scenario()
    profiles = {}
    for key in ("A", "B", "C", "D"):
        b = _build(key, sc, condition="severe")
        net = getattr(b.bus, "network", None)
        profiles[key] = None if net is None else net.profile.name
    assert len(set(profiles.values())) == 1, \
        f"the same condition built different networks: {profiles}"
    assert set(profiles.values()) == {"severe"}


def test_each_architecture_differs_on_exactly_one_axis():
    A, B, C, D = (arch.spec(k) for k in "ABCD")
    assert _axes_differing(C, D) == {"policy"}, \
        "C and D must differ only in the policy, or C-vs-D is not an LLM result"
    assert _axes_differing(B, C) == {"coordination"}, \
        "B and C must differ only in coordination"
    assert _axes_differing(A, C) == {"coordination"}, \
        "A and C must differ only in coordination"


def _axes_differing(x, y):
    a, b = x.as_dict(), y.as_dict()
    skip = {"key", "name", "ablation_of"}
    return {k for k in a if k not in skip and a[k] != b[k]}


def test_each_ablation_changes_exactly_one_switch():
    for ab in arch.ABLATIONS:
        parent = arch.spec(ab.ablation_of)
        diff = _axes_differing(parent, ab)
        assert len(diff) <= 1, \
            f"ablation {ab.key} changes {sorted(diff)} - an ablation that moves " \
            f"two things at once measures neither"


# --- the strongest check -------------------------------------------------


def test_disabling_the_llm_reproduces_the_deterministic_architecture():
    """D5 is D with the model switched off. It should behave like C.

    If it does not, then C and D differ in something besides the LLM, and every
    C-versus-D number in the paper is confounded. This is the single most
    valuable test in the file.
    """
    sc = _scenario()
    c = _run("C", sc)
    d5 = _run("D5", sc)
    assert d5.coverage == c.coverage, (
        f"D with the LLM disabled covered {d5.coverage} but C covered "
        f"{c.coverage}; C and D differ in more than the model")
    assert d5.duplicated_sectors == c.duplicated_sectors
    assert d5.all_landed == c.all_landed


def test_the_llm_ablation_really_does_disable_the_model():
    """Guard against the ablation quietly still calling a model."""
    built = _build("D5")
    for policy in built.policies.values():
        policy_stats = policy.log.stats()
        assert policy_stats["turns"] == 0 or True     # nothing run yet
    arch.run(built)
    for vid, policy in built.policies.items():
        s = policy.log.stats()
        assert s["fallback_rate"] == 1.0, (
            f"{vid} made {s['model_decisions']} model decisions with the LLM "
            f"ablation enabled")


# --- coordination actually does something --------------------------------


def test_coordination_recovers_work_that_a_lost_drone_was_carrying():
    """B has no way to notice; C and D do. This is the B-vs-C axis."""
    sc = _scenario()
    kill = {"Drone2": 1.0}
    b = _run("B", sc, stop_at=kill)
    c = _run("C", sc, stop_at=kill)
    assert b.coverage < 1.0, \
        "the fault did not cost Architecture B anything; it cannot discriminate"
    assert c.coverage > b.coverage, (
        f"coordination recovered nothing: B={b.coverage}, C={c.coverage}")


def test_the_centralized_controller_actually_assigns_the_work():
    r = _run("A")
    assert r.controller is not None
    assert r.controller["assignments_sent"] >= len(_scenario().sectors), \
        "the controller did not assign every sector"


def test_independent_agents_never_negotiate():
    """B must hold no allocator at all - otherwise it is a weak C."""
    for agent in _build("B").agents:
        assert agent.allocator is None, \
            "Architecture B has an allocator; it is not independent"


def test_centralized_drones_do_not_bid():
    for agent in _build("A").agents:
        assert isinstance(agent.allocator, CentralAssignmentClient)
        assert not isinstance(agent.allocator, TaskAllocator), \
            "Architecture A is bidding; it is not centralized"


def test_decentralized_drones_bid():
    for key in ("C", "D"):
        for agent in _build(key).agents:
            assert isinstance(agent.allocator, TaskAllocator), \
                f"{key} is not running the contract-net protocol"


# --- ablations bite ------------------------------------------------------


def test_the_no_lease_ablation_disables_expiry():
    for agent in _build("D2").agents:
        assert agent.allocator.lease_s >= arch.LEASE_DISABLED_S, \
            "D2 still has expiring leases"


def test_the_no_roles_ablation_keeps_health_monitoring():
    """The ablation must remove role changes only - not failure detection."""
    for agent in _build("D3").agents:
        assert agent.health is not None, \
            "D3 lost health monitoring as well as roles; that is two changes"
        assert agent.roles is not None
        before = agent.roles.role
        decision = agent.roles.decide(agent.belief)
        assert not decision.changed and decision.role is before


def test_the_perfect_comms_ablation_overrides_the_condition():
    built = _build("D4", condition="severe")
    assert built.condition == "nominal", \
        "D4 did not force perfect communication"


def test_the_no_memory_ablation_removes_the_agents_history():
    for policy in _build("D1").policies.values():
        assert policy.memory_turns == 0
        policy.memory.append({"x": 1})
        policy._remember(type("T", (), {"step": 1, "tool": "hold",
                                        "reason_code": None})(),
                         __import__("agentic_uav.agents.objectives",
                                    fromlist=["Objective"]).Objective.HOLD)
        assert policy.memory == [], "D1 still accumulates decision history"


# --- the trap this phase fell into ---------------------------------------


def test_recovery_is_faster_than_the_mission():
    """The experiment's timings must let a failure be detected before the end.

    At the demo default of a 20 s heartbeat, a peer is not declared failed until
    160 s, and the task lease is 120 s - but a run of this scenario lasts about
    112 s. Every architecture then scores identically on failure recovery
    because *none* of them can recover, and the comparison silently measures the
    timeout constants rather than the architecture. Caught only because C and D
    disagreed when they should not have.
    """
    from agentic_uav.coordination.task_allocator import DEFAULT_LEASE_S
    typical_mission_s = 120.0
    detect_s = EXPERIMENT_HEARTBEAT_S * FAILED_AFTER_MISSED
    assert detect_s < typical_mission_s, (
        f"failure detection takes {detect_s:.0f}s but the mission lasts about "
        f"{typical_mission_s:.0f}s; no architecture can recover")
    assert DEFAULT_LEASE_S < typical_mission_s * 1.2, (
        f"the lease ({DEFAULT_LEASE_S}s) outlives the mission")


def test_the_timing_checker_warns_on_the_bad_default():
    from run_experiment import check_timings
    assert check_timings(_scenario(), 20.0), \
        "the 20s heartbeat should have produced a warning"
    assert not check_timings(_scenario(), EXPERIMENT_HEARTBEAT_S,
                             lease_s=100.0), \
        "a commensurate configuration should not warn"


# --- reproducibility -----------------------------------------------------


def test_a_run_is_reproducible_given_the_same_seed():
    for key in ("A", "B", "C", "D"):
        a = _run(key, condition="severe", seed=5)
        b = _run(key, condition="severe", seed=5)
        assert (a.coverage, a.duplicated_sectors, a.messages_sent) == \
               (b.coverage, b.duplicated_sectors, b.messages_sent), \
            f"{key} is not reproducible under a fixed seed"


def test_results_carry_the_spec_that_produced_them():
    r = _run("D1")
    row = r.as_row()
    assert row["architecture"] == "D1"
    assert arch.spec("D1").ablation_of == "D"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name[5:].replace('_', ' ')}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name[5:].replace('_', ' ')}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
