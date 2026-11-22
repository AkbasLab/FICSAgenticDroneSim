import math
import unittest

from fics_drone.core.obstacles import BoxObstacle
from fics_drone.planners.plan3d import plan_3d, route_length

BOUNDS = (-10.0, 80.0, -30.0, 30.0)


def box(x0, x1, y0, y1, zb, zt):
    return BoxObstacle(x0, x1, y0, y1, zb, zt)


class Plan3DTests(unittest.TestCase):
    def test_open_ground_is_a_straight_run(self):
        p = plan_3d((0, 0, 1), (40, 0, 1), [], 0.5, BOUNDS)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[-1], (40, 0, 1))

    def test_goes_under_a_crown_when_there_is_room(self):
        crown = box(15, 25, -6, 6, 10.0, 20.0)         # floats high; clear below 10 m
        p = plan_3d((0, 0, 1), (40, 0, 1), [crown], 0.5, BOUNDS)
        self.assertIsNotNone(p)
        self.assertLess(route_length((0, 0, 1), p), 41.0)
        self.assertTrue(all(pt[2] < 9.0 for pt in p))

    def test_goes_over_a_wall_it_cannot_go_round(self):
        wall = box(15, 17, -30, 30, 0.0, 6.0)          # the whole width, 6 m tall
        p = plan_3d((0, 0, 1), (40, 0, 1), [wall], 0.5, BOUNDS)
        self.assertIsNotNone(p)
        self.assertTrue(any(pt[2] > 7.0 for pt in p))

    def test_climbs_on_the_way_to_a_roof_between_trees(self):
        trees = [box(10, 14, -3, 3, 8.0, 22.0), box(24, 28, -3, 3, 8.0, 22.0)]    # trunks absent: crowns from 8 m
        p = plan_3d((0, 0, 1), (40, 0, 13.5), trees, 0.5, BOUNDS)
        self.assertIsNotNone(p)
        self.assertLess(max(pt[2] for pt in p), 18.0)       # not over everything (22 m + margin)

    def test_no_route_when_the_goal_is_inside_a_keep_out(self):
        self.assertIsNone(plan_3d((0, 0, 1), (20, 0, 1), [box(18, 22, -2, 2, 0.0, 10.0)], 0.5, BOUNDS))


if __name__ == "__main__":
    unittest.main()
