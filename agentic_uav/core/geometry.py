"""Shapes on the map: rectangles and polygons, in metres, x and y only.

Pure, so it is tested without a simulator. Heights are not geometry here:
everything above the ground is the navigation module's business.

`Region` came from `control/navigation.py` in Phase 4, unchanged, when the
scenario's sectors needed it; `navigation` still exports it, the same class.
`Polygon` is new, for AUV-05's restricted regions.
"""

from __future__ import annotations

from dataclasses import dataclass


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

    @property
    def area(self) -> float:
        return (self.x_max - self.x_min) * (self.y_max - self.y_min)

    def overlaps(self, other: "Region") -> bool:
        """True if the two share any area (touching edges do not count)."""
        return (self.x_min < other.x_max and other.x_min < self.x_max
                and self.y_min < other.y_max and other.y_min < self.y_max)


@dataclass(frozen=True)
class Polygon:
    """A simple polygon on the map, vertices in order, not closed."""

    vertices: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        vertices = tuple((float(x), float(y)) for x, y in self.vertices)
        object.__setattr__(self, "vertices", vertices)
        if len(vertices) < 3:
            raise ValueError("a polygon needs at least three vertices")
        if abs(self.area) == 0.0:
            raise ValueError("a polygon must enclose some area")

    @property
    def area(self) -> float:
        """Unsigned area (shoelace)."""
        total = 0.0
        n = len(self.vertices)
        for i in range(n):
            x1, y1 = self.vertices[i]
            x2, y2 = self.vertices[(i + 1) % n]
            total += x1 * y2 - x2 * y1
        return abs(total) / 2.0

    def bounds(self) -> Region:
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        return Region(min(xs), min(ys), max(xs), max(ys))

    def edges(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        n = len(self.vertices)
        return [(self.vertices[i], self.vertices[(i + 1) % n]) for i in range(n)]

    def contains(self, x: float, y: float) -> bool:
        """Inside or on the boundary. Ray casting, with the boundary included."""
        for a, b in self.edges():
            if _on_segment((x, y), a, b):
                return True
        inside = False
        for (x1, y1), (x2, y2) in self.edges():
            if (y1 > y) != (y2 > y):
                crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < crossing:
                    inside = not inside
        return inside

    def crosses(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        """Whether the straight path from `start` to `end` enters the polygon."""
        if self.contains(*start) or self.contains(*end):
            return True
        return any(_segments_intersect(start, end, a, b) for a, b in self.edges())

    def entry_fraction(self, start: tuple[float, float], end: tuple[float, float],
                       eps: float = 1e-9) -> float | None:
        """How far along the path from `start` to `end` it first enters, 0..1; None if never.

        0 when `start` is already inside. Touching the boundary counts as
        entering, as it does for `contains` and `crosses`.
        """
        if self.contains(*start):
            return 0.0
        if not self.crosses(start, end):
            return None
        dx, dy = end[0] - start[0], end[1] - start[1]
        best = 1.0
        for a, b in self.edges():
            ex, ey = b[0] - a[0], b[1] - a[1]
            wx, wy = a[0] - start[0], a[1] - start[1]
            denom = dx * ey - dy * ex
            if denom == 0.0:
                # Parallel. Only a path along the edge's own line meets it:
                # first at whichever of the edge's ends comes first.
                if abs(_cross(start, end, a)) > eps:
                    continue
                length2 = dx * dx + dy * dy
                for q in (a, b):
                    s = ((q[0] - start[0]) * dx + (q[1] - start[1]) * dy) / length2
                    if -eps <= s <= 1.0 + eps:
                        best = min(best, max(0.0, s))
                continue
            s = (wx * ey - wy * ex) / denom          # along the path
            u = (wx * dy - wy * dx) / denom          # along the edge
            if -eps <= s <= 1.0 + eps and -eps <= u <= 1.0 + eps:
                best = min(best, max(0.0, s))
        return best


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p, a, b, eps: float = 1e-9) -> bool:
    if abs(_cross(a, b, p)) > eps:
        return False
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def _segments_intersect(p1, p2, q1, q2) -> bool:
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (_on_segment(p1, q1, q2) or _on_segment(p2, q1, q2)
            or _on_segment(q1, p1, p2) or _on_segment(q2, p1, p2))
