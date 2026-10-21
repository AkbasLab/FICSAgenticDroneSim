"""The mission's ground truth: where the targets are, and what a flight did (AUV-05, 4.1-4.2).

    targets = place_targets(scenario)                    # from the seed; never in the brief
    facts = observe(scenario, trajectories, start, end)  # what happened, exactly

The scenario says what the world is; this says what happened in it. Only
the simulator side and the evaluator call it: a controller is handed
`scenario.brief()` and learns of targets only by flying over them.

WHAT IS MODELLED, all of it simulated, none of it a perception network
(AUV-05, 4.2: "no object-detection network at this stage"):

* TARGETS are points on the ground, placed uniformly over the sectors (by
  area) from the scenario's seed, outside every restricted zone and at least
  `min_spacing_m` apart -- or at the scenario's fixed positions.
* DETECTION: a target is detected by a drone that is airborne and keeps it
  within `radius_m` HORIZONTALLY for `min_observation_s` without a break. It
  is detected at the moment that time is reached. Height does not narrow the
  footprint; line of sight is not modelled (Phase 4 decisions).
* RESTRICTED ZONES: a drone enters a zone when its ground track first touches
  the polygon, flying or not.
* BATTERY, in percent, linear and uncalibrated: `hover_drain_per_s` for every
  second airborne plus `move_drain_per_m` for every metre flown, nothing on
  the ground. It is RECORDED, not enforced: a drone that runs flat keeps
  flying here, and the record says when it would have stopped. Enforcing it
  is a fault, and faults are Phases 9-11's.
* CONNECTIVITY: a drone is connected to the base while a chain of radio links
  joins them, each link no longer than `communication_range_m` in 3D, through
  any drones, flying or landed. The base is a node on the ground. Perfect
  network: in range is delivered.
* REPORTED: a detection is reported at the first moment, at or after it, that
  its drone is connected to the base -- directly or relayed. AUV-05's "or
  eventually synchronized", before messaging exists (Phase 7). Information
  does not hop from drone to drone over time: only a chain at one instant.
* SEPARATION: the closest any two drones came while at least one was
  airborne, in 3D, and every interval spent closer than `min_separation_m`.

EXACT, not sampled. Trajectories are straight legs between knots, so each of
these is a quadratic in time on each leg and is solved, not ticked: a 2 s
dwell is 2 s, a 1.9 s dwell is not a detection, and the closest approach is
the true minimum, not the nearest sample to it. How exact the trajectory
itself is depends on its source: the mock's knots are exact; a live poller's
are samples (see `observer.py`).
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..core.scenario import BatterySpec, DetectionSpec, Scenario
from .trajectory import Knot, Point, Trajectory, breakpoints, intervals

BASE_NODE = "base"
MAX_PLACEMENT_ATTEMPTS = 10_000
_EPS = 1e-9


# ------------------------------------------------------------------ targets

@dataclass(frozen=True)
class Target:
    id: str
    x: float
    y: float
    sector: str


def place_targets(scenario: Scenario) -> tuple[Target, ...]:
    """The scenario's targets: its fixed positions, or drawn from its seed.

    Deterministic: the same scenario and seed always give the same targets,
    drawn with Python's own Mersenne Twister and nothing else.
    """
    spec = scenario.targets
    if spec.placement == "fixed":
        return tuple(Target(f"T{i + 1}", x, y, _sector_of(scenario, x, y))
                     for i, (x, y) in enumerate(spec.fixed))

    rng = random.Random(scenario.random_seed)
    sectors = scenario.sectors
    areas = [s.region.area for s in sectors]
    total = sum(areas)
    placed: list[Target] = []
    attempts = 0
    while len(placed) < spec.count:
        attempts += 1
        if attempts > MAX_PLACEMENT_ATTEMPTS:
            raise ValueError(f"{scenario.scenario_id}: could not place {spec.count} targets "
                             f"{spec.min_spacing_m} m apart outside the restricted zones "
                             f"in {MAX_PLACEMENT_ATTEMPTS} attempts")
        pick, acc = rng.random() * total, 0.0
        sector = sectors[-1]
        for s, area in zip(sectors, areas):
            acc += area
            if pick < acc:
                sector = s
                break
        r = sector.region
        x = r.x_min + rng.random() * (r.x_max - r.x_min)
        y = r.y_min + rng.random() * (r.y_max - r.y_min)
        if any(z.polygon.contains(x, y) for z in scenario.restricted_zones):
            continue
        if any(math.hypot(x - t.x, y - t.y) < spec.min_spacing_m for t in placed):
            continue
        placed.append(Target(f"T{len(placed) + 1}", x, y, sector.id))
    return tuple(placed)


def _sector_of(scenario: Scenario, x: float, y: float) -> str:
    for s in scenario.sectors:
        if s.region.contains(x, y):
            return s.id
    raise ValueError(f"({x}, {y}) is in no sector")       # the scenario refuses this already


# ------------------------------------------------------------ the quadratics

def _dot(a, b) -> float:
    return sum(p * q for p, q in zip(a, b))


def _in_range(u: float, v: float, d0, d1, r: float) -> tuple[float, float] | None:
    """The part of [u, v] where |d| <= r, d moving linearly from d0 at u to d1 at v."""
    span = v - u
    w = [(b - a) / span for a, b in zip(d0, d1)]
    a = _dot(w, w)
    b = 2.0 * _dot(d0, w)
    c = _dot(d0, d0) - r * r
    if a == 0.0:
        return (u, v) if c <= 0.0 else None
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    lo = max(0.0, (-b - root) / (2.0 * a))
    hi = min(span, (-b + root) / (2.0 * a))
    if lo > hi:
        return None
    return (u + lo, u + hi)


def _closest(u: float, v: float, d0, d1) -> tuple[float, float]:
    """The smallest |d| over [u, v] and when, d moving linearly from d0 to d1."""
    span = v - u
    w = [(b - a) / span for a, b in zip(d0, d1)]
    a = _dot(w, w)
    s = 0.0 if a == 0.0 else min(span, max(0.0, -_dot(d0, w) / a))
    at = [p + q * s for p, q in zip(d0, w)]
    return math.sqrt(_dot(at, at)), u + s


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Join spans that overlap or meet (a dwell carries over a knot)."""
    out: list[tuple[float, float]] = []
    for s0, s1 in sorted(spans):
        if out and s0 <= out[-1][1] + _EPS:
            out[-1] = (out[-1][0], max(out[-1][1], s1))
        else:
            out.append((s0, s1))
    return out


