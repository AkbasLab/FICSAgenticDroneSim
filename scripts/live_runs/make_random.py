import os
home = os.path.expanduser("~")
src = open(os.path.join(home, "live_big7.py")).read()
head = src.split("A, T1, T2 = parse(args.A), parse(args.T1), parse(args.T2)")[0]
head = head.replace('ap.add_argument("--A", default="240,-233.0")',
    'ap.add_argument("--targets", type=int, default=8, help="stop after this many targets (0 = until --max-seconds)")\n'
    'ap.add_argument("--max-seconds", type=float, default=240.0)\n'
    'ap.add_argument("--min-dist", type=float, default=14.0)\n'
    'ap.add_argument("--max-dist", type=float, default=45.0)\n'
    'ap.add_argument("--A", default="240,-233.0")')
head = head.replace('"""BIG filmed test:',
    '"""RANDOM TARGETS (like the NavRL demo): after take-off a green target appears somewhere sensible nearby; when the drone reaches it a new one '
    'appears, and so on. Same street scene as live_big7.py (crowd + traffic). Targets are drawn from points on the simulator navigation mesh '
    '(pavement) inside the mapped street area that are clear of every map keep-out.\n\nBIG filmed test:', 1)
head = head.replace("def __init__(self, x, y, r=3.0):\n        self.x, self.y, self.detection_radius_m = x, y, r",
                    "def __init__(self, x, y, r=3.0, z=0.0):\n        self.x, self.y, self.detection_radius_m, self.z = x, y, r, z")
head = head.replace("from fics_drone.core.map_geometry import load_region_obstacles", "from fics_drone.core.map_geometry import load_region_obstacles, default_labels")
head = head.replace("ground_z=GZ)\nprint(\"map keep-outs:\"", "ground_z=GZ, labels=default_labels() + [carla.CityObjectLabel.Car, carla.CityObjectLabel.Truck, carla.CityObjectLabel.Bus])\nprint(\"map keep-outs:\"")
_grow_src = (
    "import dataclasses\n"
    "def _grow(o):\n"
    "    n = getattr(o, 'name', '')\n"
    "    if 'InstancedFoliageActor' in n and 'crown' in n:      # the leaves drawn are wider and hang lower than the map box: the drone vanished under crowns\n"
    "        return dataclasses.replace(o, x_min=o.x_min - 0.5, x_max=o.x_max + 0.5, y_min=o.y_min - 0.5, y_max=o.y_max + 0.5, z_bottom=max(0.2, o.z_bottom - 3.0))\n"
    "    if 'InstancedFoliageActor' in n and 'trunk' in n:\n"
    "        return dataclasses.replace(o, x_min=o.x_min - 0.5, x_max=o.x_max + 0.5, y_min=o.y_min - 0.5, y_max=o.y_max + 0.5)\n"
    "    return o\n"
    "LIM.obstacles = [_grow(o) for o in LIM.obstacles]\n"
)
head = head.replace('print("map keep-outs:"', _grow_src + 'print("map keep-outs:"', 1)
head = head.replace('leg_timeout_s=300.0', 'leg_timeout_s=90.0')
# nobody starts on the drone's take-off spot: a pedestrian spawned on it walked into the aircraft at the start of a run
_a = "if not crowd.points or not crowd.add_walker(walker_bps[i % len(walker_bps)], crowd.points[(i * 7) % len(crowd.points)]):"
_b = chr(10).join([
    "_ax, _ay = [float(v) for v in args.A.split(',')]",
    "        _far = [p for p in crowd.points if math.hypot(p.x - SX - _ax, p.y - SY - _ay) > 10.0] or crowd.points",
    "        if not crowd.points or not crowd.add_walker(walker_bps[i % len(walker_bps)], _far[(i * 7) % len(_far)]):"])
assert _a in head
head = head.replace(_a, _b, 1)
tail = open(os.path.join(home, "rand_tail.txt")).read()
out_name = "live_random.py"
if os.environ.get("AUTONOMOUS") == "1":
    # autonomous crowd: cars change lanes by themselves, pedestrians roam the whole street area (crossing the road) choosing their own goals
    out_name = "live_random_auto.py"
    reps = [
        ("self.tm.auto_lane_change(car, False)", "self.tm.auto_lane_change(car, True)"),
        ("""        far = SIDEWALK[1] - 2.0 if loc.x - SX < (SIDEWALK[0] + SIDEWALK[1]) / 2 else SIDEWALK[0] + 2.0
        y = min(max(loc.y - SY + self.rng.uniform(-1.0, 1.0), SIDEWALK[2] + 0.5), SIDEWALK[3] - 0.5)
        return carla.Location(far + SX, y + SY, loc.z)""",
         """        cands = [p for p in self.points if 8.0 < math.hypot(p.x - loc.x, p.y - loc.y) < 22.0]      # their own choice: any reachable spot, any distance from 8 to 22 m
        p = self.rng.choice(cands or self.points)
        return carla.Location(p.x, p.y, loc.z)"""),
        ("self.walkers.append([walker, None, self.stroll_goal(start), self.rng.uniform(1.0, 1.5)])",
         "self.walkers.append([walker, None, self.stroll_goal(start), self.rng.uniform(1.0, 1.7), (start.x, start.y), time.monotonic()])"),
        ("""                    if d < 1.5:
                        w[2] = self.stroll_goal(loc)""",
         """                    if math.hypot(loc.x - w[4][0], loc.y - w[4][1]) > 0.6:
                        w[4], w[5] = (loc.x, loc.y), time.monotonic()
                    stuck = time.monotonic() - w[5] > 3.0                  # blocked by a wall or a tree: choose somewhere else
                    if d < 1.5 or stuck:
                        w[4], w[5] = (loc.x, loc.y), time.monotonic()
                        w[2] = self.stroll_goal(loc)"""),
        ("while len(crowd.points) < 60 and tries < 40000:", "while len(crowd.points) < 160 and tries < 60000:"),
        ("if loc is not None and SIDEWALK[0] < loc.x - SX < SIDEWALK[1] and SIDEWALK[2] < loc.y - SY < SIDEWALK[3]:",
         "if loc is not None and 175.0 < loc.x - SX < 255.0 and -262.0 < loc.y - SY < -222.0:"),
    ]
    for a, b in reps:
        assert a in head, a[:60]
        head = head.replace(a, b, 1)
open(os.path.join(home, out_name), "w").write(head + tail)
