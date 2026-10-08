"""Phase 10. Phase 7 proved the protocol under perfect communication - this
degrades it honestly and reproducibly.

Scoped down from FICS's own NetworkModel (which also models bandwidth caps,
burst loss, interference zones and asymmetric links): this build's runner is
real-time threaded, not a deterministic simulated-time stepper (team_runner.py
has its own note on why a sim-clock runner isn't built here). Effects that
only mean something against a stepped clock - burst-loss windows timed to
simulation ticks, interference zones tied to a drone's current position -
aren't buildable honestly on top of wall-clock threads without inventing a
second runner. Latency+jitter, packet loss, a per-sender rate limit, and
time-windowed partitions between a specific pair of agents are all meaningful
under real wall-clock time, so those are what's implemented.

NetworkModel owns the one RNG for a run, drawn in a deterministic order
(rate-limit check, then packet-loss roll, then latency draw, per send) so
the same seed means the same drops and the same delays - the whole point of
comparing two runs "under identical degraded conditions."
"""

import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Partition:
    """Blocks messages between exactly two named agents during a wall-clock
    window - simpler than FICS's position-based interference zones, but
    meaningful without needing a stepped clock or drone positions at the bus
    layer."""
    a: str
    b: str
    start_t: float
    end_t: float

    def blocks(self, sender: str, recipient: str, now: float) -> bool:
        if not (self.start_t <= now <= self.end_t):
            return False
        return {sender, recipient} == {self.a, self.b}


@dataclass
class NetworkProfile:
    name: str
    latency_ms_mean: float = 0.0
    latency_ms_jitter: float = 0.0
    packet_loss_probability: float = 0.0
    message_rate_limit: Optional[float] = None  # messages/sec/sender, None = unlimited
    partitions: List[Partition] = field(default_factory=list)


class NetworkModel:
    """Owned by the test harness/MessageBus, never handed to an agent - an
    agent that could read `profile.packet_loss_probability` wouldn't need to
    estimate link quality, which defeats the point of Phase 10."""

    def __init__(self, profile: NetworkProfile, seed: int = 0):
        self.profile = profile
        self._rng = random.Random(seed)
        self._sent_times = {}  # sender -> recent send timestamps (sliding 1s window)

    def check_rate_limit(self, sender: str, now: float) -> bool:
        """One check per outgoing send() call, not per recipient - the limit
        is on how many distinct messages a sender puts on the wire per
        second, regardless of fan-out."""
        limit = self.profile.message_rate_limit
        if limit is None:
            return False
        window = self._sent_times.setdefault(sender, [])
        window[:] = [t for t in window if now - t < 1.0]
        if len(window) >= limit:
            return True
        window.append(now)
        return False

    def transmit_to_recipient(self, sender: str, recipient: str, now: float) -> Tuple[bool, float, str]:
        """Per-(sender, recipient) delivery decision: partition, then packet
        loss, then a latency draw for when it actually arrives. Returns
        (delivered, deliver_at, reason)."""
        for p in self.profile.partitions:
            if p.blocks(sender, recipient, now):
                return False, now, "partitioned"
        if self._rng.random() < self.profile.packet_loss_probability:
            return False, now, "packet_loss"
        latency_s = max(0.0, self._rng.gauss(self.profile.latency_ms_mean,
                                              self.profile.latency_ms_jitter)) / 1000.0
        return True, now + latency_s, "delivered"
