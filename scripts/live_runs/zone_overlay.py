"""Draws the scenario's no-fly zones inside the CarlaAir window, so a live flight can be watched.

Kept outside the repo, next to the live scripts. Read-only: it never touches a drone. Every REFRESH_S it asks the
zone where it is at the current mission time and redraws a red box with a label that counts down the seconds left;
a zone that has not switched on yet draws nothing (the live scripts park it at a huge start time until the drone's
own detection switches it on), and a zone past its end draws nothing. Shapes live 0.6 s, so they vanish by
themselves if this stops.

Use: start_overlay(scenario, clock_fn) where clock_fn() is the mission time in seconds (agent._live_elapsed).
"""
import math
import os
import threading
import time

import carla

CARLA_PORT = int(os.environ.get("CARLA_PORT", 2100))   # set by ~/.carlaair/ports.env
# measured frame (memory reference_carlaair_live_setup): CARLA x,y = world x,y + shift; ground z -1.8
SX, SY, GZ = -172.2, 183.86, -1.8
ZONE_HEIGHT_M = 20.0
REFRESH_S = 0.25
SHAPE_LIFE_S = 0.6
FAR_FUTURE_S = 1.0e8   # a start time beyond this means "not switched on yet"

RED = carla.Color(120, 8, 8, 255)       # dim on purpose: debug lines glow (bloom), and up close bright ones blind the picture
YELLOW = carla.Color(255, 220, 0, 255)
GREEN = carla.Color(0, 95, 32, 255)


def _draw_zone(debug, zone, t):
    if zone.active_from_s > FAR_FUTURE_S or not zone.active_at(t):
        return
    x0, x1, y0, y1 = zone.bounds_at(t)
    cx, cy = (x0 + x1) / 2 + SX, (y0 + y1) / 2 + SY
    centre = carla.Location(cx, cy, GZ + ZONE_HEIGHT_M / 2)
    extent = carla.Vector3D((x1 - x0) / 2, (y1 - y0) / 2, ZONE_HEIGHT_M / 2)
    debug.draw_box(carla.BoundingBox(centre, extent), carla.Rotation(), 0.08, RED, SHAPE_LIFE_S)


def _draw_target(debug, target):
    """A green pole with a ring at the detection radius (the drone must stay inside it for the dwell time)."""
    cx, cy = target.x + SX, target.y + SY
    base, top = carla.Location(cx, cy, GZ), carla.Location(cx, cy, GZ + 8.0)
    debug.draw_line(base, top, 0.06, GREEN, SHAPE_LIFE_S)
    for dx, dy in ((1.2, 0.0), (0.0, 1.2)):
        debug.draw_line(carla.Location(cx - dx, cy - dy, top.z), carla.Location(cx + dx, cy + dy, top.z), 0.06, GREEN, SHAPE_LIFE_S)
    r, n = target.detection_radius_m, 24
    ring = [carla.Location(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), GZ + 0.3)
            for i in range(n + 1)]
    for a, b in zip(ring, ring[1:]):
        debug.draw_line(a, b, 0.06, GREEN, SHAPE_LIFE_S)


ORANGE = carla.Color(120, 60, 0, 255)


def _draw_tree(debug, tree):
    """The trunk keep-out the agents use: a thin cylinder (rings at three heights, four posts)."""
    cx, cy, r, n = tree.x + SX, tree.y + SY, tree.trunk_r, 16
    top = GZ + min(tree.z_top, tree.z_bottom + tree.crown_from_frac * (tree.z_top - tree.z_bottom))
    for z in (GZ + tree.z_bottom, (GZ + tree.z_bottom + top) / 2, top):
        ring = [carla.Location(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n + 1)]
        for a, b in zip(ring, ring[1:]):
            debug.draw_line(a, b, 0.05, ORANGE, SHAPE_LIFE_S)
    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
        debug.draw_line(carla.Location(cx + dx, cy + dy, GZ + tree.z_bottom), carla.Location(cx + dx, cy + dy, top), 0.05, ORANGE, SHAPE_LIFE_S)
    # the leaf footprint: rings at the crown radius from where the crown starts to the top
    R = tree.crown_r
    for z in (top, (top + GZ + tree.z_top) / 2, GZ + tree.z_top):
        ring = [carla.Location(cx + R * math.cos(2 * math.pi * i / 32), cy + R * math.sin(2 * math.pi * i / 32), z) for i in range(33)]
        for a, b in zip(ring, ring[1:]):
            debug.draw_line(a, b, 0.05, ORANGE, SHAPE_LIFE_S)


