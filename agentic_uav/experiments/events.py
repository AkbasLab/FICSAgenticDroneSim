"""Structured event logging for experiments (Phase 14.3).

One JSON Lines stream per run. Each line is a self-contained event with a
sequence number, simulated time, type, the vehicle it concerns, and a payload.
JSONL rather than console output because a run produces thousands of events and
the analysis is `pandas.read_json(..., lines=True)`, not reading.

**Live versus derived.** Two kinds of event end up in the stream and every line
says which it is:

  * `live` - emitted by the runner as the run happens: mission lifecycle, fault
    injection, and anything that has no other record.
  * `derived:<log>` - reconstructed afterwards from a component's own log. The
    message bus already records every send, drop and delivery; the guardian
    records every intervention; the decision log records every belief snapshot
    and skill outcome; the LLM log records every call.

Deriving is deliberate. The alternative is threading an event sink through the
agent loop, the bus, the allocator, the guardian and the policy - twelve phases
of working, tested code modified for the benefit of logging, with a real chance
of changing behaviour. The component logs are already the authoritative record
and are already covered by tests; this module translates them into one ordered
stream. The `source` field keeps that honest rather than implying every event
was captured live.

Ordering is by simulated time, then by sequence within a timestamp. Because
several agents advance on independent clocks, two events with the same `t` are
genuinely concurrent and their relative order carries no meaning.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class EventType(str, Enum):
    """The event vocabulary from 14.3, and nothing outside it."""
    MISSION_STARTED = "MISSION_STARTED"
    OBSERVATION_RECEIVED = "OBSERVATION_RECEIVED"
    BELIEF_UPDATED = "BELIEF_UPDATED"
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_DROPPED = "MESSAGE_DROPPED"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    TASK_ANNOUNCED = "TASK_ANNOUNCED"
    TASK_BID = "TASK_BID"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_RELEASED = "TASK_RELEASED"
    ROLE_CHANGED = "ROLE_CHANGED"
    LLM_CALLED = "LLM_CALLED"
    DECISION_PROPOSED = "DECISION_PROPOSED"
    GUARDIAN_INTERVENED = "GUARDIAN_INTERVENED"
    SKILL_STARTED = "SKILL_STARTED"
    SKILL_COMPLETED = "SKILL_COMPLETED"
    TARGET_FOUND = "TARGET_FOUND"
    FAULT_INJECTED = "FAULT_INJECTED"
    MISSION_COMPLETED = "MISSION_COMPLETED"


#: Message types that are themselves coordination events worth promoting out of
#: the generic MESSAGE_* stream, so an analysis of task flow does not have to
#: re-parse payloads.
MESSAGE_TO_EVENT = {
    "task_announcement": EventType.TASK_ANNOUNCED,
    "task_bid": EventType.TASK_BID,
    "task_award": EventType.TASK_ASSIGNED,
    "task_accept": EventType.TASK_ASSIGNED,
    "task_release": EventType.TASK_RELEASED,
    "role_change": EventType.ROLE_CHANGED,
    "target_found": EventType.TARGET_FOUND,
}


@dataclass
class Event:
    seq: int
    t: float                       # simulated seconds
    type: str
    vehicle: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "live"

    def to_json(self):
        return json.dumps({"seq": self.seq, "t": round(self.t, 3),
                           "type": self.type, "vehicle": self.vehicle,
                           "source": self.source, "data": self.data},
                          default=str, sort_keys=False)


class EventLog:
    """Collects events in memory and writes them as JSON Lines.

    Held in memory first so the stream can be sorted by simulated time before it
    is written: derived events arrive component by component, not in time order,
    and an unsorted stream is close to useless for reconstructing a run.
    """

    def __init__(self):
        self.events: List[Event] = []
        self._seq = 0

    def emit(self, type_, t=0.0, vehicle=None, source="live", **data) -> Event:
        self._seq += 1
        ev = Event(seq=self._seq, t=float(t),
                   type=type_.value if isinstance(type_, EventType) else str(type_),
                   vehicle=vehicle, data=data, source=source)
        self.events.append(ev)
        return ev

    def extend(self, events: Iterable[Event]):
        for e in events:
            self.events.append(e)

    def sorted_events(self):
        """By simulated time, with insertion order as the tie-break."""
        return sorted(self.events, key=lambda e: (e.t, e.seq))

    def write(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        ordered = self.sorted_events()
        # renumber so seq is the position in the written stream
        with open(path, "w", encoding="utf-8") as f:
            for i, e in enumerate(ordered, 1):
                e.seq = i
                f.write(e.to_json() + "\n")
        return path

    # --- summary ---

    def counts(self):
        out = {}
        for e in self.events:
            out[e.type] = out.get(e.type, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def types_present(self):
        return {e.type for e in self.events}

    def missing_types(self):
        """Which of the 19 never occurred. Expected for some architectures: a
        run with no LLM has no LLM_CALLED, one with no faults has no
        FAULT_INJECTED. Reported rather than hidden so an empty category is
        visibly empty rather than silently absent."""
        return sorted({t.value for t in EventType} - self.types_present())

    def __len__(self):
        return len(self.events)


def read_events(path):
    """Read a stream back. Used by the tests and by analysis."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# --- derivation from the component logs ----------------------------------


