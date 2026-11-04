"""What one drone can say to another: the message types and the common envelope (AUV-07, 7.1-7.2).

    msg = new_message(MessageType.HEARTBEAT, "Drone1", BROADCAST, "search_relay_001",
                      at=12.5, sequence_number=13,
                      payload={"position": [40.0, -12.0, 12.0], "airborne": True, "battery": 97.4})
    msg.size_bytes(), msg.expires_at, AgentMessage.from_json(msg.as_json()) == msg

THE TYPES (7.1). AUV-07 says fourteen and names thirteen; these are the
thirteen it names, and the gap is recorded in the phase record rather than
filled with an invented type. Six are the contract-net protocol of Phase 8
(`TASK_*`); `HEARTBEAT` is what Phase 9's failure detection is built on;
`INTENT_UPDATE` is the shared-intent half of controlled emergence.

PAYLOAD SCHEMAS ONLY FOR THE TYPES IN USE. Phase 7 sends `HEARTBEAT` and
`STATUS_UPDATE`; Phase 8 adds the six `TASK_*` of its contract-net. The other
five exist as names; a message of a type with no schema yet is refused, so no
phase can start sending one without first saying what it carries. Every
payload field is checked: none missing, none unknown, each of its kind.

AN OPTIONAL GROUP (Phase 8). A drone holding a task reports its progress on
its `STATUS_UPDATE` -- the task, its version and how far along it is -- and
that is what renews its lease. The three fields come together or not at all,
so a drone holding nothing (and every Phase 7 agent) sends the status update
it always did.

THE ENVELOPE (7.2) is AUV-07's, field for field. Two fields are not
decoration: `sequence_number` and `time_to_live_s` are what let an agent
ESTIMATE its own link -- from gaps and from staleness -- rather than be told
it (AUV-10, 10.5). The id is the sender and its sequence number, so the same
flight gives the same ids. `recipient_ids` is a tuple of drones, or
BROADCAST. A message expires `time_to_live_s` after its timestamp: a
heartbeat soon, since a stale one says nothing about now (AUV-10, 10.4).

This module is plain data: it knows nothing of how a message travels. The
bus that carries them is simulation infrastructure (`simulator/`); an agent
only ever sends and receives these. An `AgentMessage` only validates itself:
`new_message` builds the plain copy of the payload a sender hands over, and
the bus gives each recipient a copy of its own, so no two agents ever hold
the same mutable payload -- which would be a channel no message went through.
It touches no dunder attribute, so the boundary checks can hold it to the
same rules as the agent code that imports it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class MessageType(str, Enum):
    HEARTBEAT = "heartbeat"
    STATUS_UPDATE = "status_update"
    TASK_ANNOUNCEMENT = "task_announcement"          # Phase 8, contract-net
    TASK_BID = "task_bid"                            # Phase 8
    TASK_AWARD = "task_award"                        # Phase 8
    TASK_ACCEPT = "task_accept"                      # Phase 8
    TASK_RELEASE = "task_release"                    # Phase 8
    TASK_COMPLETE = "task_complete"                  # Phase 8
    INTENT_UPDATE = "intent_update"                  # Phases 8-9, shared intent
    TARGET_FOUND = "target_found"
    HELP_REQUEST = "help_request"                    # Phase 9
    ROLE_CHANGE = "role_change"                      # Phase 9
    MISSION_UPDATE = "mission_update"


BROADCAST = ("*",)


def _point(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_number(c) for c in v)


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _flag(v: Any) -> bool:
    return isinstance(v, bool)


def _text_or_none(v: Any) -> bool:
    return v is None or (isinstance(v, str) and bool(v))


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v)


def _version(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _fraction(v: Any) -> bool:
    return _number(v) and 0.0 <= v <= 1.0


KINDS: dict[str, Callable[[Any], bool]] = {
    "point": _point, "number": _number, "flag": _flag, "text_or_none": _text_or_none, "text": _text,
    "version": _version, "fraction": _fraction}

# Field -> kind. Every field is required; text fields may be None (not known).
SCHEMAS: dict[MessageType, dict[str, str]] = {
    # A heartbeat says who is alive, where, and on what: a teammate's record is
    # its latest report, so a bare heartbeat after a status would wipe the task.
    MessageType.HEARTBEAT: {"position": "point", "airborne": "flag", "battery": "number",
                            "task": "text_or_none", "stage": "text_or_none"},
    MessageType.STATUS_UPDATE: {"task": "text_or_none", "stage": "text_or_none", "skill": "text_or_none",
                                "position": "point", "battery": "number", "degraded": "flag"},
    # Phase 8's contract-net (AUV-08, 8.2). A bid carries its terms, so a
    # reader of the log can see why it won; a claim carries its value, so a
    # conflict can be settled by the rules from the claims alone (8.5).
    MessageType.TASK_ANNOUNCEMENT: {"task_id": "text", "version": "version", "why": "text"},
    MessageType.TASK_BID: {"task_id": "text", "version": "version", "value": "number",
                           "d": "number", "b": "number", "l": "number", "c": "number", "r": "number"},
    MessageType.TASK_AWARD: {"task_id": "text", "version": "version", "value": "number"},
    MessageType.TASK_ACCEPT: {"task_id": "text", "version": "version", "holder": "text"},
    MessageType.TASK_RELEASE: {"task_id": "text", "version": "version", "why": "text"},
    MessageType.TASK_COMPLETE: {"task_id": "text", "version": "version"},
}

# Fields that come all together or not at all (Phase 8: a holder's progress).
OPTIONAL_GROUPS: dict[MessageType, dict[str, str]] = {
    MessageType.STATUS_UPDATE: {"task_id": "text", "task_version": "version", "task_progress": "fraction"},
}

# How long a message is current after its timestamp (AUV-10, 10.4: a
# heartbeat short-lived, longer for what changes less often). Phase 10 will
# put these under the network model; until then they are fixed here.
DEFAULT_TTL_S: dict[MessageType, float] = {
    MessageType.HEARTBEAT: 3.0,          # three heartbeats at 1 Hz
    MessageType.STATUS_UPDATE: 10.0,     # a decision's worth: the periodic check is 10 s
    # Phase 8: what a task message says is current for as long as a lease.
    MessageType.TASK_ANNOUNCEMENT: 10.0,
    MessageType.TASK_BID: 10.0,
    MessageType.TASK_AWARD: 10.0,
    MessageType.TASK_ACCEPT: 10.0,
    MessageType.TASK_RELEASE: 10.0,
    MessageType.TASK_COMPLETE: 10.0,
}


def payload_problems(message_type: MessageType, payload: Any) -> list[str]:
    """What is wrong with `payload` for `message_type`; empty if nothing is."""
    schema = SCHEMAS.get(message_type)
    if schema is None:
        return [f"{message_type.value} has no payload schema yet: no phase sends it so far"]
    if not isinstance(payload, dict):
        return [f"payload must be a dict, got {payload!r}"]
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return [f"payload is not plain JSON: {exc}"]
    group = OPTIONAL_GROUPS.get(message_type, {})
    problems = [f"missing {k}" for k in schema if k not in payload]
    problems += [f"unknown field {k}" for k in payload if k not in schema and k not in group]
    problems += [f"{k} is not a {schema[k]}: {payload[k]!r}" for k in schema
                 if k in payload and not KINDS[schema[k]](payload[k])]
    present = [k for k in group if k in payload]
    if present and len(present) != len(group):
        problems.append(f"{', '.join(sorted(group))} come together or not at all; got {', '.join(present)}")
    problems += [f"{k} is not a {group[k]}: {payload[k]!r}" for k in present if not KINDS[group[k]](payload[k])]
    return problems


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    message_type: MessageType
    sender_id: str
    recipient_ids: tuple[str, ...]
    mission_id: str
    timestamp: float
    sequence_number: int
    time_to_live_s: float
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None

    def __post_init__(self) -> None:
        problems = self.problems()
        if problems:
            raise ValueError("not a valid message: " + "; ".join(problems))

    def problems(self) -> list[str]:
        p: list[str] = []
        if not isinstance(self.message_type, MessageType):
            return [f"unknown message type {self.message_type!r}"]
        for name, value in (("message_id", self.message_id), ("sender_id", self.sender_id),
                            ("mission_id", self.mission_id)):
            if not isinstance(value, str) or not value:
                p.append(f"{name} must be a non-empty string")
        if not isinstance(self.recipient_ids, tuple):
            p.append(f"recipient_ids must be a tuple, got {self.recipient_ids!r}")
        elif not self.recipient_ids:
            p.append("no recipients")
        elif self.recipient_ids != BROADCAST:
            if any(not isinstance(r, str) or not r or r == "*" for r in self.recipient_ids):
                p.append(f"recipients must be drone ids, or BROADCAST alone: {self.recipient_ids}")
            if self.sender_id in self.recipient_ids:
                p.append("a drone does not send to itself")
            if len(set(self.recipient_ids)) != len(self.recipient_ids):
                p.append("a recipient is named twice")
        if not _number(self.timestamp):
            p.append(f"timestamp must be a finite number, got {self.timestamp!r}")
        if not isinstance(self.sequence_number, int) or isinstance(self.sequence_number, bool) \
                or self.sequence_number < 1:
            p.append(f"sequence_number must be an integer from 1, got {self.sequence_number!r}")
        if not _number(self.time_to_live_s) or self.time_to_live_s <= 0:
            p.append(f"time_to_live_s must be positive, got {self.time_to_live_s!r}")
        if self.confidence is not None and not (_number(self.confidence) and 0.0 <= self.confidence <= 1.0):
            p.append(f"confidence must be in [0, 1] or None, got {self.confidence!r}")
        p += payload_problems(self.message_type, self.payload)
        return p

    @property
    def expires_at(self) -> float:
        return self.timestamp + self.time_to_live_s

    def expired(self, now: float) -> bool:
        return now >= self.expires_at

    def is_for(self, drone: str) -> bool:
        return drone != self.sender_id and (self.recipient_ids == BROADCAST or drone in self.recipient_ids)

    def as_json(self) -> dict[str, Any]:
        return {"message_id": self.message_id, "message_type": self.message_type.value,
                "sender_id": self.sender_id, "recipient_ids": list(self.recipient_ids),
                "mission_id": self.mission_id, "timestamp": self.timestamp,
                "sequence_number": self.sequence_number, "time_to_live_s": self.time_to_live_s,
                "payload": self.payload, "confidence": self.confidence}

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "AgentMessage":
        return cls(row["message_id"], MessageType(row["message_type"]), row["sender_id"],
                   tuple(row["recipient_ids"]), row["mission_id"], row["timestamp"],
                   row["sequence_number"], row["time_to_live_s"], row["payload"], row["confidence"])

    def size_bytes(self) -> int:
        """The message's size as it would travel: compact JSON, UTF-8."""
        return len(json.dumps(self.as_json(), separators=(",", ":"), sort_keys=True).encode("utf-8"))


