"""FILMED target mission (chase camera): Drone3 flies out along the road to a target, a pedestrian walks at it on the way out, then flies back
while a car drives at it. Same flight code and avoidance as live_moving.py; adds a camera behind the drone that records
~/recordings/<film>_view.mp4, and a green target marker at B. --film <tag> turns the camera on.

Original notes:
Live check of vehicles and pedestrians: Drone3 flies LOW (default 4 m, under a person's top plus the guardian's vertical pad)
along the clear road x=-52, and the simulator's own pedestrian and car come at it head-on. The agent and NavRL read them
from the world (core/moving.CarlaMovers); with --avoid off they are ignored, as before, for comparison.
Leg 1: a real pedestrian walks toward the drone at 1.4 m/s. Leg 2: a real car drives toward it at 6 m/s.
Writes ~/live_moving_<tag>.json. Run: NAVRL_PROFILE=limit5 ~/run_navrl_py.sh live_moving.py --tag V1 [--avoid off] [--overlay]"""
import argparse
import json
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.expanduser("~/FICSAgenticDroneSim"))
sys.path.insert(0, os.path.expanduser("~"))
import carla
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.control.skills import take_off
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.core.moving import CarlaMovers
from fics_drone.core.scenario import DRONE_RADIUS_M, load_scenario
from fics_drone.planners.navrl_planner import NavRLPlanner
from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter

ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--height", type=float, default=4.0)
ap.add_argument("--avoid", default="on", choices=["on", "off"])
ap.add_argument("--overlay", action="store_true")
ap.add_argument("--film", default=None, help="tag for the recording ~/recordings/<tag>_view.mp4")
ap.add_argument("--A", default="236,-246.5")
ap.add_argument("--B", default="182,-246.5")
args = ap.parse_args()
SX, SY = -172.2, 183.86                       # CARLA x, y = mission world x, y + (SX, SY)

client = carla.Client("localhost", int(os.environ["CARLA_PORT"]))
client.set_timeout(20.0)
world = client.get_world()
movers = CarlaMovers(world, origin=(SX, SY), refresh_s=0.1)
scenario = load_scenario(os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/full_map_001.json"))
spec = next(d for d in scenario.drones if d.name == "Drone3")
ox, oy, _ = spec.spawn_offset
adapter = AirSimVehicleAdapter("Drone3")
planner = NavRLPlanner()
bus = MessageBus()
agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name="Drone3",
                        link=AgentLink(bus, "Drone3"), cruise_height=args.height, leg_planner=planner, leg_timeout_s=300.0)
if args.avoid == "on":
    planner.movers_fn = movers.snapshot
    agent.guardian.limits.moving_fn = movers.snapshot
LIM = agent.guardian.limits
LIM.altitude_floor_m = min(LIM.altitude_floor_m, args.height - 0.5)      # the demo flies below the default 3 m floor


def ground_z(x, y):
    try:
        return world.ground_projection(carla.Location(x, y, 100.0), 200.0).location.z
    except Exception:
        return -1.8


class Driver(threading.Thread):
    """Keeps one spawned actor moving at a steady velocity (mission-frame direction) until stopped."""
    def __init__(self, actor, vx, vy, kind):
        super().__init__(daemon=True)
        self.actor, self.vx, self.vy, self.kind, self.stop_ev = actor, vx, vy, kind, threading.Event()

    def run(self):
        speed = math.hypot(self.vx, self.vy)
        while not self.stop_ev.is_set():
            try:
                if self.kind == "walker":
                    self.actor.apply_control(carla.WalkerControl(carla.Vector3D(self.vx / speed, self.vy / speed, 0.0), speed))
                else:
                    self.actor.set_target_velocity(carla.Vector3D(self.vx, self.vy, 0.0))
            except Exception:
                pass
            time.sleep(0.1)

    def end(self):
        self.stop_ev.set()
        time.sleep(0.2)
        try:
            self.actor.destroy()
        except Exception:
            pass