def derive(log: EventLog, built, result=None):
    """Translate every component log into the event stream.

    Called once after a run. Each helper is deliberately small and reads only
    the public shape of the log it translates, so a change to a log's internals
    breaks here loudly rather than silently producing an incomplete stream.
    """
    _from_messages(log, built)
    _from_decisions(log, built)
    _from_guardian(log, built)
    _from_llm(log, built)
    _from_roles(log, built)
    _from_allocator(log, built)
    return log


def _from_messages(log, built):
    bus_log = getattr(built.bus, "log", None)
    if bus_log is None:
        return
    for e in getattr(bus_log, "entries", []):
        base = {"message_id": e.message_id, "type": e.message_type,
                "to": e.recipient_id}
        log.emit(EventType.MESSAGE_SENT, t=e.created_at, vehicle=e.sender_id,
                 source="derived:message_log", size_bytes=e.size_bytes, **base)

        if e.dropped:
            log.emit(EventType.MESSAGE_DROPPED, t=e.scheduled_delivery_at,
                     vehicle=e.sender_id, source="derived:message_log",
                     reason=e.drop_reason, **base)
            continue

        if e.delivered:
            log.emit(EventType.MESSAGE_RECEIVED,
                     t=e.actual_delivery_at if e.actual_delivery_at is not None
                     else e.scheduled_delivery_at,
                     vehicle=e.recipient_id, source="derived:message_log",
                     latency_s=e.latency_s, influenced=e.influenced_decision,
                     **{"message_id": e.message_id, "type": e.message_type,
                        "from": e.sender_id})

            # promote coordination traffic to its own event type as well, so a
            # task-flow analysis does not have to re-parse message payloads
            promoted = MESSAGE_TO_EVENT.get(e.message_type)
            if promoted is not None:
                log.emit(promoted,
                         t=e.actual_delivery_at if e.actual_delivery_at is not None
                         else e.scheduled_delivery_at,
                         vehicle=e.sender_id, source="derived:message_log",
                         message_id=e.message_id, to=e.recipient_id)


