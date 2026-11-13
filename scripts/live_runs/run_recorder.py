"""Records a live run to an MP4 from a camera placed in the CarlaAir world. Runs unattended (no window or keys).

Kept outside the repo, next to the live scripts. This is not CarlaAir's own recording toolkit: that one records a
trajectory by hand and replays it later with a director camera and an F key (see CarlaAir-repo/examples/recording).
Here a camera sensor is added to the world, so it films the real flight as it happens, zone and target markers
included if the overlay is on. The sensor is removed when recording stops.

Views (RECORD_VIEW, default chase):
  chase     follows Drone1 from behind and above and looks toward the thing under test (`focus`, default T1 at (30, 30)),
            so the drone is in the foreground and the zone, target or obstacle ahead of it is in frame
  pair      frames two drones together from the side (separation, two drones in one sector)
  overview  a fixed high view over the whole scene; everything is tiny from there, use it only for a map-like shot

Files go to ~/recordings/<tag>.mp4 on the machine running it (Heidi). They are never added to a git repo.

Use: stop = start_recording(tag); ...flight...; stop()     (RECORD_FOCUS="29.6,30.4" to aim at the lamp pole instead)
"""
import math
import os
import queue
import threading
import time

import carla
import cv2
import numpy as np

CARLA_PORT = int(os.environ.get("CARLA_PORT", 2100))   # set by ~/.carlaair/ports.env
SX, SY, GZ = -172.2, 183.86, -1.8     # measured frame, see memory reference_carlaair_live_setup
OUT_DIR = os.path.expanduser("~/recordings")
WIDTH, HEIGHT = (int(v) for v in os.environ.get("RECORD_RES", "1280x720").lower().split("x"))   # e.g. 1600x900
FPS = int(os.environ.get("RECORD_FPS", 30))   # 60 was tried: only ~33 a second get captured, so the file played too fast
SPAWN_XY = {"SimpleFlight": (0.0, 0.0), "Drone2": (0.0, 20.0)}   # local to world: where each vehicle starts
DEFAULT_FOCUS = (30.0, 30.0)   # T1


def overview_pose(centre_world=(14.0, 14.0), back_m=18.0, up_m=75.0):
    """A camera high above the scene, tilted steeply down."""
    tx, ty, tz = centre_world[0] + SX, centre_world[1] + SY, GZ + 5.0
    cx, cy, cz = tx, ty - back_m, GZ + up_m
    yaw = math.degrees(math.atan2(ty - cy, tx - cx))
    pitch = -math.degrees(math.atan2(cz - tz, math.hypot(tx - cx, ty - cy)))
    return carla.Transform(carla.Location(cx, cy, cz), carla.Rotation(pitch=pitch, yaw=yaw))


def look_at(cam, aim):
    yaw = math.degrees(math.atan2(aim[1] - cam[1], aim[0] - cam[0]))
    pitch = -math.degrees(math.atan2(cam[2] - aim[2], math.hypot(aim[0] - cam[0], aim[1] - cam[1])))
    return carla.Transform(carla.Location(*cam), carla.Rotation(pitch=pitch, yaw=yaw))


def chase_target(drone, focus_xy, back=12.0, up=6.0, look_frac=0.5, look_max=20.0):
    """Camera and aim points (CARLA coordinates) for a chase view: `back` metres behind the drone, on the side away
    from `focus_xy`, `up` above it, aimed at a point toward the focus (half way, at most look_max ahead) so the drone
    sits in the foreground and what it is flying toward is in front of it."""
    dx, dy = focus_xy[0] - drone[0], focus_xy[1] - drone[1]
    dist = math.hypot(dx, dy)
    ux, uy = (dx / dist, dy / dist) if dist > 0.5 else (1.0, 0.0)
    cam = (drone[0] - ux * back, drone[1] - uy * back, drone[2] + up)
    ahead = min(dist * look_frac, look_max)
    aim = (drone[0] + ux * ahead, drone[1] + uy * ahead, drone[2] - 1.0)
    return cam, aim


