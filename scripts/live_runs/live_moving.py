"""Live check of vehicles and pedestrians: Drone4 flies LOW (default 4 m, under a person's top plus the guardian's vertical pad)
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
ap.add_argument("--A", default="-52,5")
ap.add_argument("--B", default="-52,-59")
args = ap.parse_args()
SX, SY = -172.2, 183.86                       # CARLA x, y = mission world x, y + (SX, SY)

client = carla.Client("localhost", int(os.environ["CARLA_PORT"]))
client.set_timeout(20.0)
world = client.get_world()
movers = CarlaMovers(world, origin=(SX, SY), refresh_s=0.1)
scenario = load_scenario(os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/full_map_001.json"))
spec = next(d for d in scenario.drones if d.name == "Drone4")
ox, oy, _ = spec.spawn_offset
adapter = AirSimVehicleAdapter("Drone4")
planner = NavRLPlanner()
bus = MessageBus()
agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name="Drone4",
                        link=AgentLink(bus, "Drone4"), cruise_height=args.height, leg_planner=planner, leg_timeout_s=300.0)
if args.avoid == "on":
    planner.movers_fn = movers.snapshot
    agent.guardian.limits.moving_fn = movers.snapshot
LIM = agent.guardian.limits


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
            info = cl.simGetCollisionInfo("Drone4")
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
            for name in ("Drone4",):
                x, y, z = adapter.get_position()
                out.append((x + ox, y + oy, z, scenario.min_separation_m / 2.0))
        except Exception:
            pass
        out += [(o.x, o.y, 0.3, o.radius + LIM.moving_pad_m) for o in movers.snapshot()]
        return out

    start_overlay(scenario, lambda: time.monotonic() - t0, stop, rings_fn=rings)


def leg(name, target_world, kind=None, start=None, vel=None, stay_s=0.0):
    """Fly one leg; if kind is given, spawn that mover at `start` moving at `vel` (mission frame) as the leg begins."""
    a, i0, trace, drv = time.monotonic(), len(samples), [], None
    if kind:
        drv = spawn(kind, start[0], start[1], vel[0], vel[1])
    try:
        event = agent._guarded_fly((target_world[0] - ox, target_world[1] - oy, args.height), trace)
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


A = tuple(float(v) for v in args.A.split(","))
B = tuple(float(v) for v in args.B.split(","))
out = []
try:
    take_off(adapter)
    agent.belief.position = adapter.get_position()
    out.append(leg("go_to_A", A))
    out.append(leg("A_to_B_pedestrian_head_on", B, "walker", (-52.0, -22.0), (0.0, 1.4)))
    out.append(leg("B_to_A_car_head_on", A, "vehicle", (-52.0, 2.0), (0.0, -6.0)))
    agent._guarded_fly((0.0, 0.0, args.height), [], purpose="home")
finally:
    stop.set()
    time.sleep(0.6)
res = {"tag": args.tag, "avoid": args.avoid, "height": args.height, "legs": out, "samples": samples}
json.dump(res, open(os.path.expanduser(f"~/live_moving_{args.tag}.json"), "w"))
print(json.dumps({"avoid": args.avoid, "legs": out}, indent=1))