def spawn(kind, x, y, vx, vy):
    """kind 'walker' or 'vehicle'; (x, y) mission metres. Returns a started Driver."""
    bp = world.get_blueprint_library().find("walker.pedestrian.0031" if kind == "walker" else "vehicle.audi.a2")
    yaw = math.degrees(math.atan2(vy, vx))
    z = ground_z(x + SX, y + SY) + (1.0 if kind == "walker" else 0.6)
    actor = world.spawn_actor(bp, carla.Transform(carla.Location(x + SX, y + SY, z), carla.Rotation(yaw=yaw)))
    drv = Driver(actor, vx, vy, kind)
    drv.start()
    return drv


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
            objs = [(o.name, o.kind, round(o.x, 2), round(o.y, 2), o.radius, o.height) for o in movers.snapshot()]
            samples.append((round(time.monotonic() - t0, 2), round(x + ox, 2), round(y + oy, 2), round(z, 2), bool(info.has_collided), objs))
        except Exception:
            pass
        time.sleep(0.25)


threading.Thread(target=sampler, daemon=True).start()

if args.overlay:
    from zone_overlay import start_overlay

    def rings():
        out = []
        try:
            for name in ("Drone3",):
                x, y, z = adapter.get_position()
                out.append((x + ox, y + oy, z, scenario.min_separation_m / 2.0))
        except Exception:
            pass
        out += [(o.x, o.y, 0.3, o.radius + LIM.moving_pad_m) for o in movers.snapshot()]
        return out

    start_overlay(scenario, lambda: time.monotonic() - t0, stop, rings_fn=rings)


def leg(name, target_world, kind=None, start=None, vel=None, stay_s=0.0, z=None):
    """Fly one leg; if kind is given, spawn that mover at `start` moving at `vel` (mission frame) as the leg begins."""
    view["target"] = (target_world[0], target_world[1])
    a, i0, trace, drv = time.monotonic(), len(samples), [], None
    if kind:
        drv = spawn(kind, start[0], start[1], vel[0], vel[1])
    try:
        event = agent._guarded_fly((target_world[0] - ox, target_world[1] - oy, z or args.height), trace)
    finally:
        if drv:
            drv.end()
    seg = samples[i0:]
    closest, contact, inside_guard = 1e9, 0, 0
    for s in seg:
        for (_n, _k, mx, my, r, h) in s[5]:
            d = math.hypot(s[1] - mx, s[2] - my)
            if s[3] < h + LIM.moving_vertical_pad_m:
                closest = min(closest, d - r)                      # gap between the drone's centre and the body's edge
                inside_guard += d < r + LIM.moving_pad_m
                contact += (d < r + DRONE_RADIUS_M) and s[3] < h + DRONE_RADIUS_M
    return {"leg": name, "mover": kind, "event": event.value, "seconds": round(time.monotonic() - a, 1), "trace": trace,
            "closest_edge_gap_m_while_low": None if closest > 1e8 else round(closest, 2),
            "samples_inside_guard_circle_while_low": int(inside_guard), "samples_body_contact": int(contact),
            "collision_samples": sum(1 for s in seg if s[4]), "min_z": min((s[3] for s in seg), default=None),
            "final": list(seg[-1][1:4]) if seg else None}


import queue
from run_recorder import GridWriter, TreeBoxes, camera_blueprint, clear_of_walls, look_at, OUT_DIR, FPS
GZ = -1.8
view = {"target": None}                       # mission-frame (x, y) the camera looks toward


