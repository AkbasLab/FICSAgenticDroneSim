"""Search lanes stop short of the sector edge when an inset is set: a fast aircraft coasts past each lane end, which is a U-turn."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.persistent_agent import _build_search_queue
from fics_drone.core.scenario import Sector


def extent(queue):
    xs = [leg.point[0] for leg in queue]
    ys = [leg.point[1] for leg in queue]
    return min(xs), max(xs), min(ys), max(ys)


class TestLaneInset(unittest.TestCase):
    SECTOR = Sector("C", -10.0, 40.0, 40.0, 90.0)

    def test_no_inset_sweeps_to_the_edge(self):
        x0, x1, y0, _ = extent(_build_search_queue(self.SECTOR, (0.0, 0.0, 0.0), 12.0, inset=0.0))
        self.assertEqual((x0, x1, y0), (-10.0, 40.0, 40.0))

    def test_inset_pulls_every_lane_end_in(self):
        x0, x1, y0, y1 = extent(_build_search_queue(self.SECTOR, (0.0, 0.0, 0.0), 12.0, inset=4.0))
        self.assertAlmostEqual(x0, -6.0)
        self.assertAlmostEqual(x1, 36.0)
        self.assertAlmostEqual(y0, 44.0)
        self.assertLessEqual(y1, 86.0)

    def test_an_inset_bigger_than_the_sector_still_leaves_a_lane(self):
        queue = _build_search_queue(Sector("S", 0.0, 6.0, 0.0, 6.0), (0.0, 0.0, 0.0), 12.0, inset=50.0)
        self.assertGreater(len(queue), 0)


if __name__ == "__main__":
    unittest.main()
