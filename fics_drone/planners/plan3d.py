"""A route through the keep-outs in three dimensions: round, over or under, whichever is shortest.

`street_path.plan_around` plans at one height. For a target on a roof that is the roof's height, where the crowns of the trees along the
street form a wall, so it finds no way round and the agent climbs over everything (25 m up and 25 m down for a 13 m roof). This plans on a
grid of heights too, so the route rises on the way to the roof, goes between trees where there is room and over them only where there is none.
The result is a short list of stops; every straight run between them is checked against the keep-outs, the way the guardian checks them."""

import heapq
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float, float]
PULL_SLACK_M = 0.4           # the stops are kept unless a run that skips them clears every keep-out by this much more than the margin
VERTICAL_COST = 1.4          # a metre of climb or descent costs this much more than a metre flown level (the aircraft climbs slower)


def _occupancy(obstacles: Sequence, x0: float, y0: float, z0: float, nx: int, ny: int, nz: int, cell: float, gap: float, gap_z: float):
    occ = np.zeros((nx, ny, nz), dtype=bool)
    xs = x0 + np.arange(nx) * cell
    ys = y0 + np.arange(ny) * cell
    zs = z0 + np.arange(nz) * cell
    for o in obstacles:
        if hasattr(o, "x_min"):
            cx, cy = 0.5 * (o.x_min + o.x_max), 0.5 * (o.y_min + o.y_max)
            r = 0.5 * math.hypot(o.x_max - o.x_min, o.y_max - o.y_min) + gap
        else:
            cx, cy, r = o.x, o.y, getattr(o, "crown_r", 0.0) + gap
        if not (x0 - r <= cx <= x0 + nx * cell + r and y0 - r <= cy <= y0 + ny * cell + r):
            continue
        i0, i1 = max(0, int((cx - r - x0) / cell)), min(nx, int((cx + r - x0) / cell) + 2)
        j0, j1 = max(0, int((cy - r - y0) / cell)), min(ny, int((cy + r - y0) / cell) + 2)
        if hasattr(o, "x_min"):          # a box: fill its inflated extent (a keep-out zone without heights is a column)
            ii = np.nonzero((xs[i0:i1] > o.x_min - gap) & (xs[i0:i1] < o.x_max + gap))[0] + i0
            jj = np.nonzero((ys[j0:j1] > o.y_min - gap) & (ys[j0:j1] < o.y_max + gap))[0] + j0
            if hasattr(o, "z_bottom"):
                kk = np.nonzero((zs >= o.z_bottom - gap_z) & (zs <= o.z_top + gap_z))[0]
            else:
                kk = np.arange(nz)
            if len(ii) and len(jj) and len(kk):
                occ[np.ix_(ii, jj, kk)] = True
        else:                             # a round tree: ask the obstacle itself
            for i in range(i0, i1):
                for j in range(j0, j1):
                    for k in range(nz):
                        if not occ[i, j, k] and o.blocks_point(float(xs[i]), float(ys[j]), float(zs[k]), gap):
                            occ[i, j, k] = True
    return occ


def plan_3d(start: Point, goal: Point, obstacles: Sequence, margin: float, bounds: Tuple[float, float, float, float],
            z_range: Tuple[float, float] = (0.8, 30.0), cell: float = 1.5, pad: float = 14.0, extra: float = 0.5,
            free_start_m: float = 3.0) -> Optional[List[Point]]:
    """Stops (x, y, z) from start to goal, the last being the goal; None if there is no route inside `bounds` (x_min, x_max, y_min, y_max).
    Cells within free_start_m of the start are open, so an aircraft standing inside a keep-out's margin can leave."""
    gap, gap_z = margin + extra, 1.0
    zlo = min(z_range[0], start[2], goal[2])
    zhi = max(z_range[1], start[2], goal[2])
    x0 = max(bounds[0], min(start[0], goal[0]) - pad)
    x1 = min(bounds[1], max(start[0], goal[0]) + pad)
    y0 = max(bounds[2], min(start[1], goal[1]) - pad)
    y1 = min(bounds[3], max(start[1], goal[1]) + pad)
    nx, ny, nz = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1, int((zhi - zlo) / cell) + 1
    if nx < 2 or ny < 2 or nz < 1:
        return None
    occ = _occupancy(obstacles, x0, y0, zlo, nx, ny, nz, cell, gap, gap_z)

    def cell_of(p):
        return (min(nx - 1, max(0, round((p[0] - x0) / cell))), min(ny - 1, max(0, round((p[1] - y0) / cell))),
                min(nz - 1, max(0, round((p[2] - zlo) / cell))))

    def centre(c):
        return (x0 + c[0] * cell, y0 + c[1] * cell, zlo + c[2] * cell)

    s, g = cell_of(start), cell_of(goal)
    for o in obstacles:      # the goal itself must be clear of everything
        if o.blocks_point(goal[0], goal[1], goal[2], margin):
            return None
    free_r = int(free_start_m / cell) + 1
    occ[max(0, s[0] - free_r):s[0] + free_r + 1, max(0, s[1] - free_r):s[1] + free_r + 1, max(0, s[2] - 1):s[2] + 2] = False
    occ[g] = False
    moves = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)]
    step_cost = {m: math.sqrt(m[0] ** 2 + m[1] ** 2 + (VERTICAL_COST * m[2]) ** 2) * cell for m in moves}
    h = lambda c: math.sqrt((c[0] - g[0]) ** 2 + (c[1] - g[1]) ** 2 + (VERTICAL_COST * (c[2] - g[2])) ** 2) * cell
    best = {s: 0.0}
    came = {}
    heap = [(h(s), 0.0, s)]
    done = set()
    while heap:
        _, cost, cur = heapq.heappop(heap)
        if cur in done:
            continue
        done.add(cur)
        if cur == g:
            break
        for m in moves:
            nb = (cur[0] + m[0], cur[1] + m[1], cur[2] + m[2])
            if not (0 <= nb[0] < nx and 0 <= nb[1] < ny and 0 <= nb[2] < nz) or occ[nb] or nb in done:
                continue
            if m[0] and m[1] and (occ[cur[0] + m[0], cur[1], cur[2]] or occ[cur[0], cur[1] + m[1], cur[2]]):
                continue                  # no squeezing diagonally between two blocked cells
            c = cost + step_cost[m]
            if c < best.get(nb, 1e18):
                best[nb] = c
                came[nb] = cur
                heapq.heappush(heap, (c + h(nb), c, nb))
    if g not in done:
        return None
    cells = [g]
    while cells[-1] != s:
        cells.append(came[cells[-1]])
    cells.reverse()
    pts = [start] + [centre(c) for c in cells[1:-1]] + [goal]
    return _pull_string(pts, obstacles, margin + PULL_SLACK_M)      # runs with room to spare: the aircraft passes a stop 1.5-3 m off it, so the next run starts off the line


def _pull_string(pts: List[Point], obstacles: Sequence, margin: float) -> List[Point]:
    """Drops the stops a straight run can skip (the run is judged the way the guardian judges it), so the route is a few long runs."""
    def run_ok(a, b):
        return not any(o.blocks_segment(a, b, margin=margin) for o in obstacles)
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not run_ok(pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return out[1:]


def route_length(start: Point, stops: Sequence[Point]) -> float:
    pts = [start, *stops]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
