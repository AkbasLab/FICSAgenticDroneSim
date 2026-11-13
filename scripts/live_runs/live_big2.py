"""BIG filmed test: a crowd on the sidewalk and traffic in the street. Drone3 flies low, weaves through the pedestrians on the
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
ap.add_argument("--peds", type=int, default=10)
ap.add_argument("--cars", type=int, default=8)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--guard-range", type=float, default=2.5, help="a moving body only holds a leg back at the start if it is this near")
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
                        link=AgentLink(bus, "Drone3"), cruise_height=args.height, leg_planner=planner, leg_timeout_s=300.0)
planner.movers_fn = movers.snapshot
agent.guardian.limits.moving_fn = movers.snapshot
LIM = agent.guardian.limits
LIM.altitude_floor_m = min(LIM.altitude_floor_m, args.height - 0.5)
LIM.moving_check_range_m = args.guard_range
from fics_drone.core.map_geometry import load_region_obstacles
# the real solid things in this stretch (buildings, trees with their crowns, poles, lamps, props), read from the simulator's own map
LIM.obstacles = load_region_obstacles(world, (SX, SY), (160.0, 260.0, -285.0, -215.0), ground_z=GZ)
print("map keep-outs:", len(LIM.obstacles), flush=True)


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

    def add_walker(self, bp, start):
        walker = world.try_spawn_actor(bp, carla.Transform(carla.Location(start.x, start.y, start.z + 0.6)))
        if walker is None:
            return False
        ctrl = world.spawn_actor(world.get_blueprint_library().find("controller.ai.walker"), carla.Transform(), attach_to=walker)
        ctrl.start()
        ctrl.set_max_speed(self.rng.uniform(1.0, 1.5))
        goal = self.pick_point(start)
        ctrl.go_to_location(goal)
        self.walkers.append([walker, ctrl, goal])
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
                    if math.hypot(loc.x - w[2].x, loc.y - w[2].y) < 2.0:
                        w[2] = self.pick_point(loc)
                        w[1].go_to_location(w[2])
            except Exception:
                pass
            time.sleep(0.25)

    def end(self):
        self.stop_ev.set()
        time.sleep(0.5)
        for w in self.walkers:
            for a in (w[1], w[0]):
                try:
                    if a is w[1]:
                        a.stop()
                    a.destroy()
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


def start_film(tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    cam = world.spawn_actor(camera_blueprint(world, tick=1.0 / FPS), carla.Transform(carla.Location(217 + SX, -149 + SY, 8)))
    writer = PipeWriter(os.path.join(OUT_DIR, f"{tag}_view.mp4"))
    q, halt = queue.Queue(), threading.Event()
    cam.listen(q.put)
    trees = TreeBoxes(world)

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
                want = (me[0] - ux * 10.0, me[1] - uy * 10.0, me[2] + 3.2)
                aim = (me[0] + ux * 9.0, me[1] + uy * 9.0, me[2] - 1.0)
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
    def __init__(self, x, y, r=3.0):
        self.x, self.y, self.detection_radius_m = x, y, r


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


A, T1, T2 = parse(args.A), parse(args.T1), parse(args.T2)
out = []
finish_film = None
try:
    populate()
    crowd.start()
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
    time.sleep(8.0)                          # a few seconds for the autopilot cars and the AI pedestrians to get going
    del samples[:]
    if args.film:
        finish_film = start_film(args.film)       # filming starts here, as the first leg begins
        time.sleep(1.0)
    _st = adapter.get_position()
    _wp = (_st[0] + ox, _st[1] + oy, _st[2])
    print("start position", _wp, "static blockers:", _blockers(_wp, _wp[2], LIM.obstacle_margin_m),
          "route obstacles that block it:", [(type(o).__name__, round(o.x, 1), round(o.y, 1)) for o in agent._route_obstacles()
                                              if o.blocks_point(_wp[0], _wp[1], _wp[2], LIM.obstacle_margin_m)], flush=True)
    _Stub.targets = [_Target(*T1)]
    out.append(leg("weave_through_pedestrians_to_T1", T1))
    time.sleep(0.4)                                          # on the target
    _Stub.targets = []                                       # it disappears,
    time.sleep(0.8)
    _Stub.targets = [_Target(*T2)]                           # and a second one appears across the street
    out.append(leg("through_traffic_to_T2", T2))
    time.sleep(1.2)
finally:
    stop.set()
    time.sleep(0.8)                     # the sampler stops before anything is closed
    crowd.end()
    res = {"film": None, "tag": args.tag, "height": args.height, "peds": args.peds, "cars": args.cars, "legs": out, "samples": samples}
    json.dump(res, open(os.path.expanduser(f"~/live_big_{args.tag}.json"), "w"))       # saved first, in case closing the video goes wrong
    film = finish_film() if finish_film else None
    res["film"] = film
    json.dump(res, open(os.path.expanduser(f"~/live_big_{args.tag}.json"), "w"))
print(json.dumps({"legs": out}, indent=1))
