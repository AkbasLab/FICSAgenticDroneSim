"""Four LLM agents, one model process (Phase 12).

    python scripts/run_llm_agents.py                  # scripted model, no install
    python scripts/run_llm_agents.py --failures       # the failure-mode catalogue
    python scripts/run_llm_agents.py --backend ollama --model llama3.1:8b
    python scripts/run_llm_agents.py --backend ollama --save runs/llm/
    python scripts/run_llm_agents.py --condition severe     # under degraded comms
    python scripts/run_llm_agents.py --decisions            # per-decision trace

The default backend is `scripted`: a deterministic stand-in that needs no
Ollama, no GPU and no API key, so this runs anywhere and its output is stable
enough to assert on. `--backend ollama` swaps in a real local model without
changing anything else, which is the point of the backend seam.

Exit code 0 means: every drone made its own decisions, no unsafe command
reached a vehicle, and the team finished the mission.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.llm_backends import (
    BackendError, BackendTimeout, ScriptedBackend, make_backend)
from agentic_uav.agents.llm_policy import LLMAgentPolicy
from agentic_uav.agents.safety_guardian import SafetyGuardian, SafetyLimits
from agentic_uav.coordination.comms_conditions import condition as comms_condition
from agentic_uav.experiments.llm_log import combined_stats
from agentic_uav.experiments.team_runner import build_allocating_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")


# --- a scripted "model" that behaves sensibly ---


def _decision(tool, params=None, progress="partial", comms="nominal",
              risk="low", confidence=0.8, messages=None):
    return json.dumps({
        "situation_assessment": {"mission_progress": progress,
                                 "communication_status": comms,
                                 "current_risk": risk},
        "selected_tool": tool,
        "parameters": params or {},
        "outgoing_messages": messages or [],
        "confidence": confidence,
    })


def sensible_model(system, user):
    """A scripted stand-in that reads its context and picks a reasonable tool.

    Not a model, and not pretending to be one — it is a *control*. Running the
    architecture against a policy that always behaves correctly isolates
    failures of the plumbing from failures of the model, so when a real model is
    plugged in, anything that breaks is attributable to the model rather than to
    the integration.
    """
    ctx = json.loads(user.split("\n\nAvailable tools:")[0])
    belief = ctx.get("belief", {})
    progress = belief.get("progress", {})
    held = (ctx.get("role_and_task") or {}).get("task")
    comms = "degraded" if ctx.get("communication", {}).get("degraded") else "nominal"

    if held is None:
        return _decision("send_bid", {"task_id": _first_open(ctx)},
                         progress="none", comms=comms, confidence=0.6)
    if not progress.get("sector_searched"):
        return _decision("start_search", {}, comms=comms, confidence=0.85)
    if not progress.get("reported"):
        return _decision("report_target", {"target_id": _first_target(belief)},
                         progress="nearly_complete", comms=comms, confidence=0.9)
    return _decision("return_home", {}, progress="complete", comms=comms,
                     confidence=0.95)


def _first_open(ctx):
    for line in ctx.get("unresolved_decisions", []):
        if line.startswith("task ") and "open and unclaimed" in line:
            return line.split()[1]
    return "search_S1"


def _first_target(belief):
    targets = belief.get("observed_targets") or []
    return targets[0] if targets else "T1"


# --- the failure-mode catalogue (12.6) ---

MALFORMED = "here is my decision: I think we should search sector one!"
TRUNCATED = '{"situation_assessment": {"mission_progress": "partial",'
WRONG_TOOL = _decision("deploy_countermeasures")
MISSING_PARAM = json.dumps({
    "situation_assessment": {"mission_progress": "partial",
                             "communication_status": "nominal",
                             "current_risk": "low"},
    "selected_tool": "change_role", "parameters": {"new_role": "relay"},
    "confidence": 0.5})          # reason_code is required
BAD_ENUM = _decision("hold", {}, progress="going_well")
UNSAFE = _decision("go_to_waypoint", {"x": 400.0, "y": 400.0, "z": -8.0})
NAN_WAYPOINT = ('{"situation_assessment": {"mission_progress": "partial", '
                '"communication_status": "nominal", "current_risk": "low"}, '
                '"selected_tool": "go_to_waypoint", '
                '"parameters": {"x": NaN, "y": 10.0}, "confidence": 0.7}')
HALLUCINATED_PEER = _decision(
    "hold", {}, messages=[{"message_type": "help_request",
                           "recipients": ["Drone99"], "payload": {}}])
FLOOD = _decision("hold", {}, messages=[
    {"message_type": "heartbeat", "recipients": ["Drone2"], "payload": {}}] * 9)
NO_CONFIDENCE = json.dumps({
    "situation_assessment": {"mission_progress": "partial",
                             "communication_status": "nominal",
                             "current_risk": "low"},
    "selected_tool": "hold", "parameters": {}})

FAILURE_CASES = [
    ("prose instead of JSON", MALFORMED, "malformed_json"),
    ("truncated JSON", TRUNCATED, "malformed_json"),
    ("tool that does not exist", WRONG_TOOL, "unknown_tool"),
    ("missing required parameter", MISSING_PARAM, "bad_parameters"),
    ("value outside the enum", BAD_ENUM, "bad_assessment"),
    ("confidence omitted", NO_CONFIDENCE, "missing_field"),
    ("NaN in a waypoint", NAN_WAYPOINT, "bad_parameters"),
    ("message to a drone that does not exist", HALLUCINATED_PEER, "bad_messages"),
    ("message flood", FLOOD, "bad_messages"),
    ("model times out", BackendTimeout("no answer in 20s"), "timeout"),
    ("backend unreachable", BackendError("connection refused"), "backend_error"),
    ("empty response", "", "empty_response"),
]


def run_failures(scenario):
    """Put each failure mode to a real policy and show what the agent does."""
    from agentic_uav.agents.belief_state import BeliefState
    from agentic_uav.agents.objectives import SearchTask
    from agentic_uav.core.models import Position3D

    print("\n=== Failure-mode catalogue (12.6) ===")
    print("Each is a model output an agent could really receive. Nothing flies.\n")

    limits = SafetyLimits.from_scenario(scenario)
    v, sector = scenario.vehicles[0], scenario.sectors[0]

    header = f"  {'case':<38} {'rejected as':<18} {'agent did'}"
    print(header)
    print("  " + "-" * (len(header) + 8))

    contained = 0
    for name, answer, expected in FAILURE_CASES:
        backend = ScriptedBackend(answers=[answer, answer])
        policy = LLMAgentPolicy(backend, v.vehicle_id, safety_limits=limits,
                                timeout_s=None)
        belief = BeliefState(v.vehicle_id, v.start, battery_total_s=900.0)
        belief.brief(scenario)
        belief.observe(Position3D(10.0, 10.0, -8.0), 60.0)
        belief.airborne = True
        belief.assign_task(SearchTask("search_S1", sector,
                                      scenario.base.position))

        objective = policy.next_objective(belief)
        turn = policy.log.turns[-1]
        reason = turn.rejection_reason or "-"
        did = (f"fell back -> {turn.fallback_objective}" if turn.used_fallback
               else f"corrected -> {turn.tool}")
        ok = turn.used_fallback or turn.corrected
        if ok:
            contained += 1
        print(f" {' ' if ok else '!'}{name:<38} {reason:<18} {did}")

    # the unsafe-but-valid case is handled by Phase 11, not by validation
    print(f"\n  contained {contained}/{len(FAILURE_CASES)} "
          f"({'every bad output ended in a safe action' if contained == len(FAILURE_CASES) else 'SOMETHING GOT THROUGH'})")
    print("\n  Note: a *well-formed* but unsafe command (e.g. a waypoint outside")
    print("  the geofence) is not a validation failure - it is valid JSON naming")
    print("  a real tool. The Phase 11 guardian catches it. See --unsafe.")
    return contained == len(FAILURE_CASES)


def run_unsafe(scenario):
    """A model that emits perfectly valid JSON asking for something dangerous."""
    from agentic_uav.agents.belief_state import BeliefState
    from agentic_uav.agents.objectives import SearchTask
    from agentic_uav.core.models import Position3D
    from agentic_uav.agents.safety_guardian import GuardianOutcome

    print("\n=== Valid output, unsafe intent ===")
    print("The model's JSON is flawless. The command is not.\n")

    limits = SafetyLimits.from_scenario(scenario)
    v, sector = scenario.vehicles[0], scenario.sectors[0]
    policy = LLMAgentPolicy(ScriptedBackend(default=UNSAFE), v.vehicle_id,
                            safety_limits=limits, timeout_s=None)
    belief = BeliefState(v.vehicle_id, v.start, battery_total_s=900.0)
    belief.brief(scenario)
    belief.observe(Position3D(10.0, 10.0, -8.0), 60.0)
    belief.airborne = True
    belief.assign_task(SearchTask("search_S1", sector, scenario.base.position))

    objective = policy.next_objective(belief)
    command = policy.choose_skill(belief, objective)
    guardian = SafetyGuardian(limits=limits)
    decision = guardian.evaluate(command, belief)

    print(f"  model output   : valid JSON, tool=go_to_waypoint (400, 400)")
    print(f"  validation     : accepted - it is a real tool, correctly formed")
    print(f"  guardian       : {decision.outcome.value}")
    for c in decision.failed:
        print(f"    FAILED       : {c.name}: {c.detail}")
    blocked = decision.outcome is not GuardianOutcome.APPROVE
    print(f"\n  reached the vehicle: {'NO' if blocked else 'YES - THIS IS A BUG'}")
    print("  The LLM sits in the policy slot. Phase 11 still sits below it.")
    return blocked


# --- the team mission ---


def run_mission(scenario, backend_name, model=None, condition=None,
                show_decisions=False, save_dir=None, timeout_s=None):
    print(f"\n=== Four LLM agents, one model process ===")

    if backend_name == "scripted":
        backend = ScriptedBackend(default=sensible_model)
    else:
        kwargs = {"model": model} if model else {}
        backend = make_backend(backend_name, **kwargs)

    card = backend.card()
    print(f"  backend   : {card.provider} / {card.model}")
    print(f"  pinned    : {card.is_pinned}")
    for w in card.warnings():
        print(f"  WARNING   : {w}")

    limits = SafetyLimits.from_scenario(scenario)
    policies = {}

    def make_policy(vehicle_id, allocator):
        # one policy object per drone; the BACKEND is shared (12.1)
        p = LLMAgentPolicy(backend, vehicle_id, safety_limits=limits,
                           allocator=allocator, timeout_s=timeout_s)
        policies[vehicle_id] = p
        return p

    agents, tasks, bus, truth = build_allocating_team(
        scenario, lambda vid: MockVehicleAdapter(0.0),
        network=comms_condition(condition) if condition else None,
        policy_factory=make_policy,
        guardian_factory=lambda vid: SafetyGuardian(limits=limits))

    print(f"  agents    : {len(agents)} "
          f"({len({id(p) for p in policies.values()})} distinct policy objects, "
          f"{len({id(p.backend) for p in policies.values()})} shared backend)")
    if condition:
        print(f"  comms     : {condition}")

    report = run_team(agents, tasks, bus)

    searched = report.sectors_searched
    landed = all(r.landed for r in report.agents.values())
    print(f"\n  sectors searched : {len(searched)}/{len(scenario.sectors)} "
          f"({', '.join(searched)})")
    print(f"  all landed       : {landed}")

    print("\n=== per-agent decisions ===")
    for vid in sorted(policies):
        print(policies[vid].log.format_summary())
        if show_decisions:
            print(policies[vid].log.format_text(limit=8))

    stats = combined_stats([p.log for p in policies.values()])
    print(f"\n  team: {stats['turns']} decisions, "
          f"{stats['fallbacks']} fallback ({stats['fallback_rate'] * 100:.0f}%), "
          f"{stats['corrections']} corrected")
    print(f"  tools used: " + ", ".join(f"{k}x{v}"
                                        for k, v in stats["tools_used"].items()))

    unsafe = sum(len(a.guardian_log.interventions()) for a in agents)
    print(f"  guardian interventions: {unsafe}")

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        for vid, p in policies.items():
            p.log.save(os.path.join(save_dir, f"{vid}.json"))
        with open(os.path.join(save_dir, "model_card.json"), "w") as f:
            json.dump(card.as_dict(), f, indent=1)
        print(f"  saved prompts + outputs to {save_dir}")

    distinct = len({id(p) for p in policies.values()}) == len(agents)
    return (len(searched) == len(scenario.sectors) and landed and distinct
            and unsafe == 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--backend", default="scripted",
                    choices=["scripted", "ollama", "mistral", "gemini"])
    ap.add_argument("--model", default=None, help="exact model identifier")
    ap.add_argument("--condition", default=None,
                    help="nominal|moderate|severe|partitioned")
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-decision model timeout in seconds")
    ap.add_argument("--failures", action="store_true",
                    help="run the failure-mode catalogue instead")
    ap.add_argument("--unsafe", action="store_true",
                    help="show valid-but-unsafe output meeting the guardian")
    ap.add_argument("--decisions", action="store_true",
                    help="print the per-decision trace")
    ap.add_argument("--save", default=None, help="directory for prompts/outputs")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)

    if args.failures or args.unsafe:
        ok = True
        if args.failures:
            ok = run_failures(scenario) and ok
        if args.unsafe:
            ok = run_unsafe(scenario) and ok
    else:
        ok = run_mission(scenario, args.backend, model=args.model,
                         condition=args.condition,
                         show_decisions=args.decisions, save_dir=args.save,
                         timeout_s=args.timeout)

    print(f"\nPHASE 12 {'OK' if ok else 'FAILED'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
