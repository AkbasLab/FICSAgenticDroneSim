import math
import unittest

from fics_drone.core.evade import evasion_velocity
from fics_drone.core.moving import MovingObject


def walker(x, y, vx=0.0, vy=0.0):
    return MovingObject("w", "pedestrian", x, y, vx, vy, 0.4, 1.8)


def car(x, y, vx, vy):
    return MovingObject("c", "vehicle", x, y, vx, vy, 2.5, 1.5, 1.0, 2.3, math.atan2(vy, vx))


class EvadeTests(unittest.TestCase):
    def test_nothing_near_means_no_move(self):
        self.assertIsNone(evasion_velocity((0, 0, 0.8), [walker(20, 0)]))

    def test_a_walker_coming_at_it_pushes_it_back_the_way_it_came(self):
        vx, vy = evasion_velocity((0, 0, 0.8), [walker(3, 0, -1.2, 0)])
        self.assertLess(vx, -0.5)

    def test_a_standing_walker_beside_it_pushes_it_away(self):
        vx, vy = evasion_velocity((0, 0, 0.8), [walker(0.0, 1.2)])
        self.assertLess(vy, -0.5)

    def test_a_car_driving_at_it_is_dodged_sideways(self):
        vx, vy = evasion_velocity((0, 0, 0.8), [car(-6, 0.0, 6.0, 0.0)])
        self.assertLess(abs(vx), 0.2)
        self.assertGreater(abs(vy), 0.8)

    def test_a_body_far_below_the_aircraft_is_ignored(self):
        self.assertIsNone(evasion_velocity((0, 0, 7.0), [walker(0.5, 0, 0, 0)]))

    def test_the_escape_turns_away_from_a_wall(self):
        wall = lambda x, y: y < -0.5          # solid on the side it would go to
        vx, vy = evasion_velocity((0, 0, 0.8), [walker(0.0, 1.2)], blocked_fn=wall)
        self.assertGreater(vy, -0.2)

    def test_fully_boxed_in_stays_put(self):
        self.assertIsNone(evasion_velocity((0, 0, 0.8), [walker(0.0, 1.2)], blocked_fn=lambda x, y: True))

    def test_exactly_on_it_still_returns_a_move(self):
        self.assertIsNotNone(evasion_velocity((0, 0, 0.8), [walker(0.0, 0.0, 1.0, 0.0)]))


if __name__ == "__main__":
    unittest.main()
