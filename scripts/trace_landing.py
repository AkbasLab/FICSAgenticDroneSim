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
    args = parser.parse_args()

    adapter = AirSimVehicleAdapter(args.vehicle)
    adapter.connect_and_takeoff()
    ground = adapter._ground_ned
    print(f"ground_z = {ground:.3f}; airborne, starting landing trace")

    sampler = airsim.MultirotorClient()
    sampler.confirmConnection()

    done = threading.Event()

    def do_land():
        t = time.monotonic()
        adapter.land()
        print(f"--- land() returned after {time.monotonic() - t:.1f}s ---")
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
        print(f"[{time.monotonic() - t0:5.1f}s {tag}] est_z={ground - est.position.z_val:7.2f}  "
              f"true_z={ground - truth.position.z_val:7.2f}  speed={speed:5.2f}  "
              f"hit={col.has_collided}{' ' + col.object_name if col.has_collided else ''}")
        if done.is_set():
            after_start = after_start or time.monotonic()
            if time.monotonic() - after_start >= args.after:
                break
        time.sleep(0.5)


if __name__ == "__main__":
    main()
