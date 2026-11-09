"""plan_around: a way through packed keep-outs where the one-tree ring detour fails."""
import math
import unittest

from fics_drone.core.obstacles import BoxKeepOut, TreeObstacle
from fics_drone.planners.street_path import plan_around


def tree(x, y, r=2.0):
    return TreeObstacle(x=x, y=y, z_bottom=0.0, z_top=30.0, trunk_r=r, crown_r=r, crown_from_frac=0.0)


def clear_of(path, start, obstacles, margin):
    pts = [start[:2]] + [p[:2] for p in path]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.dist(a, b) / 0.25))
        for k in range(n + 1):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            if math.dist(p, start[:2]) > 2.5 and any(o.blocks_point(p[0], p[1], 12.0, margin) for o in obstacles):
                return False
    return True


class PlanAroundTests(unittest.TestCase):
    def test_open_ground_is_one_straight_leg(self):
        self.assertEqual(plan_around((0, 0, 12), (20, 0, 12), [tree(50, 50)], 1.0), [(20, 0, 12)])

    def test_goes_round_a_row_of_trees_and_stays_clear(self):
        wall = [tree(10, y) for y in range(-6, 7, 3)]
        path = plan_around((0, 0, 12), (20, 0, 12), wall, 1.0)
        self.assertIsNotNone(path)
        self.assertEqual(path[-1], (20, 0, 12))
        self.assertGreater(len(path), 1)
        self.assertTrue(clear_of(path, (0, 0), wall, 1.0))

    def test_goes_round_a_zone_box(self):
        path = plan_around((0, 0, 12), (20, 0, 12), [BoxKeepOut(8, 12, -5, 5)], 1.0)
        self.assertIsNotNone(path)
        self.assertTrue(clear_of(path, (0, 0), [BoxKeepOut(8, 12, -5, 5)], 1.0))

    def test_a_goal_inside_a_keepout_has_no_way(self):
        self.assertIsNone(plan_around((0, 0, 12), (20, 0, 12), [tree(20, 0)], 1.0))

    def test_an_aircraft_standing_inside_a_keepout_can_leave(self):
        path = plan_around((0, 0, 12), (20, 0, 12), [tree(0.5, 0.5, 3.0)], 1.0)
        self.assertIsNotNone(path)

    def test_a_closed_pocket_has_no_way(self):
        ring = [tree(10 + 8 * math.cos(a / 10 * 2 * math.pi), 8 * math.sin(a / 10 * 2 * math.pi), 3.0) for a in range(10)]
        self.assertIsNone(plan_around((10, 0, 12), (40, 0, 12), ring, 1.0, pad=12.0))


if __name__ == "__main__":
    unittest.main()
