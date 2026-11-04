"""What a drone would bid for a task, term by term (AUV-08, 8.3).

    bid = bid_for(task, Bidder("Drone2", x=4.0, y=0.0, battery=100.0, home=(4.0, 0.0), time_left=900.0,
                              altitude_m=16.0, speed_mps=5.0), brief, WEIGHTS)
    bid.value, bid.terms, bid.eligible, bid.why_not

AUV-08:  Bid(i, k) = w_d D(i,k) + w_b B(i,k) + w_l L(i) + w_c C(i) + w_r R(i,k).
Lowest wins; the vehicle id breaks ties (`rank`). Every term is kept with the
bid, so a reader can see why a drone won.

A BID IS THE EXPECTED SECONDS UNTIL THIS DRONE WOULD FINISH THE TASK
(Phase 8, recommendation 2), so the terms share one unit:

    D  travel time: to the task's first lane and through its lanes, at the
       drone's speed -- the very lanes the rule policy will fly
       (`search_lanes`, pinned to the policy's own by a test).
    B  battery: the task and the way home from its last lane costed with the
       brief's battery model; if that would leave less than the reserve plus
       the policy's margin, the drone is NOT ELIGIBLE. Otherwise 0.
    L  workload: seconds of work the drone has already committed to. A drone
       holds one task at a time (recommendation 4), so a free drone's is 0.
    C  communication risk: seconds of the task's lanes beyond the base's
       radio range. Computed and logged; weighted 0 under perfect
       communication, until Phase 10 gives it a meaning.
    R  capability mismatch: a drone lacking a capability the task requires
       is NOT ELIGIBLE. Otherwise 0.

The deadline is a gate too: a drone that could not finish and land before it
is not eligible. An ineligible bid has no value and is never ranked.

THE WEIGHTS are the knobs a reviewer will ask about (AUV-08): they are fixed
in a manifest (`configs/allocation/default.toml`) before any run, recorded
with every run, and not tuned after seeing results.

This module is inside the agents' boundary: it costs a task from what the
drone believes of itself and from the public brief, nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..control import navigation as nav
from ..control.routing import NoRouteError, grown, length, route
from ..control.scripted import ZONE_CLEARANCE_M, lane_end_overrun, lane_spacing, searched_region
from ..core.geometry import Region
from ..core.scenario import MissionBrief
from .tasks import DEFAULT_CAPABILITIES, MissionTask

BATTERY_MARGIN = 2.0          # percent above the reserve: the rule policy's own BATTERY_MARGIN
LANDING_ALLOWANCE_S = 30.0    # kept for the descent and landing: the rule policy's own
TERMS = ("D", "B", "L", "C", "R")


@dataclass(frozen=True)
class BidWeights:
    w_d: float = 1.0
    w_b: float = 1.0
    w_l: float = 1.0
    w_c: float = 0.0
    w_r: float = 1.0

    def __post_init__(self) -> None:
        bad = [f"{k} {v!r}" for k, v in self.as_json().items()
               if not (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0)]
        if bad:
            raise ValueError("weights must be finite and not negative: " + ", ".join(bad))

    def as_json(self) -> dict[str, float]:
        return {"w_d": self.w_d, "w_b": self.w_b, "w_l": self.w_l, "w_c": self.w_c, "w_r": self.w_r}


@dataclass(frozen=True)
class AllocationConfig:
    """The manifest: the weights, and the protocol's timings (`configs/allocation/`)."""

    weights: BidWeights = field(default_factory=BidWeights)
    bid_window_s: float = 1.0          # 0: claim at once, before any bid can arrive (contested)
    progress_period_s: float = 2.0
    lease_s: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.weights, BidWeights):
            raise ValueError("weights must be BidWeights")
        if not (math.isfinite(self.bid_window_s) and self.bid_window_s >= 0):
            raise ValueError(f"bid_window_s must be finite and not negative, got {self.bid_window_s}")
        if not (math.isfinite(self.progress_period_s) and self.progress_period_s > 0):
            raise ValueError(f"progress_period_s must be positive, got {self.progress_period_s}")
        if not (math.isfinite(self.lease_s) and self.lease_s > self.progress_period_s):
            raise ValueError(f"lease_s must outlast the progress period, got {self.lease_s}")

    def as_json(self) -> dict[str, Any]:
        return {"weights": self.weights.as_json(), "bid_window_s": self.bid_window_s,
                "progress_period_s": self.progress_period_s, "lease_s": self.lease_s}


@dataclass(frozen=True)
class Bidder:
    """What a drone knows of itself when it bids: its own belief, nothing more."""

    drone: str
    x: float
    y: float
    battery: float
    home: tuple[float, float]
    time_left: float
    altitude_m: float
    speed_mps: float
    committed_s: float = 0.0
    capabilities: frozenset[str] = field(default=DEFAULT_CAPABILITIES)


