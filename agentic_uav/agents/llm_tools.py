"""The LLM's tools and its decision schema (AUV-12, 12.2, 12.3, 12.5).

    tool, params, problems = parse_reply(text)          # the model's answer, read strictly; never raises
    problems = check(tool, params, policy, belief)      # can this tool be used now, as given?
    decision = execute(tool, params, policy, belief)    # the same primitives the rule team flies
    tool, params = rule_tool(decision, policy)          # what the rule policy chose, as a tool

12.2: "Restrict the LLM to structured tools. The LLM must not invent arbitrary
Python or AirSim calls." These are AUV-12's fifteen, and one more:

    ACTIONS   the model picks exactly one per decision, and it runs on the rule
              team's own primitives (`team_policy`, `recovery_policy`, the
              contract-net), so Architectures C and D differ only in who chooses:
                continue_task   carry on with what is flying (added: most events change nothing)
                accept_task     go and do the task the protocol has given this drone
                start_search    search the task's sector now
                go_to_waypoint  target "task" | "home" | "relay_point" -- symbolic, never coordinates
                act_as_relay    hold half way between the base and an unreachable teammate
                return_home     give the task back and fly home
                hold            hold where it is for a while
                claim_task      bid again for an open task it had declined
                decline_task    never bid for a task (and give it back if held)
                release_task    give a held task back, and hold
                change_role     relay | reserve | scout -- as the actions above
    PROTOCOL  run for it, every tick, deterministically: announce_task, send_bid,
              compute_task_cost. Bids are COMPUTED, never estimated (12.5); the
              model sees their results in its context and may not pick them.
    NOT YET   request_help, report_target: no message carries a request or a
              sighting yet (Phase 9, open question 3). Picking one is refused.

12.3, THE REPLY, one JSON object:

    {"situation_assessment": {"mission_progress": "...", "communication_status": "...", "current_risk": "..."},
     "selected_tool": "...", "parameters": {...}, "outgoing_messages": [], "confidence": 0.0-1.0,
     "reason_code": "SHORT_CODE"}

A short reason code, not a chain of thought. `outgoing_messages` is read and
recorded, never sent: every message comes from the protocol. Read as strictly
as Phase 11's channel: an unknown key is a problem; nothing raises.
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..control.skills import (
    FollowWaypointsCommand,
    HoldPositionCommand,
    ReturnHomeCommand,
    SearchRegionCommand,
)
from ..coordination.health import Health
from .belief_state import BeliefState
from .decision import Decision, DecisionKind

ACTIONS = ("continue_task", "accept_task", "start_search", "go_to_waypoint", "act_as_relay", "return_home", "hold",
           "claim_task", "decline_task", "release_task", "change_role")
PROTOCOL = ("announce_task", "send_bid", "compute_task_cost")
NOT_YET = ("request_help", "report_target")
TOOLS = ACTIONS + PROTOCOL + NOT_YET

PARAMS: dict[str, dict[str, str]] = {      # each action's parameters: name -> what it is
    "continue_task": {},
    "accept_task": {"task_id": "the task the protocol gave this drone"},
    "start_search": {"task_id": "the task this drone holds"},
    "go_to_waypoint": {"target": "task | home | relay_point"},
    "act_as_relay": {"teammate": "an unreachable teammate"},
    "return_home": {},
    "hold": {"duration_s": "1 to 30"},
    "claim_task": {"task_id": "an open task"},
    "decline_task": {"task_id": "an open or held task"},
    "release_task": {"task_id": "the task this drone holds"},
    "change_role": {"new_role": "relay | reserve | scout"},
}
TARGETS = ("task", "home", "relay_point")
ROLES = ("relay", "reserve", "scout")
TOP = ("situation_assessment", "selected_tool", "parameters", "outgoing_messages", "confidence", "reason_code")
ASSESSMENT = ("mission_progress", "communication_status", "current_risk")
HOLD_MAX_S = 30.0


def reply_schema() -> dict[str, Any]:
    """The reply's JSON schema, as Ollama's `format` takes it: the shape, not the meaning."""
    return {"type": "object", "required": list(TOP), "additionalProperties": False, "properties": {
        "situation_assessment": {"type": "object", "required": list(ASSESSMENT),
                                 "properties": {k: {"type": "string"} for k in ASSESSMENT}},
        "selected_tool": {"type": "string", "enum": list(TOOLS)},
        "parameters": {"type": "object"},
        "outgoing_messages": {"type": "array"},
        "confidence": {"type": "number"},
        "reason_code": {"type": "string"}}}


def parse_reply(text: str) -> tuple[str | None, dict[str, Any], list[str]]:
    """(tool, parameters, problems). The problems are for the one correction (12.6); none means usable."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        return None, {}, [f"not JSON: {exc}"]
    if not isinstance(data, dict):
        return None, {}, ["not one JSON object"]
    problems = [f"unknown key {k!r}" for k in data if k not in TOP]
    problems += [f"missing {k!r}" for k in TOP if k not in data]
    sa = data.get("situation_assessment")
    if "situation_assessment" in data and (not isinstance(sa, dict) or set(sa) != set(ASSESSMENT)
                                           or not all(isinstance(v, str) for v in sa.values())):
        problems.append(f"situation_assessment must hold exactly {', '.join(ASSESSMENT)}, as words")
    tool = data.get("selected_tool")
    if tool not in TOOLS:
        problems.append(f"selected_tool {tool!r} is not one of the tools")
        tool = None
    elif tool in PROTOCOL:
        problems.append(f"{tool} is run for you by the protocol every tick; its results are in your context -- "
                        "pick an action")
    elif tool in NOT_YET:
        problems.append(f"{tool} is not available in this mission: no message carries it yet -- pick an action")
    params = data.get("parameters", {})
    if not isinstance(params, dict):
        problems.append("parameters must be an object")
        params = {}
    elif tool in PARAMS:
        problems += [f"{tool} has no parameter {k!r}" for k in params if k not in PARAMS[tool]]
        problems += [f"{tool} needs {k!r}" for k in PARAMS[tool] if k not in params]
    if not isinstance(data.get("outgoing_messages", []), list):
        problems.append("outgoing_messages must be a list")
    c = data.get("confidence")
    if "confidence" in data and (isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c)
                                 or not 0 <= c <= 1):
        problems.append("confidence must be a number from 0 to 1")
    if "reason_code" in data and (not isinstance(data["reason_code"], str) or len(data["reason_code"]) > 60):
        problems.append("reason_code must be a short code, at most 60 characters")
    return (tool if tool in ACTIONS else None), (params if isinstance(params, dict) else {}), problems


