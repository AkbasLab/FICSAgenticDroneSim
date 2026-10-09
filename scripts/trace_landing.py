"""Live landing trace (needs CarlaAir running). Takes off, lands, and prints every 0.5 s,
through the landing and for 10 s after disarm:

  est_z   kinematics_estimated height above the recorded ground (what the code uses)
  true_z  ground-truth height above the recorded ground (simGetGroundTruthKinematics)
  speed   estimated speed
  hit     whether the sim reports a collision, and with what

If est_z drifts away from true_z after disarm, the post-landing position read is an
estimator artefact, not a real fall. A separate client does the sampling so it never
touches the adapter's own client from two threads.

    python scripts/trace_landing.py --vehicle Drone1
    python scripts/trace_landing.py --vehicle Drone1 --hover-s 150       # suspect 1: just time in the air
    python scripts/trace_landing.py --vehicle Drone1 --out-and-back 40   # suspect 2: fly 40 m out and back first
    python scripts/trace_landing.py --vehicle Drone1 --stop-above 0.3    # descend to 0.3 m, NEVER landAsync/disarm

A full solo mission lands with est_z = -11.8 m and a ~64 s landing (reproduced 2026-10-08); a bare
take-off-then-land trace is clean (7 s, est_z -0.01). These two switches separate "time in the air"
from "flew away and came back".
"""

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import airsim

from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle", default="Drone1")
    parser.add_argument("--after", type=float, default=10.0, help="seconds to keep sampling after land() returns")
    parser.add_argument("--hover-s", type=float, default=0.0, help="hover this long before landing")
    parser.add_argument("--stop-above", type=float, default=0.0,
                        help="instead of land(): descend to this height above ground_z and hold. No landAsync, no disarm")
    parser.add_argument("--out-and-back", type=float, default=0.0,
                        help="fly this many metres out on x and y, then back to (0, 0), before landing")
    args = parser.parse_args()

    adapter = AirSimVehicleAdapter(args.vehicle)
    adapter.connect_and_takeoff()
    ground = adapter._ground_ned
    print(f"ground_z = {ground:.3f}; airborne")
    if args.out_and_back:
        d = args.out_and_back
        t = time.monotonic()
        adapter.fly_to(d, d, 8.0)
        print(f"flew out to ({d}, {d}) in {time.monotonic() - t:.1f}s")
        t = time.monotonic()
        adapter.fly_to(0.0, 0.0, 8.0)
        print(f"flew back home in {time.monotonic() - t:.1f}s")
    if args.hover_s:
        print(f"hovering {args.hover_s}s ...")
        adapter.hover(args.hover_s)
    x, y, h = adapter.get_position()
    print(f"before landing: x={x:.2f} y={y:.2f} height={h:.2f}  ground_z still {adapter._ground_ned:.3f}")
    print("starting landing trace")

    sampler = airsim.MultirotorClient()
    sampler.confirmConnection()

    # What is the drone standing on? The collision flag names `SM_seaM` at take-off and touchdown.
    try:
        names = sampler.simListSceneObjects("SM_sea.*")
        print(f"scene objects matching SM_sea.*: {len(names)}")
        for name in names[:6]:
            pose = sampler.simGetObjectPose(name)
            scale = sampler.simGetObjectScale(name)
            print(f"   {name}: x={pose.position.x_val:.1f} y={pose.position.y_val:.1f} z={pose.position.z_val:.1f} "
                  f"scale=({scale.x_val:.1f}, {scale.y_val:.1f}, {scale.z_val:.1f})")
    except Exception as exc:
        print(f"could not list scene objects: {exc}")

    done = threading.Event()

    def do_land():
        t = time.monotonic()
        if args.stop_above:
            adapter.set_height(args.stop_above)
            adapter.hover(2.0)
        else:
            adapter.land()
        print(f"--- land() returned after {time.monotonic() - t:.1f}s ---")
        if getattr(adapter, "landing_note", None):
            print(f"--- landing note: {adapter.landing_note} ---")
        done.set()

    threading.Thread(target=do_land, daemon=True).start()

    t0 = time.monotonic()
    after_start = None
    while True:
        est = sampler.getMultirotorState(args.vehicle).kinematics_estimated
        truth = sampler.simGetGroundTruthKinematics(args.vehicle)
        col = sampler.simGetCollisionInfo(args.vehicle)
        v = est.linear_velocity
        speed = (v.x_val ** 2 + v.y_val ** 2 + v.z_val ** 2) ** 0.5
        tag = "after" if done.is_set() else "land "
        print(f"[{time.monotonic() - t0:5.1f}s {tag}] xy=({est.position.x_val:6.2f},{est.position.y_val:6.2f}) "
              f"est_z={ground - est.position.z_val:7.2f}  "
              f"true_z={ground - truth.position.z_val:7.2f}  speed={speed:5.2f}  "
              f"hit={col.has_collided}{' ' + col.object_name if col.has_collided else ''}")
        if done.is_set():
            after_start = after_start or time.monotonic()
            if time.monotonic() - after_start >= args.after:
                break
        time.sleep(0.5)


if __name__ == "__main__":
    main()
