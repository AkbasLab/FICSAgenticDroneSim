"""Keep clear of a teammate that has gone silent in the air (the Phase 9 live flight's fix).

    cfg = KeepOutConfig(half_width_m=5.0, after_s=10.0, min_altitude_m=3.0)
    for drone, x, y in silent_in_the_air(heard, now, cfg): ...
    zone = square(x, y, cfg.half_width_m)          # a Polygon the routes and the search go round

WHY. Phase 9's live flight (2026-11-04, `recovery-live-20261104-223149-live1`):
Drone2 was stopped mid-search and hovered; Drone1, given its sector, searched it
at its own layer, passed 5.5 m beneath the hovering drone, was lifted, and the
two collided. The team kept apart by height alone, and nothing avoided a
silent teammate's last known position. A stopped drone hovering where it was
last heard is exactly where that position is the most reliable thing known.

WHAT. A teammate is SILENT IN THE AIR when its latest report is at least
`after_s` old -- judged from the report's own time, the record alone, so the
guardian can apply the same rule without reading anything a policy writes --
and put it at least `min_altitude_m` up (a drone landed on its pad is no hazard
to one flying overhead at its layer, and a finished drone stops talking). Round
its last known position stands a KEEP-OUT: a square `half_width_m` either side,
at every height -- the live lift began passing BENEATH the stopped drone, so a
height cannot be trusted. It lasts while the teammate stays silent; the
moment it is heard again it is gone.

A drone already inside a keep-out when it appears is not held there: the zone
is left out of its own routes, so it can fly away (callers' `excluding`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from ..control.routing import grown
from ..core.geometry import Polygon

KEY_ORDER = ("half_width_m", "after_s", "min_altitude_m")


@dataclass(frozen=True)
class KeepOutConfig:
    half_width_m: float             # the square reaches this far either side of the last known position
    after_s: float                  # silent at least this long (the ladder's "unreachable")
    min_altitude_m: float           # last known at least this high: in the air, not on a pad

    def __post_init__(self) -> None:
        if not (self.half_width_m > 0 and self.after_s > 0 and self.min_altitude_m >= 0):
            raise ValueError(f"keep-out: half width and silence must be positive, altitude not negative: {self}")

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_keepout(data: dict[str, Any], source: str = "") -> KeepOutConfig:
    """Strictly: [keep_out] and its three numbers, nothing else."""
    problems = [f"unknown section [{k}]" for k in data if k != "keep_out"]
    got = data.get("keep_out")
    if not isinstance(got, dict):
        problems.append("missing section [keep_out]")
    else:
        problems += [f"[keep_out] missing {k}" for k in KEY_ORDER if k not in got]
        problems += [f"[keep_out] unknown key {k}" for k in got if k not in KEY_ORDER]
        problems += [f"[keep_out] {k} is not a number: {got[k]!r}" for k in KEY_ORDER
                     if k in got and (not isinstance(got[k], (int, float)) or isinstance(got[k], bool))]
    if problems:
        raise ValueError(f"not a valid keep-out manifest{' ' + source if source else ''}: " + "; ".join(problems))
    return KeepOutConfig(*(float(got[k]) for k in KEY_ORDER))


def silent_in_the_air(heard: Iterable[tuple[str, float, float, float, float]], now: float,
                      cfg: KeepOutConfig) -> list[tuple[str, float, float]]:
    """From (drone, x, y, altitude, when it was true): the teammates silent in the air, with where they were."""
    return [(d, x, y) for d, x, y, alt, at in sorted(heard)
            if now - at >= cfg.after_s - 1e-9 and alt >= cfg.min_altitude_m]


def square(x: float, y: float, half_width_m: float) -> Polygon:
    h = half_width_m
    return Polygon(((x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)))


def inside(point: tuple[float, float], centre: tuple[float, float], reach_m: float) -> bool:
    """Within `reach_m` of `centre` along both axes: inside the square of that half width."""
    return abs(point[0] - centre[0]) <= reach_m and abs(point[1] - centre[1]) <= reach_m


def keep_outs(heard: Iterable[tuple[str, float, float, float, float]], now: float, cfg: KeepOutConfig,
              here: tuple[float, float], clearance_m: float) -> list[tuple[str, Polygon]]:
    """The keep-out squares to plan round, leaving out any the drone is already within (it must fly away)."""
    # "Within" exactly as the router judges it -- inside the square grown by the clearance -- so a drone
    # standing on a route's corner just outside still plans round it, and one inside can still fly out.
    out = []
    for d, x, y in silent_in_the_air(heard, now, cfg):
        zone = square(x, y, cfg.half_width_m)
        if not grown(zone, clearance_m).contains(*here):
            out.append((d, zone))
    return out
