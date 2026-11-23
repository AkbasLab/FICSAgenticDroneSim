r"""Save what the drone's cameras see while it flies (read-only towards the simulator).
    python capture_frames.py --out ~/drone-work/frames/run1 --every 3 --seconds 120
Every --every seconds, for each vehicle and camera: the picture (PNG), the distance picture (.npy, metres)
and one line in index.jsonl with the time, the camera and drone position, and the distance straight ahead.
Run it in a second terminal while the persistent agent flies. Stop early with Ctrl+C.
"""
import argparse
import json
import os
import pathlib
import time
import airsim
import numpy as np
def distance_ahead(depth):
    h, w = depth.shape
    roi = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    roi = roi[np.isfinite(roi) & (roi > 0.2)]
    return (round(float(np.percentile(roi, 5)), 1), round(float(np.median(roi)), 1)) if roi.size else (None, None)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="a NEW folder for this run")
    ap.add_argument("--every", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--cameras", default="front_center,bottom_center")
    ap.add_argument("--vehicle", default=None, help="default: every vehicle")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    c = airsim.MultirotorClient()
    c.confirmConnection()
    cams = a.cameras.split(",")
    k, end, saved = 0, time.time() + a.seconds, 0
    with open(out / "index.jsonl", "a", encoding="utf-8") as index:
        try:
            while time.time() < end:
                for v in ([a.vehicle] if a.vehicle else c.listVehicles()):
                    pos = c.getMultirotorState(vehicle_name=v).kinematics_estimated.position
                    for cam in cams:
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
                        print(f"{stem}  height {-pos.z_val:5.1f} m  ahead: nearest {near} m, typical {med} m", flush=True)
                index.flush()
                k += 1
                time.sleep(a.every)
        except KeyboardInterrupt:
            print("stopped by Ctrl+C")
    print(f"saved {saved} pictures to {out}")
if __name__ == "__main__":
    main()
