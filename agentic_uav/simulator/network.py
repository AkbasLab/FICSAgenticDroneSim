"""The network model: what happens to a message between two drones (AUV-10, 10.1-10.3).

    model = load_network("severe").seeded(17)     # configs/network/severe.toml, for seed 17
    bus = MessageBus(roster, clock, positions, None, network=model, start=t0)

Simulation infrastructure, like the bus that uses it: it decides, for each
message and each recipient, whether the message arrives and when. An agent
never holds it, never reads it, and is never told which condition it flies
in -- it can only notice what arrives (10.5). The model is handed to the
bus, to the base-link sensing, to the evaluator and to the knowledge log's
truth, and to nothing else.

WHAT IT MODELS (10.1). Each a level of an experimental factor, not a claim
about any radio (AUV-10's warning); the levels are calibrated by pilots later.

* LATENCY: mean, jitter (a normal spread), and a FLOOR. A latency below the
  floor is raised to it, so a message never arrives at the instant it was
  sent -- the same rule as Phase 7's fixed delay, and for the same reason: a
  message sent at the instant a teammate reads would otherwise arrive or not
  by which thread ran first. With no jitter the latency is the mean exactly.
* LOSS: each message to each recipient lost with a fixed probability,
  independently.
* A RATE LIMIT: messages a drone may send per second -- a token bucket that
  holds one second's worth and starts full. A broadcast is one transmission.
  A message over the limit is not sent at all: `rate_limited`, for everyone.
* BANDWIDTH: bytes a drone can send per second. A message takes its size
  over the bandwidth to send, and waits for the drone's earlier messages to
  finish: it arrives that much later. Its size is its JSON's.
* RANGE: a direct link no longer than this, in 3D, at sending -- Phase 7's
  rule. None is unlimited.
* PARTITIONS: for an interval from the flight's start, the roster (and the
  base, named "base") split into groups, and nothing crosses between groups:
  `partitioned`. Judged at sending, like range: a message already in the air
  when a partition begins still arrives.

SEEDED, AND KEYED PER MESSAGE (10.3). Whether a message is lost, and how long
it takes, are drawn from a generator seeded with the experiment's seed, the
sender, the recipient and the message's sequence number -- not from one
shared stream. So the order in which drones' threads happen to send cannot
change any message's fate, the same message meets the same fate whenever it
is sent, and two architectures that send the same message see the same thing
happen to it (AUV-16's paired comparison). The rate limit and the bandwidth
are a drone's own queue, in the order it sends, so they are deterministic too.

The four conditions (10.2) are manifests in `configs/network/`, read
strictly by `experiments.conditions.load_network`.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

BASE = "base"                      # the base's name in a partition's groups
# A partition's interval is judged with this allowance, everywhere alike (the bus,
# a drone's base-link reading, the judge's exact connectivity): a decision taken
# "at 60 s" is 60 s give or take the clock's rounding, and all three must agree on it.
PARTITION_TOL_S = 1e-6


@dataclass(frozen=True)
class Partition:
    """For [start_s, end_s) from the flight's start, nothing crosses between these groups."""

    groups: tuple[frozenset[str], ...]
    start_s: float
    end_s: float

    def problems(self) -> list[str]:
        p = []
        if len(self.groups) < 2:
            p.append("a partition needs at least two groups")
        seen: set[str] = set()
        for g in self.groups:
            if not g:
                p.append("a partition group is empty")
            twice = seen & g
            if twice:
                p.append(f"in two groups: {sorted(twice)}")
            seen |= g
        if not (0 <= self.start_s < self.end_s and math.isfinite(self.end_s)):
            p.append(f"a partition's interval must run forward from 0: {self.start_s}..{self.end_s}")
        return p

    def members(self) -> frozenset[str]:
        return frozenset().union(*self.groups)

    def active(self, t_s: float) -> bool:
        """In force at `t_s` from the flight's start: strictly inside its interval, each end moved back by
        PARTITION_TOL_S -- so a decision "at" its start is inside, one "at" its end is outside."""
        return self.start_s - PARTITION_TOL_S < t_s < self.end_s - PARTITION_TOL_S

    def splits(self, a: str, b: str) -> bool:
        """Whether `a` and `b` are in different groups (while the partition is active)."""
        found = [i for n in (a, b) for i, g in enumerate(self.groups) if n in g]
        if len(found) != 2:
            raise ValueError(f"{a} or {b} is in none of the partition's groups {[sorted(g) for g in self.groups]}")
        return found[0] != found[1]

    def as_json(self) -> dict[str, Any]:
        return {"groups": [sorted(g) for g in self.groups], "start_s": self.start_s, "end_s": self.end_s}


