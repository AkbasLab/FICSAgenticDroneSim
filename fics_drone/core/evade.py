"""Stepping out of the way of a moving body, for an aircraft that is hovering or creeping along (at a target, held up in a crowd).

The leg planner keeps clear of movers while it flies at speed, but when the aircraft is waiting on a target, or crawling the last metres
of a leg, nothing moved it out of the way: a pedestrian or a car could walk or drive straight into it. `evasion_velocity` looks ahead
a couple of seconds at where every nearby body will be and, if any will come within `clear_m` of the aircraft's edge, returns a
horizontal velocity that takes the aircraft away from it (sideways for a fast body, so it is not run along the road ahead of it)."""
import math
from typing import Callable, Optional, Sequence, Tuple

from .moving import MovingObject
from .scenario import DRONE_RADIUS_M

EVADE_SPEED_MPS = 1.6
EVADE_HORIZON_S = 2.0
EVADE_CLEAR_M = 1.3          # gap between the body's edge and the aircraft's edge below which the aircraft moves
EVADE_STEP_S = 0.25
VERTICAL_PAD_M = 4.0         # a body this far below the aircraft is no threat (same rule the guardian and planner use)


def _closest_approach(px: float, py: float, body: MovingObject, horizon_s: float, step_s: float, drone_r: float):
    """(smallest edge gap, the time it happens, the body's position then) over the look-ahead."""
    best = (float("inf"), 0.0, (body.x, body.y))
    n = max(1, int(horizon_s / step_s))
    for i in range(n + 1):
        t = i * step_s
        b = body.at(t)
        gap = math.hypot(px - b.x, py - b.y) - b.reach(px, py) - drone_r
        if gap < best[0]:
            best = (gap, t, (b.x, b.y))
    return best


def evasion_velocity(pos: Tuple[float, float, float], movers: Sequence[MovingObject], speed_mps: float = EVADE_SPEED_MPS,
                     horizon_s: float = EVADE_HORIZON_S, clear_m: float = EVADE_CLEAR_M, drone_r: float = DRONE_RADIUS_M,
                     vertical_pad_m: float = VERTICAL_PAD_M,
                     blocked_fn: Optional[Callable[[float, float], bool]] = None) -> Optional[Tuple[float, float]]:
    """pos is the aircraft's world (x, y, z). Returns (vx, vy) to step away, or None when nothing will come within clear_m.
    blocked_fn(x, y) says a point is inside something solid (a wall, a trunk): the escape direction is turned to avoid it."""
    px, py, pz = pos
    push_x = push_y = 0.0
    worst = float("inf")
    for body in movers:
        if pz >= body.height + vertical_pad_m:
            continue
        if math.hypot(px - body.x, py - body.y) > 15.0 + body.speed * horizon_s:
            continue
        gap, when, (bx, by) = _closest_approach(px, py, body, horizon_s, EVADE_STEP_S, drone_r)
        if gap >= clear_m:
            continue
        worst = min(worst, gap)
        dx, dy = px - bx, py - by
        d = math.hypot(dx, dy)
        if d < 1e-6:                       # exactly on it: leave across its path
            dx, dy, d = -body.vy, body.vx, max(body.speed, 1e-6)
        ux, uy = dx / d, dy / d
        if body.speed > 2.0:               # a car: leave sideways, not along the road in front of it
            hx, hy = body.vx / body.speed, body.vy / body.speed
            along = ux * hx + uy * hy
            ux, uy = ux - along * hx, uy - along * hy
            n = math.hypot(ux, uy)
            if n < 1e-3:                   # dead in line with it: pick a side
                ux, uy = -hy, hx
            else:
                ux, uy = ux / n, uy / n
        weight = (clear_m - gap) / clear_m + 0.2
        push_x += ux * weight
        push_y += uy * weight
    if worst == float("inf"):
        return None
    n = math.hypot(push_x, push_y)
    if n < 1e-6:
        return None
    ux, uy = push_x / n, push_y / n
    if blocked_fn is not None:
        for turn in (0.0, 0.6, -0.6, 1.2, -1.2, 1.9, -1.9):       # turn the escape away from a solid thing
            c, s = math.cos(turn), math.sin(turn)
            vx, vy = ux * c - uy * s, ux * s + uy * c
            if not blocked_fn(px + vx * 1.5, py + vy * 1.5):
                ux, uy = vx, vy
                break
        else:
            return None
    scale = speed_mps * (1.0 if worst < 0.5 else 0.7)
    return ux * scale, uy * scale
