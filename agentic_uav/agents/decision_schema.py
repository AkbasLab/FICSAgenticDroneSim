"""The structured decision an LLM agent returns, and its validator (Phase 12.3).

One turn of an LLM agent is one JSON object:

    {
      "situation_assessment": {
        "mission_progress": "partial",
        "communication_status": "degraded",
        "current_risk": "medium"
      },
      "selected_tool": "change_role",
      "parameters": {"new_role": "relay", "reason_code": "BASE_LINK_LOST"},
      "outgoing_messages": [
        {"message_type": "ROLE_CHANGE",
         "recipients": ["Drone2", "Drone3"],
         "payload": {"new_role": "relay"}}
      ],
      "confidence": 0.78
    }

**No private chain of thought is requested or accepted.** The model gives a
short assessment from a closed vocabulary and a reason code. That is a
methodological choice as much as an engineering one: free-form rationale invites
treating a model's self-report as evidence about its own processing, which it is
not. Three enum fields and a reason code can be counted across a thousand
decisions; a paragraph of prose cannot, and reads as more informative than it is.

Validation is strict and, importantly, **typed**. Phase 12.6 has to decide
whether to attempt a correction or fall straight through to the deterministic
policy, and that decision depends on *why* the output was rejected: a missing
field is worth one corrective round-trip, a model that emitted prose instead of
JSON on a second attempt is not.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from . import llm_tools
from .llm_tools import ParamError

# --- closed vocabularies for the assessment ---

MISSION_PROGRESS = ("none", "partial", "nearly_complete", "complete", "blocked")
COMMUNICATION_STATUS = ("nominal", "degraded", "isolated", "unknown")
RISK_LEVELS = ("low", "medium", "high", "critical")

MAX_OUTGOING_MESSAGES = 4
MAX_PAYLOAD_KEYS = 8
MAX_RECIPIENTS = 8


class RejectionReason(str, Enum):
    """Why a model's output was not usable. Drives the 12.6 fallback chain."""
    MALFORMED_JSON = "malformed_json"
    NOT_AN_OBJECT = "not_an_object"
    MISSING_FIELD = "missing_field"
    UNKNOWN_TOOL = "unknown_tool"
    BAD_PARAMETERS = "bad_parameters"
    BAD_ASSESSMENT = "bad_assessment"
    BAD_CONFIDENCE = "bad_confidence"
    BAD_MESSAGES = "bad_messages"
    TIMEOUT = "timeout"
    BACKEND_ERROR = "backend_error"
    EMPTY_RESPONSE = "empty_response"

    @property
    def correctable(self) -> bool:
        """Whether one structured correction is worth attempting (12.6.1).

        A model that produced *something* structurally wrong can usually fix it
        when told precisely what was wrong. A timeout or a dead backend cannot
        be corrected by explaining the problem to it, and retrying costs another
        timeout in an agent that is currently airborne.
        """
        return self in (
            RejectionReason.MALFORMED_JSON, RejectionReason.NOT_AN_OBJECT,
            RejectionReason.MISSING_FIELD, RejectionReason.UNKNOWN_TOOL,
            RejectionReason.BAD_PARAMETERS, RejectionReason.BAD_ASSESSMENT,
            RejectionReason.BAD_CONFIDENCE, RejectionReason.BAD_MESSAGES,
            RejectionReason.EMPTY_RESPONSE,
        )


class DecisionError(Exception):
    """A model output that failed validation, with the reason and a repair hint."""

    def __init__(self, reason: RejectionReason, detail: str, hint: str = ""):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        #: what to tell the model on the corrective attempt. Naming the offending
        #: field and the legal values is what makes a correction likely to work;
        #: "invalid output" is not actionable by anything, model or human.
        self.hint = hint or detail


@dataclass(frozen=True)
class SituationAssessment:
    mission_progress: str
    communication_status: str
    current_risk: str

    def as_dict(self):
        return {"mission_progress": self.mission_progress,
                "communication_status": self.communication_status,
                "current_risk": self.current_risk}


@dataclass(frozen=True)
class OutgoingMessage:
    message_type: str
    recipients: tuple
    payload: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {"message_type": self.message_type,
                "recipients": list(self.recipients),
                "payload": dict(self.payload)}


@dataclass
class AgentDecisionTurn:
    """One validated decision. Everything downstream consumes this, not raw JSON."""
    assessment: SituationAssessment
    tool: llm_tools.Tool
    parameters: Dict[str, Any]
    outgoing: List[OutgoingMessage] = field(default_factory=list)
    confidence: float = 0.0
    raw: str = ""

    @property
    def tool_name(self):
        return self.tool.name

    @property
    def reason_code(self):
        return self.parameters.get("reason_code")

    def as_dict(self):
        return {"situation_assessment": self.assessment.as_dict(),
                "selected_tool": self.tool.name,
                "parameters": dict(self.parameters),
                "outgoing_messages": [m.as_dict() for m in self.outgoing],
                "confidence": self.confidence}