@dataclass(frozen=True)
class NetworkModel:
    name: str
    latency_mean_s: float
    latency_jitter_s: float = 0.0
    latency_floor_s: float = 0.05
    loss_probability: float = 0.0
    rate_limit_per_s: float | None = None
    bandwidth_bytes_per_s: float | None = None
    range_m: float | None = None
    partitions: tuple[Partition, ...] = field(default_factory=tuple)
    seed: int | None = None            # set per flight: `seeded`

    def __post_init__(self) -> None:
        p = self.problems()
        if p:
            raise ValueError(f"not a valid network model {self.name!r}: " + "; ".join(p))

    def problems(self) -> list[str]:
        p = []

        def positive(v: float | None, what: str, none_ok: bool = False) -> None:
            if v is None and none_ok:
                return
            if v is None or not (v > 0 and math.isfinite(v)):
                p.append(f"{what} must be positive: {v}")

        positive(self.latency_floor_s, "latency floor")
        if not (math.isfinite(self.latency_mean_s) and self.latency_mean_s >= self.latency_floor_s):
            p.append(f"latency mean {self.latency_mean_s} must be at least the floor {self.latency_floor_s}")
        if not (math.isfinite(self.latency_jitter_s) and self.latency_jitter_s >= 0):
            p.append(f"latency jitter must be zero or more: {self.latency_jitter_s}")
        if not (0.0 <= self.loss_probability < 1.0):
            p.append(f"loss probability must be in [0, 1): {self.loss_probability}")
        positive(self.rate_limit_per_s, "rate limit", none_ok=True)
        positive(self.bandwidth_bytes_per_s, "bandwidth", none_ok=True)
        positive(self.range_m, "range", none_ok=True)
        for part in self.partitions:
            p += part.problems()
        return p

    def seeded(self, seed: int) -> "NetworkModel":
        """This model for one experiment seed: every draw follows from it."""
        return replace(self, seed=int(seed))

    def check_roster(self, roster: Iterable[str]) -> None:
        """Every drone, and the base, in exactly one group of every partition."""
        names = set(roster) | {BASE}
        for part in self.partitions:
            members = part.members()
            if members != names:
                raise ValueError(f"partition at {part.start_s:g}-{part.end_s:g} s: groups name "
                                 f"{sorted(members)}, the roster and base are {sorted(names)}")

    # ------------------------------------------------------------ the draws

    def draw(self, sender: str, recipient: str, sequence_number: int) -> tuple[bool, float]:
        """Whether this message to this recipient is lost, and its latency -- the same every time it is asked."""
        if self.seed is None:
            raise RuntimeError(f"network model {self.name!r} has no seed: use .seeded(seed)")
        rng = random.Random(f"{self.name}|{self.seed}|{sender}|{recipient}|{sequence_number}")
        u, g = rng.random(), rng.gauss(0.0, 1.0)          # both drawn always: one never shifts the other
        latency = self.latency_mean_s if self.latency_jitter_s == 0 else \
            max(self.latency_floor_s, self.latency_mean_s + self.latency_jitter_s * g)
        return u < self.loss_probability, latency

    def partitioned(self, a: str, b: str, t_s: float) -> bool:
        """Whether a partition keeps `a` and `b` apart at `t_s` from the flight's start."""
        return any(p.active(t_s) and p.splits(a, b) for p in self.partitions)

    def windows(self, a: str, b: str) -> list[tuple[float, float]]:
        """The OPEN intervals, from the flight's start, in which a partition keeps `a` and `b` apart --
        exactly where `partitioned` says so."""
        return [(p.start_s - PARTITION_TOL_S, p.end_s - PARTITION_TOL_S) for p in self.partitions if p.splits(a, b)]

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "latency_mean_s": self.latency_mean_s, "latency_jitter_s": self.latency_jitter_s,
                "latency_floor_s": self.latency_floor_s, "loss_probability": self.loss_probability,
                "rate_limit_per_s": self.rate_limit_per_s, "bandwidth_bytes_per_s": self.bandwidth_bytes_per_s,
                "range_m": self.range_m, "partitions": [p.as_json() for p in self.partitions], "seed": self.seed}


class Transmitter:
    """One drone's side of the radio: its rate-limit bucket and its send queue, in the order it sends."""

    def __init__(self, model: NetworkModel, start: float) -> None:
        self.model = model
        self.tokens = model.rate_limit_per_s or 0.0
        self.refilled_at = start
        self.busy_until = start

    def admit(self, now: float) -> bool:
        """Whether a message may be sent now, under the rate limit (taking a token if so)."""
        rate = self.model.rate_limit_per_s
        if rate is None:
            return True
        self.tokens = min(rate, self.tokens + (now - self.refilled_at) * rate)
        self.refilled_at = now
        if self.tokens >= 1.0 - 1e-9:
            self.tokens -= 1.0
            return True
        return False

    def sent_by(self, now: float, size_bytes: int) -> float:
        """When the message has finished leaving the drone, after any earlier ones."""
        bw = self.model.bandwidth_bytes_per_s
        if bw is None:
            return now
        begin = max(now, self.busy_until)
        self.busy_until = begin + size_bytes / bw
        return self.busy_until
