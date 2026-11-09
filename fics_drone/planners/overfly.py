"""Flying over a tree instead of round it.

NavRL (our leg planner) only steers sideways, at one fixed height. The agent already knows how tall each tree is, so when a
straight leg is blocked by trees it can climb above the tallest blocker, cross, and come back down. This module only decides
the height; the agent flies the three parts (climb, cross, descend)."""

import math
from typing import Optional, Sequence, Tuple

TEAMMATE_TOP_M = 500.0     # a teammate's keep-out is a column to +/-1000 m: nothing is flown over that


def overfly_altitude(start: Tuple[float, float, float], goal: Tuple[float, float, float], obstacles: Sequence, margin: float,
                     clearance: float = 3.0, max_extra: float = 15.0) -> Optional[float]:
    """The lowest height z (above the higher of start and goal, at most max_extra above it) at which the path
    climb straight up from start, fly level to above the goal, descend to the goal misses every obstacle by `margin` (and the
    level part by `clearance` more).
    Candidate heights are just above a tree's top (top + clearance). None if no height within the limit works: a zone, a
    teammate, or a tree that is too tall."""
    if max_extra <= 0.0:
        return None
    base = max(start[2], goal[2])
    tops = set()
    for o in obstacles:
        top = getattr(o, "z_top", None)
        if top is None or top >= TEAMMATE_TOP_M:
            continue
        z = top + clearance
        if base < z <= base + max_extra:
            tops.add(round(z, 3))
    for z in sorted(tops):
        up = (start[0], start[1], z)
        over = (goal[0], goal[1], z)
        # the crossing is tested `clearance` lower than it is flown, so a height that only clears a tree by being a hair above
        # its top (because another tree's top + clearance happened to land there) is refused; the climb ends up to a tolerance short
        # of z and the crossing then slopes, so without that margin it can dip into the tree (seen live, 2026-11-08)
        lo = z - clearance + 0.01      # (a tree is clear only strictly above its top)
        low_a, low_b = (start[0], start[1], lo), (goal[0], goal[1], lo)
        parts = ((start, up), (low_a, low_b), (over, goal))
        if not any(o.blocks_segment(a, b, margin=margin, skip_start_m=0.0) for o in obstacles for a, b in parts):
            return z
    return None


def overfly_cost_s(start, goal, z: float, climb_mps: float) -> float:
    """Extra seconds a climb to z and back down costs, against flying level."""
    return ((z - start[2]) + (z - goal[2])) / climb_mps


def detour_cost_s(start, spots, goal, speed_mps: float) -> float:
    """Extra seconds a detour through `spots` costs over the straight line, at the speed live legs actually average."""
    pts = [start, *spots, goal]
    length = sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:]))
    return max(0.0, length - math.dist(start[:2], goal[:2])) / speed_mps
