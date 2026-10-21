"""A drone's path as flown: knots joined by straight legs, in map metres.

    traj = Trajectory("Drone1", [Knot(0.0, 0, 0, 0, False), Knot(2.0, 0, 0, 3, True), ...])
    traj.position_at(1.0)           # (x, y, altitude_m)

What the mission world judges a flight by (Phase 4, step 2). Between two
consecutive knots a drone moves in a straight line at constant velocity, so
anything that depends on distance -- whether a target is in view, whether two
drones are in radio range, how close they came -- is a quadratic in time on
each leg and is solved exactly rather than sampled.

THE FRAME is the mission's, not AirSim's: x and y on the map, and ALTITUDE
above the ground, positive up. Observers convert from NED once, with the
measured ground, as `control.navigation` does for the skill layer.

AIRBORNE is a flag on each knot and holds for the leg that starts there. The
mock knows it exactly (its own landed state); a poller decides it from height.

A JUMP is two knots at the same instant: a drone placed, reset, or falling
when its motors are cut. It takes no time and covers no distance in
anything computed here.

Before its first knot a drone is where the first knot says; after its last,
where the last says.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Iterator

Point = tuple[float, float, float]           # x, y, altitude_m


@dataclass(frozen=True)
class Knot:
    t: float
    x: float
    y: float
    altitude_m: float
    airborne: bool

    @property
    def point(self) -> Point:
        return (self.x, self.y, self.altitude_m)


@dataclass(frozen=True)
class Leg:
    """Straight, constant-velocity motion from `p0` at `t0` to `p1` at `t1`."""

    t0: float
    t1: float
    p0: Point
    p1: Point
    airborne: bool

    @property
    def duration(self) -> float:
        return self.t1 - self.t0

    @property
    def length(self) -> float:
        return math.dist(self.p0, self.p1)

    def at(self, t: float) -> Point:
        if self.t1 <= self.t0:
            return self.p1
        f = min(1.0, max(0.0, (t - self.t0) / (self.t1 - self.t0)))
        return tuple(a + (b - a) * f for a, b in zip(self.p0, self.p1))  # type: ignore[return-value]


class Trajectory:
    """One drone's knots, in time order. Immutable once built."""

    def __init__(self, drone: str, knots: list[Knot] | tuple[Knot, ...]) -> None:
        if not knots:
            raise ValueError(f"{drone}: a trajectory needs at least one knot")
        for a, b in zip(knots, knots[1:]):
            if b.t < a.t:
                raise ValueError(f"{drone}: knots out of time order ({a.t} then {b.t})")
        self.drone = drone
        self.knots: tuple[Knot, ...] = tuple(knots)
        self._times = [k.t for k in self.knots]

    def __repr__(self) -> str:
        return f"Trajectory({self.drone!r}, {len(self.knots)} knots, t {self.start}..{self.end})"

    @property
    def start(self) -> float:
        return self.knots[0].t

    @property
    def end(self) -> float:
        return self.knots[-1].t

    def legs(self) -> Iterator[Leg]:
        """Every leg between consecutive knots, jumps (zero duration) included."""
        for a, b in zip(self.knots, self.knots[1:]):
            yield Leg(a.t, b.t, a.point, b.point, a.airborne)

    def leg_over(self, u: float, v: float) -> Leg:
        """The motion over [u, v], an interval inside one leg (no knot strictly within).

        The leg is found from the midpoint, so at a jump at `u` the motion
        after the jump is used, and at a jump at `v` the motion before it.
        """
        m = (u + v) / 2.0
        i = bisect.bisect_right(self._times, m) - 1
        if i < 0:
            k = self.knots[0]
            return Leg(u, v, k.point, k.point, k.airborne)
        if i >= len(self.knots) - 1:
            k = self.knots[-1]
            return Leg(u, v, k.point, k.point, k.airborne)
        a, b = self.knots[i], self.knots[i + 1]
        leg = Leg(a.t, b.t, a.point, b.point, a.airborne)
        return Leg(u, v, leg.at(u), leg.at(v), a.airborne)

    def position_at(self, t: float) -> Point:
        """Where the drone is at `t`; at a jump, where it is after it."""
        i = bisect.bisect_right(self._times, t) - 1
        if i < 0:
            return self.knots[0].point
        if i >= len(self.knots) - 1:
            return self.knots[-1].point
        a, b = self.knots[i], self.knots[i + 1]
        return Leg(a.t, b.t, a.point, b.point, a.airborne).at(t)

    def airborne_at(self, t: float) -> bool:
        i = bisect.bisect_right(self._times, t) - 1
        return self.knots[max(0, i)].airborne

    def times(self) -> list[float]:
        return list(self._times)


def breakpoints(trajectories: list[Trajectory] | tuple[Trajectory, ...], start: float, end: float,
                extra: list[float] | tuple[float, ...] = ()) -> list[float]:
    """Every instant in [start, end] at which any of these changes leg, sorted, unique.

    Between consecutive breakpoints every trajectory is on one straight leg.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    ts = {start, end}
    for traj in trajectories:
        ts.update(t for t in traj.times() if start < t < end)
    ts.update(t for t in extra if start < t < end)
    return sorted(ts)


def intervals(points: list[float]) -> Iterator[tuple[float, float]]:
    """Consecutive pairs of `points` with positive length."""
    for u, v in zip(points, points[1:]):
        if v > u:
            yield u, v
