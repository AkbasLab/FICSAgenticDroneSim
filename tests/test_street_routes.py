"""A scenario with search routes flies the route instead of lanes, and keep-outs far from a leg are not sampled."""
import unittest

from fics_drone.agents.persistent_agent import SEARCH_WAYPOINT_SPACING_M, _build_search_queue
from fics_drone.core.obstacles import TreeObstacle, _segment_distance_xy
from fics_drone.core.scenario import Sector


class RouteQueueTests(unittest.TestCase):
    def test_route_legs_follow_the_route_in_local_coordinates(self):
        sector = Sector("A", 0.0, 100.0, 0.0, 100.0)
        route = [(10.0, 10.0), (10.0, 19.0), (25.0, 19.0)]
        queue = _build_search_queue(sector, (10.0, 10.0, 0.0), 12.0, route=route)
        points = [leg.point for leg in queue]
        self.assertEqual(points[-1], (15.0, 9.0, 12.0))              # world (25, 19) seen from a spawn at (10, 10)
        self.assertNotIn((0.0, 0.0, 12.0), points)                    # the start of the route is where the drone already is
        for a, b in zip(points, points[1:]):                          # no gap longer than the sub-waypoint spacing
            self.assertLessEqual(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5, SEARCH_WAYPOINT_SPACING_M + 1e-6)

    def test_without_a_route_the_sector_is_swept_in_lanes(self):
        sector = Sector("A", 0.0, 40.0, 0.0, 40.0)
        queue = _build_search_queue(sector, (0.0, 0.0, 0.0), 12.0)
        self.assertGreater(len(queue), 10)
        self.assertTrue(any(abs(leg.point[0] - 40.0) < 1.0 for leg in queue))   # lanes reach the far edge


class SegmentRejectTests(unittest.TestCase):
    def test_distance_to_a_segment(self):
        self.assertAlmostEqual(_segment_distance_xy(5.0, 3.0, (0.0, 0.0, 12.0), (10.0, 0.0, 12.0)), 3.0)
        self.assertAlmostEqual(_segment_distance_xy(-4.0, 3.0, (0.0, 0.0, 12.0), (10.0, 0.0, 12.0)), 5.0)   # past the end: to the end point
        self.assertAlmostEqual(_segment_distance_xy(3.0, 4.0, (0.0, 0.0, 12.0), (0.0, 0.0, 12.0)), 5.0)      # a segment of no length

    def test_far_keepout_does_not_block_and_near_one_does(self):
        tree = TreeObstacle(x=5.0, y=20.0, z_bottom=0.0, z_top=20.0, trunk_r=1.0, crown_r=1.0, crown_from_frac=0.0)
        a, b = (0.0, 0.0, 12.0), (10.0, 0.0, 12.0)
        self.assertFalse(tree.blocks_segment(a, b, margin=2.0))
        near = TreeObstacle(x=5.0, y=2.0, z_bottom=0.0, z_top=20.0, trunk_r=1.0, crown_r=1.0, crown_from_frac=0.0)
        self.assertTrue(near.blocks_segment(a, b, margin=2.0))


if __name__ == "__main__":
    unittest.main()
