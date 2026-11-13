"""Tests for BoxObstacle and the loader that turns the simulator's map objects into keep-outs."""
import math
import unittest
from types import SimpleNamespace as NS

from fics_drone.core.map_geometry import box_from_bounding_box, load_region_obstacles, split_tree
from fics_drone.core.obstacles import BoxObstacle


def bbox(x, y, z, ex, ey, ez, yaw=0.0):
    return NS(location=NS(x=x, y=y, z=z), extent=NS(x=ex, y=ey, z=ez), rotation=NS(yaw=yaw))


class FakeWorld:
    def __init__(self, by_label):
        self.by_label = by_label

    def get_environment_objects(self, label):
        return [NS(bounding_box=b, name=n) for n, b in self.by_label.get(label, [])]


class BoxObstacleTests(unittest.TestCase):
    def setUp(self):
        self.box = BoxObstacle(10.0, 14.0, 0.0, 2.0, 0.0, 6.0, "wall")

    def test_blocks_points_inside_at_the_right_height(self):
        self.assertTrue(self.box.blocks_point(12.0, 1.0, 3.0))
        self.assertFalse(self.box.blocks_point(12.0, 3.0, 3.0))
        self.assertFalse(self.box.blocks_point(12.0, 1.0, 20.0))          # well above it
        self.assertTrue(self.box.blocks_point(12.0, 1.0, 6.4))            # within the aircraft's half height of the top

    def test_margin_grows_the_footprint(self):
        self.assertFalse(self.box.blocks_point(9.5, 1.0, 3.0))
        self.assertTrue(self.box.blocks_point(9.5, 1.0, 3.0, margin=1.0))

    def test_a_line_through_it_is_blocked_and_one_round_it_is_not(self):
        self.assertTrue(self.box.blocks_segment((0.0, 1.0, 3.0), (20.0, 1.0, 3.0)))
        self.assertFalse(self.box.blocks_segment((0.0, 5.0, 3.0), (20.0, 5.0, 3.0)))
        self.assertFalse(self.box.blocks_segment((0.0, 1.0, 12.0), (20.0, 1.0, 12.0)))     # over the top

    def test_it_looks_like_a_tree_to_the_code_that_culls_by_distance(self):
        self.assertAlmostEqual(self.box.x, 12.0)
        self.assertAlmostEqual(self.box.y, 1.0)
        self.assertAlmostEqual(self.box.trunk_r, math.hypot(2.0, 1.0))
        self.assertEqual(self.box.radius_at(3.0), self.box.trunk_r)
        self.assertIsNone(self.box.radius_at(20.0))

    def test_it_is_shown_to_a_leg_planner_as_its_own_rectangle(self):
        self.assertEqual(self.box.rects_at(3.0), [(10.0, 14.0, 0.0, 2.0)])
        self.assertEqual(self.box.rects_at(20.0), [])