# --- validation ---


def _enum(value, allowed, field_name):
    if not isinstance(value, str) or value.strip() not in allowed:
        raise DecisionError(
            RejectionReason.BAD_ASSESSMENT,
            f"situation_assessment.{field_name}={value!r} is not valid",
            f"situation_assessment.{field_name} must be exactly one of: "
            + ", ".join(allowed))
    return value.strip()


def _assessment(raw) -> SituationAssessment:
    if not isinstance(raw, dict):
        raise DecisionError(RejectionReason.MISSING_FIELD,
                            "situation_assessment must be an object",
                            "include a situation_assessment object with "
                            "mission_progress, communication_status and current_risk")
    missing = [k for k in ("mission_progress", "communication_status", "current_risk")
               if k not in raw]
    if missing:
        raise DecisionError(
            RejectionReason.MISSING_FIELD,
            f"situation_assessment is missing {', '.join(missing)}",
            f"situation_assessment must contain {', '.join(missing)}")
    return SituationAssessment(
        mission_progress=_enum(raw["mission_progress"], MISSION_PROGRESS,
                               "mission_progress"),
        communication_status=_enum(raw["communication_status"],
                                   COMMUNICATION_STATUS, "communication_status"),
        current_risk=_enum(raw["current_risk"], RISK_LEVELS, "current_risk"))


def _confidence(raw) -> float:
    if raw is None:
        raise DecisionError(RejectionReason.MISSING_FIELD, "confidence is missing",
                            "include a confidence between 0 and 1")
    if isinstance(raw, bool):
        raise DecisionError(RejectionReason.BAD_CONFIDENCE,
                            "confidence must be a number, not a boolean",
                            "confidence must be a number between 0 and 1")
    try:
        c = float(raw)
    except (TypeError, ValueError):
        raise DecisionError(RejectionReason.BAD_CONFIDENCE,
                            f"confidence={raw!r} is not a number",
                            "confidence must be a number between 0 and 1")
    if c != c or not (0.0 <= c <= 1.0):
        raise DecisionError(RejectionReason.BAD_CONFIDENCE,
                            f"confidence={raw!r} is outside 0..1",
                            "confidence must be between 0 and 1 inclusive")
    return c


