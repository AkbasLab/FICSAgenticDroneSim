"""The model's output contract (Plan.docx 12.3). A model never writes code - it
returns one structured JSON object:

    {"situation_assessment": {"mission_progress": ..., "communication_status": ..., "current_risk": ...},
     "selected_tool": "<one of the 15 tools, and only if the code offered it right now>",
     "parameters": {"reason_code": "<closed list>", <the tool's own parameters, if any>},
     "outgoing_messages": [{"message_type": "help_request", "recipients": [...], "payload": {...}}],
     "confidence": 0.0 - 1.0}

Validation is strict and TYPED, because the fallback chain has to know why an
output was rejected: a malformed answer is worth one correction, a timeout is
not (explaining the problem to a hung model does not un-hang it, and a second
wait costs another timeout on a drone that is currently airborne).

Deliberately NOT requested: free-form rationale. It invites treating the model's
self-report as evidence about its own processing, which it is not, and a handful
of closed codes can be counted across a thousand decisions where a thousand
paragraphs cannot. The assessment is three closed enums for the same reason.

What a model may SEND is the sharpest edge here. A model-authored message could
forge a protocol message (a fake TARGET_FOUND, a stolen TASK_CLAIM). So the
model gets exactly one low-privilege type, help_request, whose payload is a
single closed reason code; it can only address teammates the agent actually
knows, and no more than MAX_OUTGOING_MESSAGES per decision.
"""

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple

from ..coordination.protocols import MessageType
from .llm_tools import BY_NAME, Offered
from .objectives import Objective

# Closed list on purpose.
REASON_CODES = (
    "waiting_for_report",       # a teammate may still be about to broadcast a target
    "nothing_more_to_wait_for",
    "teammate_may_need_help",
    "battery_conserving",
    "my_work_is_done",
    "search_elsewhere",         # Phase 12: repositioning to look somewhere new
)

MISSION_PROGRESS = ("none", "partial", "complete")
COMMUNICATION_STATUS = ("good", "degraded", "lost")
CURRENT_RISK = ("low", "medium", "high")
MODEL_MESSAGE_TYPES = (MessageType.HELP_REQUEST,)   # the ONLY types a model may author
MAX_OUTGOING_MESSAGES = 4

TOP_KEYS = {"situation_assessment", "selected_tool", "parameters", "outgoing_messages", "confidence"}
ASSESSMENT_KEYS = {"mission_progress", "communication_status", "current_risk"}
MESSAGE_KEYS = {"message_type", "recipients", "payload"}
BASE_PARAM_KEYS = {"reason_code"}
WAYPOINT_PARAM_KEYS = {"x", "y"}   # allowed ONLY with selected_tool == go_to_waypoint, and required then


class RejectionKind(str, Enum):
    MALFORMED_JSON = "malformed_json"
    UNKNOWN_OBJECTIVE = "unknown_objective"   # not a real tool, OR real but not offered right now
    BAD_FIELDS = "bad_fields"
    BAD_ASSESSMENT = "bad_assessment"          # situation_assessment missing/wrong/out of the closed enums
    BAD_MESSAGES = "bad_messages"              # outgoing_messages malformed, forbidden type, or unknown recipient
    TIMEOUT = "timeout"
    BACKEND_ERROR = "backend_error"


# Only these are worth a single "that was invalid, try again" correction.
CORRECTABLE = frozenset({RejectionKind.MALFORMED_JSON, RejectionKind.UNKNOWN_OBJECTIVE,
                         RejectionKind.BAD_FIELDS, RejectionKind.BAD_ASSESSMENT,
                         RejectionKind.BAD_MESSAGES})


