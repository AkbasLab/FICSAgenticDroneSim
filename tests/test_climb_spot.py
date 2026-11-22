import unittest

from fics_drone.agents.persistent_agent import climb_spot, clear_run_m


class Post:
    def __init__(self, x, y, r):
        self.x, self.y, self.r = x, y, r

    def blocks_point(self, x, y, z, margin=0.0):
        return ((x - self.x) ** 2 + (y - self.y) ** 2) ** 0.5 < self.r + margin


class Walker:
    def __init__(self, x, y):
        self.x, self.y = x, y


class ClimbSpotTests(unittest.TestCase):
    def test_with_room_the_climb_moves_on_toward_the_target(self):
        x, y, z = climb_spot((0, 0, 1), (40, 0, 1), 9.0, free_m=30.0)
        self.assertGreater(x, 5.0)
        self.assertEqual((y, z), (0, 9.0))

    def test_no_room_means_straight_up(self):
        self.assertEqual(climb_spot((0, 0, 1), (40, 0, 1), 9.0, free_m=1.0), (0, 0, 9.0))

    def test_never_more_than_part_of_the_way(self):
        x, _y, _z = climb_spot((0, 0, 1), (10, 0, 1), 30.0, free_m=100.0)
        self.assertLessEqual(x, 6.0)

    def test_clear_run_stops_before_a_post(self):
        run = clear_run_m((0, 0, 1), (40, 0, 1), [Post(20, 0, 1)], margin=0.5)
        self.assertLess(run, 18.0)
        self.assertGreater(run, 10.0)

    def test_clear_run_stops_short_of_a_body_on_the_leg(self):
        self.assertAlmostEqual(clear_run_m((0, 0, 1), (40, 0, 1), [], 0.5, movers=[Walker(25, 0)], mover_gap_m=10.0), 15.0)


if __name__ == "__main__":
    unittest.main()
