"""The speed governor's cap: how fast the aircraft may go given the nearest lidar return in the way it is heading.

Plain numpy, no simulator and no torch; skipped where numpy is missing (the plain test environment), run in NavRL's environment with
`python -m unittest tests.test_navrl_governor`.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def scan(*points):
    flat = []
    for p in points:
        flat.extend(p)
    return flat


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestSpeedCap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fics_drone.planners.navrl_planner import speed_cap_from_scan
        cls.cap = staticmethod(speed_cap_from_scan)

    def test_nothing_ahead_means_no_cap(self):
        self.assertEqual(self.cap([], 0.0, (1.0, 0.0), 1.5, 0.75), math.inf)

    def test_open_air_far_return_does_not_bind_at_cruise(self):
        self.assertGreater(self.cap(scan((12.0, 0.0, 0.0)), 0.0, (1.0, 0.0), 1.5, 0.75), 4.75)

    def test_cap_falls_with_distance(self):
        self.assertAlmostEqual(self.cap(scan((3.0, 0.0, 0.0)), 0.0, (1.0, 0.0), 1.5, 0.75), 2.0)
        self.assertAlmostEqual(self.cap(scan((5.0, 0.0, 0.0)), 0.0, (1.0, 0.0), 1.5, 0.75), 4.6667, places=3)

    def test_something_behind_or_beside_is_ignored(self):
        self.assertEqual(self.cap(scan((-2.0, 0.0, 0.0), (0.0, 3.0, 0.0)), 0.0, (1.0, 0.0), 1.5, 0.75), math.inf)

    def test_ground_returns_are_ignored(self):
        # 3 m ahead and 1.5 m below the sensor is about -27 degrees: the ground, not an obstacle
        self.assertEqual(self.cap(scan((3.0, 0.0, 1.5)), 0.0, (1.0, 0.0), 1.5, 0.75), math.inf)

    def test_a_ledge_just_below_the_sensor_is_seen(self):
        # 6 m ahead and 1 m below the sensor is about -9.5 degrees: the channel that saw the ledge at the Drone4 wall
        cap = self.cap(scan((6.0, 0.0, 1.0)), 0.0, (1.0, 0.0), 1.5, 0.75)
        self.assertAlmostEqual(cap, 6.0, places=1)

    def test_floor_keeps_the_aircraft_creeping(self):
        self.assertEqual(self.cap(scan((1.0, 0.0, 0.0)), 0.0, (1.0, 0.0), 1.5, 0.75), 0.4)


if __name__ == "__main__":
    unittest.main()
