"""RANDOM TARGETS (like the NavRL demo): after take-off a green target appears somewhere sensible nearby; when the drone reaches it a new one appears, and so on. Same street scene as live_big7.py (crowd + traffic). Targets are drawn from points on the simulator navigation mesh (pavement) inside the mapped street area that are clear of every map keep-out.

BIG filmed test: a crowd on the sidewalk and traffic in the street. Drone3 flies low, weaves through the pedestrians on the
sidewalk to a first green target; that target disappears and a second one appears across the street; the drone then gets there
through the traffic. The pedestrians and cars are real CARLA actors (the simulator's own bodies, driven in straight lines and
wrapped round at the ends of the street), read by the agent and NavRL through core/moving.CarlaMovers like everything else.

Run (the sim is restarted by go_big.sh):
  AGENT_OVERFLY_MAX_M=0 NAVRL_PROFILE=limit5 ~/run_navrl_py.sh live_big.py --tag B1 --film big_B1
Writes ~/live_big_<tag>.json and, with --film, ~/recordings/<film>_view.mp4."""
import faulthandler
faulthandler.enable(all_threads=True)      # a crash prints where every thread was
import argparse
import json
import math
import os
import queue
import random
import sys
import threading
import time

sys.path.insert(0, os.path.expanduser("~/FICSAgenticDroneSim"))
sys.path.insert(0, os.path.expanduser("~"))
import carla
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.control.skills import go_to_waypoint, take_off
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.core.moving import CarlaMovers, MovingObject
from fics_drone.core.scenario import DRONE_RADIUS_M, load_scenario
from fics_drone.planners.navrl_planner import NavRLPlanner
from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter
import subprocess
import numpy as np
from run_recorder import FPS, HEIGHT, OUT_DIR, WIDTH, TreeBoxes, camera_blueprint, clear_of_walls, look_at

ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--height", type=float, default=1.5)
ap.add_argument("--film", default=None)
ap.add_argument("--marker", action="store_true", help="draw a thin orange ring round the drone so it stays easy to see against the pavement")
ap.add_argument("--no-occlusion", action="store_true", help="switch off the engine's occlusion culling, which can drop the small drone model from the render")
ap.add_argument("--console", action="append", default=[], help="an engine console command to run once the sim is up (repeatable), e.g. \"r.ForceLOD 0\"")
ap.add_argument("--hide-object", action="append", default=[], help="hide this map object (by name) in the render; the planner still treats it as a keep-out")
ap.add_argument("--cam-back", type=float, default=5.0)
ap.add_argument("--cam-up", type=float, default=1.8)
ap.add_argument("--peds", type=int, default=10)
ap.add_argument("--cars", type=int, default=8)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--guard-range", type=float, default=2.5, help="a moving body only holds a leg back at the start if it is this near")
ap.add_argument("--targets", type=int, default=8, help="stop after this many targets (0 = until --max-seconds)")
ap.add_argument("--max-seconds", type=float, default=240.0)
ap.add_argument("--min-dist", type=float, default=14.0)
ap.add_argument("--max-dist", type=float, default=45.0)
ap.add_argument("--A", default="240,-233.0")      # where the drone starts on the sidewalk
ap.add_argument("--T1", default="196,-233.3")     # first target, on the sidewalk
ap.add_argument("--T2", default="203.0,-248.0")     # second target, across the traffic
args = ap.parse_args()
SX, SY = -172.2, 183.86


def parse_xy(text):
    return tuple(float(v) for v in text.split(","))

GZ = 0.0       # the real ground here: the road is at world z 0.0 and the pavement at 0.15 (the old -1.8 was off by that much)
random.seed(args.seed)

client = carla.Client("localhost", int(os.environ["CARLA_PORT"]))
client.set_timeout(20.0)
world = client.get_world()
movers = CarlaMovers(world, origin=(SX, SY), refresh_s=0.1)
scenario = load_scenario(os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/full_map_001.json"))
spec = next(d for d in scenario.drones if d.name == "Drone3")
ox, oy, _ = spec.spawn_offset
adapter = AirSimVehicleAdapter("Drone3")
planner = NavRLPlanner()
planner._load()      # the policy is loaded first, before any other thread or simulator connection exists
bus = MessageBus()
agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name="Drone3",
                        link=AgentLink(bus, "Drone3"), cruise_height=args.height, leg_planner=planner, leg_timeout_s=90.0)
planner.movers_fn = movers.snapshot
agent.guardian.limits.moving_fn = movers.snapshot
LIM = agent.guardian.limits
LIM.altitude_floor_m = min(LIM.altitude_floor_m, args.height - 0.5)
LIM.moving_check_range_m = args.guard_range
from fics_drone.core.map_geometry import load_region_obstacles, default_labels
# the real solid things in this stretch (buildings, trees with their crowns, poles, lamps, props), read from the simulator's own map
LIM.obstacles = load_region_obstacles(world, (SX, SY), (160.0, 260.0, -285.0, -215.0), ground_z=GZ, labels=default_labels() + [carla.CityObjectLabel.Car, carla.CityObjectLabel.Truck, carla.CityObjectLabel.Bus])
import dataclasses
def _grow(o):
    n = getattr(o, 'name', '')
    if 'InstancedFoliageActor' in n and 'crown' in n:      # the leaves drawn are wider and hang lower than the map box: the drone vanished under crowns
        return dataclasses.replace(o, x_min=o.x_min - 0.5, x_max=o.x_max + 0.5, y_min=o.y_min - 0.5, y_max=o.y_max + 0.5, z_bottom=max(0.2, o.z_bottom - 3.0))
    if 'InstancedFoliageActor' in n and 'trunk' in n:
        return dataclasses.replace(o, x_min=o.x_min - 0.5, x_max=o.x_max + 0.5, y_min=o.y_min - 0.5, y_max=o.y_max + 0.5)
    return o