class DecisionRejected(Exception):
    def __init__(self, kind: RejectionKind, detail: str):
        super().__init__(f"{kind.value}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class Assessment:
    mission_progress: str
    communication_status: str
    current_risk: str


@dataclass(frozen=True)
class OutgoingMessage:
    type: MessageType
    recipients: Tuple[str, ...]
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    objective: Objective              # what the agent executes (derived from the tool, never from the model)
    reason_code: str
    assessment: Assessment
    confidence: float
    tool: str = ""                    # the registry tool the model selected
    args: Dict[str, Any] = field(default_factory=dict)   # validated tool parameters (task_id, recipients, ...)
    waypoint: Optional[Tuple[float, float]] = None   # world (x, y); only for go_to_waypoint
    messages: Tuple[OutgoingMessage, ...] = ()


def decision_json(tool, reason_code: str = "my_work_is_done", x=None, y=None, *, params: Optional[dict] = None,
                  assessment: Optional[dict] = None, confidence: Any = 0.8, messages: Sequence = ()) -> str:
    """Build a well-formed model answer (for scripted backends, tests and demos). Any argument can
    be deliberately wrong - pass a bool for x, a bad enum in `assessment` - to build a bad answer.
    `params` adds tool-specific parameters, e.g. {"task_id": "search_B"}."""
    value = tool.value if isinstance(tool, Objective) else tool
    parameters: Dict[str, Any] = {"reason_code": reason_code}
    if x is not None or y is not None:
        parameters["x"], parameters["y"] = x, y
    parameters.update(params or {})
    return json.dumps({
        "situation_assessment": assessment or {"mission_progress": "partial",
                                               "communication_status": "good", "current_risk": "low"},
        "selected_tool": value,
        "parameters": parameters,
        "outgoing_messages": list(messages),
        "confidence": confidence,
    })


def _reject(kind: RejectionKind, detail: str):
    raise DecisionRejected(kind, detail)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)   # a bool must never become 1.0


def _parse_assessment(data) -> Assessment:
    if not isinstance(data, dict):
        _reject(RejectionKind.BAD_ASSESSMENT, "situation_assessment must be an object")
    extra, missing = set(data) - ASSESSMENT_KEYS, ASSESSMENT_KEYS - set(data)
    if extra or missing:
        _reject(RejectionKind.BAD_ASSESSMENT,
                f"situation_assessment needs exactly {sorted(ASSESSMENT_KEYS)} (extra {sorted(extra)}, missing {sorted(missing)})")
    for key, allowed in (("mission_progress", MISSION_PROGRESS), ("communication_status", COMMUNICATION_STATUS),
                         ("current_risk", CURRENT_RISK)):
        if data[key] not in allowed:
            _reject(RejectionKind.BAD_ASSESSMENT, f"{key} {data[key]!r} not one of {list(allowed)}")
    return Assessment(data["mission_progress"], data["communication_status"], data["current_risk"])


def _parse_messages(data, teammates: Sequence[str]) -> Tuple[OutgoingMessage, ...]:
    if not isinstance(data, list):
        _reject(RejectionKind.BAD_MESSAGES, "outgoing_messages must be a list")
    if len(data) > MAX_OUTGOING_MESSAGES:
        _reject(RejectionKind.BAD_MESSAGES, f"at most {MAX_OUTGOING_MESSAGES} messages per decision, got {len(data)}")
    allowed_types = [t.value for t in MODEL_MESSAGE_TYPES]
    out = []
    for item in data:
        if not isinstance(item, dict) or set(item) != MESSAGE_KEYS:
            _reject(RejectionKind.BAD_MESSAGES, f"each message needs exactly {sorted(MESSAGE_KEYS)}")
        if item["message_type"] not in allowed_types:
            _reject(RejectionKind.BAD_MESSAGES,
                    f"message_type {item['message_type']!r} is not one you may send (allowed: {allowed_types})")
        recipients = item["recipients"]
        if not isinstance(recipients, list) or not recipients or not all(isinstance(r, str) for r in recipients):
            _reject(RejectionKind.BAD_MESSAGES, "recipients must be a non-empty list of drone names")
        if len(set(recipients)) != len(recipients):
            _reject(RejectionKind.BAD_MESSAGES, "recipients must not repeat a drone")
        unknown = [r for r in recipients if r not in teammates]
        if unknown:
            _reject(RejectionKind.BAD_MESSAGES, f"unknown recipient(s) {unknown}; known teammates: {list(teammates)}")
        payload = item["payload"]
        if not isinstance(payload, dict) or set(payload) != {"reason_code"} or payload["reason_code"] not in REASON_CODES:
            _reject(RejectionKind.BAD_MESSAGES, f"payload must be exactly {{reason_code: one of {list(REASON_CODES)}}}")
        out.append(OutgoingMessage(MessageType(item["message_type"]), tuple(recipients),
                                   {"reason_code": payload["reason_code"]}))
    return tuple(out)