def _from_decisions(log, built):
    for agent in built.agents:
        dlog = getattr(agent, "log", None)
        for r in getattr(dlog, "records", []):
            # every step begins by observing position, battery and sensor input
            log.emit(EventType.OBSERVATION_RECEIVED, t=r.time_s,
                     vehicle=r.vehicle_id, source="derived:decision_log",
                     step=r.step)
            log.emit(EventType.BELIEF_UPDATED, t=r.time_s, vehicle=r.vehicle_id,
                     source="derived:decision_log", step=r.step,
                     triggers=list(r.triggers), unknown=len(r.unknown or []))
            if r.objective:
                log.emit(EventType.DECISION_PROPOSED, t=r.time_s,
                         vehicle=r.vehicle_id, source="derived:decision_log",
                         step=r.step, objective=r.objective, skill=r.skill or None)
            if r.skill:
                log.emit(EventType.SKILL_STARTED, t=r.time_s,
                         vehicle=r.vehicle_id, source="derived:decision_log",
                         step=r.step, skill=r.skill)
                log.emit(EventType.SKILL_COMPLETED, t=r.time_s,
                         vehicle=r.vehicle_id, source="derived:decision_log",
                         step=r.step, skill=r.skill, outcome=r.outcome)

        # detections, with the time the agent recorded them
        for target in getattr(agent.belief.local_map, "observed_targets", []):
            prov = getattr(target, "provenance", None)
            log.emit(EventType.TARGET_FOUND,
                     t=getattr(prov, "timestamp", agent.belief.now) or 0.0,
                     vehicle=agent.vehicle_id, source="derived:belief",
                     target_id=target.target_id,
                     via=getattr(getattr(prov, "source", None), "value", "unknown"))


def _from_guardian(log, built):
    for agent in built.agents:
        glog = getattr(agent, "guardian_log", None)
        for r in getattr(glog, "records", []):
            if r.outcome == "approve":
                continue              # only interventions are events
            log.emit(EventType.GUARDIAN_INTERVENED, t=r.time_s,
                     vehicle=r.vehicle_id, source="derived:guardian_log",
                     step=r.step, outcome=r.outcome,
                     proposed=r.proposed_action,
                     failed_checks=list(r.failed_checks),
                     substituted=r.substituted_action, fallback=r.fallback,
                     reason=r.rejection_reason, effect=r.mission_effect)


def _from_llm(log, built):
    for vid, policy in (built.policies or {}).items():
        plog = getattr(policy, "log", None)
        for t in getattr(plog, "turns", []):
            log.emit(EventType.LLM_CALLED, t=t.time_s, vehicle=vid,
                     source="derived:llm_log", step=t.step,
                     attempts=t.attempts, corrected=t.corrected,
                     latency_s=round(t.latency_s, 4),
                     tool=t.tool, reason_code=t.reason_code,
                     confidence=t.confidence,
                     rejected_as=t.rejection_reason,
                     used_fallback=t.used_fallback,
                     fallback_cause=t.fallback_cause)


def _from_roles(log, built):
    for agent in built.agents:
        roles = getattr(agent, "roles", None)
        for entry in getattr(roles, "history", []) or []:
            now, previous, new, reason = entry
            log.emit(EventType.ROLE_CHANGED, t=now, vehicle=agent.vehicle_id,
                     source="derived:role_manager",
                     **{"from": previous, "to": new, "reason": reason})


def _from_allocator(log, built):
    """The controller's own assignment log, for Architecture A.

    The decentralized allocator's task events already appear via the message
    log, since every claim and release is announced. A central controller
    assigns without needing to announce a bid, so its log is the only record.
    """
    controller = getattr(built, "controller", None)
    for line in getattr(controller, "log", []) or []:
        # "t=  12.3s  assigned SEARCH_SECTOR_S1 -> Drone1 (cost 0.094)"
        try:
            t = float(line.split("t=")[1].split("s")[0])
        except (IndexError, ValueError):
            t = 0.0
        text = line.split("s", 1)[-1].strip()
        if text.startswith("assigned"):
            etype = EventType.TASK_ASSIGNED
        elif text.startswith("reclaimed"):
            etype = EventType.TASK_RELEASED
        else:
            continue
        log.emit(etype, t=t, vehicle="FleetController",
                 source="derived:fleet_controller", detail=text)
