import unittest

from fics_drone.core.obstacles import BoxObstacle
from fics_drone.planners.overfly import overfly_altitude


class LevelCrossingTests(unittest.TestCase):
    def test_a_height_whose_crossing_passes_through_a_crown_is_refused(self):
        low_thing = BoxObstacle(40, 41, 40, 41, 0.0, 4.36)              # its top + 3 m = 7.36, the lowest candidate height
        crown = BoxObstacle(10, 20, -3, 3, 6.5, 20.9)                    # underside 6.5 m: a crossing at 4.37 m goes under it, at 7.36 m through it
        self.assertIsNone(overfly_altitude((0, 0, 0.97), (30, 0, 0.97), [low_thing, crown], 0.5, 3.0, 15.0))

    def test_a_clear_crossing_is_still_found(self):
        tree_box = BoxObstacle(10, 12, -1, 1, 0.0, 5.0)
        z = overfly_altitude((0, 0, 0.97), (30, 0, 0.97), [tree_box], 0.5, 3.0, 15.0)
        self.assertIsNotNone(z)
        self.assertGreaterEqual(z, 8.0)


if __name__ == "__main__":
    unittest.main()


class SafeClimbTests(unittest.TestCase):
    def test_a_climb_that_would_slope_through_a_tall_tree_is_shortened_to_clear_it(self):
        from fics_drone.agents.persistent_agent import safe_climb_spot
        from fics_drone.core.obstacles import BoxObstacle
        tree_box = BoxObstacle(14, 16, -1, 1, 2.0, 20.0)         # stands higher than the aircraft starts, so the clear run at ground height is long
        spot = safe_climb_spot((0, 0, 0.0), (30, 0, 8.0), 23.0, 30.0, [tree_box], 0.5)
        self.assertFalse(tree_box.blocks_segment((0, 0, 0.0), spot, margin=0.5))
        self.assertEqual(spot[2], 23.0)

    def test_open_ground_keeps_the_diagonal(self):
        from fics_drone.agents.persistent_agent import safe_climb_spot
        spot = safe_climb_spot((0, 0, 0.0), (30, 0, 8.0), 23.0, 30.0, [], 0.5)
        self.assertGreater(spot[0], 5.0)
