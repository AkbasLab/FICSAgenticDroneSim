"""What one agent sees when it is asked to decide (Phase 12.4).

The prompt carries exactly nine things:

  1. the team mission
  2. non-negotiable constraints
  3. this drone's current role and task
  4. a summarized belief state
  5. recent important messages
  6. the available tools
  7. the current communication estimate
  8. the result of the last skill
  9. unresolved decisions

and deliberately **not** the raw flight log or every message ever received.

That exclusion is a research requirement, not a token-budget convenience. An
agent whose prompt grows with mission length has a decision quality that varies
with how long it has been flying, which confounds every comparison this project
exists to make: a difference between two conditions could be the condition, or
could be that one run happened to accumulate a longer transcript. Bounded
context means turn 200 is the same kind of decision as turn 3.

It also protects the Phase 6 boundary. The belief state is already the agent's
filtered, provenance-tagged view of the world; passing the raw log alongside it
would hand the model observations that never went through `SensorModel`, which
is precisely the ground-truth leak Phase 6 was built to prevent.

`SUMMARY_LIMITS` holds every cap in one place so the whole context budget can be
inspected, tested and reported in a paper.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import llm_tools, reasoning_tools

#: Every bound on context size, in one auditable place.
SUMMARY_LIMITS = {
    "recent_messages": 6,        # most recent important messages
    "teammates": 6,              # closest/most relevant peers
    "detections": 8,             # target ids
    "searched_regions": 8,
    "assumptions": 4,
    "unresolved": 5,
    "open_tasks": 6,
    "message_payload_chars": 160,
}

#: Message types that are worth a decision cycle. Heartbeats and status updates
#: are how the agent's *belief* stays current - they are already reflected in
#: the team summary - so replaying them into the prompt as well is duplication
#: that crowds out the messages that actually demand a response.
IMPORTANT_MESSAGE_TYPES = (
    "task_announcement", "task_bid", "task_award", "task_accept",
    "task_release", "task_complete", "target_found", "help_request",
    "role_change", "mission_update",
)


@dataclass
class AgentPromptContext:
    """The assembled context for one decision. Serialisable, and logged verbatim."""
    vehicle_id: str
    step: int
    time_s: float
    mission: Dict[str, Any]
    constraints: Dict[str, Any]
    role_and_task: Dict[str, Any]
    belief_summary: Dict[str, Any]
    recent_messages: List[Dict[str, Any]]
    communication: Dict[str, Any]
    last_skill_result: Optional[Dict[str, Any]]
    unresolved: List[str]
    computed: Dict[str, Any] = field(default_factory=dict)
    tools: str = ""

    def as_dict(self):
        return {
            "vehicle_id": self.vehicle_id, "step": self.step,
            "time_s": round(self.time_s, 1),
            "mission": self.mission, "constraints": self.constraints,
            "role_and_task": self.role_and_task,
            "belief": self.belief_summary,
            "recent_messages": self.recent_messages,
            "communication": self.communication,
            "last_skill_result": self.last_skill_result,
            "unresolved_decisions": self.unresolved,
            "computed": self.computed,
        }

    def to_prompt(self) -> str:
        """Render as the user message. JSON, not prose.

        Models follow a structured block more reliably than a paragraph, and —
        more usefully here — a JSON prompt can be diffed between runs, so two
        agents disagreeing can be traced to a concrete difference in what they
        were told rather than to phrasing.
        """
        body = json.dumps(self.as_dict(), indent=1, sort_keys=False,
                          default=str)
        return (f"{body}\n\nAvailable tools:\n{self.tools}\n\n"
                "Select exactly one tool and reply with the decision object.")

    def size_chars(self):
        return len(self.to_prompt())


def _message_summary(msg, limit):
    payload = msg.payload if isinstance(getattr(msg, "payload", None), dict) else {}
    text = json.dumps(payload, default=str)
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    mtype = getattr(msg.message_type, "value", str(msg.message_type))
    return {"from": msg.sender_id, "type": mtype,
            "age_s": None, "payload": text}


def recent_important(messages, now, limit=None, payload_chars=None):
    """The last few messages that call for a decision, newest last.

    Filtered by type, then truncated, then ordered oldest-to-newest so the
    model reads them the way a person would read a chat log.
    """
    limit = limit or SUMMARY_LIMITS["recent_messages"]
    payload_chars = payload_chars or SUMMARY_LIMITS["message_payload_chars"]

    important = []
    for m in messages:
        mtype = getattr(m.message_type, "value", str(m.message_type))
        if mtype in IMPORTANT_MESSAGE_TYPES:
            important.append(m)

    picked = important[-limit:]
    out = []
    for m in picked:
        row = _message_summary(m, payload_chars)
        sent = getattr(m, "sent_at_s", None)
        if sent is not None:
            row["age_s"] = round(max(0.0, now - sent), 1)
        out.append(row)
    return out


def summarize_belief(belief, limits=None) -> Dict[str, Any]:
    """A bounded view of `belief.known()`.

    Built from the same snapshot the Phase 6 decision log records, so what the
    model saw and what the audit trail says it knew cannot drift apart.
    """
    L = dict(SUMMARY_LIMITS)
    L.update(limits or {})
    known = belief.known()

    team = {}
    for vid, rec in list(known.get("team", {}).items())[:L["teammates"]]:
        team[vid] = {"position": rec.get("last_position"),
                     "role": rec.get("current_role"),
                     "task": rec.get("current_task"),
                     "status": rec.get("status"),
                     "age_s": rec.get("age_s"),
                     "stale": rec.get("stale")}

    lm = known.get("local_map", {})
    return {
        "self": known.get("self", {}),
        "progress": known.get("mission", {}).get("progress", {}),
        "searched_regions": lm.get("searched_regions", [])[:L["searched_regions"]],
        "observed_targets": lm.get("observed_targets", [])[:L["detections"]],
        "restricted_zones": lm.get("restricted_zones", []),
        "team": team,
        "assumptions": [a.get("statement") if isinstance(a, dict) else str(a)
                        for a in (known.get("assumptions") or [])][:L["assumptions"]],
        "unknown": known.get("unknown") if isinstance(known.get("unknown"), (list, dict))
                   else None,
    }


def unresolved_decisions(belief, allocator=None, now=None) -> List[str]:
    """What is currently waiting on this agent.

    This is the field that makes a *persistent* agent different from a
    stateless one being asked a question: it is the agent's own sense of what it
    has left hanging, carried from turn to turn.
    """
    now = belief.now if now is None else now
    out = []

    if getattr(belief, "no_work_remaining", False):
        out.append("ALL MISSION WORK IS COMPLETE; there is nothing left to claim")
    elif belief.task is None:
        out.append("no task held; work must be claimed before flying")
    else:
        tid = getattr(belief.task, "task_id", "?")
        if not belief.at_sector and not belief.sector_searched:
            out.append(f"task {tid} claimed but the sector has not been reached")
        elif not belief.sector_searched:
            out.append(f"task {tid}: sector reached, sweep not yet flown")
        elif not belief.reported:
            out.append(f"task {tid}: sweep complete, completion not yet reported")

    if allocator is not None:
        try:
            open_tasks = allocator.open_for_me(now)
        except TypeError:
            open_tasks = []
        for t in list(open_tasks)[:SUMMARY_LIMITS["open_tasks"]]:
            out.append(f"task {t.task_id} is open and unclaimed")

    if belief.low_battery:
        out.append("battery is low; continuing work may not be possible")
    if belief.critical_battery:
        out.append("battery is critical; landing takes priority over the mission")
    if not belief.communication.base_reachable:
        out.append("base is unreachable; reports are not getting through")
    if belief.detections and not belief.reported:
        out.append(f"{len(belief.detections)} detection(s) not yet reported")

    return out[:SUMMARY_LIMITS["unresolved"]]


def constraints_for(belief, safety_limits=None) -> Dict[str, Any]:
    """The non-negotiable envelope, stated to the model as fact.

    The model is told these because a decision that respects them is better than
    one the guardian has to correct — but the guardian enforces them regardless.
    Nothing here is load-bearing for safety; it is load-bearing for *efficiency*.
    Telling the model the geofence does not make the geofence optional.
    """
    out = {"note": "these are enforced by an independent safety layer; "
                   "a command that breaks one will be rejected or modified"}
    m = belief.mission
    if m.deadline_s != float("inf"):
        out["mission_deadline_s"] = round(m.deadline_s, 1)
    if m.constraints:
        out.update({k: v for k, v in m.constraints.items()})

    if safety_limits is not None:
        L = safety_limits
        out["geofence"] = {"min_x": L.geofence_min_x, "max_x": L.geofence_max_x,
                           "min_y": L.geofence_min_y, "max_y": L.geofence_max_y}
        out["altitude_range_ned"] = [L.min_altitude, L.max_altitude]
        out["max_speed_mps"] = L.max_speed_mps
        out["min_separation_m"] = L.min_separation_m
        out["battery_reserve_frac"] = L.min_battery_reserve_frac
        out["restricted_zones"] = [getattr(z, "zone_id", "?")
                                   for z in L.restricted_zones]
    return out


def build(belief, *, step=0, role=None, task=None, messages=None,
          last_result=None, allocator=None, safety_limits=None,
          capabilities=None, limits=None) -> AgentPromptContext:
    """Assemble the nine sections. This is the whole of what the model sees."""
    now = belief.now
    messages = list(messages or [])

    mission = {
        "mission_id": belief.mission.mission_id,
        "objective": belief.mission.objective or
                     "search the assigned sectors and report any targets found",
        "team": sorted(set(list(belief.team.teammates.keys())
                           + [belief.vehicle_id])),
    }

    role_and_task = {
        "role": role or belief.self_.role,
        "capabilities": sorted(capabilities or []),
        "task": None if task is None else {
            "task_id": getattr(task, "task_id", None),
            "sector": getattr(getattr(task, "sector", None), "sector_id", None),
            "type": getattr(task, "task_type", "search"),
        },
    }

    skill_result = None
    if last_result is not None:
        skill_result = {
            "skill": getattr(getattr(last_result, "skill_type", None), "value",
                             str(getattr(last_result, "skill_type", "?"))),
            "status": getattr(getattr(last_result, "status", None), "value",
                              str(getattr(last_result, "status", "?"))),
            "error_code": getattr(last_result, "error_code", None),
            "duration_s": round(getattr(last_result, "duration_s", 0.0) or 0.0, 1),
        }

    return AgentPromptContext(
        vehicle_id=belief.vehicle_id,
        step=step,
        time_s=now,
        mission=mission,
        constraints=constraints_for(belief, safety_limits),
        role_and_task=role_and_task,
        belief_summary=summarize_belief(belief, limits),
        recent_messages=recent_important(messages, now),
        communication=reasoning_tools.comms_reachable(belief),
        last_skill_result=skill_result,
        unresolved=unresolved_decisions(belief, allocator, now),
        computed=reasoning_tools.brief(belief, task=task, limits=safety_limits,
                                       capabilities=capabilities),
        tools=llm_tools.catalogue(),
    )


# --- the system prompt ---


SYSTEM_PROMPT = """You are one drone in a team of autonomous search drones.

