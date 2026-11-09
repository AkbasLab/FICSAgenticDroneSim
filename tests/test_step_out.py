"""An aircraft standing inside a keep-out's margin is given a nearest clear spot to step out to, and a line that goes deeper is blocked."""
import unittest

from fics_drone.agents.persistent_agent import _nearest_clear_spot
from fics_drone.core.obstacles import TreeObstacle


def pole(x, y, r=2.5):
    return TreeObstacle(x=x, y=y, z_bottom=0.0, z_top=25.0, trunk_r=r, crown_r=r, crown_from_frac=0.0)


class StepOutTests(unittest.TestCase):
    def test_spot_is_outside_every_margin_and_close(self):
        trees = [pole(0.0, 0.0), pole(7.0, 0.0)]
        start = (1.0, 0.0, 12.0)                                  # inside the first pole
        spot = _nearest_clear_spot(start, trees, margin=2.0)
        self.assertIsNotNone(spot)
        for t in trees:
            self.assertFalse(t.blocks_point(*spot, margin=2.0))
        self.assertLess(((spot[0] - 1.0) ** 2 + spot[1] ** 2) ** 0.5, 9.0)

    def test_line_out_of_a_margin_is_allowed_and_line_deeper_is_not(self):
        t = pole(0.0, 0.0)
        start = (5.0, 0.0, 12.0)                                  # 2.5 m from the edge: inside a 3 m margin
        self.assertFalse(t.blocks_segment(start, (9.0, 0.0, 12.0), margin=3.0))
        self.assertTrue(t.blocks_segment(start, (2.0, 0.0, 12.0), margin=3.0))

    def test_none_when_boxed_in(self):
        trees = [pole(0.0, 0.0, r=40.0)]
        self.assertIsNone(_nearest_clear_spot((0.0, 0.0, 12.0), trees, margin=2.0))


if __name__ == "__main__":
    unittest.main()
