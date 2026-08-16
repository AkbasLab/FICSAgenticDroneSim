"""Small 2D/3D geometry helpers for the mission layer.

Kept dependency-free (pure math) so tests and CI don't need anything extra.
Coverage, detection, restricted-zone and separation checks all build on these.
"""

import math
from typing import List, Tuple

Point2 = Tuple[float, float]


def point_in_polygon(x: float, y: float, polygon: List[Point2]) -> bool:
    """Ray-casting point-in-polygon test (polygon = list of (x, y) vertices)."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and \
                (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def dist_point_to_segment(px, py, ax, ay, bx, by) -> float:
    """Shortest distance from point P to segment AB, in 2D (horizontal)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def segment_length_within_radius(px, py, ax, ay, bx, by, radius) -> float:
    """Length of segment AB (2D) that lies within `radius` of point P.

    Used for the observation-period check: how long a drone travelling AB stays
    within a target's detection radius (length / speed = time in view).
    """
    seg_len = math.hypot(bx - ax, by - ay)
    if seg_len == 0:
        return 0.0 if math.hypot(px - ax, py - ay) > radius else 0.0
    # sample the segment and count the portion inside the radius
    samples = max(2, int(seg_len))  # ~1 m resolution
    inside = 0
    for i in range(samples + 1):
        t = i / samples
        cx, cy = ax + t * (bx - ax), ay + t * (by - ay)
        if math.hypot(px - cx, py - cy) <= radius:
            inside += 1
    return (inside / (samples + 1)) * seg_len


class Rect:
    """Axis-aligned rectangle (a search sector footprint)."""

    def __init__(self, min_x, min_y, max_x, max_y):
        self.min_x, self.min_y = min_x, min_y
        self.max_x, self.max_y = max_x, max_y

    def contains(self, x, y) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    @property
    def polygon(self):
        return [(self.min_x, self.min_y), (self.max_x, self.min_y),
                (self.max_x, self.max_y), (self.min_x, self.max_y)]