LIM.obstacles = [_grow(o) for o in LIM.obstacles]
print("map keep-outs:", len(LIM.obstacles), flush=True)
if args.hide_object:
    ids = [o.id for o in world.get_environment_objects(carla.CityObjectLabel.Any) if o.name in args.hide_object]
    print("hiding", len(ids), "map objects:", args.hide_object, flush=True)
    if ids:
        world.enable_environment_objects(set(ids), False)


def _blockers(p, z, margin=1.0):
    return [(o.name[:24], round(o.x, 1), round(o.y, 1)) for o in LIM.obstacles if o.blocks_point(p[0], p[1], z, margin)]


for _nm, _p in (("A", parse_xy(args.A)), ("T1", parse_xy(args.T1)), ("T2", parse_xy(args.T2))):
    print("keep-outs at", _nm, _p, _blockers(_p, args.height), flush=True)


def ground_z(x, y):
    try:
        return world.ground_projection(carla.Location(x, y, 100.0), 200.0).location.z
    except Exception:
        return GZ


TM_PORT = int(os.environ.get("TM_PORT", 8000))
LANES = [-241.2, -244.7, -248.2, -251.7]       # lane centres of the straight stretch (mission y); the simulator knows which way each runs
CENTRE = (212.0, -246.5)                       # the middle of the stretch: a car that wanders further than RECYCLE_M from it is put back up the road
RECYCLE_M = 110.0
SIDEWALK = (203.0, 232.0, -236.0, -228.5)      # where the pedestrians walk: x range, y range (mission metres)


class Crowd(threading.Thread):
    """The cars drive themselves (the Traffic Manager's autopilot keeps each in its lane, at a sensible speed, braking for the car ahead) and
    the pedestrians walk between points on the sidewalk by the simulator's own walker AI. This thread only tidies up: a car that has driven
    far away is put back 70 m up the road, out of the camera's view, and a pedestrian that has arrived is given a new place to walk to.
    All simulator calls are made here, from this one thread."""
    def __init__(self):
        super().__init__(daemon=True)
        self.cars, self.walkers, self.points = [], [], []
        self.members = self.cars + self.walkers
        self.stop_ev = threading.Event()
        self.tm = client.get_trafficmanager(TM_PORT)
        self.map = world.get_map()
        self.rng = random.Random(args.seed)

    def lane_waypoint(self, x, y):
        return self.map.get_waypoint(carla.Location(x + SX, y + SY, 0.0), project_to_road=True, lane_type=carla.LaneType.Driving)

    def add_car(self, bp, wp):
        tf = wp.transform
        tf.location.z += 0.4
        car = world.try_spawn_actor(bp, tf)
        if car is None:
            return False
        car.set_autopilot(True, TM_PORT)
        self.tm.auto_lane_change(car, False)
        self.tm.vehicle_percentage_speed_difference(car, self.rng.uniform(10.0, 30.0))      # a little under the limit
        self.cars.append(car)
        return True

    def pick_point(self, near=None):
        pts = [p for p in self.points if near is None or math.hypot(p.x - near.x, p.y - near.y) > 8.0]
        return self.rng.choice(pts or self.points)

    def stroll_goal(self, loc):
        """A point at the far end of the sidewalk from where this pedestrian is, a little off to one side."""
        far = SIDEWALK[1] - 2.0 if loc.x - SX < (SIDEWALK[0] + SIDEWALK[1]) / 2 else SIDEWALK[0] + 2.0
        y = min(max(loc.y - SY + self.rng.uniform(-1.0, 1.0), SIDEWALK[2] + 0.5), SIDEWALK[3] - 0.5)
        return carla.Location(far + SX, y + SY, loc.z)

    def add_walker(self, bp, start):
        walker = world.try_spawn_actor(bp, carla.Transform(carla.Location(start.x, start.y, start.z + 0.6)))
        if walker is None:
            return False
        # The simulator's walker-AI controller does not move anyone in this build, so each pedestrian is driven directly
        # with a walking command (a direction and a speed), strolling back and forth along the sidewalk.
        self.walkers.append([walker, None, self.stroll_goal(start), self.rng.uniform(1.0, 1.5)])
        return True

    def run(self):
        while not self.stop_ev.is_set():
            try:
                for car in self.cars:
                    loc = car.get_location()
                    if math.hypot(loc.x - SX - CENTRE[0], loc.y - SY - CENTRE[1]) > RECYCLE_M:
                        wp = self.lane_waypoint(self.rng.uniform(190.0, 235.0), self.rng.choice(LANES))
                        back = wp.previous(70.0) if wp is not None else []
                        if back:
                            tf = back[0].transform
                            tf.location.z += 0.4
                            car.set_transform(tf)
                for w in self.walkers:
                    loc = w[0].get_location()
                    dx, dy = w[2].x - loc.x, w[2].y - loc.y
                    d = math.hypot(dx, dy)
                    if d < 1.5:
                        w[2] = self.stroll_goal(loc)
                        dx, dy = w[2].x - loc.x, w[2].y - loc.y
                        d = max(math.hypot(dx, dy), 1e-6)
                    w[0].apply_control(carla.WalkerControl(carla.Vector3D(dx / d, dy / d, 0.0), w[3], False))
            except Exception:
                pass
            time.sleep(0.25)

    def end(self):
        self.stop_ev.set()
        time.sleep(0.5)
        for w in self.walkers:
            try:
                w[0].destroy()
            except Exception:
                pass
        for car in self.cars:
            try:
                car.destroy()
            except Exception:
                pass


