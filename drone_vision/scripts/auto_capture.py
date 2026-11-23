r"""Automatic street-level picture runs - version 4: 10-20 m above the streets, no getting stuck.


The simulator has to run, because it is what draws the pictures. Without --no-start this script starts it
off-screen (no window); it adds traffic, then makes one or more flights along roads taken from the CARLA map
and saves pictures from both cameras.


    python ~/drone-work/scripts/auto_capture.py --no-start --runs 3


Two ways to move along the street (--mode):
  hop  (default) the drone is placed every --step metres above the middle of the street, at a random height
       between --height-min and --height-max, facing along the road; it steadies for --settle seconds and
       both cameras take a picture. A point where it does not fit (tree, lamp, wall, overhang) is skipped,
       so it can never crash or get stuck. Best for collecting training pictures.
  fly  the drone really flies along the street at one height (random in the same range) and --speed.
       When it hits something, sees something closer than --clearance ahead, or stops moving, it jumps
       --skip route points forward past the problem instead of climbing; after --max-hops jumps the flight ends.
Each flight starts at a different random road point and saves into its own folder
~/drone-work/frames/auto_<date>_<time>_runNN/ (same files as capture_frames.py plus flight.json).
"""
import argparse
import datetime
import json
import math
import os
import pathlib
import random
import signal
import socket
import subprocess
import sys
import time


import airsim
import numpy as np


HOME = pathlib.Path.home()
# These two lines must point at where CarlaAir really is on this computer (not used with --no-start / --no-traffic).
SIM = pathlib.Path("/mnt/newhome/carlaair/CarlaAir-v0.1.7/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping")
TRAFFIC = pathlib.Path("/home/borysy/CarlaAir/examples/auto_traffic.py")
SETTINGS = HOME / "Documents" / "AirSim" / "settings.json"
LOGS = HOME / "drone-work" / "logs"
FRAMES = HOME / "drone-work" / "frames"
CAMERAS = ["front_center", "bottom_center"]