class TreeBoxes:
    """The boxes (canopy included) of every tree near the flight area, in CARLA coordinates. The sim lists tens of
    thousands of vegetation objects, so only those inside `area` (world x_min, x_max, y_min, y_max) are kept, and the
    tests run on all of them at once with numpy (they run about 30 times a second)."""

    def __init__(self, world, area=(-70.0, 100.0, -70.0, 100.0)):
        rows = []
        for o in world.get_environment_objects(carla.CityObjectLabel.Vegetation):
            b = o.bounding_box
            if area[0] < b.location.x - SX < area[1] and area[2] < b.location.y - SY < area[3]:
                rows.append((b.location.x - b.extent.x, b.location.x + b.extent.x, b.location.y - b.extent.y,
                             b.location.y + b.extent.y, b.location.z - b.extent.z, b.location.z + b.extent.z))
        arr = np.array(rows, dtype=float).reshape(-1, 6)
        self.lo, self.hi = arr[:, [0, 2, 4]], arr[:, [1, 3, 5]]
        self.boxes = rows

    def contains(self, p, pad=0.6):
        p = np.asarray(p, float)
        return bool(np.any(np.all((p >= self.lo - pad) & (p <= self.hi + pad), axis=1)))

    def segment_hits(self, a, c, pad=0.6):
        """True if the straight line from a to c passes through any tree box (slab test, all boxes at once)."""
        a = np.asarray(a, float)
        d = np.asarray(c, float) - a
        lo, hi = self.lo - pad - a, self.hi + pad - a
        with np.errstate(divide="ignore", invalid="ignore"):
            t1, t2 = lo / d, hi / d
        inside = (lo <= 0) & (hi >= 0)
        flat = d == 0
        tmin = np.where(flat, np.where(inside, -np.inf, np.inf), np.minimum(t1, t2))
        tmax = np.where(flat, np.where(inside, np.inf, -np.inf), np.maximum(t1, t2))
        enter = np.maximum(0.0, tmin.max(axis=1))
        leave = np.minimum(1.0, tmax.min(axis=1))
        return bool(np.any(enter <= leave))


def clear_of_walls(world, anchor, cam, margin=0.8, min_back=2.0, trees=None):
    """Pulls the camera in toward `anchor` (the drone) if a wall or tree stands between them, so the picture is never
    taken from inside a building. A ray from the anchor to the wanted camera spot; the camera stops short of the hit."""
    try:
        hits = world.cast_ray(carla.Location(*anchor), carla.Location(*cam))
    except Exception:
        return cam
    full = math.dist(anchor, cam)
    # hits within 1.5 m are the drone's own body (or the ground it sits on), not a wall between it and the camera
    dists = [math.dist(anchor, (h.location.x, h.location.y, h.location.z)) for h in hits]
    nearest = min((d for d in dists if d > 1.5), default=None)
    keep = 1.0
    if nearest is not None and nearest < full:
        keep = max(min_back, nearest - margin) / full
    if trees is not None:
        # trees are invisible to the ray: shorten the camera arm until neither the camera nor its line to the drone is in one
        floor = min_back / full
        while keep > floor:
            spot = tuple(a + (c - a) * keep for a, c in zip(anchor, cam))
            if not trees.contains(spot) and not trees.segment_hits(anchor, spot):
                break
            keep -= 0.05
        keep = max(keep, floor)
    return tuple(a + (c - a) * keep for a, c in zip(anchor, cam)) if keep < 1.0 else cam


def pair_target(a, b, min_dist=9.0):
    """Camera and aim points that frame two drones: to the side of the line between them, far enough to hold both."""
    mx, my, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
    sep = math.hypot(b[0] - a[0], b[1] - a[1])
    px, py = -(b[1] - a[1]), (b[0] - a[0])
    n = math.hypot(px, py) or 1.0
    d = max(min_dist, sep * 0.75)
    cam = (mx + px / n * d, my + py / n * d, mz + d * 0.35)
    return cam, (mx, my, mz)