crowd = Crowd()
lib = world.get_blueprint_library()
walker_bps = [b for b in lib.filter("walker.pedestrian.*")]
SEDANS = ("audi.a2", "audi.tt", "audi.etron", "bmw.grandtourer", "mini.cooper", "tesla.model3", "toyota.prius", "dodge.charger", "ford.mustang", "seat.leon",
          "lincoln.mkz", "mercedes.coupe", "nissan.micra", "chevrolet.impala", "citroen.c3")
car_bps = [b for b in lib.filter("vehicle.*") if any(k in b.id for k in SEDANS)]
random.shuffle(walker_bps)
random.shuffle(car_bps)


def populate():
    world.set_pedestrians_cross_factor(0.0)           # the pedestrians stay on the pavement
    crowd.tm.set_global_distance_to_leading_vehicle(3.0)
    # cars: spread along all four lanes; the simulator gives each its lane's direction
    per_lane = max(1, args.cars // len(LANES))
    k = 0
    for j, ly in enumerate(LANES):
        for m in range(per_lane):
            wp = crowd.lane_waypoint(188.0 + j * 7.0 + m * 24.0, ly)
            if wp is None or not crowd.add_car(car_bps[k % len(car_bps)], wp):
                print("car spawn failed", k, flush=True)
            k += 1
    # pedestrians: sidewalk points are found on the navigation mesh
    tries = 0
    while len(crowd.points) < 60 and tries < 40000:
        tries += 1
        loc = world.get_random_location_from_navigation()
        if loc is not None and SIDEWALK[0] < loc.x - SX < SIDEWALK[1] and SIDEWALK[2] < loc.y - SY < SIDEWALK[3]:
            crowd.points.append(loc)
    print("sidewalk points found:", len(crowd.points), "after", tries, "tries", flush=True)
    for i in range(args.peds):
        if not crowd.points or not crowd.add_walker(walker_bps[i % len(walker_bps)], crowd.points[(i * 7) % len(crowd.points)]):
            print("walker spawn failed", i, flush=True)


samples, stop = [], threading.Event()
t0 = time.monotonic()


def sampler():
    import airsim
    cl = airsim.MultirotorClient()
    cl.confirmConnection()
    while not stop.is_set():
        try:
            x, y, z = adapter.get_position()
            info = cl.simGetCollisionInfo("Drone3")
            objs = [(o.name, o.kind, round(o.x, 2), round(o.y, 2), o.radius, o.height, o.half_width, o.half_length, round(o.yaw, 3))
                    for o in movers.snapshot()]
            samples.append((round(time.monotonic() - t0, 2), round(x + ox, 2), round(y + oy, 2), round(z, 2), bool(info.has_collided), objs,
                            (info.object_name, round(info.impact_point.x_val, 1), round(info.impact_point.y_val, 1), round(info.impact_point.z_val, 1)) if info.has_collided else None))
        except Exception:
            pass
        time.sleep(0.25)


threading.Thread(target=sampler, daemon=True).start()

view = {"target": None}
LASTPOSE = {}
FRAMELOG = []     # for every video frame written: the camera position, where it looks, and the drone's world position then


class PipeWriter:
    """Frames go to ffmpeg on a pipe, on the same exact 1/FPS grid of simulator time the recorder uses (a late frame is covered by repeating
    the last picture), so the file plays at true speed. ffmpeg finishes the file when the pipe closes."""

    def __init__(self, path):
        self.proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}",
                                      "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                                      path], stdin=subprocess.PIPE)
        self.next_t, self.last, self.written, self.path = None, None, 0, path

    def add(self, image):
        frame = np.ascontiguousarray(np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))[:, :, :3])
        if self.next_t is None:
            self.next_t = image.timestamp
        while self.next_t <= image.timestamp + 1e-6:
            use = self.last if (self.last is not None and self.next_t < image.timestamp - 0.5 / FPS) else frame
            self.proc.stdin.write(use.tobytes())
            FRAMELOG.append((self.written, LASTPOSE.get('c'), LASTPOSE.get('a'), LASTPOSE.get('me'), self.next_t))
            self.written += 1
            self.next_t += 1.0 / FPS
        self.last = frame

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.wait(timeout=600)
        return self.path, self.written


class MapBoxes:
    """The map's real keep-out boxes (buildings, trunks, crowns, poles, lamps, props) in world coordinates, for the camera's
    line-of-sight test. TreeBoxes covers a default area around the origin, not this street, so before this the camera's only
    check here was a ray that misses trees, poles and props: a trunk or pillar could stand between the camera and the drone."""

    def __init__(self, boxes):
        rows = [(b.x_min + SX, b.y_min + SY, b.z_bottom + GZ, b.x_max + SX, b.y_max + SY, b.z_top + GZ) for b in boxes]
        arr = np.array(rows, dtype=float).reshape(-1, 6)
        self.lo, self.hi = arr[:, :3], arr[:, 3:]

    contains = TreeBoxes.contains
    segment_hits = TreeBoxes.segment_hits


