"""The separation filter plans for the coast: a faster aircraft starts easing off a peer further away."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestSeparationCoast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fics_drone.planners.navrl_planner import keep_separation
        cls.keep = staticmethod(keep_separation)

    def closing(self, distance, real_speed):
        pos = np.array([0.0, 0.0])
        out = self.keep(pos, np.array([3.0, 0.0]), [np.array([distance, 0.0])], 5.0, real_speed=real_speed)
        return float(out[0])

    def test_a_peer_far_away_changes_nothing(self):
        self.assertAlmostEqual(self.closing(20.0, 3.4), 3.0)

    def test_a_moving_aircraft_is_eased_off_at_a_greater_distance(self):
        # 8 m from a peer: a stationary aircraft is outside the 7 m ease zone, a 3.4 m/s one is already inside its larger zone
        self.assertAlmostEqual(self.closing(8.0, 0.0), 3.0)
        self.assertLess(self.closing(8.0, 3.4), 3.0)

    def test_the_closing_speed_is_gone_by_limit_plus_coast(self):
        # 3.4 m/s of real speed: 5 m + 2.7 m of coast = 7.7 m
        self.assertLess(self.closing(7.7, 3.4), 0.5)


if __name__ == "__main__":
    unittest.main()
