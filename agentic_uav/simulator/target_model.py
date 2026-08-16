"""Simulated target detection (Phase 4.2) - deliberately NO neural network.

A target is considered detected when a drone's flown path comes within the
target's detection radius and stays within it long enough to satisfy the
observation period (path length inside the radius / speed >= period). Modelling
detection geometrically keeps perception out of the picture, so a mission
failure can be attributed to coordination / communication / flight control
rather than a vision model.
"""

from ..core.geometry import (
    dist_point_to_segment, segment_length_within_radius,
)
from ..core.mission_models import Detection
from ..core.models import Position3D


def detect_targets(targets, drone_paths, speed_mps):
    """
    targets:     list[Target]
    drone_paths: dict {vehicle_id: [(Position3D, time_s), ...]} - the flown path
                 as timed waypoints (constant speed between them).
    Returns: list[Detection] (one per detected target, earliest detector).
    """
    detections = []
    for target in targets:
        best = None  # (time, vehicle)
        for vid, path in drone_paths.items():
            hit = _first_detection(target, path, speed_mps)
            if hit is not None and (best is None or hit < best[0]):
                best = (hit, vid)
        if best is not None:
            detections.append(Detection(
                target_id=target.target_id, by_vehicle=best[1],
                at_time_s=best[0],
                position=Position3D(target.position.x, target.position.y,
                                    target.position.z)))
    return detections


def _first_detection(target, path, speed_mps):
    """Time at which `target` is first observed along `path`, or None."""
    tx, ty = target.position.x, target.position.y
    for i in range(len(path) - 1):
        (a, ta), (b, tb) = path[i], path[i + 1]
        d = dist_point_to_segment(tx, ty, a.x, a.y, b.x, b.y)
        if d <= target.detection_radius_m:
            # long enough in view?
            length_in = segment_length_within_radius(
                tx, ty, a.x, a.y, b.x, b.y, target.detection_radius_m)
            time_in = length_in / max(speed_mps, 0.001)
            if time_in >= target.observation_period_s:
                return tb   # observed by the time this segment ends
    return None
