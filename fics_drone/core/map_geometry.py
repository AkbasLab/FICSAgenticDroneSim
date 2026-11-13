"""The real solid things in the simulator's map, as keep-outs: buildings, trees with their crowns, poles, lamp posts, benches.

The scenario's own obstacle list holds only trees, as circles, and misses everything else; the ray casts a leg planner could use do
not see vegetation. The simulator itself knows every object in the map and its bounding box (`world.get_environment_objects`), so
this reads those for a region and turns each into a BoxObstacle, in the mission frame (the simulator's x, y minus `origin`; z
is height above `ground_z`). Read-only: it never changes the world.
"""
import math
from typing import Iterable, List, Optional, Sequence, Tuple

from .obstacles import BoxObstacle

# what to read by default: the labels that name something an aircraft can fly into (the road, the pavement and the ground are not)
# a tree is not a solid block: a thin trunk up to where its crown begins, then the crown. (The scenario's own trees are solid cylinders from
# the ground, which closes a whole pavement under a big tree.) These are measured as a share of the tree's height.
TREE_LABEL_NAMES = ("Vegetation",)
TREE_MIN_HEIGHT_M = 3.0     # shorter than this (a bush) stays one box
CROWN_FROM_FRAC = 0.45     # the crown starts this far up the tree
TRUNK_HALF_WIDTH_M = 0.6   # the trunk's half width, at most

DEFAULT_LABEL_NAMES = ("Buildings", "Vegetation", "Poles", "Static", "Other", "Walls", "Fences", "Bridge", "GuardRail")


def default_labels() -> list:
    """The simulator's CityObjectLabel members named in DEFAULT_LABEL_NAMES that exist in this build."""
    import carla
    out = []
    for name in DEFAULT_LABEL_NAMES:
        label = getattr(carla.CityObjectLabel, name, None)
        if label is not None:
            out.append(label)
    return out


def box_from_bounding_box(bb, origin: Tuple[float, float], ground_z: float, name: str = "") -> BoxObstacle:
    """A BoxObstacle from a simulator bounding box (location, extent, rotation.yaw in degrees), as the smallest axis-aligned rectangle
    that covers it, in the mission frame."""
    yaw = math.radians(getattr(getattr(bb, "rotation", None), "yaw", 0.0) or 0.0)
    ex, ey, ez = bb.extent.x, bb.extent.y, bb.extent.z
    hx = abs(ex * math.cos(yaw)) + abs(ey * math.sin(yaw))
    hy = abs(ex * math.sin(yaw)) + abs(ey * math.cos(yaw))
    cx, cy = bb.location.x - origin[0], bb.location.y - origin[1]
    return BoxObstacle(x_min=cx - hx, x_max=cx + hx, y_min=cy - hy, y_max=cy + hy,
                       z_bottom=bb.location.z - ez - ground_z, z_top=bb.location.z + ez - ground_z, name=name)


def split_tree(box: BoxObstacle, crown_from_frac: float = CROWN_FROM_FRAC, trunk_half_width_m: float = TRUNK_HALF_WIDTH_M) -> List[BoxObstacle]:
    """A tall tree's bounding box as a thin trunk (from the ground to where the crown begins) and the crown (the whole box above that)."""
    height = box.z_top - box.z_bottom
    if height < TREE_MIN_HEIGHT_M:
        return [box]
    crown_z = box.z_bottom + crown_from_frac * height
    hx = min(trunk_half_width_m, 0.5 * (box.x_max - box.x_min))
    hy = min(trunk_half_width_m, 0.5 * (box.y_max - box.y_min))
    trunk = BoxObstacle(box.x - hx, box.x + hx, box.y - hy, box.y + hy, box.z_bottom, crown_z, box.name + " trunk")
    crown = BoxObstacle(box.x_min, box.x_max, box.y_min, box.y_max, crown_z, box.z_top, box.name + " crown")
    return [trunk, crown]


def load_region_obstacles(world, origin: Tuple[float, float], region: Tuple[float, float, float, float], ground_z: float = 0.0,
                          labels: Optional[Sequence] = None, min_height_m: float = 0.8, max_count: int = 4000,
                          tree_labels: Sequence = TREE_LABEL_NAMES) -> List[BoxObstacle]:
    """Every solid object whose box overlaps `region` = (x_min, x_max, y_min, y_max) in mission metres, as BoxObstacles.

    Things lower than min_height_m (kerbs, grates, grass) are left out: an aircraft flies over them. Repeats of the same box (a
    building is often many pieces with the same box) are kept once. At most max_count are returned, the nearest the region's
    centre first, so a huge region cannot make the checks slow."""
    labels = list(labels) if labels is not None else default_labels()
    x0, x1, y0, y1 = region
    seen, out = set(), []
    for label in labels:
        is_tree = getattr(label, "name", str(label)) in tuple(tree_labels)
        try:
            objects = world.get_environment_objects(label)
        except Exception:
            continue
        for obj in objects:
            bb = obj.bounding_box
            wx, wy = bb.location.x - origin[0], bb.location.y - origin[1]
            reach = bb.extent.x + bb.extent.y
            if wx + reach < x0 or wx - reach > x1 or wy + reach < y0 or wy - reach > y1:
                continue
            box = box_from_bounding_box(bb, origin, ground_z, getattr(obj, "name", ""))
            if box.z_top - max(box.z_bottom, 0.0) < min_height_m:
                continue
            key = tuple(round(v, 1) for v in (box.x_min, box.x_max, box.y_min, box.y_max, box.z_bottom, box.z_top))
            if key in seen:
                continue
            seen.add(key)
            out.extend(split_tree(box) if is_tree else [box])
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    out.sort(key=lambda b: math.hypot(b.x - cx, b.y - cy))
    return out[:max_count]
