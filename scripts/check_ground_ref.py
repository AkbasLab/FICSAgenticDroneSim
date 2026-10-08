"""Live check of the ground reference (needs CarlaAir running; no take-off).

Connects to one drone, reports what the OLD code would have recorded as ground_z
(the first raw position read) and what the new settle guard records, and how long
the guard waited. If the two differ, the old code was recording a ground that was
too high. If they match, the drone was already still and the guard changed nothing.

    python scripts/check_ground_ref.py --vehicle Drone1
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle", default="Drone1")
    args = parser.parse_args()

    adapter = AirSimVehicleAdapter(args.vehicle)
    first = adapter._get_position_ned().z_val
    print(f"{args.vehicle}: first raw z (what the old code recorded) = {first:.3f}  speed = {adapter.get_speed():.3f}")

    t0 = time.monotonic()
    settled = adapter._wait_until_settled()
    waited = time.monotonic() - t0
    print(f"{args.vehicle}: settled z (what the guard records)       = {settled:.3f}  after {waited:.2f}s")
    diff = first - settled
    print(f"difference: {diff:+.3f} m  ->", "OLD CODE WAS WRONG HERE" if abs(diff) > 0.05 else "no difference (drone already at rest)")


if __name__ == "__main__":
    main()