def new_message(message_type: MessageType, sender_id: str, recipient_ids: tuple[str, ...], mission_id: str,
                at: float, sequence_number: int, payload: dict[str, Any], ttl_s: float | None = None,
                confidence: float | None = None) -> AgentMessage:
    """A message with its id made from the sender and sequence number, and the type's default TTL."""
    if ttl_s is None:
        if message_type not in DEFAULT_TTL_S:
            raise ValueError(f"{message_type.value} has no default time to live yet; give one")
        ttl_s = DEFAULT_TTL_S[message_type]
    problems = payload_problems(message_type, payload)
    if problems:
        raise ValueError(f"not a valid {message_type.value} payload: " + "; ".join(problems))
    plain = json.loads(json.dumps(payload))                 # the sender keeps its dict; the message its own
    return AgentMessage(f"{sender_id}#{sequence_number}", message_type, sender_id, tuple(recipient_ids),
                        mission_id, at, sequence_number, ttl_s, plain, confidence)


@dataclass(frozen=True)
class Comms:
    """All a drone can do with the network (AUV-07, 7.3): send, and take what has arrived.

    Built like `core.sensing.Sensors`: a drone id and two plain functions,
    closing over the bus that the simulation runs. No attribute leads to the
    bus, its queues, the other drones' mail or what was never delivered, and
    there is no `peek` -- not even for debugging (AUV-07: "resist adding a
    `peek()`"). `send` refuses a message not from this drone; `receive_available`
    returns what has arrived for it, each message its own copy, oldest first.
    """

    drone: str
    send: Callable[[AgentMessage], None]
    receive_available: Callable[[], tuple[AgentMessage, ...]]
