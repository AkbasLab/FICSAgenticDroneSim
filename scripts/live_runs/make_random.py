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
tail = open(os.path.join(home, "rand_tail.txt")).read()
open(os.path.join(home, "live_random.py"), "w").write(head + tail)