# ------------------------------------------------------------ preconditions

def _unreachable(policy: Any) -> tuple[str, ...]:
    return () if policy.detector is None else policy.detector.in_state(Health.UNREACHABLE)


def check(tool: str, params: dict[str, Any], policy: Any, belief: BeliefState) -> list[str]:
    """Why this tool cannot be used now, as given; nothing if it can."""
    held = policy.net.holding
    open_ids = [t.task_id for t in policy.net.book.open()]
    me = belief.self_
    problems: list[str] = []
    if not me.airborne and tool != "continue_task":
        return ["the drone is on the ground: only continue_task"]
    if tool in ("accept_task", "start_search", "release_task"):
        if held is None:
            problems.append(f"{tool}: this drone holds no task")
        elif params.get("task_id") != held:
            problems.append(f"{tool}: this drone holds {held!r}, not {params.get('task_id')!r}")
    if tool == "go_to_waypoint":
        target = params.get("target")
        if target not in TARGETS:
            problems.append(f"go_to_waypoint: target must be one of {', '.join(TARGETS)}")
        elif target == "task" and held is None:
            problems.append("go_to_waypoint: no task held to go to")
        elif target == "relay_point" and not _unreachable(policy):
            problems.append("go_to_waypoint: no teammate is unreachable, so there is no relay point")
    if tool == "act_as_relay" and params.get("teammate") not in _unreachable(policy):
        problems.append(f"act_as_relay: {params.get('teammate')!r} is not unreachable "
                        f"(unreachable: {', '.join(_unreachable(policy)) or 'none'})")
    if tool == "hold":
        d = params.get("duration_s")
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not 1 <= d <= HOLD_MAX_S:
            problems.append(f"hold: duration_s must be a number from 1 to {HOLD_MAX_S:g}")
    if tool == "claim_task" and params.get("task_id") not in open_ids:
        problems.append(f"claim_task: {params.get('task_id')!r} is not open (open: {', '.join(open_ids) or 'none'})")
    if tool == "decline_task" and params.get("task_id") not in open_ids + ([held] if held else []):
        problems.append(f"decline_task: {params.get('task_id')!r} is neither open nor held")
    if tool == "change_role":
        role = params.get("new_role")
        if role not in ROLES:
            problems.append(f"change_role: new_role must be one of {', '.join(ROLES)}")
        elif role == "relay" and not _unreachable(policy):
            problems.append("change_role: relay needs an unreachable teammate")
        elif role == "scout" and held is None:
            problems.append("change_role: scout needs a task held")
    return problems