def _messages(raw, known_peers=None) -> List[OutgoingMessage]:
    """Validate the outgoing messages.

    Bounded on purpose. An agent that emits 200 messages in one turn is not
    coordinating, it is flooding — and under the Phase 10 degraded-comms model a
    flood is indistinguishable from an attack on the team's own bandwidth.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DecisionError(RejectionReason.BAD_MESSAGES,
                            "outgoing_messages must be a list",
                            "outgoing_messages must be a list (use [] for none)")
    if len(raw) > MAX_OUTGOING_MESSAGES:
        raise DecisionError(
            RejectionReason.BAD_MESSAGES,
            f"{len(raw)} outgoing messages exceeds the limit",
            f"send at most {MAX_OUTGOING_MESSAGES} messages in one decision")

    from ..coordination.protocols import MessageType
    valid_types = {m.value for m in MessageType} | {m.name for m in MessageType}

    out = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise DecisionError(RejectionReason.BAD_MESSAGES,
                                f"outgoing_messages[{i}] is not an object",
                                "each outgoing message must be an object with "
                                "message_type, recipients and payload")
        mtype = m.get("message_type")
        if not isinstance(mtype, str) or mtype.strip() not in valid_types:
            raise DecisionError(
                RejectionReason.BAD_MESSAGES,
                f"outgoing_messages[{i}].message_type={mtype!r} is not a known type",
                "message_type must be one of: "
                + ", ".join(sorted(m.name for m in MessageType)))

        recips = m.get("recipients", [])
        if isinstance(recips, str):
            recips = [recips]
        if not isinstance(recips, list) or len(recips) > MAX_RECIPIENTS:
            raise DecisionError(
                RejectionReason.BAD_MESSAGES,
                f"outgoing_messages[{i}].recipients is not a list of at most "
                f"{MAX_RECIPIENTS} ids",
                f"recipients must be a list of at most {MAX_RECIPIENTS} vehicle ids")
        for r in recips:
            if not isinstance(r, str) or not r.strip():
                raise DecisionError(RejectionReason.BAD_MESSAGES,
                                    f"outgoing_messages[{i}] has a bad recipient {r!r}",
                                    "each recipient must be a vehicle id string")
        # A message addressed to a drone that does not exist is a hallucinated
        # teammate. It cannot be delivered, so it is caught here rather than
        # silently disappearing into the bus and looking like packet loss.
        if known_peers is not None:
            unknown = [r for r in recips if r not in known_peers]
            if unknown:
                raise DecisionError(
                    RejectionReason.BAD_MESSAGES,
                    f"outgoing_messages[{i}] addressed to unknown drone(s) "
                    f"{', '.join(unknown)}",
                    "recipients must be drones on the team roster: "
                    + ", ".join(sorted(known_peers)))

        payload = m.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise DecisionError(RejectionReason.BAD_MESSAGES,
                                f"outgoing_messages[{i}].payload must be an object",
                                "payload must be a JSON object")
        if len(payload) > MAX_PAYLOAD_KEYS:
            raise DecisionError(
                RejectionReason.BAD_MESSAGES,
                f"outgoing_messages[{i}].payload has {len(payload)} keys",
                f"payload may have at most {MAX_PAYLOAD_KEYS} keys")

        out.append(OutgoingMessage(mtype.strip(), tuple(recips), dict(payload)))
    return out


def parse_decision(raw_text, known_peers=None) -> AgentDecisionTurn:
    """Parse and validate one model output. Raises DecisionError on anything wrong.

    `known_peers`, when given, is the agent's roster: it lets the validator
    reject messages addressed to drones that do not exist.
    """
    if raw_text is None or (isinstance(raw_text, str) and not raw_text.strip()):
        raise DecisionError(RejectionReason.EMPTY_RESPONSE,
                            "the model returned nothing",
                            "return a single JSON object and nothing else")

    if isinstance(raw_text, dict):
        data = raw_text                      # already-parsed (scripted backends)
    else:
        text = _strip_fences(str(raw_text))
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            raise DecisionError(
                RejectionReason.MALFORMED_JSON,
                f"output is not valid JSON: {e}",
                "return a single valid JSON object and nothing else - "
                "no prose, no markdown fences, no trailing commas")

    if not isinstance(data, dict):
        raise DecisionError(RejectionReason.NOT_AN_OBJECT,
                            f"top level is {type(data).__name__}, not an object",
                            "the top level must be a JSON object")

    if "selected_tool" not in data:
        raise DecisionError(RejectionReason.MISSING_FIELD,
                            "selected_tool is missing",
                            "include selected_tool, naming exactly one tool")

    assessment = _assessment(data.get("situation_assessment"))

    try:
        tool, params = llm_tools.validate_call(data.get("selected_tool"),
                                               data.get("parameters", {}))
    except ParamError as e:
        name = data.get("selected_tool")
        unknown = isinstance(name, str) and name.strip() not in llm_tools.BY_NAME
        raise DecisionError(
            RejectionReason.UNKNOWN_TOOL if unknown else RejectionReason.BAD_PARAMETERS,
            str(e), str(e))

    confidence = _confidence(data.get("confidence"))
    outgoing = _messages(data.get("outgoing_messages"), known_peers=known_peers)

    return AgentDecisionTurn(
        assessment=assessment, tool=tool, parameters=params,
        outgoing=outgoing, confidence=confidence,
        raw=raw_text if isinstance(raw_text, str) else json.dumps(raw_text))


def _strip_fences(text):
    """Remove ```json fences, which even schema-constrained models still emit."""
    t = text.strip()
    if t.startswith("```"):
        lines = [ln for ln in t.splitlines() if not ln.strip().startswith("```")]
        t = "\n".join(lines).strip()
    return t


# --- the schema, for models that support constrained decoding ---


def response_schema() -> Dict[str, Any]:
    """A JSON schema for the decision object.

    Ollama's `format=` and Gemini's `response_schema` both accept this, which
    removes most malformed-output failures at the source rather than catching
    them afterwards. The validator above still runs: constrained decoding
    guarantees shape, not that `selected_tool` names a real tool.
    """
    return {
        "type": "object",
        "properties": {
            "situation_assessment": {
                "type": "object",
                "properties": {
                    "mission_progress": {"type": "string",
                                         "enum": list(MISSION_PROGRESS)},
                    "communication_status": {"type": "string",
                                             "enum": list(COMMUNICATION_STATUS)},
                    "current_risk": {"type": "string", "enum": list(RISK_LEVELS)},
                },
                "required": ["mission_progress", "communication_status",
                             "current_risk"],
            },
            "selected_tool": {"type": "string", "enum": list(llm_tools.TOOL_NAMES)},
            "parameters": {"type": "object"},
            "outgoing_messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "message_type": {"type": "string"},
                        "recipients": {"type": "array", "items": {"type": "string"}},
                        "payload": {"type": "object"},
                    },
                    "required": ["message_type", "recipients"],
                },
            },
            "confidence": {"type": "number"},
        },
        "required": ["situation_assessment", "selected_tool", "parameters",
                     "confidence"],
    }