def start_film(tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    cam = world.spawn_actor(camera_blueprint(world, tick=1.0 / FPS), carla.Transform(carla.Location(217 + SX, -149 + SY, 8)))
    writer = GridWriter(os.path.join(OUT_DIR, f"{tag}_view.mp4"))
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
        heading, c, a, fix, step = (0.0, -1.0), None, None, None, 0
        ang, last_t = [-math.pi / 2], [time.monotonic()]   # chase starts looking south, toward the road
        while not halt.is_set():
            try:
                x, y, z = adapter.get_position()
                mx, my = x + ox, y + oy
                me = (mx + SX, my + SY, ground_z(mx + SX, my + SY) + z)
                tgt = view["target"]
                if tgt is not None:
                    dx, dy = tgt[0] - mx, tgt[1] - my
                    if math.hypot(dx, dy) > 2.0:
                        want_ang = math.atan2(dy, dx)
                        now = time.monotonic()
                        dt, last_t[0] = min(now - last_t[0], 0.2), now
                        delta = (want_ang - ang[0] + math.pi) % (2 * math.pi) - math.pi
                        step_a = math.radians(110.0) * dt            # the view turns at a steady rate, so a turn-around swings round the drone
                        ang[0] += max(-step_a, min(step_a, delta))
                    heading = (math.cos(ang[0]), math.sin(ang[0]))
                ux, uy = heading
                want = (me[0] - ux * 10.0, me[1] - uy * 10.0, me[2] + 3.5)
                aim = (me[0] + ux * 9.0, me[1] + uy * 9.0, me[2] - 1.5)
                if step % 6 == 0 or fix is None:
                    fixed = clear_of_walls(world, me, want, trees=trees)
                    fix = tuple(f - w for f, w in zip(fixed, want))
                step += 1
                want = tuple(w + f for w, f in zip(want, fix))
                if c is None:
                    c, a = want, aim
                else:
                    c = tuple(p + 0.2 * (n - p) for p, n in zip(c, want))
                    a = tuple(p + 0.2 * (n - p) for p, n in zip(a, aim))
                cam.set_transform(look_at(c, a))
            except Exception:
                pass
            time.sleep(0.03)

    threading.Thread(target=pump, daemon=True).start()
    threading.Thread(target=pose, daemon=True).start()

    def finish():
        time.sleep(1.5)
        halt.set()
        time.sleep(1.0)
        cam.stop()
        try:
            cam.destroy()
        except Exception:
            pass
        return writer.close()
    return finish


class _Target:
    def __init__(self, x, y, r):
        self.x, self.y, self.detection_radius_m = x, y, r


def draw_target_loop(tg):
    from zone_overlay import _draw_target
    while not stop.is_set():
        try:
            _draw_target(world.debug, tg)
        except Exception:
            pass
        time.sleep(0.25)


A = tuple(float(v) for v in args.A.split(","))
B = tuple(float(v) for v in args.B.split(","))
out = []
finish_film, film_t0 = None, time.monotonic()
if args.film:
    finish_film = start_film(args.film)
    film_t0 = time.monotonic()
    from zone_overlay import start_overlay as _so

    class _Stub:                                             # only the target marker and the rings: no zones, no trees
        no_fly_zones, obstacles = [], []
        targets = [_Target(B[0], B[1], 3.0)]

    def _film_rings():
        out = []
        try:
            x, y, z = adapter.get_position()
            pass                                              # no ring round the drone in the film
        except Exception:
            pass
        return []                                          # no rings in the film: only the green target (and any no-fly zones)
    _so(_Stub, lambda: time.monotonic() - t0, stop, rings_fn=_film_rings)
try:
    take_off(adapter)
    agent.belief.position = adapter.get_position()
    # setup for the film: the drone is placed over the start of the road (the transit through the tall street is not what this
    # video is about), then everything that follows is the real flight code
    import airsim
    from fics_drone.control.skills import go_to_waypoint
    asc = airsim.MultirotorClient()
    asc.confirmConnection()
    pose = asc.simGetVehiclePose("Drone3")
    pose.position.x_val, pose.position.y_val, pose.position.z_val = A[0] - ox, A[1] - oy, args.height
    pose.orientation = airsim.to_quaternion(0.0, 0.0, math.pi)     # facing -x, down the road toward the target
    asc.simSetVehiclePose(pose, True, "Drone3")
    time.sleep(1.5)
    go_to_waypoint(adapter, A[0] - ox, A[1] - oy, args.height)
    agent.belief.position = adapter.get_position()
    print("FILM_START_OFFSET_S", round(time.monotonic() - film_t0, 1), "placed at", adapter.get_position(), flush=True)
    del samples[:]                                           # the setup move is not part of the measurement
    out.append(leg("A_to_B_pedestrian_head_on", B, "walker", (206.0, -247.6), (1.4, 0.0)))
    time.sleep(2.0)                                           # target reached: a short pause on it
    out.append(leg("B_to_A_car_head_on", A, "vehicle", (238.0, -248.2), (-6.0, 0.0)))
finally:
    time.sleep(1.0)
    film = finish_film() if finish_film else None
    stop.set()
    time.sleep(0.6)
res = {"film": film, "tag": args.tag, "avoid": args.avoid, "height": args.height, "legs": out, "samples": samples}
json.dump(res, open(os.path.expanduser(f"~/live_moving_film_{args.tag}.json"), "w"))
print(json.dumps({"avoid": args.avoid, "legs": out}, indent=1))
