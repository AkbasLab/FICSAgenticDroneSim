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
        # (a box keeps the aircraft 0.5 m clear above its top as well, so the crossing, tested `clearance` lower, only clears its own top at
        # top + clearance + 0.5 or more: without that candidate the lowest height that worked was set by some other, taller object)
        for z in (top + clearance, top + clearance + 0.6):
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
        parts = ((start, up), (low_a, low_b), (up, over), (over, goal))      # (up, over) is the crossing at the height it is flown: a crown whose underside is between lo and z passes the low test but not this one
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


def _dist_to_segment_xy(px: float, py: float, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def movers_on_leg(start, goal, movers: Sequence, corridor_m: float = 3.0, look_s: Sequence[float] = (0.0, 3.0, 6.0, 9.0)) -> list:
    """The vehicles and pedestrians that are on the straight way from start to goal, or will be within the next few seconds:
    their body (and the corridor beside the line) touches it at any of the look-ahead times."""
    if math.dist(start[:2], goal[:2]) < 1e-6:
        return []
    found = []
    for m in movers:
        for t in look_s:
            p = m.at(t)
            if _dist_to_segment_xy(p.x, p.y, start, goal) <= corridor_m + m.reach(p.x, p.y):
                found.append(m)
                break
    return found


def mover_overfly_altitude(start, goal, movers: Sequence, obstacles: Sequence, margin: float, vertical_pad_m: float = 4.0,
                           extra_m: float = 1.0, min_movers: int = 3, min_leg_m: float = 10.0, corridor_m: float = 3.0,
                           max_extra: float = 15.0) -> Optional[float]:
    """The height at which to cross a leg that vehicles and pedestrians are on, or None to go round them as before.

    The leg planner ignores a body once the aircraft is `vertical_pad_m` above its top, so the crossing is flown at the tallest
    such body's top + vertical_pad_m + extra_m. It is chosen only when at least `min_movers` bodies are on the way (a lone person
    is passed sideways), the leg is long enough to be worth a climb, the height is within `max_extra` of the start and goal, the
    aircraft is not already that high, and the climb, the level crossing and the descent are clear of every fixed obstacle."""
    if max_extra <= 0.0 or math.dist(start[:2], goal[:2]) < min_leg_m:
        return None
    on_leg = movers_on_leg(start, goal, movers, corridor_m)
    if len(on_leg) < min_movers:
        return None
    z0 = max(m.height for m in on_leg) + vertical_pad_m + extra_m
    base = max(start[2], goal[2])
    # the lowest height clears the bodies; if a fixed obstacle (a street tree, a pole) is in the way at that height, try just above
    # each such obstacle's top instead, as far up as max_extra allows
    tops = {round(getattr(o, "z_top") + extra_m + 1.0, 3) for o in obstacles
            if getattr(o, "z_top", None) is not None and o.z_top < TEAMMATE_TOP_M and z0 < o.z_top + extra_m + 1.0}
    for z in [z0] + sorted(tops):
        if start[2] >= z - 0.5 or z - base > max_extra:
            continue
        lo = z - 1.0 + 0.01
        parts = (((start[0], start[1], start[2]), (start[0], start[1], z)), ((start[0], start[1], lo), (goal[0], goal[1], lo)),
                 ((goal[0], goal[1], z), goal))
        if not any(o.blocks_segment(a, b, margin=margin, skip_start_m=0.0) for o in obstacles for a, b in parts):
            return z
    return None


def target_busy(goal, movers: Sequence, horizon_s: float, clearance_m: float = 3.0, step_s: float = 0.5) -> bool:
    """True if a vehicle or pedestrian will be on top of `goal` (within clearance_m of its body) at any moment in the next horizon_s
    seconds, going on at its present velocity. Used before coming down at a target: the descent takes seconds and the leg planner
    does not steer a vertical descent round a car that is still far off when it starts."""
    n = max(1, int(math.ceil(horizon_s / step_s)))
    for m in movers:
        for i in range(n + 1):
            p = m.at(i * step_s)
            if math.hypot(p.x - goal[0], p.y - goal[1]) <= clearance_m + m.reach(goal[0], goal[1]):
                return True
    return False
