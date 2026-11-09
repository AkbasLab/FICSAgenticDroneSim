"""Builds a street-level scenario from the dumps of the sim's road network (road_graph.json) and objects (map_objects.json).

What it writes (one JSON, same shape as configs/missions/medium_001.json plus two things):
  obstacles      every pole, tree, wall and building that reaches the flight band near the roads, as keep-out circles
  search_routes  per sector, the road-following path a drone flies: out from its spawn, along every road in the sector

All coordinates are the drone-local map frame (CARLA minus (-172.2, 183.86)). Pure Python, no sim needed.
Usage: python make_street_scenario.py --id large_001 --bounds X0 X1 Y0 Y1 --cols C --rows R --out FILE
"""
import argparse
import heapq
import json
import math
import os
import random

CRUISE = 12.0
BAND_LO, BAND_HI = CRUISE - 3.0, CRUISE + 1.5   # an object matters if it reaches this band
CELL = 1.0
INFLATE_M = 2.5                                  # the route keeps this far from an obstacle's edge
HOME = os.path.expanduser("~")


def circles_for(name, r):
    """An object as keep-out circles. Poles and trees are one circle; walls and buildings are a row of circles along the long axis."""
    ex, ey = r["ex"], r["ey"]
    z0, z1 = max(r["z0"], 0.0), r["z1"]
    if name in ("Buildings", "Walls", "Fences", "GuardRail", "Bridge", "Static", "Other") and max(ex, ey) > 2.0:
        half, long_axis = (ey, 0) if ex >= ey else (ex, 1)   # radius = the short half-width
        half = max(half, 0.5)
        length = max(ex, ey)
        th = math.radians(r["yaw"] + (0 if long_axis == 0 else 90))
        n = max(1, int(math.ceil(2 * length / (1.2 * half))))
        out = []
        for i in range(n + 1):
            s = -length + 2 * length * i / n
            out.append((r["x"] + s * math.cos(th), r["y"] + s * math.sin(th), half, z0, z1))
        return out
    return [(r["x"], r["y"], max(ex, ey, 0.2) + 0.2, z0, z1)]


class Grid:
    def __init__(self, x0, x1, y0, y1, circles):
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int((x1 - x0) / CELL) + 1, int((y1 - y0) / CELL) + 1
        self.blocked = bytearray(self.nx * self.ny)
        self.clear = [99.0] * (self.nx * self.ny)    # distance to the nearest obstacle edge, capped
        for cx, cy, r, _, _ in circles:
            reach = r + 12.0
            for i in range(max(0, int((cx - reach - x0) / CELL)), min(self.nx, int((cx + reach - x0) / CELL) + 1)):
                for j in range(max(0, int((cy - reach - y0) / CELL)), min(self.ny, int((cy + reach - y0) / CELL) + 1)):
                    d = math.hypot(x0 + i * CELL - cx, y0 + j * CELL - cy) - r
                    k = i + j * self.nx
                    if d < self.clear[k]:
                        self.clear[k] = d
                    if d < INFLATE_M:
                        self.blocked[k] = 1

    def cell(self, x, y):
        return int(round((x - self.x0) / CELL)), int(round((y - self.y0) / CELL))

    def ok(self, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and not self.blocked[i + j * self.nx]

    def free_near(self, x, y, reach=4.0):
        """The free cell nearest (x, y) within `reach`, preferring the most clearance among equally near ones."""
        i0, j0 = self.cell(x, y)
        best = None
        for di in range(-int(reach), int(reach) + 1):
            for dj in range(-int(reach), int(reach) + 1):
                i, j = i0 + di, j0 + dj
                d = math.hypot(di, dj)
                if d <= reach and self.ok(i, j):
                    key = (round(d), -min(self.clear[i + j * self.nx], 6.0))
                    if best is None or key < best[0]:
                        best = (key, i, j)
        return None if best is None else (self.x0 + best[1] * CELL, self.y0 + best[2] * CELL)

    def sees(self, a, b):
        n = max(1, int(math.dist(a, b) / (CELL * 0.5)))
        return all(self.ok(*self.cell(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)) for k in range(n + 1))

    def path(self, a, b):
        """Shortest way from a to b through free cells, with straight stretches merged. None if there is none."""
        s, g = self.cell(*a), self.cell(*b)
        if not (self.ok(*s) and self.ok(*g)):
            return None
        if self.sees(a, b):
            return [a, b]
        dist, prev, heap = {s: 0.0}, {}, [(0.0, 0.0, s)]
        while heap:
            _, d, u = heapq.heappop(heap)
            if u == g:
                break
            if d > dist[u]:
                continue
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                v = (u[0] + di, u[1] + dj)
                if not self.ok(*v):
                    continue
                nd = d + math.hypot(di, dj)
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd + math.hypot(v[0] - g[0], v[1] - g[1]), nd, v))
        if g not in prev and g != s:
            return None
        cells = [g]
        while cells[-1] != s:
            cells.append(prev[cells[-1]])
        pts = [(self.x0 + i * CELL, self.y0 + j * CELL) for i, j in reversed(cells)]
        out = [pts[0]]                      # string pulling: keep a point only where the view from the last kept one ends
        k = 0
        while k < len(pts) - 1:
            far = k + 1
            for m in range(len(pts) - 1, k, -1):
                if self.sees(pts[k], pts[m]):
                    far = m
                    break
            out.append(pts[far])
            k = far
        return out