def start_film(tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    cam = world.spawn_actor(camera_blueprint(world, tick=1.0 / FPS), carla.Transform(carla.Location(217 + SX, -149 + SY, 8)))
    writer = PipeWriter(os.path.join(OUT_DIR, f"{tag}_view.mp4"))
    q, halt = queue.Queue(), threading.Event()
    cam.listen(q.put)
    trees = MapBoxes(LIM.obstacles)

    def pump():
        while not halt.is_set() or not q.empty():
            try:
                writer.add(q.get(timeout=0.3))
            except queue.Empty:
                continue

    def pose():
        heading, c, a, fix, step = (-1.0, 0.0), None, None, None, 0
        ang, last_t = [math.pi], [time.monotonic()]
        tick = [time.monotonic()]
        while not halt.is_set():
            try:
                x, y, z = adapter.get_position()
                mx, my = x + ox, y + oy
                me = (mx + SX, my + SY, GZ + 0.15 + z)   # a fixed ground height: the ground lookup could hit a tree top or an awning and throw the camera up
                tgt = view["target"]
                if tgt is not None:
                    dx, dy = tgt[0] - mx, tgt[1] - my
                    if math.hypot(dx, dy) > 2.0:
                        want_ang = math.atan2(dy, dx)
                        now = time.monotonic()
                        dt, last_t[0] = min(now - last_t[0], 0.2), now
                        delta = (want_ang - ang[0] + math.pi) % (2 * math.pi) - math.pi
                        step_a = math.radians(110.0) * dt
                        ang[0] += max(-step_a, min(step_a, delta))
                    heading = (math.cos(ang[0]), math.sin(ang[0]))
                ux, uy = heading
                want = (me[0] - ux * args.cam_back, me[1] - uy * args.cam_back, me[2] + args.cam_up)
                aim = (me[0] + ux * 2.5, me[1] + uy * 2.5, me[2] - 0.2)
                if step % 6 == 0 or fix is None:
                    fixed = clear_of_walls(world, me, want, trees=trees)
                    fix = tuple(f - w for f, w in zip(fixed, want))
                step += 1
                want = tuple(w + f for w, f in zip(want, fix))
                now_t = time.monotonic()
                dt_c, tick[0] = min(now_t - tick[0], 0.5), now_t
                k = 1.0 - math.exp(-dt_c / 0.35)        # smoothing by elapsed time (about a third of a second), not per loop pass
                if c is None:
                    c, a = want, aim
                else:
                    c = tuple(p + k * (n - p) for p, n in zip(c, want))
                    a = tuple(p + k * (n - p) for p, n in zip(a, aim))
                cam.set_transform(look_at(c, a))
                LASTPOSE['c'], LASTPOSE['a'], LASTPOSE['me'] = c, a, me
                if args.marker and step % 2 == 0:
                    ring = [carla.Location(me[0] + 0.6 * math.cos(2 * math.pi * i / 10), me[1] + 0.6 * math.sin(2 * math.pi * i / 10), me[2] + 0.1) for i in range(11)]
                    for p, q2 in zip(ring, ring[1:]):
                        world.debug.draw_line(p, q2, thickness=0.02, color=carla.Color(110, 45, 0), life_time=0.15)
            except Exception:
                pass
            time.sleep(0.03)

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()
    threading.Thread(target=pose, daemon=True).start()

    def finish():
        time.sleep(1.5)
        halt.set()
        cam.stop()
        pump_thread.join(timeout=90)       # every queued frame is written before the file is closed
        time.sleep(0.5)
        try:
            cam.destroy()
        except Exception:
            pass
        return writer.close()
    return finish


class _Target:
    def __init__(self, x, y, r=3.0, z=0.0):
        self.x, self.y, self.detection_radius_m, self.z = x, y, r, z


class _Stub:                                              # only the green target marker: no zones, no trees, no rings
    no_fly_zones, obstacles = [], []
    targets = []


from zone_overlay import start_overlay
start_overlay(_Stub, lambda: time.monotonic() - t0, stop, rings_fn=lambda: [])


def summarize(name, seg, event, trace, secs):
    gap_min, contacts, close1, speeds = 1e9, 0, 0, []
    prev = None
    for s in seg:
        if prev is not None and s[0] > prev[0]:
            speeds.append(math.hypot(s[1] - prev[1], s[2] - prev[2]) / (s[0] - prev[0]))
        prev = s
        for (_n, _k, mx, my, r, h, hw, hl, yaw) in s[5]:
            if s[3] >= h + LIM.moving_vertical_pad_m:
                continue
            o = MovingObject(_n, _k, mx, my, 0.0, 0.0, r, h, hw, hl, yaw)
            gap = math.hypot(s[1] - mx, s[2] - my) - o.reach(s[1], s[2])
            gap_min = min(gap_min, gap)
            contacts += gap < DRONE_RADIUS_M
            close1 += gap < 1.0
    return {"leg": name, "event": event.value, "seconds": round(secs, 1), "trace": trace,
            "closest_edge_gap_m": None if gap_min > 1e8 else round(gap_min, 2), "samples_touching": int(contacts),
            "samples_within_1m": int(close1), "collision_samples": sum(1 for s in seg if s[4]),
            "collided_with": sorted({s[6][0] for s in seg if len(s) > 6 and s[6]}),
            "z_range": [round(min((s[3] for s in seg), default=0), 2), round(max((s[3] for s in seg), default=0), 2)],
            "speed_min_mean_max": [round(min(speeds), 2), round(sum(speeds) / len(speeds), 2), round(max(speeds), 2)] if speeds else None,
            "final": list(seg[-1][1:4]) if seg else None}


def leg(name, target):
    view["target"] = target
    a, i0, trace = time.monotonic(), len(samples), []
    event = agent._guarded_fly((target[0] - ox, target[1] - oy, args.height), trace)
    return summarize(name, samples[i0:], event, trace, time.monotonic() - a)


def parse(s):
    return tuple(float(v) for v in s.split(","))


A = parse(args.A)
rng = random.Random(args.seed)
REGION = (165.0, 258.0, -283.0, -217.0)      # same mapped street area as the keep-outs


import zone_overlay
from fics_drone.core.map_geometry import box_from_bounding_box
GREEN = carla.Color(0, 110, 0, 255)        # dim: the bright neon swamped the picture next to the drone


def _draw_target_3d(debug, target):
    """A green pole standing on the target, a cross at its top and a ring round it, at the target's own height (roofs included)."""
    cx, cy, cz = target.x + SX, target.y + SY, GZ + getattr(target, "z", 0.0)
    try:
        dpos = adapter.get_position()
        if math.hypot(dpos[0] + ox + SX - cx, dpos[1] + oy + SY - cy) < 4.0:
            return                                   # close to the drone the marker is hidden (it was blinding there)
    except Exception:
        pass
    lo = cz - (3.0 if cz > 3.0 else 0.0)
    hi = cz + 5.0
    debug.draw_line(carla.Location(cx, cy, lo), carla.Location(cx, cy, hi), 0.03, GREEN, zone_overlay.SHAPE_LIFE_S)
    for dx, dy in ((1.2, 0.0), (0.0, 1.2)):
        debug.draw_line(carla.Location(cx - dx, cy - dy, hi), carla.Location(cx + dx, cy + dy, hi), 0.03, GREEN, zone_overlay.SHAPE_LIFE_S)
    ring = [carla.Location(cx + 1.0 * math.cos(2 * math.pi * i / 24), cy + 1.0 * math.sin(2 * math.pi * i / 24), cz) for i in range(25)]
    for a, b in zip(ring, ring[1:]):
        debug.draw_line(a, b, 0.03, GREEN, zone_overlay.SHAPE_LIFE_S)


zone_overlay._draw_target = _draw_target_3d
STREET_Z = 6.5              # street targets hover above the traffic, not in a lane at car height
ROOF_WALL_CLEAR_M = 3.0      # a roof spot must be this far from any wall that rises above the roof
ROOF_MAX_TOP_M = 12.0       # roofs higher than this are skipped (a long climb, and the agent's overfly cap is 15 m)


def clear_of_things(x, y, zs, margin):
    """True if no keep-out (building, tree trunk or crown, pole, prop) is within `margin` of the point at any of the heights `zs`."""
    return not any(o.blocks_point(x, y, z, margin) for o in LIM.obstacles for z in zs)


def sidewalk_points():
    pts, tries = [], 0
    while len(pts) < 200 and tries < 60000:
        tries += 1
        loc = world.get_random_location_from_navigation()
        if loc is None:
            continue
        x, y = loc.x - SX, loc.y - SY
        if REGION[0] < x < REGION[1] and REGION[2] < y < REGION[3] and clear_of_things(x, y, (args.height, 2.5, 5.0, 8.0), 2.0):
            pts.append((round(x, 2), round(y, 2), args.height))
    return pts


def street_points():
    pts = []
    for _ in range(3000):
        if len(pts) >= 120:
            break
        x, y = rng.uniform(REGION[0] + 5, REGION[1] - 5), rng.choice(LANES) + rng.uniform(-1.0, 1.0)
        wp = crowd.lane_waypoint(x, y)
        if wp is None:
            continue
        p = wp.transform.location
        x, y = p.x - SX, p.y - SY
        if REGION[0] < x < REGION[1] and clear_of_things(x, y, (args.height, 2.5, 5.0, 6.5, 8.0), 2.0):
            pts.append((round(x, 2), round(y, 2), STREET_Z))
    return pts


ROOFBOX = {}


def roof_points():
    pts = []
    for o in world.get_environment_objects(carla.CityObjectLabel.Buildings):
        try:
            b = box_from_bounding_box(o.bounding_box, (SX, SY), GZ, o.name)
        except Exception:
            continue
        top = b.z_top
        if top < 5.0 or top > ROOF_MAX_TOP_M or (b.x_max - b.x_min) < 5.0 or (b.y_max - b.y_min) < 5.0:
            continue
        if not (REGION[0] < b.x_min and b.x_max < REGION[1] and REGION[2] < b.y_min and b.y_max < REGION[3]):
            continue
        # roof spots: the ones furthest from any wall that stands higher than the roof beside it (the planner stalled next to one),
        # kept only if at least ROOF_WALL_CLEAR_M from it; up to 2 per roof, well apart
        z = round(top + 3.0, 2)
        scored = []
        gx = b.x_min + 1.5
        while gx <= b.x_max - 1.5:
            gy = b.y_min + 1.5
            while gy <= b.y_max - 1.5:
                if clear_of_things(gx, gy, (z + 1.5,), 1.5):
                    room = 0.0
                    for m in (2.0, 3.0, 4.0, 5.0, 6.0, 8.0):
                        if clear_of_things(gx, gy, (z,), m):
                            room = m
                        else:
                            break
                    if room >= ROOF_WALL_CLEAR_M:
                        scored.append((room, gx, gy))
                gy += 1.0
            gx += 1.0
        scored.sort(reverse=True)
        chosen = []
        for room, gx, gy in scored:
            if all(math.hypot(gx - c[0], gy - c[1]) > 4.0 for c in chosen):
                chosen.append((gx, gy))
            if len(chosen) == 2:
                break
        for gx, gy in chosen:
            pts.append((round(gx, 2), round(gy, 2), z))
            ROOFBOX[pts[-1]] = (b.x_min, b.x_max, b.y_min, b.y_max, top)
    return pts


from fics_drone.planners.overfly import overfly_altitude
from fics_drone.planners.street_path import plan_around
from fics_drone.agents.persistent_agent import route_runs_clear
from fics_drone.planners.plan3d import plan_3d

BOUNDS3 = (REGION[0] - 2.0, REGION[1] + 2.0, REGION[2] - 2.0, REGION[3] + 2.0)      # keep-outs are mapped only here


def needs_3d(start, target):
    return True            # every leg: the 3-D plan is as short as the flat one on open ground, and goes under crowns the flat one has to go round


def route3d(start, target):
    """A route through the trees in three dimensions (round, under, over); None if there is none. More room is asked for until no stop is
    inside a keep-out and every run is clear the way the guardian judges it."""
    trees = agent._route_obstacles()
    margin = agent.guardian.limits.obstacle_margin_m
    for extra in (0.3, 0.8, 1.3):
        stops = plan_3d(start, target, trees, margin, BOUNDS3, extra=extra)
        if stops is None:
            continue
        pts = [start] + stops
        if (not any(t.blocks_point(*sp, margin=margin) for sp in stops[:-1] for t in trees)
                and not any(t.blocks_segment(a, b, margin=margin) for a, b in zip(pts, pts[1:]) for t in trees)):
            return stops
    return None


def ramp_points(start, target):
    """World waypoints of a roof leg: along the straight line to the target every ~6 m, rising in step with the distance covered, each lifted
    to the lowest height clear of every crown (a waypoint inside a crown is refused), ending 1 m above the roof spot."""
    d = math.hypot(target[0] - start[0], target[1] - start[1])
    n = max(1, int(d // 6.0))
    pts = []
    for i in range(1, n + 1):
        f = i / n
        wx, wy = start[0] + (target[0] - start[0]) * f, start[1] + (target[1] - start[1]) * f
        wz = start[2] + (target[2] + 1.0 - start[2]) * f
        while wz < target[2] + 12.0 and not clear_of_things(wx, wy, (wz,), 2.0):
            wz += 1.0
        pts.append((wx, wy, wz))
    return pts


def route_ok(start, target):
    """Would the agent find a way to fly from start to target (world x, y, z)? The same tests it makes when it plans a leg: nothing on the
    straight line, or a way over (overfly), or a way round (grid plan) whose stops are clear; a roof leg's ramp must have clear segments.
    Checked when a target is picked, so the drone does not set off on a leg that is refused after flying part of it."""
    trees = agent._route_obstacles()
    margin = agent.guardian.limits.obstacle_margin_m
    seg_ok = lambda a, b: not any(t.blocks_segment(a, b, margin=margin) for t in trees)
    if any(t.blocks_point(*target, margin=margin) for t in trees):
        return False
    if route3d(start, target) is not None:
        return True
    if target[2] > 10.0:
        return False
    if not any(t.blocks_segment(start, target, margin=margin) for t in trees):
        return True
    if overfly_altitude(start, target, trees, margin, 3.0, 15.0) is not None:
        return True
    for pad in (12.0, 24.0, 40.0):
        for extra in (0.5, 1.5, 2.5):
            path = plan_around(start, target, trees, margin, pad=pad, extra=extra)
            if path and route_runs_clear(start, path, trees, margin):
                return not any(t.blocks_point(*sp, margin=margin) for sp in path[:-1] for t in trees)
    return False


def next_target(pos, done, pools, last_kind, force_kind=None):
    """A different kind from the last one (roof, street, sidewalk), at a flyable distance, not near a recent target."""
    kinds = [k for k in pools if pools[k] and k != last_kind] or [k for k in pools if pools[k]]
    kind = force_kind or rng.choice(kinds)
    pts = pools[kind]
    ok = [p for p in pts if args.min_dist <= math.hypot(p[0] - pos[0], p[1] - pos[1]) <= args.max_dist
          and all(math.hypot(p[0] - d[0], p[1] - d[1]) > 6.0 for d in done[-4:])]
    bodies = movers.snapshot()
    free = [p for p in ok if p[2] > 5.0 or all(math.hypot(p[0] - m.x, p[1] - m.y) > 4.0 for m in bodies)]     # not one a person or car stands on now
    sx, sy, sz = adapter.get_position()
    here = (sx + ox, sy + oy, max(sz, 0.8))
    order = [kind] + [k for k in pools if k != kind and pools[k] and not force_kind]
    first = None
    for k in order:
        kp = pools[k]
        kok = [p for p in kp if args.min_dist <= math.hypot(p[0] - pos[0], p[1] - pos[1]) <= args.max_dist
               and all(math.hypot(p[0] - d[0], p[1] - d[1]) > 6.0 for d in done[-4:])]
        cands = [p for p in kok if k == kind or True]
        if k == kind:
            cands = list(free or ok or pts)
        rng.shuffle(cands)
        first = first or (k, cands[0] if cands else None)
        for p in cands[:14]:
            try:
                if route_ok(here, p):
                    return k, p
            except Exception as e:
                print("  route check failed:", e, flush=True)
                return kind, cands[0]
    return first if first and first[1] is not None else (kind, rng.choice(free or ok or pts))


from fics_drone.core.evade import evasion_velocity
EVADE_ON = os.environ.get("AGENT_EVADE", "1") != "0"
FLOW = os.environ.get("DEMO_FLOW", "1") != "0"      # fly through each target and straight on to the next, instead of stopping on it


ROAD_Y = (-254.0, -238.5)      # the traffic lanes: a low aircraft stepping away from a walker must not step into them


def lift_clear():
    """Low and a vehicle within 3.5 m (it ended a leg in the road, or stopped in a queue): straight up to street-target height, clear of the cars."""
    x, y, z = adapter.get_position()
    if z >= 3.0:
        return
    if not any(m.kind == "vehicle" and math.hypot(m.x - (x + ox), m.y - (y + oy)) < 3.5 for m in movers.snapshot()):
        return
    print("  lifting clear of the traffic", flush=True)
    end = time.monotonic() + 9.0
    while time.monotonic() < end and adapter.get_position()[2] < STREET_Z - 0.3:
        adapter.start_velocity(0.0, 0.0, 1.0)
        time.sleep(0.1)
    adapter.start_hover()


def _evade(pos_world):
    z = pos_world[2]
    return evasion_velocity(pos_world, movers.snapshot(), speed_mps=1.3, horizon_s=1.5, clear_m=0.8, blocked_fn=lambda x, y: (not clear_of_things(x, y, (z,), 0.8)) or (z < 3.0 and ROAD_Y[0] < y < ROAD_Y[1] and REGION[0] < x < REGION[1]))


def evade_hold(seconds):
    """Wait on the spot, but step out of the way of anything that is about to run into the aircraft."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        x, y, z = adapter.get_position()
        step = _evade((x + ox, y + oy, z)) if EVADE_ON else None
        if step is None:
            adapter.start_hover()
        else:
            adapter.start_velocity(float(step[0]), float(step[1]), 0.0)
        time.sleep(0.1)
    adapter.start_hover()


if EVADE_ON:
    agent.evade_fn = lambda p: _evade(p)

import inspect
_orig_hover = adapter.start_hover
def _logged_hover(*a, **k):
    fr = [f.function for f in inspect.stack()[1:5]]
    print("HOVER t=%.1f via %s" % (time.monotonic() - t0, "<-".join(fr)), flush=True)
    return _orig_hover(*a, **k)
adapter.start_hover = _logged_hover
CMD = []
_orig_vel = adapter.start_velocity
def _logged_vel(vx, vy, vz, *a, **k):
    CMD.append((time.monotonic() - t0, math.hypot(vx, vy), vz))
    return _orig_vel(vx, vy, vz, *a, **k)
adapter.start_velocity = _logged_vel


def leave_roof(roof, towards):
    """The planner cannot route a descent through a building, so from a roof the drone first slides sideways at roof height to a spot 3 m
    beyond the nearest clear edge (on the side facing the next target), then drops straight down beside the wall."""
    x0, x1, y0, y1, top = ROOFBOX[roof]
    z = roof[2]
    cands = [(x0 - 3.0, min(max(roof[1], y0), y1)), (x1 + 3.0, min(max(roof[1], y0), y1)),
             (min(max(roof[0], x0), x1), y0 - 3.0), (min(max(roof[0], x0), x1), y1 + 3.0)]
    cands.sort(key=lambda c: math.hypot(c[0] - towards[0], c[1] - towards[1]))
    column = [args.height + 1.5 * i for i in range(int((z - args.height) / 1.5) + 1)] + [z]     # the whole drop, not a few heights
    for cx, cy in cands:
        inside = REGION[0] + 2 < cx < REGION[1] - 2 and REGION[2] + 2 < cy < REGION[3] - 2          # keep-outs are only mapped inside REGION
        if inside and clear_of_things(cx, cy, column, 2.0):
            for stage, spot in (("off_roof", (cx, cy, z)), ("down", (cx, cy, args.height))):
                trace = []
                ev = agent._guarded_fly((spot[0] - ox, spot[1] - oy, spot[2]), trace)
                print("  leave roof", stage, ev.value, trace[-1][:90] if trace else "", flush=True)
                if ev.value != "skill_succeeded":
                    return False
            return True
    print("  leave roof: no clear side", flush=True)
    return False


def roof_entry(target):
    """A spot 2.5 m off one of the roof's walls, outside the mapped keep-outs from street height up to the roof, so the drone can come in low
    (between and under the trees), climb straight along the wall's face and step over the edge. Chosen to make the shortest trip from here."""
    x0, x1, y0, y1, top = ROOFBOX[target]
    z = target[2]
    x, y, _ = adapter.get_position()
    here = (x + ox, y + oy)
    column = [args.height + 1.5 * i for i in range(int((z + 0.5 - args.height) / 1.5) + 1)] + [z + 0.5]
    cands = []
    for t in (0.15, 0.3, 0.5, 0.7, 0.85):
        px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        for cx, cy in ((x0 - 2.5, py), (x1 + 2.5, py), (px, y0 - 2.5), (px, y1 + 2.5)):
            if not (REGION[0] + 2 < cx < REGION[1] - 2 and REGION[2] + 2 < cy < REGION[3] - 2):
                continue
            if cy > ROAD_Y[0] and cy < ROAD_Y[1]:
                continue
            if clear_of_things(cx, cy, column, 1.5):
                cands.append((math.hypot(cx - here[0], cy - here[1]) + math.hypot(cx - target[0], cy - target[1]), cx, cy))
    if not cands:
        print("  roof entry: no clear strip", flush=True)
        return None
    cands.sort()
    print("  roof entry strip", (round(cands[0][1], 1), round(cands[0][2], 1)), flush=True)
    return cands[0][1], cands[0][2]


def leg3(name, target):
    view["target"] = target[:2]
    a, i0, trace = time.monotonic(), len(samples), []
    event, stops = None, None
    for attempt in range(3):
        x, y, z0 = adapter.get_position()
        stops = route3d((x + ox, y + oy, z0), target)
        if stops is None:
            break
        # the route the 3-D planner found (rises on the way, between trees where there is room, over only where there is none); the aircraft passes
        # a stop within 1.5 m, so the next run can start a little off the planned line and be refused: the route is then planned again from where it is
        for i, (wx, wy, wz) in enumerate(stops, 1):
            last = (i == len(stops))
            agent.pass_lead_s, agent.pass_dz_m = (0.45, 1.2) if last else (0.7, 2.0)      # the target itself is cut closer than a mid-route stop
            event = agent._guarded_fly((wx - ox, wy - oy, wz), trace, pass_through=(FLOW or i < len(stops)), _detouring=True)      # the stops are planned in 3-D: not re-routed by the 2-D detour logic
            if event.value != "skill_succeeded":
                break
        trace.append("route3d_%d_stops" % len(stops))
        if event.value != "guardian_blocked":
            break
    if stops is not None:
        pass
    elif target[2] > 10.0:
        # a roof: climb on the way, along the straight line to the target (height rises in step with the distance covered), not low-then-up
        pts = ramp_points((x + ox, y + oy, z0), target)
        event = None
        for i, (wx, wy, wz) in enumerate(pts, 1):
            event = agent._guarded_fly((wx - ox, wy - oy, wz), trace, pass_through=(i < len(pts)))
            if event.value != "skill_succeeded":
                break
        if event.value == "skill_succeeded":
            event = agent._guarded_fly((target[0] - ox, target[1] - oy, target[2]), trace)
    else:
        event = agent._guarded_fly((target[0] - ox, target[1] - oy, target[2]), trace)
    cs = sorted(c[1] for c in CMD if c[0] >= a - t0)
    if cs:
        print("  commanded horizontal speed this leg: p50 %.2f p90 %.2f max %.2f (n=%d)" % (cs[len(cs) // 2], cs[int(len(cs) * .9)], cs[-1], len(cs)), flush=True)
    return summarize(name, samples[i0:], event, trace, time.monotonic() - a)


out = []
finish_film = None
try:
    populate()
    crowd.start()
    pools = {"sidewalk": sidewalk_points(), "street": street_points(), "roof": roof_points()}
    print("candidate targets:", {k: len(v) for k, v in pools.items()}, flush=True)
    print("spawned", len(crowd.cars), "cars and", len(crowd.walkers), "pedestrians", flush=True)
    take_off(adapter)
    import airsim
    asc = airsim.MultirotorClient()
    asc.confirmConnection()
    pose = asc.simGetVehiclePose("Drone3")
    pose.position.x_val, pose.position.y_val, pose.position.z_val = A[0] - ox, A[1] - oy, args.height
    pose.orientation = airsim.to_quaternion(0.0, 0.0, math.pi)
    asc.simSetVehiclePose(pose, True, "Drone3")
    time.sleep(1.5)
    go_to_waypoint(adapter, A[0] - ox, A[1] - oy, args.height)
    agent.belief.position = adapter.get_position()
    time.sleep(8.0)
    del samples[:]
    if args.film:
        finish_film = start_film(args.film)
        time.sleep(1.0)
    done, done_kinds, begun = [], [], time.monotonic()
    force, tries, roof_now = None, 0, None
    while (args.targets == 0 or len(done) < args.targets) and time.monotonic() - begun < args.max_seconds:
        x, y, _z = adapter.get_position()
        pos = (x + ox, y + oy)
        kind, tgt = next_target(pos, done, pools, done_kinds[-1] if done_kinds else None, force)
        under = next((k for k, v in ROOFBOX.items() if v[0] <= pos[0] <= v[1] and v[2] <= pos[1] <= v[3] and _z > v[4] + 1.0), None) if _z > 3.0 else None
        if under is not None and route3d((pos[0], pos[1], _z), tgt) is not None:
            under = None               # a 3-D route from the roof to the next target exists: leg3 flies it
        if under is not None:          # on a roof (reached, or a leg that failed up there): off it and down before the next leg
            leave_roof(under, tgt)
            roof_now = None
            x, y, _z = adapter.get_position()
            pos = (x + ox, y + oy)
        _Stub.targets = [_Target(tgt[0], tgt[1], z=tgt[2])]
        print("target", len(done) + 1, kind, tgt, "distance", round(math.hypot(tgt[0] - pos[0], tgt[1] - pos[1]), 1), flush=True)
        res = leg3("target_%d_%s" % (len(done) + 1, kind), tgt)
        out.append(res)
        px, py, pz = adapter.get_position()
        if res["event"] == "skill_failed" and math.hypot(tgt[0] - ox - px, tgt[1] - oy - py) < 2.5 and abs(tgt[2] - pz) < 1.5:
            res["event"] = "skill_succeeded"           # held off the last metre by evading a walker: close enough to count as arrived
            res["note"] = "near arrival"
        print("  ->", res["event"], res["seconds"], "s, closest gap", res["closest_edge_gap_m"], flush=True)
        _Stub.targets = []
        if not (FLOW and res["event"] == "skill_succeeded"):      # a run flows on from one target to the next: no stop, no wait
            lift_clear()
            evade_hold(0.6)
        agent.belief.position = adapter.get_position()
        if res["event"] == "guardian_blocked" and tries < 3:        # no safe route to that one: try another of the same kind
            force, tries = kind, tries + 1
            continue
        force, tries, roof_now = None, 0, None
        done_kinds.append(kind)
        done.append(tgt)
        if kind == "roof" and res["event"] == "skill_succeeded":
            roof_now = tgt
finally:
    stop.set()
    time.sleep(0.8)
    crowd.end()
    res = {"film": None, "tag": args.tag, "height": args.height, "peds": args.peds, "cars": args.cars, "legs": out, "samples": samples, "framelog": FRAMELOG}
    json.dump(res, open(os.path.expanduser(f"~/live_rand_{args.tag}.json"), "w"))
    film = finish_film() if finish_film else None
    res["film"] = film
    json.dump(res, open(os.path.expanduser(f"~/live_rand_{args.tag}.json"), "w"))
print(json.dumps({"legs": out}, indent=1))
