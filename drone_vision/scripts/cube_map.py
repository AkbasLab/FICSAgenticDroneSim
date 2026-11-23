r"""Build a small 3D cube (voxel) map of obstacles from a recorded flight.
    python ~/drone-work/scripts/cube_map.py --frames ~/drone-work/frames/run1
Reads the distance pictures (*_depth.npy) and camera positions (index.jsonl) that capture_frames.py saved,
turns every distance pixel into a 3D point, and marks the cubes those points fall into as occupied.
Writes into the frames folder (nothing else is changed):
    cube_map.ply       the occupied cubes as coloured points (open in CloudCompare or MeshLab)
    cube_map_top.png   a top view, coloured by height, with the drone's path
and prints, for every recorded position, the distance to the nearest obstacle at about the drone's height.
"""
import argparse
import json
import math
from pathlib import Path
import numpy as np
def rotate(q, v):
    """Rotate points v (N x 3) by the unit quaternion q = (w, x, y, z)."""
    w, x, y, z = q
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    return v @ r.T
def depth_to_points(depth, fov_deg, stride, min_m, max_m):
    """Distance picture (metres along the viewing direction) -> points in the camera frame (x ahead, y right, z down)."""
    h, w = depth.shape
    f = (w / 2) / math.tan(math.radians(fov_deg) / 2)
    v, u = np.mgrid[0:h:stride, 0:w:stride]
    d = depth[::stride, ::stride]
    keep = np.isfinite(d) & (d > min_m) & (d < max_m)
    d, u, v = d[keep], u[keep], v[keep]
    return np.stack([d, (u - (w - 1) / 2) / f * d, (v - (h - 1) / 2) / f * d], axis=1)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="a folder written by capture_frames.py")
    ap.add_argument("--camera", default="front_center", help="which camera's pictures to use ('all' = every camera)")
    ap.add_argument("--voxel", type=float, default=0.25, help="cube size in metres")
    ap.add_argument("--fov", type=float, default=90.0, help="camera field of view in degrees (settings FOV_Degrees)")
    ap.add_argument("--stride", type=int, default=4, help="use every n-th pixel (bigger = faster, coarser)")
    ap.add_argument("--min-range", type=float, default=0.5, help="ignore closer distances (the drone's own parts)")
    ap.add_argument("--max-range", type=float, default=40.0, help="ignore farther distances (sky, noisy far values)")
    ap.add_argument("--min-hits", type=int, default=2, help="a cube counts as occupied after this many points")
    a = ap.parse_args()
    folder = Path(a.frames).expanduser()
    rows = [json.loads(line) for line in open(folder / "index.jsonl", encoding="utf-8") if line.strip()]
    rows = [r for r in rows if a.camera == "all" or r["camera"] == a.camera]
    if not rows:
        raise SystemExit(f"no pictures from camera {a.camera!r} in {folder / 'index.jsonl'}")
    hits = {}
    path = []
    used = 0
    for r in rows:
        depth_file = folder / (r["stem"] + "_depth.npy")
        if not depth_file.exists():
            continue
        cam = depth_to_points(np.load(depth_file), a.fov, a.stride, a.min_range, a.max_range)
        world = rotate(r["cam_q"], cam) + np.array(r["cam_pos"])          # AirSim world frame: north, east, down
        keys, counts = np.unique(np.floor(world / a.voxel).astype(np.int64), axis=0, return_counts=True)
        for k, c in zip(map(tuple, keys), counts):
            hits[k] = hits.get(k, 0) + int(c)
        path.append(r["vehicle_pos"])
        used += 1
    occupied = np.array([k for k, c in hits.items() if c >= a.min_hits], dtype=float)
    if occupied.size == 0:
        raise SystemExit("no occupied cubes: check --fov, --max-range and that the distance files are not empty")
    centres = (occupied + 0.5) * a.voxel
    path = np.array(path)
    print(f"pictures used: {used}   occupied cubes: {len(centres)} of {a.voxel} m")
    # PLY in east, north, up (what point-cloud viewers expect), coloured by height
    enu = np.stack([centres[:, 1], centres[:, 0], -centres[:, 2]], axis=1)
    lo, hi = np.percentile(enu[:, 2], [2, 98])
    t = np.clip((enu[:, 2] - lo) / max(hi - lo, 1e-6), 0, 1)
    rgb = (np.stack([t, 1 - np.abs(2 * t - 1), 1 - t], axis=1) * 255).astype(int)
    with open(folder / "cube_map.ply", "w") as ply:
        ply.write(f"ply\nformat ascii 1.0\nelement vertex {len(enu)}\nproperty float x\nproperty float y\n"
                  "property float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
        for (x, y, z), (cr, cg, cb) in zip(enu, rgb):
            ply.write(f"{x:.3f} {y:.3f} {z:.3f} {cr} {cg} {cb}\n")
    # nearest obstacle at about the drone's height (within 2 m up or down), for every recorded position
    print("height(m)  nearest obstacle at drone height (m)")
    for p in path[:: max(1, len(path) // 15)]:
        level = np.abs(centres[:, 2] - p[2]) <= 2.0
        dist = np.linalg.norm(centres[level] - p, axis=1).min() if level.any() else float("inf")
        print(f"{-p[2]:8.1f}  {dist:8.1f}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 8))
        sc = ax.scatter(centres[:, 1], centres[:, 0], c=-centres[:, 2], s=1, cmap="turbo")
        ax.plot(path[:, 1], path[:, 0], "k-", lw=1.5, label="drone path")
        ax.set_xlabel("east (m)"), ax.set_ylabel("north (m)"), ax.set_aspect("equal"), ax.legend()
        fig.colorbar(sc, label="height (m)")
        fig.savefig(folder / "cube_map_top.png", dpi=120, bbox_inches="tight")
    except ImportError:
        print("matplotlib not installed: no top-view picture")
    print("wrote", folder / "cube_map.ply", "and", folder / "cube_map_top.png")
if __name__ == "__main__":
    main()