def road_points(roads, rect):
    """The road waypoints inside `rect` that a drone must pass close to: one carriageway per road (lane ids below zero where a
    road has them), no two closer than 2.5 m."""
    neg = {w["road"] for w in roads if w["lane"] < 0}
    x0, x1, y0, y1 = rect
    out = []
    for w in roads:
        if (w["lane"] < 0 or w["road"] not in neg) and x0 <= w["x"] < x1 and y0 <= w["y"] < y1:
            p = (w["x"], w["y"])
            if all(math.dist(p, q) >= 2.5 for q in out):
                out.append(p)
    return out


def sweep_route(grid, points, start, cover_m=4.0):
    """Goes to the nearest point not yet passed within cover_m, again and again, joining them by free-space paths; the
    route as a list of (x, y) and the number of points it could not reach."""
    todo, pos, route, skipped = list(points), start, [start], 0

    def passed(a, b):
        n = max(1, int(math.dist(a, b) / 2.0))
        return [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]

    while todo:
        todo.sort(key=lambda p: math.dist(pos, p))
        target = todo.pop(0)
        q = grid.free_near(*target, reach=3.0)
        link = grid.path(pos, q) if q is not None else None
        if link is None:
            skipped += 1
            continue
        for a, b in zip(link, link[1:]):
            trail = passed(a, b)
            todo = [p for p in todo if all(math.dist(p, t) > cover_m for t in trail)]
        route.extend(link[1:])
        pos = q
    return route, skipped


