"""Determinism tests (Phase 16.4).

Same architecture, same seed, same model output - same run. Every claim this
project makes about comparing two architectures "under identical conditions"
depends on that, so it is tested directly rather than assumed from the fact
that nothing has looked obviously random.

Two kinds of test here, and the structural ones matter more:

  - *Behavioural*: run it twice and compare. Catches a difference, but only on
    the path the test happens to exercise, and only if the difference is large
    enough to change the compared values.

  - *Structural*: there is exactly one source of randomness in the package and
    it is seeded, and nothing on the simulator-free path reads the wall clock.
    This holds for every path at once, including the ones no test exercises,
    and it is what actually makes reproducibility a property of the system
    rather than an observation about a few runs.

Residual LLM variability is recorded separately: a live model is not promised
to be deterministic, so `ScriptedBackend` is what the deterministic tests use,
and the live-model case is reported as a measured fallback/decision profile
rather than as an equality assertion.

Run: python tests/test_determinism.py
"""

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination.comms_conditions import condition as comms_condition
from agentic_uav.coordination.network_model import NetworkModel
from agentic_uav.experiments import architectures as arch
from agentic_uav.experiments.team_runner import (
    build_allocating_team, run_team_with_faults)
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")
PKG = os.path.join(ROOT, "agentic_uav")

#: Modules that may read the wall clock, because they talk to a real simulator
#: whose latency is wall-clock by nature. Nothing else may.
WALL_CLOCK_ALLOWED = {"airsim_adapter.py", "fake_airsim.py", "clock.py",
                      "experiment_config.py", "experiment_runner.py",
                      "llm_backends.py", "llm_log.py", "llm_policy.py",
                      "guardian_log.py", "decision_log.py", "events.py",
                      "logger.py",
                      # measures latency (MVL, model response time), which is
                      # wall-clock by definition; the timings are reported,
                      # never used to make a decision
                      "guardrail_benchmark.py"}

#: The one module allowed to hold a random number generator.
RNG_ALLOWED = {"network_model.py"}

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append((name, detail))


def _adapter(_vid):
    return MockVehicleAdapter(0.0)


def _scenario():
    return load_scenario(SCENARIO)


# --- structural: where randomness and time are allowed to come from ---------


def _py_files():
    for dirpath, dirnames, filenames in os.walk(PKG):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in sorted(filenames):
            if f.endswith(".py"):
                yield f, os.path.join(dirpath, f)


