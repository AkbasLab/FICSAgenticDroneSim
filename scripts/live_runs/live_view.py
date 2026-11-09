"""A live picture of the sim in a small window, for watching a run while the sim itself runs headless.

Kept outside the repo, next to the live scripts. The sim's own window is slow on Heidi (about 1 frame a second through
the virtual desktop) while the headless sim ticks at 60 a second, so this films the world with a camera sensor and
draws the frames in an ordinary window, which the desktop shows smoothly. It never sends a command to a drone: moving
the camera, or recording from it, cannot affect a mission. It uses the same camera views as the recordings
(run_recorder.py), so what you watch is what gets filmed, unless you take the camera yourself.

Run from a terminal inside the Heidi Desktop session (after `source ~/.carlaair/ports.env`):
    python live_view.py                        chase view: behind Drone1, looking toward T1 (the default)
    python live_view.py --focus 29.6,30.4      ...looking toward the lamp pole instead
    python live_view.py --view pair            frames Drone1 and Drone2 together (separation tests)
    python live_view.py --view overview        fixed high view over the whole scene (everything is tiny)
    python live_view.py --record mytake        also write ~/recordings/mytake_view.mp4 of exactly what this window shows

Keys:  F  switch between the automatic camera and your own (free) camera
       free camera:  W A S D move,  E or Space up,  Q or Shift down,  hold the right mouse button and drag to look,
                     mouse wheel changes speed (Ctrl-click does nothing special)
       Esc closes the window.
Also: --mark-pole draws a yellow marker on the lamp pole; --no-targets hides the green target markers.
Zones are drawn by the flight script (run it with --overlay).
"""
import argparse
import math
import os
import queue
import sys
import threading
import time

import carla
import numpy as np
import pygame

sys.path.insert(0, os.path.expanduser("~"))
from run_recorder import (CARLA_PORT, GZ, HEIGHT, OUT_DIR, SX, SY, WIDTH, GridWriter, TreeBoxes, ViewPoser,   # noqa: E402
                          camera_blueprint, overview_pose, look_at, clear_of_walls)

parser = argparse.ArgumentParser()
parser.add_argument("--view", default="chase", choices=["chase", "pair", "overview"])
parser.add_argument("--vehicle", default="SimpleFlight", help="a vehicle name, or auto: follow one that is still flying (see AutoPoser)")
parser.add_argument("--follow", default=None, help="with --vehicle auto: follow this drone (e.g. Drone3) from the start and never switch")
parser.add_argument("--heading", default=None, help="with --follow: the direction the camera looks at first, as dx,dy")
parser.add_argument("--scenario", default=None, help="scenario file whose spawn offsets place each vehicle (with --vehicle auto)")
parser.add_argument("--focus", default="30,30", help="x,y the chase view looks toward (T1 by default)")
parser.add_argument("--no-targets", action="store_true")
parser.add_argument("--mark-pole", action="store_true")
parser.add_argument("--record", default=None, help="tag: write ~/recordings/<tag>_view.mp4 of what this window shows")
args = parser.parse_args()