def _pair_legs(a: Trajectory, b: Trajectory, start: float, end: float):
    for u, v in intervals(breakpoints((a, b), start, end)):
        yield u, v, a.leg_over(u, v), b.leg_over(u, v)


def _sub(p: Point, q: Point) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(p, q))


# --------------------------------------------------------------- detection

@dataclass(frozen=True)
class Detection:
    """The first time `drone` held `target` in view long enough."""

    target: str
    drone: str
    in_view_at: float         # when the dwell that counted began
    detected_at: float        # in_view_at + min_observation_s


def detections(trajectories: list[Trajectory], targets: tuple[Target, ...] | list[Target],
               spec: DetectionSpec, start: float, end: float) -> list[Detection]:
    """Every (target, drone) pair's first detection, in time order."""
    out = []
    for target in targets:
        for traj in trajectories:
            spans = []
            for u, v in intervals(breakpoints((traj,), start, end)):
                leg = traj.leg_over(u, v)
                if not leg.airborne:
                    continue
                d0 = (leg.p0[0] - target.x, leg.p0[1] - target.y)
                d1 = (leg.p1[0] - target.x, leg.p1[1] - target.y)
                span = _in_range(u, v, d0, d1, spec.radius_m)
                if span:
                    spans.append(span)
            for s0, s1 in _merge(spans):
                if s1 - s0 >= spec.min_observation_s - _EPS:
                    out.append(Detection(target.id, traj.drone, s0, s0 + spec.min_observation_s))
                    break
    return sorted(out, key=lambda d: (d.detected_at, d.target, d.drone))


# ----------------------------------------------------------- restricted zones

@dataclass(frozen=True)
class ZoneEntry:
    """The first time `drone`'s ground track touched restricted zone `zone`."""

    drone: str
    zone: str
    at: float
    x: float
    y: float


def zone_entries(trajectories: list[Trajectory], zones, start: float, end: float) -> list[ZoneEntry]:
    out = []
    for traj in trajectories:
        for zone in zones:
            # A leg that starts inside enters at its start (fraction 0).
            for u, v in intervals(breakpoints((traj,), start, end)):
                leg = traj.leg_over(u, v)
                f = zone.polygon.entry_fraction(leg.p0[:2], leg.p1[:2])
                if f is not None:
                    at = u + f * (v - u)
                    x, y, _ = leg.at(at)
                    out.append(ZoneEntry(traj.drone, zone.id, at, x, y))
                    break
    return sorted(out, key=lambda e: (e.at, e.drone, e.zone))


# ------------------------------------------------------------------ battery

@dataclass(frozen=True)
class BatteryTrace:
    drone: str
    capacity: float
    reserve: float
    airborne_s: float
    flown_m: float
    used: float
    remaining: float                     # may be negative: the battery is not enforced
    below_reserve_at: float | None       # first moment under the reserve
    depleted_at: float | None            # first moment at zero


