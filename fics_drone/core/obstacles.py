"""Obstacles a scenario can hold besides no-fly zones. Today: trees.

A tree is a vertical trunk with a wider crown near the top. Below `crown_from_frac` of its height only the trunk radius
counts; above it, the crown radius. Coordinates are world metres; z is height above the ground reference.
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple


def _segment_distance_xy(px: float, py: float, a, b) -> float:
    """Shortest distance in the horizontal plane from the point (px, py) to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    f = 0.0 if span == 0.0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / span))
    return math.hypot(px - (a[0] + f * dx), py - (a[1] + f * dy))


@dataclass(frozen=True)
class TreeObstacle:
    x: float
    y: float
    z_bottom: float
    z_top: float
    trunk_r: float = 1.2           # keep-out radius around the trunk axis (trunk plus a margin for the aircraft)
    crown_r: float = 5.0
    crown_from_frac: float = 0.6   # the crown starts this far up the tree

    def radius_at(self, z: float) -> Optional[float]:
        """Keep-out radius at height z, or None if z is above or below the tree."""
        if z < self.z_bottom or z > self.z_top:
            return None
        crown_start = self.z_bottom + self.crown_from_frac * (self.z_top - self.z_bottom)
        return self.crown_r if z >= crown_start else self.trunk_r

    def blocks_point(self, x: float, y: float, z: float, margin: float = 0.0) -> bool:
        r = self.radius_at(z)
        return r is not None and math.hypot(x - self.x, y - self.y) < r + margin

    def blocks_segment(self, a: Tuple[float, float, float], b: Tuple[float, float, float], margin: float = 0.0,
                       step: float = 0.5, skip_start_m: float = 2.0) -> bool:
        """True if the straight line a-b passes through the tree. The first `skip_start_m` metres are not tested, so an
        aircraft that already stands inside the keep-out can still leave."""
        length = math.dist(a, b)
        r0 = self.radius_at(a[2])
        if r0 is not None:
            # an aircraft already inside the margin may leave: the line is judged against the depth it starts at, so it
            # is blocked only if it goes deeper
            depth = math.hypot(a[0] - self.x, a[1] - self.y) - r0
            if depth < margin:
                margin = depth - 0.05
        if _segment_distance_xy(self.x, self.y, a, b) >= max(self.trunk_r, self.crown_r) + margin:
            return False
        n = max(1, int(length / step))
        for i in range(n + 1):
            f = i / n
            if f * length < skip_start_m and f < 1.0:
                continue
            if self.blocks_point(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, margin):
                return True
        return False

    def rect_at(self, z: float) -> Optional[Tuple[float, float, float, float]]:
        """(x_min, x_max, y_min, y_max) of the keep-out at height z, or None: how a leg planner is shown the tree."""
        r = self.radius_at(z)
        return None if r is None else (self.x - r, self.x + r, self.y - r, self.y + r)

    def rects_at(self, z: float, strips: int = 8) -> list:
        """The keep-out at height z as a stack of thin rectangles that hug the circle, for a leg planner that only knows
        rectangles. One square of the circle's radius also covers the corners the circle does not, and a waypoint outside
        the circle but inside that square cannot be reached. Each strip is as wide as the circle is at the strip's edge nearest
        the centre, so the stack never leaves the circle uncovered between its rows by more than the strip height."""
        r = self.radius_at(z)
        if r is None:
            return []
        h = 2.0 * r / strips
        out = []
        for i in range(strips):
            y0, y1 = -r + i * h, -r + (i + 1) * h
            near = 0.0 if y0 <= 0.0 <= y1 else min(abs(y0), abs(y1))
            half = math.sqrt(max(r * r - near * near, 0.0))
            out.append((self.x - half, self.x + half, self.y + y0, self.y + y1))
        return out


