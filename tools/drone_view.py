#!/usr/bin/env python3
"""Live camera view from every drone, side by side in one window.

    python tools/drone_view.py                 # all drones that have a camera
    python tools/drone_view.py --drones Drone1,Drone2
    python tools/drone_view.py --fps 10 --scale 0.5

Press `q` or Escape to close.

WHY A SEPARATE VIEWER
---------------------
The simulator window shows one third-person view. Watching what each drone sees
means pulling images over the API and composing them, which is what this does:
one tile per drone, labelled, refreshed a few times a second.

It is a VIEWER, not part of the experiment. The baseline agent never reads an
image -- it is blind by design -- and nothing here is recorded or scored.
Running it during a scored flight is safe but not free; see the cost note below.

CAMERAS ONLY EXIST ON DECLARED DRONES
-------------------------------------
A drone created at runtime with `simAddVehicle` has no cameras. Only vehicles
declared in `settings.json` get them. So to watch two drones, declare two:

    python tools/write_roster.py 2      # then restart the simulator

A drone without a camera still gets a tile, saying so, rather than vanishing
from the view.

THE COST, STATED PLAINLY
------------------------
Each frame pulls a full-resolution image per drone over RPC -- 1280x960 here --
and the GPU is already at ~93% of its 4 GB on Town10HD at Epic. At 5 fps with
two drones that is noticeable but workable; at 30 fps with four it is not.
Default is deliberately 5 fps, and --scale only shrinks the display, not the
capture. If it disturbs a flight, lower the camera resolution in settings.json
rather than raising the frame rate here.
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

LABEL_HEIGHT = 28
PLACEHOLDER = (40, 40, 40)


def grab(client, drone: str, camera: str):
    """One Scene image for a drone, or None if it has no usable camera."""
    import airsim

    try:
        responses = client.simGetImages(
            [airsim.ImageRequest(camera, airsim.ImageType.Scene, False, False)],
            vehicle_name=drone,
        )
    except Exception:
        return None
    if not responses:
        return None

    response = responses[0]
    if not response.image_data_uint8 or response.height == 0:
        return None
    frame = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
    try:
        return frame.reshape(response.height, response.width, 3)
    except ValueError:
        return None


def label(tile, text: str, colour=(255, 255, 255)):
    """Put a caption bar under a tile."""
    bar = np.zeros((LABEL_HEIGHT, tile.shape[1], 3), dtype=np.uint8)
    cv2.putText(bar, text, (8, LABEL_HEIGHT - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
    return np.vstack([tile, bar])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--drones", help="comma-separated names; default is every vehicle")
    parser.add_argument("--camera", default="front_center",
                        help="camera name from settings.json (default front_center)")
    parser.add_argument("--fps", type=float, default=5.0,
                        help="refresh rate; higher costs simulator performance")
    parser.add_argument("--scale", type=float, default=0.5,
                        help="display scale for each tile (capture is unaffected)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=41451)
    args = parser.parse_args()

    import airsim

    client = airsim.MultirotorClient(ip=args.host, port=args.port)
    client.confirmConnection()

    drones = ([d.strip() for d in args.drones.split(",")] if args.drones
              else list(client.listVehicles()))
    if not drones:
        sys.exit("no vehicles in the simulator")
    print(f"watching: {', '.join(drones)}  (camera '{args.camera}', {args.fps} fps)")
    print("press q or Escape to close")

    window = "drone cameras"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    interval = 1.0 / max(args.fps, 0.5)
    missing_reported: set[str] = set()

    while True:
        started = time.time()
        tiles = []

        for drone in drones:
            frame = grab(client, drone, args.camera)
            if frame is None:
                # Most often a drone spawned at runtime, which has no cameras.
                if drone not in missing_reported:
                    print(f"  {drone}: no image from camera '{args.camera}' "
                          f"(runtime-spawned drones have no cameras)")
                    missing_reported.add(drone)
                tile = np.full((240, 320, 3), PLACEHOLDER, dtype=np.uint8)
                cv2.putText(tile, "no camera", (90, 130), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (120, 120, 120), 1, cv2.LINE_AA)
                tiles.append(label(tile, f"{drone} — no camera", (120, 120, 200)))
                continue

            small = cv2.resize(frame, None, fx=args.scale, fy=args.scale)
            try:
                position = client.getMultirotorState(
                    vehicle_name=drone).kinematics_estimated.position
                # NED: z is negative upward, so altitude reads better negated.
                caption = (f"{drone}   x {position.x_val:6.1f}  y {position.y_val:6.1f}"
                           f"   alt {-position.z_val:5.1f} m")
            except Exception:
                caption = drone
            tiles.append(label(small, caption))

        if tiles:
            # Pad to equal height so tiles of different sizes still stack.
            height = max(t.shape[0] for t in tiles)
            padded = [
                np.vstack([t, np.zeros((height - t.shape[0], t.shape[1], 3), dtype=np.uint8)])
                if t.shape[0] < height else t
                for t in tiles
            ]
            cv2.imshow(window, np.hstack(padded))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break

        elapsed = time.time() - started
        if elapsed < interval:
            time.sleep(interval - elapsed)

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
