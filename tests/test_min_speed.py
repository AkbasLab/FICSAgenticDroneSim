"""The speed floor: lift a crawling policy to a walking pace when nothing is ahead, never when something is, and let it taper at the goal."""
import unittest

import numpy as np

from fics_drone.planners.navrl_planner import MAX_RAY_M, apply_speed_floor, clear_ahead

ROWS = [1, 2, 3]


def empty():
    return np.full((36, 4), MAX_RAY_M)


class SpeedFloorTests(unittest.TestCase):
    def test_a_crawl_is_lifted_when_nothing_is_ahead(self):
        v = apply_speed_floor(np.array([0.2, 0.0]), np.array([10.0, 0.0]), 10.0, empty(), 0.0, 1.5, ROWS)
        self.assertAlmostEqual(float(np.hypot(*v)), 1.5, places=3)
        self.assertGreater(v[0], 0.0)                         # the policy's own direction is kept

    def test_nothing_changes_when_something_is_ahead(self):
        g = empty()
        g[0, 1] = 2.0                                         # a return straight ahead (direction 0 = the start angle)
        v = apply_speed_floor(np.array([0.2, 0.0]), np.array([10.0, 0.0]), 10.0, g, 0.0, 1.5, ROWS)
        self.assertAlmostEqual(float(np.hypot(*v)), 0.2, places=3)

    def test_a_return_off_to_the_side_does_not_block_it(self):
        g = empty()
        g[18, 1] = 1.0                                        # behind it
        v = apply_speed_floor(np.array([0.2, 0.0]), np.array([10.0, 0.0]), 10.0, g, 0.0, 1.5, ROWS)
        self.assertAlmostEqual(float(np.hypot(*v)), 1.5, places=3)

    def test_the_floor_tapers_to_half_the_distance_near_the_goal(self):
        v = apply_speed_floor(np.array([0.1, 0.0]), np.array([1.0, 0.0]), 1.0, empty(), 0.0, 1.5, ROWS)
        self.assertAlmostEqual(float(np.hypot(*v)), 0.5, places=3)

    def test_a_fast_policy_is_left_alone_and_off_means_off(self):
        fast = np.array([3.0, 0.0])
        self.assertTrue(np.allclose(apply_speed_floor(fast, np.array([10.0, 0.0]), 10.0, empty(), 0.0, 1.5, ROWS), fast))
        slow = np.array([0.2, 0.0])
        self.assertTrue(np.allclose(apply_speed_floor(slow, np.array([10.0, 0.0]), 10.0, empty(), 0.0, 0.0, ROWS), slow))

    def test_a_standing_policy_is_sent_toward_the_goal(self):
        v = apply_speed_floor(np.array([0.0, 0.0]), np.array([0.0, 8.0]), 8.0, empty(), 0.0, 1.5, ROWS)
        self.assertAlmostEqual(float(v[1]), 1.5, places=3)

    def test_clear_ahead_reads_the_cone_around_the_heading(self):
        g = empty()
        g[9, 2] = 1.5                                         # direction 9 = 90 degrees from the start angle
        self.assertAlmostEqual(clear_ahead(g, 0.0, np.array([0.0, 1.0]), ROWS), 1.5)
        self.assertAlmostEqual(clear_ahead(g, 0.0, np.array([1.0, 0.0]), ROWS), MAX_RAY_M)


if __name__ == "__main__":
    unittest.main()