@dataclass(frozen=True)
class Bid:
    task_id: str
    version: int
    bidder: str
    value: float | None            # None: not eligible
    terms: dict[str, float]
    detail: dict[str, Any]
    why_not: str | None = None

    @property
    def eligible(self) -> bool:
        return self.value is not None

    def as_json(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "version": self.version, "bidder": self.bidder,
                "value": None if self.value is None else round(self.value, 3),
                "terms": {k: round(v, 3) for k, v in self.terms.items()}, "detail": self.detail,
                "why_not": self.why_not}


def rank(bid: Bid) -> tuple[float, str]:
    """The order bids are compared in: lowest value first, then the lower vehicle id (8.3)."""
    if not bid.eligible:
        raise ValueError(f"{bid.bidder}'s bid for {bid.task_id} is not eligible: it is never ranked")
    return (round(bid.value, 6), bid.bidder)


def search_lanes(brief: MissionBrief, region: Region, altitude_m: float, speed_mps: float) -> list[tuple[float, float]]:
    """The lanes the rule policy flies over `region`: the same calls, in the same order."""
    obstacles = [grown(z.polygon, ZONE_CLEARANCE_M) for z in brief.restricted_zones]
    spacing = lane_spacing(region.y_max - region.y_min, brief.detection, speed_mps)
    searched = searched_region(region, spacing, altitude_m, lane_end_overrun(brief.detection, speed_mps), obstacles)
    return [(w.x, w.y) for w in nav.lawnmower(searched, spacing, altitude_m)]


def _leg(a: tuple[float, float], b: tuple[float, float], brief: MissionBrief) -> float:
    try:
        return length(route(a, b, [z.polygon for z in brief.restricted_zones], ZONE_CLEARANCE_M))
    except NoRouteError:
        return math.dist(a, b)


def _beyond_base(lanes: list[tuple[float, float]], brief: MissionBrief, steps_per_m: float = 1.0) -> float:
    """Metres of the lanes farther from the base than its radio reaches, sampled every metre."""
    base, reach = (brief.base.x, brief.base.y), brief.network.communication_range_m
    out = 0.0
    for a, b in zip(lanes, lanes[1:]):
        n = max(1, math.ceil(math.dist(a, b) * steps_per_m))
        for i in range(n):
            f = (i + 0.5) / n
            if math.dist((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])), base) > reach:
                out += math.dist(a, b) / n
    return out


def bid_for(task: MissionTask, me: Bidder, brief: MissionBrief, weights: BidWeights) -> Bid:
    """`me`'s bid for `task`, every term kept; not eligible if it could not do the task and get home."""
    lanes = search_lanes(brief, task.region, me.altitude_m, me.speed_mps)
    here = (me.x, me.y)
    to_task = _leg(here, lanes[0], brief)
    through = length(lanes)
    home = _leg(lanes[-1], me.home, brief)
    D = (to_task + through) / me.speed_mps
    metres = to_task + through + home
    seconds = metres / me.speed_mps
    b = brief.battery
    cost = b.hover_drain_per_s * seconds + b.move_drain_per_m * metres
    left = me.battery - cost
    C = _beyond_base(lanes, brief) / me.speed_mps
    terms = {"D": D, "B": 0.0, "L": me.committed_s, "C": C, "R": 0.0}
    detail = {"to_task_m": round(to_task, 3), "lanes_m": round(through, 3), "home_m": round(home, 3),
              "battery_cost": round(cost, 3), "battery_left": round(left, 3),
              "seconds_with_home": round(seconds, 3), "time_left": round(me.time_left, 3)}
    missing = sorted(task.required_capabilities - me.capabilities)
    why_not = None
    if missing:
        why_not = f"lacks {', '.join(missing)}"
    elif left < b.reserve + BATTERY_MARGIN:
        why_not = (f"battery: {me.battery:.1f} % less {cost:.1f} % for the task and home leaves {left:.1f} %, "
                   f"under the {b.reserve:g} % reserve plus {BATTERY_MARGIN:g}")
    elif me.time_left < seconds + LANDING_ALLOWANCE_S:
        why_not = f"deadline: {me.time_left:.0f} s left, about {seconds + LANDING_ALLOWANCE_S:.0f} s needed"
    value = None if why_not else (weights.w_d * D + weights.w_b * terms["B"] + weights.w_l * terms["L"]
                                  + weights.w_c * C + weights.w_r * terms["R"])
    return Bid(task.task_id, task.version, me.drone, value, terms, detail, why_not)