def port_open(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0




def wait_for_ports(seconds):
    end = time.time() + seconds
    while time.time() < end:
        if port_open(2000) and port_open(41451):
            return True
        time.sleep(5)
    return False




def stop(proc, name, sig=signal.SIGINT, wait=30):
    if proc is None or proc.poll() is not None:
        return
    print(f"stopping {name} ...", flush=True)
    proc.send_signal(sig)
    try:
        proc.wait(wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()




def position(c, v):
    return c.getMultirotorState(vehicle_name=v).kinematics_estimated.position




def distance_ahead(depth):
    h, w = depth.shape
    roi = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    roi = roi[np.isfinite(roi) & (roi > 0.2)]
    return (round(float(np.percentile(roi, 5)), 1), round(float(np.median(roi)), 1)) if roi.size else (None, None)




def nearest_ahead(c, v):
    dep = c.simGetImages([airsim.ImageRequest("front_center", airsim.ImageType.DepthPlanar, True, False)],
                         vehicle_name=v)[0]
    if dep.width == 0:
        return None
    return distance_ahead(np.array(dep.image_data_float, dtype=np.float32).reshape(dep.height, dep.width))[0]




def fly_to(c, v, x, y, z, speed):
    c.moveToPositionAsync(x, y, z, speed, drivetrain=airsim.DrivetrainType.ForwardOnly,
                          yaw_mode=airsim.YawMode(False, 0), vehicle_name=v)




def place(c, v, x, y, z, yaw_deg, settle):
    """Put the drone at (x, y, z) facing yaw_deg and hold it there. True if it fits there (no hit, did not move)."""
    hit_before = c.simGetCollisionInfo(vehicle_name=v).time_stamp
    pose = airsim.Pose(airsim.Vector3r(x, y, z), airsim.to_quaternion(0, 0, math.radians(yaw_deg)))
    c.simSetVehiclePose(pose, True, vehicle_name=v)
    c.moveToPositionAsync(x, y, z, 1, vehicle_name=v)               # hold here, do not fly back
    time.sleep(settle)
    p = position(c, v)
    moved = math.dist((p.x_val, p.y_val, p.z_val), (x, y, z))
    return moved < 1.0 and c.simGetCollisionInfo(vehicle_name=v).time_stamp == hit_before




# ---------- CARLA map: road points in AirSim coordinates ----------
def carla_world():
    import carla
    client = carla.Client("localhost", 2000)
    client.set_timeout(20.0)
    return client.get_world()




def carla_offset(world, c, v):
    """CARLA -> AirSim offset, measured on the drone itself (the same method CarlaAir's demo_director.py uses)."""
    drone = next((a for a in world.get_actors()
                  if "drone" in a.type_id.lower() or "airsim" in a.type_id.lower()), None)
    if drone is None:
        return None
    cl, ap = drone.get_location(), position(c, v)
    return (ap.x_val - cl.x, ap.y_val - cl.y, ap.z_val + cl.z)




def road_waypoints(start_wp, length, step, rng):
    """Waypoints along the road from start_wp, every `step` metres, random turn at each junction."""
    wps, wp, total = [start_wp], start_wp, 0.0
    while total < length:
        nxt = wp.next(step)
        if not nxt:
            break
        wp = rng.choice(nxt)
        wps.append(wp)
        total += step
    return wps




def street_point(wp, offset):
    """(x, y, ground_z, yaw) in AirSim coordinates above the middle of the street at this waypoint.
    Waypoints lie in the middle of the right-hand lane; when there is a driving lane on its left, move half a
    lane to the left, onto the line between them, which keeps the drone further from trees and lamps."""
    import carla
    loc, yaw = wp.transform.location, wp.transform.rotation.yaw
    x, y, z = loc.x, loc.y, loc.z
    try:
        left = wp.get_left_lane()
        if left is not None and left.lane_type == carla.LaneType.Driving:
            r = wp.transform.get_right_vector()
            x, y = x - r.x * wp.lane_width / 2, y - r.y * wp.lane_width / 2
    except Exception:
        pass
    return (x + offset[0], y + offset[1], -z + offset[2], yaw)




def save_pictures(c, v, out, k, index):
    pos = position(c, v)
    saved = 0
    for cam in CAMERAS:
        rgb, dep = c.simGetImages([
            airsim.ImageRequest(cam, airsim.ImageType.Scene, False, True),
            airsim.ImageRequest(cam, airsim.ImageType.DepthPlanar, True, False)], vehicle_name=v)
        if rgb.width == 0 or dep.width == 0:
            continue
        stem = f"{v}_{cam}_{k:05d}"
        airsim.write_file(os.fspath(out / (stem + ".png")), rgb.image_data_uint8)
        depth = np.array(dep.image_data_float, dtype=np.float32).reshape(dep.height, dep.width)
        np.save(out / (stem + "_depth.npy"), depth)
        near, med = distance_ahead(depth)
        p, q = rgb.camera_position, rgb.camera_orientation
        index.write(json.dumps({
            "stem": stem, "vehicle": v, "camera": cam, "time_ns": int(rgb.time_stamp),
            "size": [rgb.width, rgb.height], "depth_size": [dep.width, dep.height],
            "cam_pos": [p.x_val, p.y_val, p.z_val], "cam_q": [q.w_val, q.x_val, q.y_val, q.z_val],
            "vehicle_pos": [pos.x_val, pos.y_val, pos.z_val],
            "ahead_nearest_m": near, "ahead_median_m": med}) + "\n")
        saved += 1
    index.flush()
    return saved




def hop_flight(c, v, a, route, out, rng):
    """Place the drone at every route point in turn and take pictures there. Returns (reason, pictures)."""
    end = time.time() + a.max_minutes * 60
    k = saved = skipped = blocked_in_a_row = 0
    reason = "route finished"
    with open(out / "index.jsonl", "a", encoding="utf-8") as index:
        for n, (x, y, gz, yaw) in enumerate(route):
            if time.time() > end:
                reason = f"time limit of {a.max_minutes:g} minutes reached"
                break
            h = rng.uniform(a.height_min, a.height_max)
            if not place(c, v, x, y, gz - h, yaw + rng.uniform(-a.yaw_jitter, a.yaw_jitter), a.settle):
                skipped += 1
                blocked_in_a_row += 1
                print(f"  point {n + 1}/{len(route)} at {h:.0f} m: something is in the way, skipped", flush=True)
                if blocked_in_a_row >= a.max_blocked:
                    reason = (f"{a.max_blocked} points in a row were blocked; if the bottom pictures do not show a "
                              "street below, the road positions do not match the drone's coordinates")
                    break
                continue
            blocked_in_a_row = 0
            near = nearest_ahead(c, v)
            if near is not None and near < a.min_view:
                skipped += 1
                print(f"  point {n + 1}/{len(route)}: only {near} m of view ahead, no picture", flush=True)
                continue
            saved += save_pictures(c, v, out, k, index)
            k += 1
            print(f"  point {n + 1}/{len(route)}  height {h:4.1f} m  ahead {near} m  pictures {saved}", flush=True)
    return f"{reason} ({skipped} points skipped)", saved




def jump_forward(c, v, route, i, h, a):
    """Place the drone --skip points further along the route (trying further on if blocked). New index or None."""
    j = i + a.skip
    while j < len(route):
        x, y, gz, yaw = route[j]
        if place(c, v, x, y, gz - h, yaw, a.settle):
            return j
        j += 1
    return None




def fly_flight(c, v, a, route, out, rng):
    """Really fly along the route at one height, jumping forward past problems. Returns (reason, pictures)."""
    h = rng.uniform(a.height_min, a.height_max)
    end = time.time() + a.max_minutes * 60
    i = jump_forward(c, v, route, -a.skip, h, a)                    # first point that is free
    if i is None:
        return "no free point on this road", 0
    print(f"  flying at {h:.0f} m", flush=True)
    hit_before = c.simGetCollisionInfo(vehicle_name=v).time_stamp
    hops = k = saved = 0
    next_picture = 0.0
    reason = "route finished"
    i += 1
    with open(out / "index.jsonl", "a", encoding="utf-8") as index:
        if i < len(route):
            fly_to(c, v, route[i][0], route[i][1], route[i][2] - h, a.speed)
        last_pos, last_move = position(c, v), time.time()
        while i < len(route):
            now = time.time()
            if now > end:
                reason = f"time limit of {a.max_minutes:g} minutes reached"
                break
            x, y, gz, _ = route[i]
            p = position(c, v)
            if math.hypot(p.x_val - x, p.y_val - y) < 1.5:
                i += 1
                if i < len(route):
                    fly_to(c, v, route[i][0], route[i][1], route[i][2] - h, a.speed)
                last_pos, last_move = p, now
                continue
            if math.dist((p.x_val, p.y_val, p.z_val), (last_pos.x_val, last_pos.y_val, last_pos.z_val)) > 0.5:
                last_pos, last_move = p, now


            hit = c.simGetCollisionInfo(vehicle_name=v)
            near = nearest_ahead(c, v)
            problem = None
            if hit.time_stamp != hit_before:
                problem = f"hit {hit.object_name}"
            elif near is not None and near < a.clearance:
                problem = f"obstacle {near:.1f} m ahead"
            elif now - last_move > a.stuck_seconds:
                problem = f"not moving for {a.stuck_seconds:.0f} s"


            if problem:
                hops += 1
                if hops > a.max_hops:
                    reason = f"stopped after {a.max_hops} jumps ({problem})"
                    break
                print(f"  {problem}: jumping {a.skip} points forward (jump {hops} of {a.max_hops})", flush=True)
                j = jump_forward(c, v, route, i, h, a)
                if j is None:
                    reason = f"no free point left ahead ({problem})"
                    break
                i = j + 1
                if i < len(route):
                    fly_to(c, v, route[i][0], route[i][1], route[i][2] - h, a.speed)
                hit_before = c.simGetCollisionInfo(vehicle_name=v).time_stamp
                last_pos, last_move = position(c, v), time.time()
                next_picture = time.time() + 1.0                 # let it steady before the next picture
                continue


            if now >= next_picture:
                saved += save_pictures(c, v, out, k, index)
                k += 1
                next_picture = now + a.every
                print(f"  pictures {saved}  height {gz - p.z_val:4.1f} m  ahead {near} m", flush=True)
            time.sleep(0.2)
    return reason, saved




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="Town10HD")
    ap.add_argument("--quality", default="High", help="High or Low")
    ap.add_argument("--mode", choices=["hop", "fly"], default="hop", help="hop from point to point, or really fly")
    ap.add_argument("--runs", type=int, default=1, help="number of flights, each from a new road point")
    ap.add_argument("--seed", type=int, default=None, help="same number = same roads, turns and heights again")
    ap.add_argument("--length", type=float, default=400.0, help="length of each street route, metres")
    ap.add_argument("--step", type=float, default=5.0, help="metres between route points")
    ap.add_argument("--height-min", type=float, default=10.0, help="lowest height above the street, metres")
    ap.add_argument("--height-max", type=float, default=20.0, help="highest height above the street, metres")
    ap.add_argument("--yaw-jitter", type=float, default=0.0, help="hop: turn up to this many degrees off the road")
    ap.add_argument("--settle", type=float, default=1.0, help="seconds to steady after each placement")
    ap.add_argument("--min-view", type=float, default=3.0, help="hop: no picture if a wall is closer than this (m)")
    ap.add_argument("--max-blocked", type=int, default=15, help="hop: end a flight after this many blocked points in a row")
    ap.add_argument("--speed", type=float, default=2.0, help="fly: metres per second")
    ap.add_argument("--every", type=float, default=2.0, help="fly: seconds between pictures")
    ap.add_argument("--clearance", type=float, default=6.0, help="fly: jump when something is this close ahead (m)")
    ap.add_argument("--stuck-seconds", type=float, default=5.0, help="fly: not moving this long = stuck")
    ap.add_argument("--skip", type=int, default=3, help="fly: route points to jump past a problem")
    ap.add_argument("--max-hops", type=int, default=10, help="fly: end a flight after this many jumps")
    ap.add_argument("--max-minutes", type=float, default=15.0, help="each flight ends after this")
    ap.add_argument("--vehicles", type=int, default=30, help="cars to spawn")
    ap.add_argument("--walkers", type=int, default=50, help="pedestrians to spawn")
    ap.add_argument("--no-traffic", action="store_true", help="do not add cars and pedestrians")
    ap.add_argument("--vehicle", default=None, help="drone name (default: the first one)")
    ap.add_argument("--no-start", action="store_true",
                    help="use a simulator that is already running (it is left running, the drone lands)")
    a = ap.parse_args()
    if a.height_min > a.height_max:
        sys.exit("--height-min must not be larger than --height-max")


    rng = random.Random(a.seed)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    LOGS.mkdir(parents=True, exist_ok=True)
    sim = traffic = None
    c = v = None
    try:
        if not a.no_start:
            if port_open(2000) or port_open(41451):
                sys.exit("a simulator is already running: stop it (pkill -f CarlaUE4-Linux-Shipping) or add --no-start")
            print("starting the simulator off-screen (no window) ...", flush=True)
            sim = subprocess.Popen(
                [str(SIM), "CarlaUE4", a.map, "-RenderOffScreen", "-carla-rpc-port=2000",
                 f"-quality-level={a.quality}", "-TexturePoolSize=4096", "-unattended", "-nosound",
                 f"-settings={SETTINGS}"],
                stdout=open(LOGS / f"carlaair_{stamp}.log", "w"), stderr=subprocess.STDOUT,
                cwd=HOME / "drone-work")
            if not wait_for_ports(300):
                sys.exit(f"the simulator did not open ports 2000 and 41451 within 5 minutes; see {LOGS}")
            time.sleep(15)                                   # let the map finish loading


        if not a.no_traffic:
            print(f"adding traffic: {a.vehicles} cars, {a.walkers} pedestrians ...", flush=True)
            traffic = subprocess.Popen(
                [sys.executable, str(TRAFFIC), "-n", str(a.vehicles), "-w", str(a.walkers)],
                stdout=open(LOGS / f"traffic_{stamp}.log", "w"), stderr=subprocess.STDOUT, cwd=HOME / "drone-work")
            time.sleep(20)                                   # cars and people start moving


        c = airsim.MultirotorClient(timeout_value=30)        # a frozen simulator raises an error instead of hanging
        c.confirmConnection()
        v = a.vehicle or c.listVehicles()[0]
        world = carla_world()
        offset = carla_offset(world, c, v)
        if offset is None:
            sys.exit("the drone was not found in the CARLA map, so street routes cannot be made")
        carla_map = world.get_map()
        spawn_points = carla_map.get_spawn_points()
        rng.shuffle(spawn_points)


        c.enableApiControl(True, vehicle_name=v)
        c.armDisarm(True, vehicle_name=v)
        print(f"{v}: taking off ...", flush=True)
        c.takeoffAsync(timeout_sec=20, vehicle_name=v).join()


        for run in range(1, a.runs + 1):
            if not spawn_points:
                print("no road start points left", flush=True)
                break
            sp = spawn_points.pop()
            wps = road_waypoints(carla_map.get_waypoint(sp.location), a.length, a.step, rng)
            route = [street_point(w, offset) for w in wps]
            out = FRAMES / (f"auto_{stamp}" if a.runs == 1 else f"auto_{stamp}_run{run:02d}")
            out.mkdir(parents=True)
            (out / "flight.json").write_text(json.dumps({
                "run": run, "mode": a.mode, "height_range": [a.height_min, a.height_max], "seed": a.seed,
                "start_carla": [sp.location.x, sp.location.y, sp.location.z],
                "route_airsim": [list(pt) for pt in route]}, indent=1), encoding="utf-8")
            print(f"\n=== flight {run} of {a.runs} ({a.mode}): {len(route)} street points, "
                  f"start x {route[0][0]:.0f}  y {route[0][1]:.0f} -> {out}", flush=True)
            flight = hop_flight if a.mode == "hop" else fly_flight
            reason, saved = flight(c, v, a, route, out, rng)
            print(f"  flight {run} ended: {reason}. {saved} pictures in {out}", flush=True)
    finally:
        if c is not None and a.no_start:
            try:
                c.hoverAsync(vehicle_name=v)
                print("landing ...", flush=True)
                c.landAsync(timeout_sec=90, vehicle_name=v).join()
                c.armDisarm(False, vehicle_name=v)
                c.enableApiControl(False, vehicle_name=v)
            except Exception as e:                              # never let landing keep the script running
                print("landing skipped:", e)
        stop(traffic, "traffic (removes the cars and pedestrians)")
        stop(sim, "the simulator", sig=signal.SIGTERM)
    print("done.")




if __name__ == "__main__":
    main()