class LoaderTests(unittest.TestCase):
    def test_a_rotated_box_becomes_the_rectangle_that_covers_it(self):
        b = box_from_bounding_box(bbox(0.0, 0.0, 5.0, 2.0, 1.0, 3.0, yaw=90.0), (0.0, 0.0), 0.0)
        self.assertAlmostEqual(b.x_max - b.x_min, 2.0, places=3)           # turned a quarter: 2 wide, 4 long
        self.assertAlmostEqual(b.y_max - b.y_min, 4.0, places=3)

    def test_the_frame_is_the_missions_not_the_worlds(self):
        b = box_from_bounding_box(bbox(100.0, 50.0, 4.0, 1.0, 1.0, 2.0), (-172.0, 184.0), -1.8)
        self.assertAlmostEqual(b.x, 272.0)
        self.assertAlmostEqual(b.y, -134.0)
        self.assertAlmostEqual(b.z_bottom, 4.0 - 2.0 + 1.8)

    def test_only_what_is_in_the_region_and_tall_enough_is_kept(self):
        world = FakeWorld({"B": [("house", bbox(10.0, 10.0, 5.0, 3.0, 3.0, 5.0)), ("far", bbox(500.0, 500.0, 5.0, 3.0, 3.0, 5.0)),
                                 ("kerb", bbox(12.0, 12.0, 0.1, 3.0, 0.2, 0.1))],
                           "V": [("tree", bbox(20.0, 10.0, 6.0, 4.0, 4.0, 6.0))]})
        out = load_region_obstacles(world, (0.0, 0.0), (0.0, 40.0, 0.0, 40.0), ground_z=0.0, labels=["B", "V"])
        self.assertEqual(sorted(o.name for o in out), ["house", "tree"])

    def test_the_same_box_is_kept_once(self):
        world = FakeWorld({"B": [("a", bbox(10.0, 10.0, 5.0, 3.0, 3.0, 5.0)), ("b", bbox(10.0, 10.0, 5.0, 3.0, 3.0, 5.0))]})
        self.assertEqual(len(load_region_obstacles(world, (0.0, 0.0), (0.0, 40.0, 0.0, 40.0), ground_z=0.0, labels=["B"])), 1)

    def test_a_cap_keeps_the_nearest_to_the_centre(self):
        world = FakeWorld({"B": [("far", bbox(38.0, 20.0, 5.0, 1.0, 1.0, 5.0)), ("mid", bbox(25.0, 20.0, 5.0, 1.0, 1.0, 5.0)),
                                 ("mid2", bbox(15.0, 20.0, 5.0, 1.0, 1.0, 5.0)), ("near", bbox(21.0, 20.0, 5.0, 1.0, 1.0, 5.0))]})
        out = load_region_obstacles(world, (0.0, 0.0), (0.0, 40.0, 0.0, 40.0), ground_z=0.0, labels=["B"], max_count=2)
        self.assertEqual([o.name for o in out], ["near", "mid"])

    def test_a_label_the_world_cannot_list_is_skipped(self):
        class Broken(FakeWorld):
            def get_environment_objects(self, label):
                if label == "bad":
                    raise RuntimeError("no such label")
                return super().get_environment_objects(label)
        world = Broken({"B": [("house", bbox(10.0, 10.0, 5.0, 3.0, 3.0, 5.0))]})
        self.assertEqual(len(load_region_obstacles(world, (0.0, 0.0), (0.0, 40.0, 0.0, 40.0), ground_z=0.0, labels=["bad", "B"])), 1)


class TreeSplitTests(unittest.TestCase):
    def test_a_tall_tree_is_a_thin_trunk_under_a_crown(self):
        tree = BoxObstacle(-4.7, 4.7, -4.8, 4.8, 0.2, 22.0, "oak")
        parts = split_tree(tree)
        self.assertEqual(len(parts), 2)
        trunk, crown = parts
        self.assertTrue(trunk.blocks_point(0.0, 0.0, 1.4))                       # the trunk is there at head height
        self.assertFalse(trunk.blocks_point(2.0, 0.0, 1.4))                      # and thin: 2 m off it is clear
        self.assertFalse(crown.blocks_point(2.0, 0.0, 1.4))                      # the crown is far above a low aircraft
        self.assertTrue(crown.blocks_point(2.0, 0.0, 15.0))                      # but holds the space up there

    def test_a_bush_stays_one_box(self):
        bush = BoxObstacle(-0.7, 0.7, -0.7, 0.7, 0.0, 1.5, "bush")
        self.assertEqual(split_tree(bush), [bush])

    def test_the_loader_splits_only_the_tree_labels(self):
        world = FakeWorld({"V": [("oak", bbox(20.0, 20.0, 11.0, 4.0, 4.0, 11.0))], "B": [("house", bbox(10.0, 10.0, 11.0, 4.0, 4.0, 11.0))]})
        out = load_region_obstacles(world, (0.0, 0.0), (0.0, 40.0, 0.0, 40.0), ground_z=0.0, labels=["V", "B"], tree_labels=("V",))
        self.assertEqual(sorted(o.name for o in out), ["house", "oak crown", "oak trunk"])


class WorksWithTheGuardianTests(unittest.TestCase):
    def test_a_building_in_the_way_refuses_the_leg_and_a_clear_path_does_not(self):
        from fics_drone.agents.safety_guardian import Command, SafetyGuardian, SafetyLimits
        wall = BoxObstacle(10.0, 12.0, -5.0, 5.0, 0.0, 20.0, "building")
        g = SafetyGuardian(limits=SafetyLimits(geofence_half_extent_m=200.0, obstacles=[wall]))
        through = Command(kind="fly", target=(30.0, 0.0, 3.0), purpose="mission")
        round_it = Command(kind="fly", target=(30.0, 20.0, 3.0), purpose="mission")
        self.assertFalse(g._check_obstacles(through, (0.0, 0.0, 3.0)).passed)
        self.assertTrue(g._check_obstacles(round_it, (0.0, 20.0, 3.0)).passed)


if __name__ == "__main__":
    unittest.main()
