"""What one drone's LLM is told at a decision: its own context, summarized (AUV-12, 12.1, 12.4, 12.5).

    context = build_context(belief, policy, events, memory)     # a dict, this drone's alone
    messages = render(context)                                   # the system prompt and the context, as chat

12.4: "Give the LLM only relevant context ... Do not include the complete raw
flight log or every previous message." So, at each decision, from THIS
drone's belief and policy and nothing else:

    you          id, role, held task and stage, position, battery, home: how far, what it costs, the reserve
    mission      time left, the sectors, the zones, any keep-out round a silent teammate
    tasks        each task: open, held (by whom), or done; THIS drone's computed bid in seconds, or why it
                 cannot bid; whether it has declined it
    teammates    each: its health on this drone's own failure ladder, how long ago it was heard, where it
                 last said it was, its task, the role it announced
    links        this drone's own link estimates, when it keeps them (Phase 10)
    now          what happened: the events of this decision, the skill that just ended, a refusal's reasons
    memory       its own last few decisions (12.1: its decision history), never another drone's
    actions      every action it could take now, already checked -- so it chooses, it does not compute

12.5: every number is computed here -- distance, the battery to get home, the
bids (the protocol's own, `bid_for`), who is unreachable -- and rounded; the
model never does arithmetic on coordinates. The context is deterministic: the
same state gives the same text, so a recorded reply replays exactly.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .belief_state import BeliefState
from .llm_tools import ACTIONS, NOT_YET, PARAMS, PROTOCOL, ROLES, check
from .validation import ESTIMATE_SPEED_MPS

MEMORY_N = 5

SYSTEM = """You are the decision-maker of one drone in a team of drones searching sectors for targets.
You decide only mission-level actions. A deterministic layer flies the skills, runs the task protocol
(announcing tasks, bidding with computed costs, settling claims), and a safety guardian checks every
action you choose before it can fly.

Answer with ONE JSON object and nothing else:
{"situation_assessment": {"mission_progress": "...", "communication_status": "...", "current_risk": "..."},
 "selected_tool": "<one action>", "parameters": {...}, "outgoing_messages": [], "confidence": <0..1>,
 "reason_code": "<SHORT_CODE>"}

Choose selected_tool and parameters from "actions" in your context: those are exactly the actions
possible now, already checked. Do not compute distances or costs: they are given. Give a short
reason_code, not an explanation. outgoing_messages are recorded, not sent: the protocol sends messages.

Actions:
""" + "\n".join(f"  {t}({', '.join(f'{k}: {v}' for k, v in PARAMS[t].items())})" for t in ACTIONS) + f"""
Run for you, not choosable: {', '.join(PROTOCOL)}. Not available yet: {', '.join(NOT_YET)}.

Priorities: keep the drone and its teammates safe; finish the team's search; get detections to the base;
come home above the battery reserve before the deadline."""


def _r(v: float, n: int = 1) -> float:
    return round(float(v), n)


def available(policy: Any, belief: BeliefState) -> list[dict[str, Any]]:
    """Every action, with every parameter it could take now, that `check` passes."""
    held = policy.net.holding
    open_ids = [t.task_id for t in policy.net.book.open()]
    mates = [] if policy.detector is None else list(policy.detector.in_state(*_unreachable_states()))
    candidates: list[tuple[str, dict[str, Any]]] = [("continue_task", {}), ("hold", {"duration_s": 10})]
    if held:
        candidates += [("accept_task", {"task_id": held}), ("start_search", {"task_id": held}),
                       ("release_task", {"task_id": held}), ("decline_task", {"task_id": held})]
    candidates += [("go_to_waypoint", {"target": t}) for t in ("task", "home", "relay_point")]
    candidates += [("act_as_relay", {"teammate": m}) for m in mates]
    candidates += [("return_home", {})]
    candidates += [("claim_task", {"task_id": t}) for t in open_ids if t in policy.declined]
    candidates += [("decline_task", {"task_id": t}) for t in open_ids if t not in policy.declined]
    candidates += [("change_role", {"new_role": r}) for r in ROLES]
    return [{"tool": t, "parameters": p} for t, p in candidates if not check(t, p, policy, belief)]


def _unreachable_states() -> tuple:
    from ..coordination.health import Health
    return (Health.UNREACHABLE,)


def build_context(belief: BeliefState, policy: Any, events: tuple[Any, ...],
                  memory: list[dict[str, Any]]) -> dict[str, Any]:
    me = belief.self_
    brief = belief.brief
    now = me.updated_at
    home_m = math.dist((me.x, me.y), me.home)
    b = brief.battery
    home_cost = b.hover_drain_per_s * home_m / ESTIMATE_SPEED_MPS + b.move_drain_per_m * home_m
    you = {"id": me.vehicle_id, "role": None if policy.roles is None else policy.roles.role.value,
           "task": policy.net.holding, "stage": "waiting" if policy.waiting else policy.stage.value,
           "airborne": me.airborne, "position_m": [_r(me.x), _r(me.y)], "altitude_m": _r(me.altitude_m),
           "battery_pct": _r(me.battery), "home_distance_m": _r(home_m), "battery_to_fly_home_pct": _r(home_cost),
           "reserve_pct": b.reserve}
    keep = sorted(d for d, _ in policy._keep_out_list(belief))
    mission = {"time_left_s": _r(belief.time_left), "sectors": [s.id for s in brief.sectors],
               "restricted_zones": [z.id for z in brief.restricted_zones], "keep_out_round": keep}
    tasks = []
    for t in sorted(policy.net.book.tasks(), key=lambda t: t.task_id):
        entry: dict[str, Any] = {"task_id": t.task_id, "status": t.status.value, "holder": t.assigned_agent}
        bid = policy.net.my_bids.get((t.task_id, t.version))
        if bid is not None:
            entry["your_bid_s"] = None if bid.value is None else _r(bid.value)
            if bid.value is None:
                entry["why_you_cannot"] = bid.why_not
        entry["declined"] = t.task_id in policy.declined
        tasks.append(entry)
    health = {} if policy.detector is None else policy.detector.states()
    roles = {h["from"]: h.get("role") for h in policy.heard_roles}
    mates = []
    for d in sorted(belief.team.members):
        r = belief.teammate(d)
        entry = {"id": d, "health": health.get(d, "unknown"), "role": roles.get(d)}
        if r is not None:
            entry["heard_s_ago"] = _r(now - r.report.at)
            if r.report.position is not None:
                entry["last_position_m"] = [_r(r.report.position[0]), _r(r.report.position[1])]
            entry["task"] = r.report.task
        mates.append(entry)
    links = belief.link_estimates(now) if belief.link_window_s is not None else None
    happened = []
    for e in events:
        detail = {k: v for k, v in e.detail.items() if k in ("skill", "status", "message", "allocation", "task",
                                                             "label", "level", "base_link", "reasons")}
        happened.append({"event": e.trigger.value, **detail})
    return {"you": you, "mission": mission, "tasks": tasks, "teammates": mates, "links": links,
            "now": happened, "memory": [dict(m, s_ago=_r(now - m["at"])) for m in memory[-MEMORY_N:]]
            if memory else [], "actions": available(policy, belief)}


def render(context: dict[str, Any]) -> list[dict[str, str]]:
    """The chat the model is sent: the fixed system prompt, then this decision's context as JSON."""
    ctx = {k: v for k, v in context.items()}
    ctx["memory"] = [{k: v for k, v in m.items() if k != "at"} for m in ctx.get("memory", [])]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(ctx, sort_keys=True, default=str)}]
