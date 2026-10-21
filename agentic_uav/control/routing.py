"""Shortest routes on the map that keep clear of restricted zones (AUV-05, 4.1).

    path = route((8, 0), (120, -72), zones)       # [(8, 0), (12.8..., -17.0...), (120, -72)]

A visibility graph: the nodes are the start, the goal and every zone's
corners pushed out by the clearance; an edge joins two nodes when the
straight line between them keeps out of every zone grown by the clearance;
the route is the shortest path through it (Dijkstra). For convex zones that
is the shortest clear route. A concave corner may become a node too; no
shortest route turns there, so it is never used. Pure geometry: x, y in map metres, no heights.

THE CLEARANCE is kept along the whole route, not only at the corners: edges
are tested against each zone grown outward by it, and the nodes sit a little
beyond that so they are never on its boundary. Zones are grown by mitring
each corner; a concave corner is grown approximately.
"""

from __future__ import annotations

import heapq
import math

from ..core.geometry import Polygon

Point2 = tuple[float, float]
NODE_MARGIN = 1.05            # nodes this far beyond the clearance, off the grown boundary


class NoRouteError(ValueError):
    """No route keeps clear of the zones."""


def _ccw(vertices: tuple[Point2, ...]) -> tuple[Point2, ...]:
    signed = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]))
    return vertices if signed > 0 else tuple(reversed(vertices))


def _grow(polygon: Polygon, by: float) -> list[Point2]:
    """Every corner moved outward by `by`, mitred: each edge moves `by` along its normal."""
    v = _ccw(polygon.vertices)
    n = len(v)
    out = []
    for i in range(n):
        p, c, q = v[i - 1], v[i], v[(i + 1) % n]
        e1 = (c[0] - p[0], c[1] - p[1])
        e2 = (q[0] - c[0], q[1] - c[1])
        l1, l2 = math.hypot(*e1), math.hypot(*e2)
        n1 = (e1[1] / l1, -e1[0] / l1)                 # outward normal of p->c, for a ccw polygon
        n2 = (e2[1] / l2, -e2[0] / l2)
        k = by / (1.0 + n1[0] * n2[0] + n1[1] * n2[1])
        out.append((c[0] + k * (n1[0] + n2[0]), c[1] + k * (n1[1] + n2[1])))
    return out


def grown(polygon: Polygon, clearance_m: float) -> Polygon:
    """`polygon` grown outward by `clearance_m`."""
    return polygon if clearance_m <= 0 else Polygon(tuple(_grow(polygon, clearance_m)))


def clear(a: Point2, b: Point2, obstacles: list[Polygon]) -> bool:
    return not any(o.crosses(a, b) for o in obstacles)


def route(start: Point2, goal: Point2, zones: list[Polygon] | tuple[Polygon, ...],
          clearance_m: float = 2.0) -> list[Point2]:
    """The shortest route from `start` to `goal` keeping `clearance_m` from every zone."""
    obstacles = [grown(z, clearance_m) for z in zones]
    for name, p in (("start", start), ("goal", goal)):
        if any(o.contains(*p) for o in obstacles):
            raise NoRouteError(f"the {name} {p} is within {clearance_m} m of a restricted zone")
    if clear(start, goal, obstacles):
        return [start, goal]
    # A corner that falls inside another grown zone joins nothing: every edge
    # to it would cross that zone, so `clear` keeps it out of any route.
    nodes: list[Point2] = [start, goal] + [c for z in zones for c in _grow(z, clearance_m * NODE_MARGIN)]
    best = {0: 0.0}
    previous: dict[int, int] = {}
    queue = [(0.0, 0)]
    done = set()
    while queue:
        d, i = heapq.heappop(queue)
        if i in done:
            continue
        done.add(i)
        if i == 1:
            break
        for j, node in enumerate(nodes):
            if j in done or not clear(nodes[i], node, obstacles):
                continue
            nd = d + math.dist(nodes[i], node)
            if nd < best.get(j, math.inf):
                best[j] = nd
                previous[j] = i
                heapq.heappush(queue, (nd, j))
    if 1 not in best:
        raise NoRouteError(f"no route from {start} to {goal} keeps {clearance_m} m from the zones")
    path, i = [nodes[1]], 1
    while i != 0:
        i = previous[i]
        path.append(nodes[i])
    return path[::-1]


def length(path: list[Point2]) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))