client = carla.Client("localhost", CARLA_PORT)
client.set_timeout(10.0)
world = client.get_world()
camera = world.spawn_actor(camera_blueprint(world, tick=0.025), overview_pose())
poser = None
class AutoPoser(ViewPoser):
    """Chase camera for a team: sits behind the drone it follows, looking the way that drone is moving. It stays on a drone
    while it is in the air; when that drone lands it moves to the airborne one that took off first (the one that has been
    flying longest), so the picture never sits on a drone that is done."""

    def __init__(self, camera, scenario_path, world=None, follow=None, heading=None):
        import json
        super().__init__(camera, "chase", "SimpleFlight", "Drone2", (0.0, 0.0), world=world)
        sc = json.load(open(os.path.expanduser(scenario_path)))
        self.names = [d["name"] for d in sc["drones"]]
        self.vehicle_of = {n: ("SimpleFlight" if n == "Drone1" else n) for n in self.names}
        self.spawn = {self.vehicle_of[d["name"]]: tuple(d["spawn_offset"][:2]) for d in sc["drones"]}
        self.ground, self.up_since, self.followed, self.last_xy, self.heading = {}, {}, "SimpleFlight", {}, (1.0, 0.0)
        self.label = "Drone1"
        self.pinned = None
        if follow:
            self.pinned = self.vehicle_of[follow]
            self.followed = self.pinned
            self.label = follow
        if heading:
            hx, hy = heading
            n = math.hypot(hx, hy) or 1.0
            self.heading = (hx / n, hy / n)
        for v in self.spawn:                       # the drones stand on the ground when the viewer starts
            self.ground[v] = 29.25                  # the measured ground reading of this sim run (every drone read 29.1 to 29.25 on the ground)

    def _carla_pos(self, name):
        p = self.client.getMultirotorState(name).kinematics_estimated.position
        ox, oy = self.spawn[name]
        return (p.x_val + ox + SX, p.y_val + oy + SY, GZ + (self.ground[name] - p.z_val) + 0.0)

    def _airborne(self, v):
        p = self.client.getMultirotorState(v).kinematics_estimated.position
        return self.ground[v] - p.z_val > 3.0

    def _choose(self):
        if self.pinned:
            return self.pinned
        now = time.monotonic()
        if now - getattr(self, "_chosen_at", 0.0) < 1.0:      # six state reads per step starved the picture; look once a second
            return self.followed
        self._chosen_at = now
        up = [v for v in self.spawn if self._airborne(v)]
        for v in self.spawn:
            if v in up:
                self.up_since.setdefault(v, now)
            else:
                self.up_since.pop(v, None)
        if self.followed in up or not up:
            return self.followed
        self.followed = min(up, key=lambda v: self.up_since[v])
        self.label = next(n for n, vv in self.vehicle_of.items() if vv == self.followed)
        self._fix = None
        return self.followed

    def run(self):
        while not self._halt.is_set():
            if self.paused:
                time.sleep(0.03)
                continue
            try:
                v = self._choose()
                me = self._carla_pos(v)
                last = self.last_xy.get(v)
                self.last_xy[v] = me
                if last is not None:
                    dx, dy = me[0] - last[0], me[1] - last[1]
                    d = math.hypot(dx, dy)
                    if d > 0.02:
                        h = (dx / d, dy / d)
                        self.heading = (self.heading[0] * 0.97 + h[0] * 0.03, self.heading[1] * 0.97 + h[1] * 0.03)
                        n = math.hypot(*self.heading) or 1.0
                        self.heading = (self.heading[0] / n, self.heading[1] / n)
                ux, uy = self.heading
                cam = (me[0] - ux * 12.0, me[1] - uy * 12.0, me[2] + 6.0)
                aim = (me[0] + ux * 10.0, me[1] + uy * 10.0, me[2] - 1.0)
                if self.world is not None:
                    if self._step % 6 == 0 or self._fix is None:
                        fixed = clear_of_walls(self.world, me, cam, trees=self.trees)
                        self._fix = tuple(f - c for f, c in zip(fixed, cam))
                    self._step += 1
                    cam = tuple(c + d for c, d in zip(cam, self._fix))
                if self._cam is None:
                    self._cam, self._aim = cam, aim
                else:
                    a = 0.2
                    self._cam = tuple(c + a * (n - c) for c, n in zip(self._cam, cam))
                    self._aim = tuple(c + a * (n - c) for c, n in zip(self._aim, aim))
                self.camera.set_transform(look_at(self._cam, self._aim))
            except Exception:
                pass
            time.sleep(0.03)


if args.view != "overview" and args.vehicle == "auto":
    poser = AutoPoser(camera, args.scenario or "~/FICSAgenticDroneSim/configs/missions/full_map_001.json", world=world,
                      follow=args.follow, heading=tuple(float(v) for v in args.heading.split(",")) if args.heading else None)
    poser.start()
elif args.view != "overview":
    poser = ViewPoser(camera, args.view, args.vehicle, "Drone2", tuple(float(v) for v in args.focus.split(",")),
                      world=world)
    poser.start()
frames = queue.Queue(maxsize=2)
trees = TreeBoxes(world)
os.makedirs(OUT_DIR, exist_ok=True)
writer = GridWriter(os.path.join(OUT_DIR, f"{args.record}_view.mp4")) if args.record else None
rec_frames = queue.Queue()


def on_frame(image):
    if writer:
        rec_frames.put(image)
    try:
        frames.put_nowait(image)
    except queue.Full:
        pass


def write_loop():
    while writer and not stop_writer.is_set() or (writer and not rec_frames.empty()):
        try:
            writer.add(rec_frames.get(timeout=0.3))
        except queue.Empty:
            continue


stop_writer = threading.Event()
if writer:
    threading.Thread(target=write_loop, daemon=True).start()
camera.listen(on_frame)


