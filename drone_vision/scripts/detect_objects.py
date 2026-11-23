r"""Find objects in the drone's pictures with a YOLO detector and give each one a distance (OpenCV + PyTorch).
    python detect_objects.py --frames ~/drone-work/frames/run1
    python detect_objects.py --live --seconds 60--frames: uses the pictures saved by capture_frames.py (and their _depth.npy files). Writes annotated
copies to <frames>/detections/ and one line per picture to <frames>/detections/detections.jsonl.--live: reads the front camera straight from the simulator and shows a window (press q to stop).
The first run downloads the model file named by --model (yolo11n.pt is about 6 MB).
"""
import argparse
import json
import pathlib
import time
import cv2
import numpy as np
from ultralytics import YOLO
def box_distance(depth, box, rgb_w, rgb_h):
    """Median distance (m) of the central half of a box, read from the planar depth picture."""
    if depth is None:
        return None
    x0, y0, x1, y1 = box
    sx, sy = depth.shape[1] / rgb_w, depth.shape[0] / rgb_h
    cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 4, (y1 - y0) / 4
    crop = depth[int((cy - hh) * sy): int((cy + hh) * sy) + 1, int((cx - hw) * sx): int((cx + hw) * sx) + 1]
    vals = crop[np.isfinite(crop) & (crop > 0.2)]
    return round(float(np.median(vals)), 1) if vals.size else None
def detect(model, img_bgr, depth, conf):
    res = model.predict(img_bgr, conf=conf, verbose=False)[0]
    h, w = img_bgr.shape[:2]
    found = []
    for box, cls, p in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()):
        found.append({"label": res.names[int(cls)], "confidence": round(float(p), 2),
                      "box": [int(round(x)) for x in box], "distance_m": box_distance(depth, box, w, h)})
    return found
def draw(img, found):
    for d in found:
        x0, y0, x1, y1 = d["box"]
        text = f'{d["label"]} {d["confidence"]:.2f}' + (f' {d["distance_m"]} m' if d["distance_m"] is not None else "")
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 255, 255), 2)
        cv2.putText(img, text, (x0, max(18, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    return img
def run_folder(model, folder, conf):
    out = folder / "detections"
    out.mkdir(exist_ok=True)
    pictures = sorted(p for p in folder.glob("*.png"))
    with open(out / "detections.jsonl", "a", encoding="utf-8") as log:
        for png in pictures:
            img = cv2.imread(str(png))
            depth_file = png.with_name(png.stem + "_depth.npy")
            if not depth_file.exists():
                depth_file = png.with_name("depth.npy")          # single-picture folders (e.g. a probe)
            depth = np.load(depth_file) if depth_file.exists() else None
            t0 = time.time()
            found = detect(model, img, depth, conf)
            cv2.imwrite(str(out / (png.stem + ".jpg")), draw(img, found))
            log.write(json.dumps({"picture": png.name, "seconds": round(time.time() - t0, 3), "objects": found}) + "\n")
            summary = ", ".join(f'{d["label"]} {d["distance_m"]} m' for d in found) or "nothing found"
            print(f"{png.name}: {summary}  ({time.time() - t0:.2f} s)")
    print(f"annotated pictures and detections.jsonl are in {out}")
def run_live(model, conf, seconds, vehicle, camera):
    import airsim
    c = airsim.MultirotorClient()
    c.confirmConnection()
    v = vehicle or c.listVehicles()[0]
    end = time.time() + seconds if seconds > 0 else None
    while end is None or time.time() < end:
        rgb, dep = c.simGetImages([airsim.ImageRequest(camera, airsim.ImageType.Scene, False, True),
                                   airsim.ImageRequest(camera, airsim.ImageType.DepthPlanar, True, False)],
                                  vehicle_name=v)
        img = cv2.imdecode(np.frombuffer(rgb.image_data_uint8, dtype=np.uint8), cv2.IMREAD_COLOR)
        depth = np.array(dep.image_data_float, dtype=np.float32).reshape(dep.height, dep.width)
        found = detect(model, img, depth, conf)
        print(", ".join(f'{d["label"]} {d["distance_m"]} m' for d in found) or "nothing found", flush=True)
        cv2.imshow("drone camera - press q to stop", draw(img, found))
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=None, help="folder with saved pictures")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--conf", type=float, default=0.25, help="minimum confidence 0-1")
    ap.add_argument("--seconds", type=float, default=0.0, help="--live: 0 = until q")
    ap.add_argument("--vehicle", default=None)
    ap.add_argument("--camera", default="front_center")
    a = ap.parse_args()
    model = YOLO(a.model)
    if a.live:
        run_live(model, a.conf, a.seconds, a.vehicle, a.camera)
    elif a.frames:
        run_folder(model, pathlib.Path(a.frames).expanduser(), a.conf)
    else:
        ap.error("give --frames FOLDER or --live")
if __name__ == "__main__":
    main()