def battery(traj: Trajectory, spec: BatterySpec, start: float, end: float) -> BatteryTrace:
    level = spec.capacity
    airborne_s = flown_m = 0.0
    below = depleted = None
    for u, v in intervals(breakpoints((traj,), start, end)):
        leg = traj.leg_over(u, v)
        if not leg.airborne:
            continue
        dt, dist = v - u, leg.length
        drain = spec.hover_drain_per_s * dt + spec.move_drain_per_m * dist
        rate = drain / dt
        after = level - drain
        if below is None and after < spec.reserve and rate > 0:
            below = u + max(0.0, level - spec.reserve) / rate
        if depleted is None and after <= 0.0 and rate > 0:
            depleted = u + max(0.0, level) / rate
        level = after
        airborne_s += dt
        flown_m += dist
    return BatteryTrace(traj.drone, spec.capacity, spec.reserve, airborne_s, flown_m,
                        spec.capacity - level, level, below, depleted)


# ------------------------------------------------------------- connectivity

class Connectivity:
    """When each drone could reach the base, directly or through others.

    Every pair's in-range interval is solved exactly; between the ends of
    those intervals the radio graph cannot change, so it is evaluated once
    per piece, at its middle.
    """

    def __init__(self, trajectories: list[Trajectory], base_xy: tuple[float, float],
                 range_m: float, start: float, end: float) -> None:
        if range_m <= 0:
            raise ValueError("communication range must be positive")
        self.range_m = range_m
        self.start, self.end = start, end
        base = Trajectory(BASE_NODE, [_static_knot(start, base_xy)])
        nodes = [base] + list(trajectories)
        self.links: dict[tuple[str, str], list[tuple[float, float]]] = {}
        cuts = {start, end}
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                spans = []
                for u, v, la, lb in _pair_legs(a, b, start, end):
                    span = _in_range(u, v, _sub(la.p0, lb.p0), _sub(la.p1, lb.p1), range_m)
                    if span:
                        spans.append(span)
                merged = _merge(spans)
                self.links[(a.drone, b.drone)] = merged
                for s0, s1 in merged:
                    cuts.update((s0, s1))
        self._spans: dict[str, list[tuple[float, float]]] = {t.drone: [] for t in trajectories}
        names = [n.drone for n in nodes]
        for u, v in intervals(sorted(t for t in cuts if start <= t <= end)):
            m = (u + v) / 2.0
            adjacent: dict[str, list[str]] = {n: [] for n in names}
            for (a, b), spans in self.links.items():
                if any(s0 <= m <= s1 for s0, s1 in spans):
                    adjacent[a].append(b)
                    adjacent[b].append(a)
            for drone in _reachable(adjacent, BASE_NODE) - {BASE_NODE}:
                self._spans[drone].append((u, v))
        for drone in self._spans:
            self._spans[drone] = _merge(self._spans[drone])

    def spans(self, drone: str) -> list[tuple[float, float]]:
        """The intervals during which `drone` was connected to the base."""
        return list(self._spans[drone])

    def connected_at(self, drone: str, t: float) -> bool:
        return any(s0 <= t <= s1 for s0, s1 in self._spans[drone])

    def first_connection(self, drone: str, at: float) -> float | None:
        """The first moment at or after `at` that `drone` was connected, if any."""
        for s0, s1 in self._spans[drone]:
            if s1 >= at:
                return max(s0, at)
        return None


def _static_knot(t: float, xy: tuple[float, float]) -> Knot:
    return Knot(t, xy[0], xy[1], 0.0, False)


def _reachable(adjacent: dict[str, list[str]], source: str) -> set[str]:
    seen, queue = {source}, deque([source])
    while queue:
        for n in adjacent[queue.popleft()]:
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


@dataclass(frozen=True)
class Report:
    target: str
    drone: str
    detected_at: float
    reported_at: float | None            # None: never connected to the base afterwards


# --------------------------------------------------------------- separation

@dataclass(frozen=True)
class PairSeparation:
    a: str
    b: str
    min_m: float | None                  # None: never was either of them airborne
    at: float | None
    violations: tuple[tuple[float, float], ...]   # closer than min_separation_m


def separations(trajectories: list[Trajectory], min_separation_m: float,
                start: float, end: float) -> list[PairSeparation]:
    out = []
    for i, ta in enumerate(trajectories):
        for tb in trajectories[i + 1:]:
            best: tuple[float, float] | None = None
            close = []
            for u, v, la, lb in _pair_legs(ta, tb, start, end):
                if not (la.airborne or lb.airborne):
                    continue
                d0, d1 = _sub(la.p0, lb.p0), _sub(la.p1, lb.p1)
                dist, at = _closest(u, v, d0, d1)
                if best is None or dist < best[0]:
                    best = (dist, at)
                if dist < min_separation_m:
                    span = _in_range(u, v, d0, d1, min_separation_m)
                    if span:
                        close.append(span)
            out.append(PairSeparation(ta.drone, tb.drone, None if best is None else best[0],
                                      None if best is None else best[1], tuple(_merge(close))))
    return out


