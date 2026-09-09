"""Agent-side estimate of how good the link actually is (Phase 10.5).

An agent must never read `packet_loss_probability` off the network model - that
is the simulator's private setting, and an agent that could see it would be
making decisions on information a real drone has no way to obtain. So the agent
infers link quality from four things it can genuinely observe:

  1. **missing sequence numbers** - every sender numbers its messages, so gaps
     in what arrives are direct evidence of loss;
  2. **heartbeat arrival rate** - how many of the heartbeats we expected in the
     recent past actually turned up;
  3. **information age on arrival** - `now - message.timestamp` when the message
     is read. Note carefully what this is and is not: it is NOT wire latency. It
     is dominated by the agent's own decision cadence, because an agent only
     reads its inbox when it wakes up to decide, which here is tens of seconds
     apart. Measuring true one-way latency would need an echo/ack protocol and a
     synchronised clock. Age-on-arrival is nevertheless the number the agent
     actually needs: it says how stale the contents are, which is what should
     govern whether to trust them;
  4. **recent deliveries** - whether anything at all is getting through.

All four are noisy and none of them can distinguish "the link is bad" from "the
sender is dead" - which is correct, because from inside a single drone those
genuinely look the same. Deciding between them is the health monitor's job
(roles.py), not this one's.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

# how many recent samples to keep per peer
WINDOW = 40


@dataclass
class PeerLinkStats:
    """What we have observed about the link from one peer."""
    vehicle_id: str
    highest_seq: int = 0
    received_count: int = 0
    missing_count: int = 0
    delays: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    arrivals: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    last_seen_seq: set = field(default_factory=set)

    @property
    def observed_loss_rate(self):
        """Fraction of this sender's messages that never arrived.

        Estimated from sequence gaps: if we have seen sequence numbers up to N
        but only received K of them, the rest were lost somewhere.
        """
        expected = self.highest_seq
        if expected <= 0:
            return 0.0
        got = self.received_count
        return max(0.0, min(1.0, (expected - got) / expected))

    @property
    def mean_age_s(self):
        """Mean age of this peer's messages when we read them (not wire latency)."""
        return (sum(self.delays) / len(self.delays)) if self.delays else 0.0

    @property
    def jitter_s(self):
        if len(self.delays) < 2:
            return 0.0
        mean = self.mean_age_s
        var = sum((d - mean) ** 2 for d in self.delays) / len(self.delays)
        return var ** 0.5


class CommsEstimator:
    """Per-agent estimate of communication health, built only from observation."""

    def __init__(self, vehicle_id, heartbeat_interval_s=15.0):
        self.vehicle_id = vehicle_id
        self.heartbeat_interval_s = heartbeat_interval_s
        self.peers: Dict[str, PeerLinkStats] = {}
        self.heartbeats: Deque[float] = deque(maxlen=WINDOW)
        self.last_delivery_s: Optional[float] = None
        self.started_at = 0.0

    # --- observation ---

    def observe(self, message, now):
        """Record one delivered message. The only input this class ever gets."""
        from ..coordination.protocols import MessageType

        sender = message.sender_id
        st = self.peers.get(sender)
        if st is None:
            st = PeerLinkStats(vehicle_id=sender)
            self.peers[sender] = st

        seq = getattr(message, "sequence_number", 0) or 0
        if seq and seq not in st.last_seen_seq:
            st.last_seen_seq.add(seq)
            st.received_count += 1
            st.highest_seq = max(st.highest_seq, seq)

        # one-way delay: the closest thing to an RTT sample we can get without
        # an explicit echo. Negative values are impossible, so clamp.
        delay = max(0.0, now - message.timestamp)
        st.delays.append(delay)
        st.arrivals.append(now)

        self.last_delivery_s = now
        if message.message_type is MessageType.HEARTBEAT:
            self.heartbeats.append(now)

    # --- estimates ---

    def estimated_loss_rate(self):
        """Team-wide loss estimate from sequence gaps across all peers."""
        expected = sum(p.highest_seq for p in self.peers.values())
        got = sum(p.received_count for p in self.peers.values())
        if expected <= 0:
            return 0.0
        return max(0.0, min(1.0, (expected - got) / expected))

    def estimated_message_age_s(self):
        """How old messages are when read. See the note in the module docstring:
        this is staleness, not link latency."""
        delays = [d for p in self.peers.values() for d in p.delays]
        return (sum(delays) / len(delays)) if delays else 0.0

    def estimated_jitter_s(self):
        delays = [d for p in self.peers.values() for d in p.delays]
        if len(delays) < 2:
            return 0.0
        mean = sum(delays) / len(delays)
        return (sum((d - mean) ** 2 for d in delays) / len(delays)) ** 0.5

    def heartbeat_arrival_rate(self, now, peers_expected=None):
        """Fraction of expected heartbeats that actually arrived recently.

        1.0 means everything we expected turned up; 0.0 means silence.
        """
        window = min(now - self.started_at, self.heartbeat_interval_s * 5)
        if window <= 0 or self.heartbeat_interval_s <= 0:
            return 1.0
        n_peers = peers_expected if peers_expected is not None else len(self.peers)
        if n_peers <= 0:
            return 1.0
        expected = (window / self.heartbeat_interval_s) * n_peers
        if expected <= 0:
            return 1.0
        recent = sum(1 for t in self.heartbeats if now - t <= window)
        return max(0.0, min(1.0, recent / expected))

    def silence_s(self, now):
        if self.last_delivery_s is None:
            return max(0.0, now - self.started_at)
        return max(0.0, now - self.last_delivery_s)

    def degraded(self, now, loss_threshold=0.2):
        return (self.estimated_loss_rate() > loss_threshold
                or self.heartbeat_arrival_rate(now) < 0.5)

    # --- for the belief / logs ---

    def apply_to(self, belief):
        """Write the current estimate into the belief's communication section.

        Note these are *estimates*, sitting in the same field the agent would
        use if it could measure them for real - the belief never holds the
        configured values.
        """
        now = belief.now
        c = belief.communication
        c.recent_loss_rate = round(self.estimated_loss_rate(), 4)
        c.estimated_latency_s = round(self.estimated_message_age_s(), 4)
        return c

    def summary(self, now):
        return {
            "estimated_loss_rate": round(self.estimated_loss_rate(), 3),
            "estimated_message_age_s": round(self.estimated_message_age_s(), 3),
            "estimated_jitter_s": round(self.estimated_jitter_s(), 3),
            "heartbeat_arrival_rate": round(self.heartbeat_arrival_rate(now), 3),
            "silence_s": round(self.silence_s(now), 1),
            "per_peer": {
                v: {"loss": round(p.observed_loss_rate, 3),
                    "age_s": round(p.mean_age_s, 3),
                    "received": p.received_count,
                    "highest_seq": p.highest_seq}
                for v, p in sorted(self.peers.items())},
        }
