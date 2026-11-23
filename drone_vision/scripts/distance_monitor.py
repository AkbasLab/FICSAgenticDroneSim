r"""Live distance readout from the front depth camera (read-only). Stop with Ctrl+C.
    python distance_monitor.py
    python distance_monitor.py --vehicle Drone1 --warn 8
Twice a second: height, speed, and how far away the nearest thing straight ahead is. Prints
"OBSTACLE" when it is closer than --warn metres. It only reads; it never steers the drone.
"""
import argparse
import math
import time
import airsim
import numpy as np
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicle", default=None, help="default: the first vehicle")
    ap.add_argument("--camera", default="front_center")
    ap.add_argument("--warn", type=float, default=8.0, help="metres")
    ap.add_argument("--period", type=float, default=0.5)
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = until Ctrl+C")
    a = ap.parse_args()
    c = airsim.MultirotorClient()
    c.confirmConnection()
    v = a.vehicle or c.listVehicles()[0]
    print(f"watching {v} / {a.camera}; warning below {a.warn} m. Ctrl+C to stop.")
    end = time.time() + a.seconds if a.seconds > 0 else None
    try:
        while end is None or time.time() < end:
            k = c.getMultirotorState(vehicle_name=v).kinematics_estimated
            vel = k.linear_velocity
            speed = math.sqrt(vel.x_val ** 2 + vel.y_val ** 2 + vel.z_val ** 2)
            dep = c.simGetImages([airsim.ImageRequest(a.camera, airsim.ImageType.DepthPlanar, True, False)],
                                 vehicle_name=v)[0]
            depth = np.array(dep.image_data_float, dtype=np.float32).reshape(dep.height, dep.width)
            h, w = depth.shape
            roi = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
            roi = roi[np.isfinite(roi) & (roi > 0.2)]
            near = float(np.percentile(roi, 5)) if roi.size else float("inf")
            flag = "  OBSTACLE" if near < a.warn else ""
            print(f"height {-k.position.z_val:5.1f} m  speed {speed:4.1f} m/s  nearest ahead {near:6.1f} m{flag}",
                  flush=True)
            time.sleep(a.period)
    except KeyboardInterrupt:
        print("stopped")
if __name__ == "__main__":
    main()