class ViewPoser(threading.Thread):
    """Moves the camera every ~30 ms to the pose its view asks for, smoothed so the picture does not jitter."""

    def __init__(self, camera, view, vehicle="SimpleFlight", mate="Drone2", focus_xy=DEFAULT_FOCUS, world=None):
        super().__init__(daemon=True)
        self.world = world
        self.trees = TreeBoxes(world) if world is not None else None
        self.camera, self.view, self.vehicle, self.mate = camera, view, vehicle, mate
        self.focus = (focus_xy[0] + SX, focus_xy[1] + SY)      # CARLA coordinates
        self._halt = threading.Event()
        self.paused = False      # True while a person drives the camera by hand (live_view.py)
        import airsim
        self.client = airsim.MultirotorClient()
        self.client.confirmConnection()
        self._cam = self._aim = None
        self._step, self._fix = 0, None

    def _carla_pos(self, name):
        p = self.client.getMultirotorState(name).kinematics_estimated.position
        ox, oy = SPAWN_XY[name]
        return (p.x_val + ox + SX, p.y_val + oy + SY, 27.45 - p.z_val)

    def run(self):
        while not self._halt.is_set():
            if self.paused:
                time.sleep(0.03)
                continue
            try:
                me = self._carla_pos(self.vehicle)
                if self.view == "pair":
                    cam, aim = pair_target(me, self._carla_pos(self.mate))
                else:
                    cam, aim = chase_target(me, self.focus)
                    if self.world is not None:
                        # the wall check is ray casts (about 33 ms), which held the camera to 18 updates a second: redo it every
                        # sixth step and in between move the camera by the same correction
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
                pass            # a failed read keeps the last pose for one step
            time.sleep(0.03)

    def stop(self):
        self._halt.set()


class GridWriter:
    """Writes camera frames to an MP4 on an exact 1/FPS grid of sim time (a late frame is covered by repeating the last
    picture), so the file plays at true speed. Used to record what the live view window shows."""

    def __init__(self, path):
        self.writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
        self.next_t, self.last, self.written, self.path = None, None, 0, path

    def add(self, image):
        rgb = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))[:, :, :3]
        if self.next_t is None:
            self.next_t = image.timestamp
        while self.next_t <= image.timestamp + 1e-6:
            self.writer.write(self.last if (self.last is not None and self.next_t < image.timestamp - 0.5 / FPS) else rgb)
            self.written += 1
            self.next_t += 1.0 / FPS
        self.last = rgb

    def close(self):
        self.writer.release()
        return self.path, self.written


def camera_blueprint(world, tick=None):
    bp = world.get_blueprint_library().find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(WIDTH))
    bp.set_attribute("image_size_y", str(HEIGHT))
    bp.set_attribute("fov", "90")
    if tick:
        bp.set_attribute("sensor_tick", str(tick))
    return bp


def start_recording(tag, pose=None, view=None, vehicle="SimpleFlight", mate="Drone2", focus_xy=None):
    """Starts filming; returns stop(), which finishes the file and returns (path, frames written)."""
    view = view or os.environ.get("RECORD_VIEW", "chase")
    if focus_xy is None:
        focus_xy = tuple(float(v) for v in os.environ.get("RECORD_FOCUS", "30,30").split(","))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{tag}.mp4")
    client = carla.Client("localhost", CARLA_PORT)
    client.set_timeout(10.0)
    world = client.get_world()
    camera = world.spawn_actor(camera_blueprint(world, tick=1.0 / FPS), pose or overview_pose())
    poser = None
    if view in ("chase", "pair") and pose is None:
        poser = ViewPoser(camera, view, vehicle, mate, focus_xy, world=world)
        poser.start()
    frames = queue.Queue()
    camera.listen(frames.put)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    done = threading.Event()
    written = [0]

    def pump():
        # Frames are placed on an exact 1/FPS grid of sim time: a frame the sim was late with is covered by repeating
        # the last picture, so the file plays at true speed even when fewer than FPS frames a second arrive.
        next_t, last = None, None
        while not done.is_set() or not frames.empty():
            try:
                image = frames.get(timeout=0.5)
            except queue.Empty:
                continue
            rgb = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))[:, :, :3]
            if next_t is None:
                next_t = image.timestamp
            while next_t <= image.timestamp + 1e-6:
                writer.write(last if (last is not None and next_t < image.timestamp - 0.5 / FPS) else rgb)
                written[0] += 1
                next_t += 1.0 / FPS
            last = rgb

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()

    def stop():
        if poser:
            poser.stop()
        camera.stop()
        done.set()
        thread.join(timeout=30)
        writer.release()
        camera.destroy()
        return path, written[0]

    return stop