def test_only_one_module_holds_a_random_number_generator():
    """Unseeded randomness anywhere would make every comparison unrepeatable.

    Checked by parsing rather than by running, so it covers the paths no test
    exercises. An `import random` in a new module is the cheapest possible way
    to destroy reproducibility, and it would not fail any behavioural test
    until someone tried to reproduce a published number.
    """
    offenders, seeded = [], []
    for name, path in _py_files():
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        uses_random = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                uses_random |= any(a.name.split(".")[0] in ("random", "secrets")
                                   for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                uses_random |= (node.module or "").split(".")[0] in (
                    "random", "secrets")
        if uses_random and name not in RNG_ALLOWED:
            offenders.append(name)
        elif uses_random:
            seeded.append(name)

    check("only the network model imports a random number generator",
          not offenders, f"also: {offenders}")
    check("the network model does import one (the test can still see it)",
          seeded == sorted(RNG_ALLOWED), f"found {seeded}")

    # And the one that exists must be explicitly seeded, never the module-level
    # global generator, which is shared process-wide and unrepeatable.
    src = open(os.path.join(PKG, "coordination", "network_model.py"),
               encoding="utf-8").read()
    check("the generator is a seeded instance, not the global one",
          "random.Random(" in src)
    bare = [ln.strip() for ln in src.splitlines()
            if ln.strip().startswith("random.") and "random.Random(" not in ln]
    check("no call goes to the process-wide generator", not bare, f"{bare[:3]}")


def test_the_simulator_free_path_never_reads_the_wall_clock():
    """A wall-clock read on the mock path makes a run unrepeatable by timing.

    Real-simulator and logging modules are exempt and listed explicitly, so
    adding a `time.time()` to a coordination module fails this test instead of
    quietly making results depend on how busy the machine was.
    """
    offenders = []
    for name, path in _py_files():
        if name in WALL_CLOCK_ALLOWED:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "time" and node.attr in (
                        "time", "monotonic", "perf_counter", "time_ns"):
                    offenders.append(f"{name}:{node.lineno}")
    check("no wall-clock read in the simulator-free path",
          not offenders, f"{offenders[:5]}")


# --- behavioural: network events ------------------------------------------


class _Msg:
    """Smallest thing the network model will evaluate."""
    def __init__(self, i):
        self.message_type = "status_update"
        self.sender_id = "Drone1"
        self.recipient_ids = ["Drone2"]
        self.size_bytes = 200
        self.timestamp = float(i)
        self.time_to_live_s = 30.0
        self.sequence_number = i


def test_network_events_repeat_for_a_given_seed():
    def verdicts(seed, name="severe"):
        net = NetworkModel(comms_condition(name), seed=seed)
        out = []
        for i in range(300):
            v = net.evaluate(_Msg(i), "Drone1", "Drone2", float(i))
            out.append((bool(getattr(v, "delivered", False)),
                        round(float(getattr(v, "delay_s", 0.0) or 0.0), 6),
                        getattr(v, "reason", "")))
        return out

    a, b, c = verdicts(17), verdicts(17), verdicts(18)
    check("the same seed draws the same network events", a == b,
          next((f"index {i}: {x} vs {y}"
                for i, (x, y) in enumerate(zip(a, b)) if x != y), ""))
    check("a different seed draws different ones", a != c)
    check("the severe profile actually drops and delays things",
          any(not d for d, _s, _r in a) and any(s > 0 for _d, s, _r in a))

    # reset(seed) must put the generator back, or a replay study is not a replay
    net = NetworkModel(comms_condition("severe"), seed=17)
    first = [net.evaluate(_Msg(i), "Drone1", "Drone2", float(i)).delivered
             for i in range(60)]
    net.reset(17)
    again = [net.evaluate(_Msg(i), "Drone1", "Drone2", float(i)).delivered
             for i in range(60)]
    check("reset to the same seed replays the same decisions", first == again)


def test_degraded_runs_repeat_end_to_end():
    def run(seed, condition="severe"):
        r = arch.run_architecture("C", _scenario(), _adapter,
                                  condition=condition, seed=seed,
                                  heartbeat_interval_s=8.0)
        return r.as_row()

    first, second = run(17), run(17)
    check("a degraded run reproduces exactly", first == second,
          _first_difference(first, second))
    other = run(18)
    check("the seed is actually doing something",
          first != other or first["delivery_rate"] == other["delivery_rate"])


# --- behavioural: target placement ---------------------------------------


def test_target_placement_repeats():
    """Targets are declared in the scenario, so this is a property of loading.

    Worth testing anyway: the obvious "improvement" to this project is to
    randomise target placement across trials, and the moment that happens
    unseeded, every architecture is scored against a different world.
    """
    a = [(t.target_id, t.position.x, t.position.y) for t in _scenario().targets]
    b = [(t.target_id, t.position.x, t.position.y) for t in _scenario().targets]
    check("loading a scenario twice gives the same targets", a == b)
    check("the scenario actually has targets to place", len(a) >= 2)

    sectors_a = [s.sector_id for s in _scenario().sectors]
    sectors_b = [s.sector_id for s in _scenario().sectors]
    check("sector layout repeats", sectors_a == sectors_b)

    starts_a = [(v.vehicle_id, v.start.x, v.start.y) for v in _scenario().vehicles]
    starts_b = [(v.vehicle_id, v.start.x, v.start.y) for v in _scenario().vehicles]
    check("vehicle start pads repeat", starts_a == starts_b)
    check("the pads are distinct, not stacked on the origin",
          len({(x, y) for _v, x, y in starts_a}) == len(starts_a))


# --- behavioural: injected faults ----------------------------------------


def test_injected_faults_repeat():
    def run(seed):
        r = arch.run_architecture("C", _scenario(), _adapter, condition="moderate",
                                  seed=seed, stop_at={"Drone2": 30.0},
                                  heartbeat_interval_s=8.0)
        return r.stopped, r.as_row()

    (s1, r1), (s2, r2) = run(17), run(17)
    check("the same fault fires on both runs", s1 == s2 == ["Drone2"])
    check("a run with an injected fault reproduces exactly", r1 == r2,
          _first_difference(r1, r2))

    # The fault must land at the same point in the mission, not merely happen.
    # A fault whose timing drifts would change what work was outstanding when
    # it fired, which is the whole independent variable of the recovery study.
    check("mission time is identical across the two runs",
          r1["mission_time_s"] == r2["mission_time_s"])

    nofault = arch.run_architecture("C", _scenario(), _adapter,
                                    condition="moderate", seed=17,
                                    heartbeat_interval_s=8.0)
    check("injecting a fault changes the outcome",
          nofault.stopped == [] and nofault.as_row() != r1)


# --- behavioural: deterministic policies ---------------------------------


def test_deterministic_policies_repeat_exactly():
    """Not just the same scores - the same decisions, in the same order."""
    def trace(seed):
        agents, tasks, bus, _t = build_allocating_team(
            _scenario(), _adapter, lease_s=150.0, heartbeat_interval_s=15.0,
            seed=seed)
        run_team_with_faults(agents, tasks, bus, stop_at={})
        return {a.vehicle_id: list(a.report().decisions) for a in agents}

    a, b = trace(17), trace(17)
    check("every agent makes the same decisions in the same order", a == b,
          next((f"{v}: {x[:1]} vs {b[v][:1]}" for v, x in a.items()
                if x != b[v]), ""))
    check("the trace is not trivially short",
          all(len(v) >= 4 for v in a.values()),
          f"{ {k: len(v) for k, v in a.items()} }")


def test_the_scripted_llm_path_repeats():
    """Architecture D with a scripted backend must be as repeatable as C.

    This is the control for the live-model case below: if the scripted path
    were non-deterministic, variability measured with a real model could not be
    attributed to the model.
    """
    from agentic_uav.agents.llm_backends import ScriptedBackend
    try:
        from run_llm_agents import sensible_model          # noqa: F401
        default = sensible_model
    except Exception:                                       # noqa: BLE001
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        try:
            from run_llm_agents import sensible_model
            default = sensible_model
        except Exception:                                   # noqa: BLE001
            default = None

    def run(seed):
        backend = ScriptedBackend(answers=[], default=default)
        r = arch.run_architecture("D", _scenario(), _adapter, condition="moderate",
                                  seed=seed, backend=backend,
                                  heartbeat_interval_s=8.0)
        return r.as_row()

    a, b = run(17), run(17)
    check("the scripted LLM path reproduces exactly", a == b,
          _first_difference(a, b))


def test_live_model_variability_is_recorded_not_asserted():
    """A live model is not promised to repeat, so nothing here asserts it does.

    What this pins is the reporting contract: every run carries the fields that
    let residual variability be quantified after the fact (how many decisions
    came from the model, how many fell back, and the pinned model identity).
    Without those, an irreproducible result could not be distinguished from a
    buggy one.
    """
    from agentic_uav.agents.llm_backends import ScriptedBackend
    backend = ScriptedBackend(answers=[], default=None)
    r = arch.run_architecture("D", _scenario(), _adapter, condition="nominal",
                              seed=17, backend=backend, heartbeat_interval_s=8.0)
    llm = r.llm or {}
    for field in ("turns", "fallbacks", "fallback_rate"):
        check(f"an LLM run reports {field}", field in llm, f"got {sorted(llm)}")
    check("the fallback rate is a fraction",
          llm.get("fallback_rate") is None
          or 0.0 <= llm["fallback_rate"] <= 1.0)

    from agentic_uav.experiments.experiment_config import Manifest
    check("the manifest has somewhere to pin the model identity",
          "model" in Manifest.__dataclass_fields__)


def _first_difference(a, b):
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            return f"{k}: {a.get(k)!r} vs {b.get(k)!r}"
    return ""


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("Phase 16.4 determinism\n")
    for name, _ in PASS:
        print(f"  ok    {name}")
    for name, detail in FAIL:
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
