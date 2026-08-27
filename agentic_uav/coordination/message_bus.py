"""The message bus, and the two-method handle agents use to reach it (7.3 / 7.4).

The bus itself is central: it is simulation infrastructure, and it keeps the
delivery queue, the clock-ordered schedule and the full message log. That is
fine. What is *not* fine is an agent reaching into any of that - a decentralized
result means nothing if an agent could read the global queue, another agent's
memory, or messages that were never delivered to it.

So agents never hold a MessageBus. They hold an `AgentLink`, which exposes
exactly two operations:

    send(message)
    receive_available()

`receive_available()` returns only messages addressed to that agent whose
delivery time has arrived and which have not expired. Everything else - other
agents' mail, in-flight messages, dropped messages, the schedule - is
unreachable through the link. tests/test_messaging.py checks this behaviourally.

Phase 7 runs with perfect communication (`latency_s=0`, `loss_rate=0`). The hooks
for degradation are here so the later phase only has to change parameters, not
the protocol.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .protocols import AgentMessage, MessageType


@dataclass
class MessageLogEntry:
    """Everything Phase 7.4 asks us to record about one delivery attempt."""
    message_id: str
    message_type: str
    sender_id: str
    recipient_id: str
    created_at: float
    scheduled_delivery_at: float
    actual_delivery_at: Optional[float] = None
    delivered: bool = False
    dropped: bool = False
    drop_reason: str = ""
    size_bytes: int = 0
    expires_at: float = float("inf")
    influenced_decision: bool = False       # set when an agent acts on it

    @property
    def latency_s(self):
        if self.actual_delivery_at is None:
            return None
        return self.actual_delivery_at - self.created_at

    def to_dict(self):
        return {
            "message_id": self.message_id, "type": self.message_type,
            "from": self.sender_id, "to": self.recipient_id,
            "created_at": round(self.created_at, 2),
            "scheduled_delivery_at": round(self.scheduled_delivery_at, 2),
            "actual_delivery_at": (None if self.actual_delivery_at is None
                                   else round(self.actual_delivery_at, 2)),
            "delivered": self.delivered, "dropped": self.dropped,
            "drop_reason": self.drop_reason, "size_bytes": self.size_bytes,
            "expires_at": (None if self.expires_at == float("inf")
                           else round(self.expires_at, 2)),
            "influenced_decision": self.influenced_decision,
        }


class MessageLog:
    def __init__(self):
        self.entries: List[MessageLogEntry] = []
        self._by_id: Dict[str, List[MessageLogEntry]] = {}

    def add(self, entry):
        self.entries.append(entry)
        self._by_id.setdefault(entry.message_id, []).append(entry)

    def mark_influential(self, message_id, recipient_id=None):
        for e in self._by_id.get(message_id, []):
            if recipient_id is None or e.recipient_id == recipient_id:
                e.influenced_decision = True

    # --- summaries for experiments ---

    def stats(self):
        """Delivery statistics.

        `dropped_link` and `dropped_expired` are kept apart on purpose. Under
        perfect communication `dropped_link` must be zero - anything lost was
        lost because it aged out before the recipient next checked its inbox,
        which is a property of the agent's decision cadence, not of the link.

        Likewise `mean_delivery_delay_s` is wall-clock delay including pickup, so
        with zero link latency it still reports the gap between a message being
        sent and the recipient next waking up to read it.
        """
        delivered = [e for e in self.entries if e.delivered]
        link_drops = [e for e in self.entries if e.drop_reason == "link_loss"]
        expired = [e for e in self.entries
                   if e.drop_reason == "expired_before_delivery"]
        delays = [e.latency_s for e in delivered if e.latency_s is not None]
        return {
            "sent": len(self.entries),
            "delivered": len(delivered),
            "dropped_link": len(link_drops),
            "dropped_expired": len(expired),
            "delivery_rate": (len(delivered) / len(self.entries)
                              if self.entries else 0.0),
            "mean_delivery_delay_s": (sum(delays) / len(delays)) if delays else 0.0,
            "bytes": sum(e.size_bytes for e in self.entries),
            "influential": sum(1 for e in self.entries if e.influenced_decision),
        }

    def by_type(self):
        out = {}
        for e in self.entries:
            d = out.setdefault(e.message_type, {"sent": 0, "delivered": 0})
            d["sent"] += 1
            if e.delivered:
                d["delivered"] += 1
        return out

    def to_json(self, path=None, indent=2):
        import json
        text = json.dumps([e.to_dict() for e in self.entries],
                          indent=indent, default=str)
        if path:
            with open(path, "w") as f:
                f.write(text)
        return text

    def format_text(self, limit=40):
        lines = []
        for e in self.entries[:limit]:
            when = ("dropped" if e.dropped
                    else f"t={e.actual_delivery_at:.1f}s"
                    if e.actual_delivery_at is not None else "in flight")
            flag = " *" if e.influenced_decision else ""
            lines.append(f"  {e.message_id} {e.message_type:<16} "
                         f"{e.sender_id}->{e.recipient_id:<8} "
                         f"sent t={e.created_at:.1f}s  {when}{flag}")
        if len(self.entries) > limit:
            lines.append(f"  ... {len(self.entries) - limit} more")
        return "\n".join(lines)


class MessageBus:
    """Central delivery infrastructure. Simulation-side only - never given to an agent."""

    def __init__(self, latency_s=0.0, loss_rate=0.0, rng=None, log=None):
        self.latency_s = latency_s          # 0 = perfect comms (Phase 7)
        self.loss_rate = loss_rate
        self._rng = rng
        self.log = log or MessageLog()
        self._pending: List[tuple] = []     # (deliver_at, recipient, message)
        self._inboxes: Dict[str, List[AgentMessage]] = {}
        self._registered: List[str] = []
        # Agents run in threads when flying in AirSim, so every mutation of the
        # queues is guarded. Deterministic mock runs are single-threaded and
        # unaffected.
        self._lock = threading.RLock()

    # --- setup ---

    def register(self, vehicle_id) -> "AgentLink":
        with self._lock:
            if vehicle_id not in self._registered:
                self._registered.append(vehicle_id)
                self._inboxes[vehicle_id] = []
        return AgentLink(self, vehicle_id)

    # --- called through AgentLink only ---

    def _send(self, message: AgentMessage):
      with self._lock:
        recipients = [v for v in self._registered if message.addressed_to(v)]
        for r in recipients:
            entry = MessageLogEntry(
                message_id=message.message_id,
                message_type=message.message_type.value,
                sender_id=message.sender_id, recipient_id=r,
                created_at=message.timestamp,
                scheduled_delivery_at=message.timestamp + self.latency_s,
                size_bytes=message.size_bytes(),
                expires_at=message.expires_at)

            if self._drop():
                entry.dropped = True
                entry.drop_reason = "link_loss"
                self.log.add(entry)
                continue

            self.log.add(entry)
            self._pending.append((entry.scheduled_delivery_at, r, message, entry))

    def _drop(self):
        if self.loss_rate <= 0:
            return False
        rand = self._rng.random() if self._rng else 0.0
        return rand < self.loss_rate

    def _receive(self, vehicle_id, now) -> List[AgentMessage]:
      """Hand over the messages that have arrived for this agent by `now`."""
      with self._lock:
        self._deliver_due(now)
        inbox = self._inboxes.get(vehicle_id, [])
        ready, keep = [], []
        for m in inbox:
            if m.expired(now):
                continue                    # silently aged out
            ready.append(m)
        self._inboxes[vehicle_id] = keep
        return ready

    def _deliver_due(self, now):
        still_pending = []
        for (at, recipient, message, entry) in self._pending:
            if at <= now:
                if message.expired(now):
                    entry.dropped = True
                    entry.drop_reason = "expired_before_delivery"
                    continue
                self._inboxes.setdefault(recipient, []).append(message)
                entry.delivered = True
                entry.actual_delivery_at = now
            else:
                still_pending.append((at, recipient, message, entry))
        self._pending = still_pending

    # --- simulation-side introspection (evaluator only, never an agent) ---

    def in_flight_count(self):
        return len(self._pending)

    def stats(self):
        return self.log.stats()


class AgentLink:
    """The *only* interface an agent has to the outside world.

    Two methods, by design. An agent holding one of these cannot enumerate peers,
    read another inbox, see what is still in flight, or inspect what was dropped.
    """

    __slots__ = ("_bus", "_vehicle_id", "_seq")

    def __init__(self, bus: MessageBus, vehicle_id: str):
        self._bus = bus
        self._vehicle_id = vehicle_id
        self._seq = 0

    def send(self, message_type, payload=None, recipients=None, now=0.0,
             mission_id="", ttl_s=30.0, confidence=None) -> AgentMessage:
        self._seq += 1
        msg = AgentMessage(
            message_type=message_type, sender_id=self._vehicle_id,
            recipient_ids=list(recipients) if recipients else ["*"],
            mission_id=mission_id, timestamp=now, sequence_number=self._seq,
            time_to_live_s=ttl_s, payload=payload or {}, confidence=confidence)
        self._bus._send(msg)
        return msg

    def receive_available(self, now=0.0) -> List[AgentMessage]:
        return self._bus._receive(self._vehicle_id, now)