@dataclass(frozen=True)
class BoxObstacle:
    """A solid thing from the map (a building piece, a tree with its crown, a lamp post, a bench): a rectangle in the horizontal plane
    that holds from z_bottom to z_top. It has the same interface as TreeObstacle, so the guardian, the route planner and the leg planner
    treat it like a tree, but its shape is the real one (its bounding box), not a circle.

    `x`, `y`, `trunk_r` and `crown_r` are the centre and the circle that covers the whole rectangle: the callers that cull by distance
    or plan a detour round a circle use them and so keep clear of it with room to spare; blocks_point and blocks_segment use the
    rectangle itself."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_bottom: float
    z_top: float
    name: str = ""

    VERTICAL_MARGIN_M = 0.5     # the aircraft's own half height: it clears a roof or a ledge by this much, not less

    @property
    def x(self) -> float:
        return 0.5 * (self.x_min + self.x_max)

    @property
    def y(self) -> float:
        return 0.5 * (self.y_min + self.y_max)

    @property
    def trunk_r(self) -> float:
        return math.hypot(0.5 * (self.x_max - self.x_min), 0.5 * (self.y_max - self.y_min))

    @property
    def crown_r(self) -> float:
        return self.trunk_r

    def _high_enough(self, z: float) -> bool:
        return self.z_bottom - self.VERTICAL_MARGIN_M <= z <= self.z_top + self.VERTICAL_MARGIN_M

    def radius_at(self, z: float) -> Optional[float]:
        """The circle that covers the rectangle, at height z (None above or below it): for the callers that plan round circles."""
        return self.trunk_r if self._high_enough(z) else None

    def blocks_point(self, x: float, y: float, z: float, margin: float = 0.0) -> bool:
        return (self._high_enough(z) and self.x_min - margin < x < self.x_max + margin
                and self.y_min - margin < y < self.y_max + margin)

    def blocks_segment(self, a: Tuple[float, float, float], b: Tuple[float, float, float], margin: float = 0.0,
                       step: float = 0.5, skip_start_m: float = 2.0) -> bool:
        """True if the straight line a-b passes through the box. The first `skip_start_m` metres are not tested, so an aircraft that
        already stands inside the margin can leave."""
        length = math.dist(a, b)
        n = max(1, int(length / step))
        for i in range(n + 1):
            f = i / n
            if f * length < skip_start_m and f < 1.0:
                continue
            if self.blocks_point(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, margin):
                return True
        return False

    def rect_at(self, z: float) -> Optional[Tuple[float, float, float, float]]:
        return (self.x_min, self.x_max, self.y_min, self.y_max) if self._high_enough(z) else None

    def rects_at(self, z: float, strips: int = 8) -> list:
        """The rectangle at height z, for a leg planner that only knows rectangles (it is one already)."""
        r = self.rect_at(z)
        return [] if r is None else [r]


@dataclass(frozen=True)
class BoxKeepOut:
    """A rectangle in the horizontal plane at every height (a no-fly zone that is on right now, padded)."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def blocks_point(self, x: float, y: float, z: float = 0.0, margin: float = 0.0) -> bool:
        return (self.x_min - margin < x < self.x_max + margin) and (self.y_min - margin < y < self.y_max + margin)

    def blocks_segment(self, a, b, margin: float = 0.0, step: float = 0.5, skip_start_m: float = 2.0) -> bool:
        """True if the straight line a-b passes through the rectangle. The first `skip_start_m` metres are not tested, so an
        aircraft that is already inside can leave."""
        length = math.dist(a[:2], b[:2])
        n = max(1, int(length / step))
        for i in range(n + 1):
            f = i / n
            if f * length < skip_start_m and f < 1.0:
                continue
            if self.blocks_point(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 0.0, margin):
                return True
        return False

    def detour_path(self, a, b, margin: float = 0.0, clearance: float = 1.0):
        """Waypoints (x, y, z) that take the aircraft from a to b round the rectangle by way of one corner, or two neighbouring
        ones, of the rectangle grown by margin + clearance; the shortest way that never enters the rectangle grown by margin."""
        g = margin + clearance
        corners = [(self.x_min - g, self.y_min - g), (self.x_max + g, self.y_min - g),
                   (self.x_max + g, self.y_max + g), (self.x_min - g, self.y_max + g)]
        z = b[2]
        options = [[c] for c in corners] + [[corners[i], corners[(i + 1) % 4]] for i in range(4)] + \
                  [[corners[(i + 1) % 4], corners[i]] for i in range(4)]
        best = None
        for option in options:
            pts = [(a[0], a[1])] + option + [(b[0], b[1])]
            if any(self._crosses(pts[i], pts[i + 1], margin) for i in range(len(pts) - 1)):
                continue
            length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            if best is None or length < best[0]:
                best = (length, option)
        chosen = best[1] if best else [corners[0], corners[1]]
        return [(c[0], c[1], z) for c in chosen]

    def _crosses(self, p, q, margin: float) -> bool:
        length = math.dist(p, q)
        n = max(1, int(length / 0.25))
        return any(self.blocks_point(p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n, 0.0, margin) for i in range(n + 1))