You are a persistent agent: you keep your own beliefs, your own task and your \
own history across the whole mission. The other drones are separate agents with \
their own beliefs. They may know things you do not, and you may be wrong.

Each turn you are given your current situation and you select EXACTLY ONE tool.

RULES
- Reply with a single JSON object and nothing else. No prose, no markdown.
- selected_tool must be one of the listed tools, spelled exactly.
- parameters must match that tool's signature. Do not invent parameters.
- Numbers under "computed" were calculated for you. Trust them over your own \
arithmetic; they are exact and you are not being asked to estimate.
- Altitude is NED: negative z is up. -8 is higher than -3.
- You cannot see the world directly. Everything under "belief" is what you have \
observed or been told, and some of it is stale. Ages are given in seconds.
- An independent safety layer checks every command. If it rejects yours, you \
will be told why and asked again. Do not attempt to work around it.
- Prefer finishing your current task to starting a new one, unless the \
situation has changed.
- Do not explain your reasoning at length. Give the short assessment and a \
reason_code.

OUTPUT FORMAT
{"situation_assessment": {"mission_progress": "...", \
"communication_status": "...", "current_risk": "..."}, \
"selected_tool": "...", "parameters": {...}, \
"outgoing_messages": [], "confidence": 0.0}
"""


def correction_prompt(hint: str) -> str:
    """What the model is told on its one corrective attempt (12.6.1).

    Names the specific fault and restates the requirement. A retry that just
    says "invalid, try again" mostly reproduces the same error, which burns the
    correction budget without improving the odds.
    """
    return ("Your previous reply was rejected and was NOT executed.\n"
            f"Problem: {hint}\n"
            "Reply again with a single corrected JSON object and nothing else. "
            "Do not repeat the problem above.")
