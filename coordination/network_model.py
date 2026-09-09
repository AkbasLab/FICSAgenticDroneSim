"""Configurable, seeded communication degradation model (Phase 10.1-10.3).

Phase 7 built the protocol under perfect communication. This is where it gets
tested honestly: latency, jitter, packet loss, rate limits, bandwidth, range,
burst loss, partitions, interference zones and asymmetric links.

Three design commitments:

*Seeded and reproducible.* Every random decision comes from one seeded RNG, and
draws happen in a deterministic order because the experiment runner is
single-threaded and stepped in simulated-time order. Same seed, same run - the
same messages are lost, the same latencies are drawn. Without that, comparing two
architectures under "the same" degraded conditions would be meaningless.

*Simulation-side only.* The model lives with the bus, never with an agent. An
agent cannot read `packet_loss_probability`; it has to estimate what the link is
doing from what it observes (see comms_estimator.py). That distinction is the
whole point of 10.5.

*Parameters, not claims.* The numbers in the shipped profiles are experimental
settings for comparing architectures. They are not a model of any particular
radio, and shouldn't be described as one.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Partition:
    """A window during which two groups of vehicles cannot reach each other."""
    group_a: List[str]
    group_b: List[str]
    start_s: float = 0.0
    end_s: float = float("inf")
    # which side (if either) keeps contact with the base station
    base_side: Optional[str] = "a"      # "a" | "b" | None (neither)

    def active(self, now):
        return self.start_s <= now < self.end_s

    def blocks(self, sender, recipient, now):
        if not self.active(now):
            return False
        a, b = set(self.group_a), set(self.group_b)
        return ((sender in a and recipient in b)
                or (sender in b and recipient in a))

    def side_of(self, vehicle_id):
        if vehicle_id in set(self.group_a):
            return "a"
        if vehicle_id in set(self.group_b):
            return "b"
        return None


@dataclass
class InterferenceZone:
    """A region where links to/from anyone inside are degraded."""
    zone_id: str
    centre: Tuple[float, float]
    radius_m: float
    extra_loss: float = 0.3          # added to packet loss probability
    latency_multiplier: float = 2.0

    def contains(self, position):
        if position is None:
            return False
        dx = position.x - self.centre[0]
        dy = position.y - self.centre[1]
        return math.hypot(dx, dy) <= self.radius_m


@dataclass
class NetworkProfile:
    """Everything that defines a communication condition (10.1)."""
    name: str = "nominal"

    latency_ms_mean: float = 0.0
    latency_ms_jitter: float = 0.0        # std-dev of a clamped normal draw
    packet_loss_probability: float = 0.0
    message_rate_limit: Optional[float] = None    # messages/sec/sender
    bandwidth_bytes_per_second: Optional[float] = None
    communication_range_m: Optional[float] = None  # None = unlimited

    # later additions (10.1)
    burst_loss_probability: float = 0.0   # chance of entering a loss burst
    burst_length_s: float = 0.0           # how long a burst lasts
    partitions: List[Partition] = field(default_factory=list)
    interference_zones: List[InterferenceZone] = field(default_factory=list)
    asymmetric_links: Dict[str, float] = field(default_factory=dict)
    # asymmetric_links maps "A->B" to an extra loss probability on that direction
    # only, so a link can be good one way and poor the other.

    def describe(self):
        bits = [f"latency {self.latency_ms_mean:.0f}±{self.latency_ms_jitter:.0f}ms",
                f"loss {self.packet_loss_probability:.0%}"]
        if self.message_rate_limit:
            bits.append(f"rate {self.message_rate_limit:.1f}/s")
        if self.bandwidth_bytes_per_second:
            bits.append(f"bw {self.bandwidth_bytes_per_second:.0f}B/s")
        if self.communication_range_m:
            bits.append(f"range {self.communication_range_m:.0f}m")
        if self.partitions:
            bits.append(f"{len(self.partitions)} partition(s)")
        if self.interference_zones:
            bits.append(f"{len(self.interference_zones)} interference zone(s)")
        if self.burst_loss_probability:
            bits.append(f"burst {self.burst_loss_probability:.0%}")
        return f"{self.name}: " + ", ".join(bits)


@dataclass
class Verdict:
    """What the network decided to do with one (message, recipient) pair."""
    delivered: bool
    delay_s: float = 0.0
    reason: str = ""          # why it was dropped, if it was


class NetworkModel:
    """Decides delivery, delay and loss. Simulation infrastructure only.

    `position_of` is an optional callable (vehicle_id -> Position3D) supplied by
    the simulator so range and interference can be evaluated. Agents never touch
    this object.
    """

    def __init__(self, profile: NetworkProfile = None, seed: int = 0,
                 position_of=None):
        self.profile = profile or NetworkProfile()
        self.seed = seed
        self.rng = random.Random(seed)
        self.position_of = position_of

        # rate limiting / bandwidth accounting, per sender
        self._sent_times: Dict[str, List[float]] = {}
        self._bytes_window: Dict[str, List[Tuple[float, int]]] = {}
        # burst-loss state, per directed link
        self._burst_until: Dict[str, float] = {}

        self.dropped_by_reason: Dict[str, int] = {}

    # --- the decision ---

    def evaluate(self, message, sender, recipient, now) -> Verdict:
        p = self.profile

        # 1. hard blocks first - these are not random, so they cost no RNG draws
        if p.communication_range_m is not None and not self._in_range(sender, recipient):
            return self._drop("out_of_range")

        for part in p.partitions:
            if part.blocks(sender, recipient, now):
                return self._drop("partitioned")

        if not self._within_rate_limit(sender, now):
            return self._drop("rate_limited")

        if not self._within_bandwidth(sender, message, now):
            return self._drop("bandwidth")

        # 2. probabilistic loss
        loss = p.packet_loss_probability
        loss += p.asymmetric_links.get(f"{sender}->{recipient}", 0.0)
        loss += self._interference_loss(sender, recipient)

        link = f"{sender}->{recipient}"
        if self._in_burst(link, now):
            return self._drop("burst_loss")
        if p.burst_loss_probability > 0 and self.rng.random() < p.burst_loss_probability:
            self._burst_until[link] = now + p.burst_length_s
            return self._drop("burst_loss")

        if loss > 0 and self.rng.random() < min(loss, 1.0):
            return self._drop("packet_loss")

        # 3. latency
        return Verdict(delivered=True, delay_s=self._draw_latency(sender, recipient))

    # --- components ---

    def _draw_latency(self, sender, recipient):
        p = self.profile
        if p.latency_ms_mean <= 0 and p.latency_ms_jitter <= 0:
            return 0.0
        ms = p.latency_ms_mean
        if p.latency_ms_jitter > 0:
            ms = self.rng.gauss(p.latency_ms_mean, p.latency_ms_jitter)
        ms = max(0.0, ms)                       # latency cannot be negative
        ms *= self._interference_latency_multiplier(sender, recipient)
        return ms / 1000.0

    def _in_range(self, sender, recipient):
        if self.position_of is None:
            return True
        a, b = self.position_of(sender), self.position_of(recipient)
        if a is None or b is None:
            return True                          # unknown position: don't block
        return a.horizontal_distance_to(b) <= self.profile.communication_range_m

    def _interference_loss(self, sender, recipient):
        if not self.profile.interference_zones or self.position_of is None:
            return 0.0
        extra = 0.0
        for zone in self.profile.interference_zones:
            for vid in (sender, recipient):
                if zone.contains(self.position_of(vid)):
                    extra += zone.extra_loss
                    break                        # count each zone once per link
        return extra

    def _interference_latency_multiplier(self, sender, recipient):
        if not self.profile.interference_zones or self.position_of is None:
            return 1.0
        mult = 1.0
        for zone in self.profile.interference_zones:
            for vid in (sender, recipient):
                if zone.contains(self.position_of(vid)):
                    mult *= zone.latency_multiplier
                    break
        return mult

    def _in_burst(self, link, now):
        until = self._burst_until.get(link)
        return until is not None and now < until

    def _within_rate_limit(self, sender, now):
        limit = self.profile.message_rate_limit
        if not limit:
            return True
        window = self._sent_times.setdefault(sender, [])
        window[:] = [t for t in window if now - t < 1.0]
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def _within_bandwidth(self, sender, message, now):
        cap = self.profile.bandwidth_bytes_per_second
        if not cap:
            return True
        size = message.size_bytes()
        window = self._bytes_window.setdefault(sender, [])
        window[:] = [(t, n) for (t, n) in window if now - t < 1.0]
        used = sum(n for (_t, n) in window)
        if used + size > cap:
            return False
        window.append((now, size))
        return True

    def _drop(self, reason):
        self.dropped_by_reason[reason] = self.dropped_by_reason.get(reason, 0) + 1
        return Verdict(delivered=False, reason=reason)

    # --- reporting (evaluator side) ---

    def base_reachable_for(self, vehicle_id, now):
        """Whether an active partition cuts this vehicle off from base."""
        for part in self.profile.partitions:
            if not part.active(now):
                continue
            side = part.side_of(vehicle_id)
            if side is None:
                continue
            if part.base_side is None or side != part.base_side:
                return False
        return True

    def stats(self):
        return {"profile": self.profile.name,
                "seed": self.seed,
                "dropped_by_reason": dict(self.dropped_by_reason)}

    def reset(self, seed=None):
        """Restart the RNG and all windowed state - used between replays."""
        self.seed = self.seed if seed is None else seed
        self.rng = random.Random(self.seed)
        self._sent_times.clear()
        self._bytes_window.clear()
        self._burst_until.clear()
        self.dropped_by_reason.clear()