# -------------------------------------------------------------------- facts

@dataclass(frozen=True)
class MissionFacts:
    """Everything that happened in one flight, measured against its scenario."""

    scenario_id: str
    random_seed: int
    start: float
    end: float
    targets: tuple[Target, ...]
    detections: tuple[Detection, ...]
    reports: tuple[Report, ...]
    zone_entries: tuple[ZoneEntry, ...]
    batteries: tuple[BatteryTrace, ...]
    separations: tuple[PairSeparation, ...]
    connected: dict[str, tuple[tuple[float, float], ...]] = field(default_factory=dict)

    def first_report(self, target: str) -> Report | None:
        """The earliest report of `target` by any drone."""
        times = [r for r in self.reports if r.target == target and r.reported_at is not None]
        return min(times, key=lambda r: r.reported_at) if times else None

    def as_json(self) -> dict[str, Any]:
        """Times relative to the mission's start, in seconds, rounded to the millisecond."""
        def rel(t):
            return None if t is None else round(t - self.start, 3)

        return {
            "scenario_id": self.scenario_id,
            "random_seed": self.random_seed,
            "duration_s": rel(self.end),
            "targets": [{"id": t.id, "x": round(t.x, 3), "y": round(t.y, 3), "sector": t.sector}
                        for t in self.targets],
            "detections": [{"target": d.target, "drone": d.drone, "in_view_s": rel(d.in_view_at),
                            "detected_s": rel(d.detected_at)} for d in self.detections],
            "reports": [{"target": r.target, "drone": r.drone, "detected_s": rel(r.detected_at),
                         "reported_s": rel(r.reported_at)} for r in self.reports],
            "zone_entries": [{"drone": e.drone, "zone": e.zone, "at_s": rel(e.at),
                              "x": round(e.x, 3), "y": round(e.y, 3)} for e in self.zone_entries],
            "batteries": [{"drone": b.drone, "airborne_s": round(b.airborne_s, 3),
                           "flown_m": round(b.flown_m, 3), "used": round(b.used, 3),
                           "remaining": round(b.remaining, 3), "reserve": b.reserve,
                           "below_reserve_s": rel(b.below_reserve_at),
                           "depleted_s": rel(b.depleted_at)} for b in self.batteries],
            "separations": [{"pair": f"{s.a}-{s.b}",
                             "min_m": None if s.min_m is None else round(s.min_m, 3),
                             "at_s": rel(s.at),
                             "violations_s": [[rel(a), rel(b)] for a, b in s.violations]}
                            for s in self.separations],
            "connected_s": {d: [[rel(a), rel(b)] for a, b in spans] for d, spans in self.connected.items()},
        }


def observe(scenario: Scenario, trajectories: dict[str, Trajectory] | list[Trajectory],
            start: float, end: float, targets: tuple[Target, ...] | None = None) -> MissionFacts:
    """Measure one flight, over [start, end], against `scenario`.

    `trajectories` must be the scenario's own drones (any of them: AUV-05
    flies two to four). `targets` defaults to `place_targets(scenario)`.
    """
    trajs = list(trajectories.values()) if isinstance(trajectories, dict) else list(trajectories)
    known = {v.id for v in scenario.vehicles}
    unknown = [t.drone for t in trajs if t.drone not in known]
    if unknown:
        raise ValueError(f"trajectories for drones not in {scenario.scenario_id}: {unknown}")
    if len({t.drone for t in trajs}) != len(trajs):
        raise ValueError("two trajectories for one drone")
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    targets = place_targets(scenario) if targets is None else tuple(targets)

    found = detections(trajs, targets, scenario.detection, start, end)
    radio = Connectivity(trajs, (scenario.base.x, scenario.base.y),
                         scenario.network.communication_range_m, start, end)
    reports = tuple(Report(d.target, d.drone, d.detected_at, radio.first_connection(d.drone, d.detected_at))
                    for d in found)
    return MissionFacts(
        scenario_id=scenario.scenario_id,
        random_seed=scenario.random_seed,
        start=start,
        end=end,
        targets=targets,
        detections=tuple(found),
        reports=reports,
        zone_entries=tuple(zone_entries(trajs, scenario.restricted_zones, start, end)),
        batteries=tuple(battery(t, scenario.battery, start, end) for t in trajs),
        separations=tuple(separations(trajs, scenario.safety.min_separation_m, start, end)),
        connected={t.drone: tuple(radio.spans(t.drone)) for t in trajs},
    )