# Targets are fixed, so this window draws them itself. Zones switch on during a run, so they come from the flight
# script (--overlay); they show here because debug shapes are part of the world.
def draw_markers():
    sys.path.insert(0, os.path.expanduser("~/FICSAgenticDroneSim"))
    from fics_drone.core.scenario import load_scenario
    import zone_overlay
    scenario = load_scenario(os.path.expanduser("~/FICSAgenticDroneSim/configs/missions/search_relay_001.json"))
    yellow = carla.Color(140, 120, 0, 255)
    while True:
        try:
            if not args.no_targets:
                for target in scenario.targets:
                    zone_overlay._draw_target(world.debug, target)
            if args.mark_pole:
                base = carla.Location(29.6 + SX, 30.4 + SY, GZ)
                top = carla.Location(base.x, base.y, GZ + 14.0)
                world.debug.draw_line(base, top, 0.1, yellow, 0.6)
                for dx, dy in ((1.5, 0.0), (0.0, 1.5)):
                    world.debug.draw_line(carla.Location(top.x - dx, top.y - dy, top.z),
                                          carla.Location(top.x + dx, top.y + dy, top.z), 0.1, yellow, 0.6)
        except Exception:
            pass
        time.sleep(0.25)


threading.Thread(target=draw_markers, daemon=True).start()
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()
free = {"on": False, "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "pitch": 0.0, "speed": 6.0}


def title():
    mode = "FREE camera (F: back to auto)" if free["on"] else f"{args.view} (F: take the camera)"
    pygame.display.set_caption(f"CarlaAir live view - {mode}" + ("  [REC]" if writer else "") + "  Esc closes")


def toggle_free():
    if not free["on"]:
        t = camera.get_transform()
        free.update(on=True, pos=[t.location.x, t.location.y, t.location.z], yaw=t.rotation.yaw, pitch=t.rotation.pitch)
        if poser:
            poser.paused = True
    else:
        free["on"] = False
        if poser:
            poser.paused = False
    title()


def steer(dt):
    keys = pygame.key.get_pressed()
    yaw, pitch = math.radians(free["yaw"]), math.radians(free["pitch"])
    fwd = (math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch))
    right = (-math.sin(yaw), math.cos(yaw), 0.0)
    move = [0.0, 0.0, 0.0]
    for key, vec, sign in ((pygame.K_w, fwd, 1), (pygame.K_s, fwd, -1), (pygame.K_d, right, 1), (pygame.K_a, right, -1)):
        if keys[key]:
            move = [m + sign * v for m, v in zip(move, vec)]
    if keys[pygame.K_e] or keys[pygame.K_SPACE]:
        move[2] += 1.0
    if keys[pygame.K_q] or keys[pygame.K_LSHIFT]:
        move[2] -= 1.0
    wanted = [p + m * free["speed"] * dt for p, m in zip(free["pos"], move)]
    if not trees.contains(wanted, pad=0.3):        # a tree stops the free camera too
        free["pos"] = wanted
    camera.set_transform(carla.Transform(carla.Location(*free["pos"]),
                                         carla.Rotation(pitch=free["pitch"], yaw=free["yaw"])))


title()
shown = [0, time.monotonic()]
try:
    running = True
    last = time.monotonic()
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_f:
                toggle_free()
            elif event.type == pygame.MOUSEMOTION and free["on"] and event.buttons[2]:
                free["yaw"] += event.rel[0] * 0.2
                free["pitch"] = max(-89.0, min(89.0, free["pitch"] - event.rel[1] * 0.2))
            elif event.type == pygame.MOUSEWHEEL and free["on"]:
                free["speed"] = max(1.0, min(40.0, free["speed"] * (1.25 ** event.y)))
        now = time.monotonic()
        if free["on"]:
            steer(now - last)
        last = now
        try:
            image = frames.get(timeout=0.2)
        except queue.Empty:
            continue
        # the frame is BGRA bytes: draw it straight, no numpy copy; the wait for the next frame is the only pacing (a 30 fps
        # cap on top of a camera at a different rate dropped frames unevenly)
        screen.blit(pygame.image.frombuffer(bytes(image.raw_data), (image.width, image.height), "BGRA"), (0, 0))
        pygame.display.flip()
        shown[0] += 1
        if time.monotonic() - shown[1] > 5:
            print(f"drawn {shown[0] / (time.monotonic() - shown[1]):.1f} frames/s", flush=True); shown[:] = [0, time.monotonic()]
finally:
    stop_writer.set()
    time.sleep(0.5)
    if writer:
        print("recorded", writer.close())
    if poser:
        poser.stop()
    camera.stop()
    camera.destroy()
    pygame.quit()