def thin(route, spacing=2.0):
    out = [route[0]]
    for p in route[1:]:
        if math.dist(out[-1], p) >= spacing or p is route[-1]:
            out.append(p)
    return [[round(x, 1), round(y, 1)] for x, y in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--bounds", type=float, nargs=4, required=True)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--rows", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lattice", type=float, default=0.0, help="also visit open ground on a grid of this spacing (m), for areas without roads")
    args = ap.parse_args()
    X0, X1, Y0, Y1 = args.bounds

    roads = json.load(open(f"{HOME}/road_graph.json"))
    roads = [w for w in roads if X0 <= w["x"] < X1 and Y0 <= w["y"] < Y1]
    objs = json.load(open(f"{HOME}/map_objects.json"))["objects"]
    pad = 25.0
    circles = []
    for name, rows in objs.items():
        if name == "Terrain":
            continue
        for r in rows:
            if r["z0"] <= BAND_HI and r["z1"] >= BAND_LO and X0 - pad <= r["x"] <= X1 + pad and Y0 - pad <= r["y"] <= Y1 + pad:
                circles += circles_for(name, r)
    print(f"{len(roads)} road waypoints, {len(circles)} obstacle circles")
    grid = Grid(X0 - pad, X1 + pad, Y0 - pad, Y1 + pad, circles)

    # sectors: a cols x rows grid over the bounds; the sector that holds a spawn gets that drone
    cw, rh = (X1 - X0) / args.cols, (Y1 - Y0) / args.rows
    sectors = []
    for r in range(args.rows):
        for c in range(args.cols):
            sectors.append({"id": "ABCDEFGHIJKL"[r * args.cols + c], "x_min": round(X0 + c * cw, 1), "x_max": round(X0 + (c + 1) * cw, 1),
                            "y_min": round(Y0 + r * rh, 1), "y_max": round(Y0 + (r + 1) * rh, 1)})
    routes, targets, spawn0 = {}, [], []
    rng = random.Random(args.seed)
    for k, s in enumerate(sectors):
        rect = (s["x_min"], s["x_max"], s["y_min"], s["y_max"])
        chains = road_points(roads, rect)
        if args.lattice > 0.0:
            gx = rect[0] + args.lattice / 2
            while gx < rect[1]:
                gy = rect[2] + args.lattice / 2
                while gy < rect[3]:
                    c = grid.cell(gx, gy)
                    if grid.ok(*c) and grid.clear[c[0] + c[1] * grid.nx] > 3.5 and all(math.dist((gx, gy), q) > args.lattice * 0.6 for q in chains):
                        chains.append((gx, gy))
                    gy += args.lattice
                gx += args.lattice
        # each drone starts on the roomiest road point of its own sector, so no two share a street on the way out
        roomy = max(chains, key=lambda p: min(grid.clear[grid.cell(*p)[0] + grid.cell(*p)[1] * grid.nx], 8.0) - 0.001 * math.dist(p, ((rect[0] + rect[1]) / 2, (rect[2] + rect[3]) / 2)))
        start = grid.free_near(*roomy, reach=2.0) or roomy
        spawn0.append(start)
        route, skipped = sweep_route(grid, chains, start)
        length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
        print(f"sector {s['id']}: {len(chains)} road points, route {length:.0f} m, {skipped} points skipped")
        routes[s["id"]] = thin(route)

    # a target for each sector, on that sector's own route and well away from every other drone's route: a drone that passes
    # another's target finds it and goes home, and its own is then never searched
    for k, sector in enumerate(sectors):
        rect = (sector["x_min"], sector["x_max"], sector["y_min"], sector["y_max"])
        own = routes[sector["id"]]
        others = [p for sid, r in routes.items() if sid != sector["id"] for p in r]
        mid = []
        for edge, room in ((8, 6.0), (4, 4.5), (1, 3.0)):     # strict first, then relax until the sector has somewhere
            mid = [tuple(p) for p in own[len(own) // 6: -(len(own) // 6) or None]
                   if rect[0] + edge <= p[0] <= rect[1] - edge and rect[2] + edge <= p[1] <= rect[3] - edge
                   and grid.clear[grid.cell(*p)[0] + grid.cell(*p)[1] * grid.nx] > room]
            if mid:
                break
        rng.shuffle(mid)
        pick = max(mid[:60], key=lambda p: min((math.dist(p, q) for q in others), default=99.0)) if mid else None
        if pick is None:
            raise SystemExit(f"no target spot in sector {sector['id']}")
        targets.append({"id": f"T{k + 1}", "x": round(pick[0], 1), "y": round(pick[1], 1), "detection_radius_m": 5.0, "dwell_s": 2.0})
        print(f"T{k + 1} at {pick}, nearest other route {min((math.dist(pick, q) for q in others), default=99.0):.0f} m")

    drones = [{"name": f"Drone{k + 1}", "battery_s": 900.0, "sector": sectors[k]["id"],
               "spawn_offset": [round(spawn0[k][0], 1), round(spawn0[k][1], 1), 0.0]} for k in range(6)]
    obstacles = [{"x": round(x, 2), "y": round(y, 2), "z_bottom": round(z0, 1), "z_top": round(z1, 1), "trunk_r": round(r, 2),
                  "crown_r": round(r, 2), "crown_from_frac": 0.0} for x, y, r, z0, z1 in circles]
    # the scenario's own frame: each drone's local (0, 0) is its spawn, so a route is stored in world coordinates
    longest = max(sum(math.dist(a, b) for a, b in zip(r, r[1:])) for r in routes.values())
    # a plan for the dynamic profile, over this scenario's own routes: a block that appears over T3 and expires, a box that drifts
    # west along a route of the fourth sector (clear of every spawn), and one that appears over T2 and stays
    spawns = [(p[0], p[1]) for p in spawn0]
    drift = None
    for sid in [sectors[3]["id"]] + [x["id"] for x in sectors]:
        for p in routes[sid][len(routes[sid]) // 4:]:
            box = (p[0] + 22.0, p[0] + 30.0, p[1] - 4.0, p[1] + 4.0)
            sweep = (box[0] - 60.0, box[1], box[2] - 6.0, box[3] + 6.0)
            if all(not (sweep[0] <= sx <= sweep[1] and sweep[2] <= sy <= sweep[3]) for sx, sy in spawns):
                drift = box
                break
        if drift:
            break
    t2, t3 = targets[1], targets[2]
    zone_plan = {"appear": [round(t3["x"] - 12, 1), round(t3["x"] + 12, 1), round(t3["y"] - 12, 1), round(t3["y"] + 12, 1)],
                 "drift": [round(v, 1) for v in drift] if drift else None,
                 "stay": [round(t2["x"] - 5, 1), round(t2["x"] + 5, 1), round(t2["y"] - 5, 1), round(t2["y"] + 5, 1)]}
    print("zone plan:", zone_plan)
    scenario = {"scenario_id": args.id, "random_seed": args.seed, "base_station": {"x": round(spawn0[0][0], 1), "y": round(spawn0[0][1], 1), "z": 0.0},
                "deadline_s": round(max(1500.0, longest / 3.0 * 2.0), 0), "comms_range_m": 400.0, "min_separation_m": 5.0,
                "required_coverage": 0.85, "mission_kind": "search", "drones": drones, "sectors": sectors, "targets": targets,
                "no_fly_zones": [{"id": "NFZ1", "x_min": X0 - 30.0, "x_max": X0 - 20.0, "y_min": Y0 - 30.0, "y_max": Y0 - 20.0}],
                "obstacles": obstacles, "search_routes": routes, "cruise_height": CRUISE, "zone_plan": zone_plan}
    json.dump(scenario, open(args.out, "w"))
    print("wrote", args.out, "longest route", round(longest), "m, deadline", scenario["deadline_s"], "s")


if __name__ == "__main__":
    main()
