"""A way round keep-outs where they stand thick, as in a street scenario.

The ring detour in the agent (one tree at a time) lands inside the next tree when keep-outs are packed along a road. This
plans on a small grid over the leg: every cell that any keep-out blocks is closed, and the shortest way through the open cells
is found, with straight stretches merged. Pure Python; the keep-outs only need `blocks_point(x, y, z, margin)`.
"""

import heapq
import math
from typing import List, Optional, Sequence, Tuple


def _reach(obstacle) -> Optional[Tuple[float, float, float, float]]:
    """(x_min, x_max, y_min, y_max) of everything this keep-out can block, or None if it does not say."""
    if hasattr(obstacle, "x_min"):
        return obstacle.x_min, obstacle.x_max, obstacle.y_min, obstacle.y_max
    if hasattr(obstacle, "trunk_r"):
        r = max(obstacle.trunk_r, obstacle.crown_r)
        return obstacle.x - r, obstacle.x + r, obstacle.y - r, obstacle.y + r
    return None


def _escape_radius(start, z, obstacles, gap, step: float = 0.5, limit: float = 10.0) -> float:
    """How far from `start` the nearest ring of points that no keep-out blocks lies (0 if the start itself is clear)."""
    if not any(o.blocks_point(start[0], start[1], z, gap) for o in obstacles):
        return 0.0
    radius = step
    while radius <= limit:
        for k in range(16):
            a = k * math.pi / 8
            if not any(o.blocks_point(start[0] + radius * math.cos(a), start[1] + radius * math.sin(a), z, gap) for o in obstacles):
                return radius
        radius += step
    return limit


def plan_around(start: Tuple[float, float, float], goal: Tuple[float, float, float], obstacles: Sequence, margin: float,
                cell: float = 1.0, pad: float = 12.0, extra: float = 0.5, free_start_m: float = 2.5
                ) -> Optional[List[Tuple[float, float, float]]]:
    """Waypoints (x, y, z) from `start` to `goal` that keep `margin + extra` clear of every obstacle, the last one being the goal;
    None if the goal is blocked or no way round exists inside the area searched. Cells within `free_start_m` of the start are
    open, so an aircraft that stands inside a keep-out can still leave."""
    z = goal[2]
    gap = margin + extra
    x0, x1 = min(start[0], goal[0]) - pad, max(start[0], goal[0]) + pad
    y0, y1 = min(start[1], goal[1]) - pad, max(start[1], goal[1]) + pad
    near = []
    for o in obstacles:
        box = _reach(o)
        if box is None or (box[1] + gap >= x0 and box[0] - gap <= x1 and box[3] + gap >= y0 and box[2] - gap <= y1):
            near.append(o)
    if any(o.blocks_point(goal[0], goal[1], z, margin) for o in near):
        return None
    # an aircraft that stands inside a keep-out's margin may leave: cells out to the depth it is in (plus a metre) are open
    # round it, and everything beyond stays closed, so no waypoint is placed inside a keep-out
    free_start_m = max(free_start_m, _escape_radius(start, z, near, gap) + 1.0)
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    closed = {}

    def is_closed(i, j):
        key = (i, j)
        if key not in closed:
            px, py = x0 + i * cell, y0 + j * cell
            closed[key] = (math.hypot(px - start[0], py - start[1]) > free_start_m
                           and any(o.blocks_point(px, py, z, gap) for o in near))
        return closed[key]

    def fully_closed(p):
        return any(o.blocks_point(p[0], p[1], z, gap) for o in near)

    def cell_of(p):
        return int(round((p[0] - x0) / cell)), int(round((p[1] - y0) / cell))

    s, g = cell_of(start), cell_of(goal)
    if not (0 <= g[0] < nx and 0 <= g[1] < ny):
        return None

    def sees(a, b):
        n = max(1, int(math.dist(a, b) / (cell * 0.5)))
        return not any(is_closed(*cell_of((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))) for k in range(n + 1))

    if sees(start, goal):
        return [goal]
    dist, prev, heap = {s: 0.0}, {}, [(0.0, 0.0, s)]
    found = False
    while heap:
        _, d, u = heapq.heappop(heap)
        if u == g:
            found = True
            break
        if d > dist[u]:
            continue
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            v = (u[0] + di, u[1] + dj)
            if not (0 <= v[0] < nx and 0 <= v[1] < ny) or (v != g and is_closed(*v)):
                continue
            nd = d + math.hypot(di, dj)
            if nd < dist.get(v, 1e18):
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd + math.hypot(v[0] - g[0], v[1] - g[1]), nd, v))
    if not found:
        return None
    cells = [g]
    while cells[-1] != s:
        cells.append(prev[cells[-1]])
    pts = [(x0 + i * cell, y0 + j * cell) for i, j in reversed(cells)]
    pts[0], pts[-1] = (start[0], start[1]), (goal[0], goal[1])
    out, k = [], 0
    while k < len(pts) - 1:
        far = None
        for m in range(len(pts) - 1, k, -1):
            # a waypoint is never in a keep-out's margin (the cells round the start are open to pass through, not to stop in)
            if sees(pts[k], pts[m]) and (m == len(pts) - 1 or not fully_closed(pts[m])):
                far = m
                break
        if far is None:
            # nothing clear is in sight: the first cell of the path that is clear, passing through the open cells round the start
            far = next((m for m in range(k + 1, len(pts) - 1) if not fully_closed(pts[m])), len(pts) - 1)
        out.append((pts[far][0], pts[far][1], z))
        k = far
    return out