# ---------------------------------------------------------------- execute

def _release(policy: Any, belief: BeliefState, why: str) -> None:
    policy._outbox += policy.net.release(belief.self_.updated_at, why)
    policy.task_id = None
    belief.self_.current_task = None


def _hold(policy: Any, seconds: float, objective: str, reason: str) -> Decision:
    policy.waiting = True
    return Decision.start(HoldPositionCommand(duration_s=float(seconds)), objective, reason)


def execute(tool: str, params: dict[str, Any], policy: Any, belief: BeliefState, reason: str) -> Decision:
    """The tool, on the rule team's own primitives. Call only after `check` found nothing."""
    from .team_policy import HOLD_S
    if tool == "continue_task":
        return Decision.carry_on(belief.mission.objective, reason)
    if tool == "hold":
        return _hold(policy, params["duration_s"], belief.mission.objective or "hold", reason)
    if tool in ("accept_task",) or (tool == "go_to_waypoint" and params["target"] == "task") or \
            (tool == "change_role" and params["new_role"] == "scout"):
        return policy._go(belief, reason)
    if tool == "start_search":
        policy._take(belief)
        policy.waiting = False
        return policy._search(belief, reason)
    if tool in ("return_home",) or (tool == "go_to_waypoint" and params["target"] == "home"):
        policy.gave_up = reason
        return policy._giving_back(belief, lambda: policy._home(belief, reason))
    if tool == "act_as_relay" or (tool == "go_to_waypoint" and params["target"] == "relay_point") or \
            (tool == "change_role" and params["new_role"] == "relay"):
        return policy._relay(belief, reason)
    if tool == "claim_task":
        policy.declined.discard(params["task_id"])
        return _hold(policy, HOLD_S, "wait for a task", f"{reason}; bidding for {params['task_id']}")
    if tool in ("decline_task", "release_task") or (tool == "change_role" and params["new_role"] == "reserve"):
        if tool == "decline_task":
            policy.declined.add(params["task_id"])
        if policy.net.holding is not None and (tool != "decline_task" or params["task_id"] == policy.net.holding):
            _release(policy, belief, reason)
        return _hold(policy, HOLD_S, "stand by", reason)
    raise ValueError(f"not an action: {tool}")


# ------------------------------------------------------- the rule's choice

def rule_tool(decision: Decision, policy: Any) -> tuple[str, dict[str, Any]]:
    """What the rule policy decided, said as a tool -- for the echo model and for agreement."""
    if decision.kind is not DecisionKind.START:
        return "continue_task", {}
    cmd = decision.command
    objective = decision.objective or ""
    if objective.startswith("relay"):
        mates = _unreachable(policy)
        return "act_as_relay", {"teammate": mates[0] if mates else ""}
    if isinstance(cmd, SearchRegionCommand):
        return "start_search", {"task_id": policy.net.holding}
    if objective.startswith("reach"):
        return "accept_task", {"task_id": policy.net.holding}
    if objective.startswith("return home") or isinstance(cmd, ReturnHomeCommand):
        return "return_home", {}
    if isinstance(cmd, HoldPositionCommand):
        return "hold", {"duration_s": cmd.duration_s}
    if isinstance(cmd, FollowWaypointsCommand):
        return "go_to_waypoint", {"target": "task"}
    return "continue_task", {}


def reply_for(tool: str, params: dict[str, Any], reason: str = "RULE") -> str:
    """A well-formed reply choosing `tool` -- what the echo model answers."""
    return json.dumps({"situation_assessment": {"mission_progress": "as planned", "communication_status": "as heard",
                                                "current_risk": "as assessed"},
                       "selected_tool": tool, "parameters": params, "outgoing_messages": [], "confidence": 1.0,
                       "reason_code": reason}, sort_keys=True)