def _check_param(tool_name: str, key: str, value, choices: Optional[Tuple]):
    """Validate one tool parameter against the values the CODE offered for it."""
    if key in ("x", "y"):
        if not _is_number(value):
            _reject(RejectionKind.BAD_FIELDS, f"{key} must be a number")
        return float(value)
    if key == "recipients":
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            _reject(RejectionKind.BAD_FIELDS, "recipients must be a non-empty list of drone names")
        if len(set(value)) != len(value):
            _reject(RejectionKind.BAD_FIELDS, "recipients must not repeat a drone")
        bad = [v for v in value if v not in (choices or ())]
        if bad:
            _reject(RejectionKind.BAD_FIELDS, f"unknown recipient(s) {bad}; valid for {tool_name}: {list(choices or ())}")
        return tuple(value)
    # task_id / target_id / new_role: a string that is one of the values offered right now
    if not isinstance(value, str) or value not in (choices or ()):
        _reject(RejectionKind.BAD_FIELDS, f"{key} {value!r} is not valid for {tool_name}; valid: {list(choices or ())}")
    return value


def parse_decision(raw: str, offered: Offered, teammates: Sequence[str] = ()) -> Decision:
    """`offered` is what the CODE put on the menu this turn: tool name -> {parameter: allowed values}."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        _reject(RejectionKind.MALFORMED_JSON, f"not valid JSON ({exc})")
    if not isinstance(data, dict):
        _reject(RejectionKind.MALFORMED_JSON, "top level must be a JSON object")

    # An unknown key is an error, not something to ignore: a model that invents a field has
    # misunderstood the contract, and silently dropping it executes a decision nobody intended.
    extra, missing = set(data) - TOP_KEYS, TOP_KEYS - set(data)
    if extra:
        _reject(RejectionKind.BAD_FIELDS, f"unknown field(s): {sorted(extra)}")
    if missing:
        _reject(RejectionKind.BAD_FIELDS, f"missing field(s): {sorted(missing)}")

    assessment = _parse_assessment(data["situation_assessment"])

    name, params = data["selected_tool"], data["parameters"]
    if not isinstance(name, str):
        _reject(RejectionKind.BAD_FIELDS, "selected_tool must be a string")
    if not isinstance(params, dict):
        _reject(RejectionKind.BAD_FIELDS, "parameters must be an object")
    if name not in BY_NAME or name not in offered:
        _reject(RejectionKind.UNKNOWN_OBJECTIVE, f"{name!r} is not one of the offered tools {sorted(offered)}")

    tool, choices = BY_NAME[name], offered[name]
    allowed = BASE_PARAM_KEYS | set(tool.params)
    p_extra, p_missing = set(params) - allowed, allowed - set(params)
    if p_extra:
        _reject(RejectionKind.BAD_FIELDS, f"unknown parameter(s) for {name}: {sorted(p_extra)}")
    if p_missing:
        _reject(RejectionKind.BAD_FIELDS, f"missing parameter(s) for {name}: {sorted(p_missing)}")
    reason = params["reason_code"]
    if not isinstance(reason, str) or reason not in REASON_CODES:
        _reject(RejectionKind.BAD_FIELDS, f"reason_code {reason!r} not in the allowed list")

    # Type and membership only. Whether a waypoint is sensible (finite, in range, inside the geofence,
    # outside a no-fly zone, away from teammates) is deliberately NOT judged here: that is the
    # SafetyGuardian's job alone, and a schema that pre-filtered unsafe coordinates would hide from it
    # exactly the commands it exists to catch.
    checked = {key: _check_param(name, key, params[key], choices.get(key)) for key in tool.params}
    waypoint = (checked.pop("x"), checked.pop("y")) if "x" in checked else None

    messages = _parse_messages(data["outgoing_messages"], teammates)

    confidence = data["confidence"]
    if not _is_number(confidence) or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        _reject(RejectionKind.BAD_FIELDS, "confidence must be a number from 0 to 1")

    return Decision(objective=tool.objective, reason_code=reason, assessment=assessment,
                    confidence=float(confidence), tool=name, args=checked, waypoint=waypoint, messages=messages)
