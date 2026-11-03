"""The message bus: simulation infrastructure that carries agents' messages (AUV-07, 7.3).

    bus = MessageBus(["Drone1", "Drone2"], clock, positions, range_m=100.0)
    comms = bus.comms("Drone1")              # hand only this to the agent
    comms.send(message)                      # Drone1's message, to whom it names
    comms.receive_available()                # what has arrived for Drone1, oldest first
    bus.deliveries()                         # the record, for the experiment -- never for an agent

AUV-07, 7.3: "The message bus may be implemented centrally as simulation
infrastructure, but agents interact with it only through send(message) and
receive_available()." This is that bus. It is central and it can see
everything -- where every drone is, every queue -- because deciding delivery
needs it. What it hands an agent is `core.messages.Comms`: a drone id and two
plain functions. No attribute of it leads back here, there is no `peek`, and
the boundary checks hold agent code to that.

PERFECT COMMUNICATION, PHASE 7's (plan, recommendation 3): no loss and no
delay, over a DIRECT radio link no longer than `range_m` in 3D -- Phase 4's
hard edge, the rule the evaluator uses for the base link -- judged at the
instant the message is sent. A message sent in range is waiting for its
recipient at once, so it is read at the recipient's next tick; one sent out
of range is never delivered, and the record says why. `range_m=None` is
unlimited range, for protocol tests. Relaying a message through other drones,
latency, loss and partitions are Phase 10's network model.

A FIXED DELAY, `delay_s`, below an agent's tick. With none, a message sent
at the instant a teammate's thread reads its inbox would arrive or not by
which thread ran first, and team beliefs would differ from run to run. A
delay shorter than the tick (agents use 0.1 s against a 0.5 s tick) gives
the same "read at the recipient's next tick" every time. It is a modelling
choice for determinism, not a claim about a radio; zero is kept for the
bus's own protocol tests.

A message is never delivered after it expires: one still waiting when its
lifetime ends is dropped as expired when its recipient next looks.

EACH RECIPIENT GETS ITS OWN COPY, rebuilt from the message's JSON, so no two
agents ever hold the same mutable payload -- a channel no message went
through. A broadcast is one delivery per drone on the roster but the sender.

THE RECORD. Every delivery -- one message to one recipient -- is kept: when
sent, when scheduled, when delivered, or why not (`out_of_range`,
`expired`), and `pending` for what was still waiting when asked. It is the
experiment's, for the message log of step 3; nothing an agent holds can reach
it. The bus is thread-safe: agents send and receive from their own threads.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from typing import Callable

from ..core.clock import Clock
from ..core.messages import BROADCAST, AgentMessage, Comms

Point = tuple[float, float, float]           # x, y, altitude, in the mission frame

DELIVERED, PENDING, OUT_OF_RANGE, EXPIRED = "delivered", "pending", "out_of_range", "expired"


@dataclass
class Delivery:
    """One message, to one recipient: what became of it."""

    message: AgentMessage
    recipient: str
    sent_at: float
    scheduled_at: float | None              # when it could first be read; None if never sendable
    status: str
    delivered_at: float | None = None
    distance_m: float | None = None          # sender to recipient, at sending


class MessageBus:
    def __init__(self, drones: list[str] | tuple[str, ...], clock: Clock, positions: Callable[[str], Point],
                 range_m: float | None, mission_id: str | None = None, delay_s: float = 0.0) -> None:
        if len(set(drones)) != len(drones) or not drones:
            raise ValueError(f"the roster must name each drone once: {drones}")
        if range_m is not None and not (range_m > 0 and math.isfinite(range_m)):
            raise ValueError(f"range_m must be positive, or None for unlimited: {range_m}")
        if not (delay_s >= 0 and math.isfinite(delay_s)):
            raise ValueError(f"delay_s must be zero or more: {delay_s}")
        self.delay_s = delay_s
        self.drones = tuple(drones)
        self.clock = clock
        self.positions = positions
        self.range_m = range_m
        self.mission_id = mission_id
        self._lock = threading.Lock()
        self._inbox: dict[str, list[Delivery]] = {d: [] for d in self.drones}
        self._record: list[Delivery] = []

    # ------------------------------------------------------- what an agent gets

    def comms(self, drone: str) -> Comms:
        """The agent's handle: `send` and `receive_available`, and nothing that leads here."""
        if drone not in self.drones:
            raise ValueError(f"{drone} is not on the bus's roster")
        bus = self

        def send(message: AgentMessage) -> None:
            bus.send(drone, message)

        def receive_available() -> tuple[AgentMessage, ...]:
            return bus.receive_available(drone)

        return Comms(drone, send, receive_available)

    # ----------------------------------------------------------- the network

    def send(self, drone: str, message: AgentMessage) -> None:
        if not isinstance(message, AgentMessage):
            raise TypeError(f"not an AgentMessage: {message!r}")
        if message.sender_id != drone:
            raise ValueError(f"{drone} cannot send a message from {message.sender_id}")
        if self.mission_id is not None and message.mission_id != self.mission_id:
            raise ValueError(f"message for mission {message.mission_id}, the bus carries {self.mission_id}")
        recipients = [d for d in self.drones if message.is_for(d)]
        unknown = [r for r in message.recipient_ids if r not in self.drones] if message.recipient_ids != BROADCAST else []
        if unknown:
            raise ValueError(f"not on the bus's roster: {unknown}")
        now = self.clock.now()
        here = self.positions(drone)
        with self._lock:
            for r in recipients:
                d = math.dist(here, self.positions(r))
                if self.range_m is None or d <= self.range_m:
                    delivery = Delivery(self._copy(message), r, now, now + self.delay_s, PENDING, distance_m=d)
                    self._inbox[r].append(delivery)
                else:
                    delivery = Delivery(message, r, now, None, OUT_OF_RANGE, distance_m=d)
                self._record.append(delivery)

    def receive_available(self, drone: str) -> tuple[AgentMessage, ...]:
        now = self.clock.now()
        with self._lock:
            ready = [d for d in self._inbox[drone] if d.scheduled_at <= now]
            self._inbox[drone] = [d for d in self._inbox[drone] if d.scheduled_at > now]
            out = []
            for d in ready:
                if d.message.expired(now):
                    d.status = EXPIRED
                else:
                    d.status, d.delivered_at = DELIVERED, now
                    out.append(d.message)
        return tuple(out)

    # -------------------------------------------------------- the experiment's

    def deliveries(self) -> tuple[Delivery, ...]:
        """Every delivery so far, in sending order -- for the record, never for an agent."""
        with self._lock:
            return tuple(self._record)

    @staticmethod
    def _copy(message: AgentMessage) -> AgentMessage:
        """The recipient's own copy: rebuilt from JSON, sharing nothing with the sender's."""
        return AgentMessage.from_json(json.loads(json.dumps(message.as_json())))