NEAR_TREE_M = 30.0
MAX_TREES_DRAWN = 40          # at most this many trees (nearest to an aircraft) per refresh: the sim cannot take more lines than it draws
TREE_REFRESH_S = 1.0         # trees are redrawn this often, not every REFRESH_S, and live a little longer      # with a positions_fn, only trees this close to an aircraft are drawn
MAX_TREES_UNFILTERED = 100   # more trees than this and no positions_fn: no trees are drawn (6,384 trees x 150 lines every 0.25 s took 500 MB a second)


def _draw_tree_light(debug, tree):
    """One ring at flight height (12 m) where the keep-out is: 12 lines instead of about 150, for scenarios with thousands of trees."""
    cx, cy, n = tree.x + SX, tree.y + SY, 12
    r = max(tree.trunk_r, tree.crown_r)
    z = GZ + 12.0
    ring = [carla.Location(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n + 1)]
    for a, b in zip(ring, ring[1:]):
        debug.draw_line(a, b, 0.05, ORANGE, TREE_REFRESH_S + 0.4)


def start_overlay(scenario, clock_fn, stop_event=None, positions_fn=None):
    """Runs in a background thread; returns the thread. Stops when `stop_event` is set."""
    stop_event = stop_event or threading.Event()

    last_trees = [0.0]

    def loop():
        debug = None
        while not stop_event.is_set():
            try:
                if debug is None:
                    client = carla.Client("localhost", CARLA_PORT)
                    client.set_timeout(5.0)
                    debug = client.get_world().debug
                t = clock_fn()
                for zone in scenario.no_fly_zones:
                    _draw_zone(debug, zone, t)
                for target in scenario.targets:
                    _draw_target(debug, target)
                trees = getattr(scenario, "obstacles", [])
                if positions_fn is not None:
                    spots = [p for p in positions_fn() if p]
                    near = []
                    for tr in trees:
                        d = min((math.hypot(tr.x - p[0], tr.y - p[1]) for p in spots), default=1e9)
                        if d < NEAR_TREE_M:
                            near.append((d, tr))
                    trees = [tr for _, tr in sorted(near, key=lambda x: x[0])[:MAX_TREES_DRAWN]]
                elif len(trees) > MAX_TREES_UNFILTERED:
                    trees = []
                if time.monotonic() - last_trees[0] < TREE_REFRESH_S:
                    trees = []
                else:
                    last_trees[0] = time.monotonic()
                draw = _draw_tree_light if len(getattr(scenario, "obstacles", [])) > MAX_TREES_UNFILTERED else _draw_tree
                for tree in trees:
                    draw(debug, tree)
            except Exception:
                debug = None    # sim not ready or briefly unreachable: reconnect on the next round
            time.sleep(REFRESH_S)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def aim_spectator(back_m=35.0, up_m=28.0, centre_world=(34.0, 32.0)):
    """Moves the free camera (the view in the CarlaAir window) to look at the zone area from the south-east."""
    import math
    world = carla.Client("localhost", CARLA_PORT).get_world()
    tx, ty, tz = centre_world[0] + SX, centre_world[1] + SY, GZ + 8.0
    cx, cy, cz = tx + 8.0, ty - back_m, GZ + up_m
    yaw = math.degrees(math.atan2(ty - cy, tx - cx))
    pitch = -math.degrees(math.atan2(cz - tz, math.hypot(tx - cx, ty - cy)))
    world.get_spectator().set_transform(carla.Transform(carla.Location(cx, cy, cz), carla.Rotation(pitch=pitch, yaw=yaw)))
