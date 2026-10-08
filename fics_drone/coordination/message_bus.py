"""Central simulation infrastructure - but agents never hold a MessageBus
directly. Each agent holds an AgentLink exposing exactly two methods,
send() and receive_available(). An agent cannot enumerate peers, read
another agent's inbox, see what is in flight, or inspect what was dropped -
that visibility exists only for the test harness and the log, never for the
agents being tested.
"""

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .network_model import NetworkModel
from .protocols import TTL_BY_TYPE, Message, MessageType


@dataclass
class LogEntry:
    message_id: int
    type: str
    sender: str
    recipient: str
    created_t: float
    delivered: bool
    reason: str  # "delivered" | "blackout" | "expired" | "packet_loss" | "rate_limited" | "partitioned"
    delay_s: float = 0.0  # Phase 10: the drawn latency, only meaningful when delivered


class MessageBus:
    """drop_all=True is the blackout test: every send is logged as dropped
    and no inbox ever receives anything - the strongest possible check that
    team belief updates only via delivered messages, never a back channel.

    Phase 10: an optional NetworkModel degrades delivery realistically instead
    of perfectly - packet loss, a per-sender rate limit, and latency that
    delays when a delivered message actually becomes visible, on top of the
    TTL-based expiry Phase 7 already had."""

    def __init__(self, drop_all: bool = False, network_model: Optional[NetworkModel] = None):
        self.drop_all = drop_all
        self.network_model = network_model
        self._inboxes: Dict[str, List[Tuple[Message, float]]] = {}  # (message, deliver_at)
        self._lock = threading.Lock()
        self._next_id = 0
        self._seq_by_sender: Dict[str, int] = {}
        self.log: List[LogEntry] = []
        self.start_time = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self.start_time

    def register(self, name: str):
        with self._lock:
            self._inboxes.setdefault(name, [])

    def send(self, type_: MessageType, sender: str, payload: dict,
              recipients: Optional[List[str]] = None, confidence: float = 1.0) -> Message:
        with self._lock:
            now = self.now()
            self._next_id += 1
            self._seq_by_sender[sender] = self._seq_by_sender.get(sender, 0) + 1
            msg = Message(id=self._next_id, type=type_, sender=sender, recipients=recipients,
                          created_t=now, ttl_s=TTL_BY_TYPE[type_], payload=payload,
                          confidence=confidence, seq=self._seq_by_sender[sender])
            targets = recipients if recipients is not None else [n for n in self._inboxes if n != sender]

            if self.drop_all:
                for name in targets:
                    self.log.append(LogEntry(msg.id, type_.value, sender, name, msg.created_t,
                                              delivered=False, reason="blackout"))
                return msg

            if self.network_model is not None and self.network_model.check_rate_limit(sender, now):
                for name in targets:
                    self.log.append(LogEntry(msg.id, type_.value, sender, name, msg.created_t,
                                              delivered=False, reason="rate_limited"))
                return msg

            for name in targets:
                if self.network_model is not None:
                    delivered, deliver_at, reason = self.network_model.transmit_to_recipient(sender, name, now)
                else:
                    delivered, deliver_at, reason = True, now, "delivered"
                if not delivered:
                    self.log.append(LogEntry(msg.id, type_.value, sender, name, msg.created_t,
                                              delivered=False, reason=reason))
                    continue
                self._inboxes.setdefault(name, []).append((msg, deliver_at))
                self.log.append(LogEntry(msg.id, type_.value, sender, name, msg.created_t,
                                          delivered=True, reason="delivered", delay_s=deliver_at - now))
            return msg

    def receive_available(self, name: str) -> List[Message]:
        """Pops every message waiting for `name` whose latency delay has
        actually elapsed (deliver_at <= now) and that hasn't expired. A
        not-yet-arrived message stays in the inbox for a later call; an
        expired one is logged as dropped (separately from a blackout or
        packet-loss drop, per FICS's own lesson: a short TTL looks identical
        to link loss unless the two are tracked apart) and never handed to
        the agent."""
        now = self.now()
        with self._lock:
            waiting = self._inboxes.get(name, [])
            ready = [(m, d) for m, d in waiting if d <= now]
            self._inboxes[name] = [(m, d) for m, d in waiting if d > now]
        delivered = []
        for msg, _ in ready:
            if now > msg.expires_at():
                self.log.append(LogEntry(msg.id, msg.type.value, msg.sender, name, msg.created_t,
                                          delivered=False, reason="expired"))
            else:
                delivered.append(msg)
        return delivered


class AgentLink:
    """The only thing an agent ever holds - two methods, nothing else."""

    def __init__(self, bus: MessageBus, name: str):
        self._bus = bus
        self.name = name
        bus.register(name)

    def send(self, type_: MessageType, payload: dict,
              recipients: Optional[List[str]] = None, confidence: float = 1.0):
        self._bus.send(type_, self.name, payload, recipients, confidence)

    def receive_available(self) -> List[Message]:
        return self._bus.receive_available(self.name)
