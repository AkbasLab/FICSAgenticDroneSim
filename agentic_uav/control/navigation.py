"""Where the skill layer turns "30 m up, there" into numbers a simulator flies.

AUV-04 (3.2) puts one warning above all the others: AirSim is NED, so up is
NEGATIVE z, and an altitude of 30 m is not z = 30. "Do the sign handling
inside the skill layer, once, where it can be unit-tested." This is that once.

Above this module, everything speaks the way a mission does: x and y in
metres on the map, and ALTITUDE in metres ABOVE THE GROUND, positive up.
Below it, everything is NED as AirSim reports it. Two facts make the
conversion more than a sign flip, and Phase 1 learned both the hard way:

* NED's zero is not the ground. Town10HD's ground is at z = +29.25, so
  "30 m up" is z = 29.25 - 30 = -0.75. Sending -30 flew 29 m too high.
* The ground is measured per drone (the executor's ground reference), and the
  terrain varies: 29.25, 29.28 and 27.29 under M10's four spawn points.

So every conversion takes the measured ground as an argument. Nothing here
guesses it.

Also here, all pure and unit-tested: headings, the reached-within-tolerance
test, a stand-off point for inspecting something, and lawnmower paths for
searching a rectangular region.

HEADINGS follow AirSim: degrees, 0 facing +x, positive turning towards +y,
normalised to (-180, 180].
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.models import Position


# ------------------------------------------------------------------ altitude

def altitude_to_z(altitude_m: float, ground_z: float) -> float:
    """NED z for `altitude_m` metres above a ground measured at NED `ground_z`."""
    if altitude_m < 0:
        raise ValueError(f"altitude {altitude_m} m is below the ground; "
                         "altitudes above this layer are metres UP, never negative")
    return ground_z - altitude_m


def z_to_altitude(z: float, ground_z: float) -> float:
    """Metres above the ground for NED `z`, over a ground at NED `ground_z`."""
    return ground_z - z


@dataclass(frozen=True)
class Waypoint:
    """A point as a mission states it: map metres, and altitude above the ground.

    `altitude_m` is POSITIVE UP. There is deliberately no `z` here: the only
    way to a NED position is `to_position`, which needs the measured ground.
    """

    x: float
    y: float
    altitude_m: float

    def __post_init__(self) -> None:
        if self.altitude_m < 0:
            raise ValueError(f"waypoint altitude {self.altitude_m} m is below the ground")

    def to_position(self, ground_z: float) -> Position:
        return Position(self.x, self.y, altitude_to_z(self.altitude_m, ground_z))

    @classmethod
    def from_position(cls, position: Position, ground_z: float) -> "Waypoint":
        return cls(position.x, position.y, max(0.0, z_to_altitude(position.z, ground_z)))


# ------------------------------------------------------------------ distance

def horizontal_distance(a: Position, b: Position) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def distance(a: Position, b: Position) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def reached(current: Position, target: Position, tolerance_m: float,
            vertical_tolerance_m: float | None = None) -> bool:
    """Whether `current` is at `target` within tolerance.

    One tolerance is a sphere. With `vertical_tolerance_m` the test is a
    cylinder instead: horizontal within `tolerance_m` and vertical within its
    own bound, for when height is held more loosely than position, or more
    tightly.
    """
    if tolerance_m < 0 or (vertical_tolerance_m is not None and vertical_tolerance_m < 0):
        raise ValueError("tolerances cannot be negative")
    if vertical_tolerance_m is None:
        return distance(current, target) <= tolerance_m
    return (horizontal_distance(current, target) <= tolerance_m
            and abs(current.z - target.z) <= vertical_tolerance_m)


# ------------------------------------------------------------------- heading

def normalise_heading(degrees: float) -> float:
    """The same heading in (-180, 180]."""
    h = math.fmod(degrees, 360.0)
    if h <= -180.0:
        h += 360.0
    elif h > 180.0:
        h -= 360.0
    return h


def heading_to(origin: Position, target: Position) -> float:
    """The heading that faces `target` from `origin`, horizontally."""
    if horizontal_distance(origin, target) == 0.0:
        raise ValueError("no heading between two points at the same x, y")
    return normalise_heading(math.degrees(math.atan2(target.y - origin.y, target.x - origin.x)))


def heading_error(current: float, target: float) -> float:
    """Signed shortest turn from `current` to `target`, in (-180, 180]."""
    return normalise_heading(target - current)


# ------------------------------------------------------------------- inspect

def standoff_point(target: Position, origin: Position, radius_m: float) -> Position:
    """Where to stand to inspect `target` from `radius_m` away, at origin's height.

    On the horizontal line from `target` towards `origin`, so the approach is
    the shortest one; from directly above, the stand-off is along +x.
    """
    if radius_m < 0:
        raise ValueError("stand-off radius cannot be negative")
    d = horizontal_distance(origin, target)
    if d == 0.0:
        ux, uy = 1.0, 0.0
    else:
        ux, uy = (origin.x - target.x) / d, (origin.y - target.y) / d
    return Position(target.x + ux * radius_m, target.y + uy * radius_m, origin.z)


# -------------------------------------------------------------------- search

@dataclass(frozen=True)
class Region:
    """An axis-aligned rectangle on the map, in metres. AUV-05's search sectors."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.x_max < self.x_min or self.y_max < self.y_min:
            raise ValueError(f"region has negative size: {self}")

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


def lawnmower(region: Region, spacing_m: float, altitude_m: float) -> list[Waypoint]:
    """A boustrophedon path covering `region`, legs along x, `spacing_m` apart.

    Legs run the full length in x, alternating direction, stepping along y.
    The first leg is at `y_min + spacing/2` and the rest follow at `spacing`,
    so with a sensor footprint `spacing` wide every point of the region is
    within `spacing/2` of a leg; a region narrower than `spacing` gets one leg
    down its middle. Deterministic: the same region always gives the same path.
    """
    if spacing_m <= 0:
        raise ValueError("spacing must be positive")
    width = region.y_max - region.y_min
    legs = max(1, math.ceil(width / spacing_m))
    if legs == 1:
        ys = [(region.y_min + region.y_max) / 2.0]
    else:
        ys = [min(region.y_min + spacing_m / 2.0 + i * spacing_m, region.y_max - spacing_m / 2.0)
              for i in range(legs)]
    path = []
    for i, y in enumerate(ys):
        x0, x1 = (region.x_min, region.x_max) if i % 2 == 0 else (region.x_max, region.x_min)
        path.append(Waypoint(x0, y, altitude_m))
        path.append(Waypoint(x1, y, altitude_m))
    return path


# --------------------------------------------------------------------- time

def travel_time(distance_m: float, speed_mps: float) -> float:
    """Seconds to cover `distance_m` at `speed_mps`, the floor for any timeout."""
    if speed_mps <= 0:
        raise ValueError("speed must be positive")
    return abs(distance_m) / speed_mps
