"""NavRL's side of vehicles and pedestrians: the velocity it commands is turned away from a body that is close, with that
body's own clearance. Needs numpy (the NavRL environment), not the simulator or the policy weights."""
import unittest

import numpy as np

from fics_drone.core.moving import MovingObject
from fics_drone.planners.navrl_planner import MOVER_CLEAR_M, _Leg, keep_separation


class _FakePlanner:
    """Stands in for the loaded planner: it commands a fixed velocity, so only the wrapper's own filtering is tested."""
    max_speed = 5.0
    action_scale = 1.0
    min_speed = 0.0
    governor = False
    down_row = 1
    gov_binds = 0

    class _TL:
        grid = None
        scan = None

    _tl = _TL()

    def __init__(self, v):
        self.v = np.array(v, float)
        self.last_peers = None

    def _plan(self, target_dir, vel, pos, goal, zone_rects, scan_fn=None, peers=None):
        self.last_peers = peers
        return self.v.copy()


class MoverAvoidanceTests(unittest.TestCase):
    def _leg(self, v, movers):
        planner = _FakePlanner(v)
        leg = _Leg(planner, np.array([1.0, 0.0]), None, None, 0.0, lambda: movers)
        return planner, leg

    def test_the_policy_is_shown_a_pedestrian_as_a_moving_obstacle_with_its_velocity(self):
        person = MovingObject("p", "pedestrian", 8.0, 0.0, vx=0.0, vy=1.4, radius=0.4)
        planner, leg = self._leg([2.0, 0.0], [person])
        leg.velocity((0.0, 0.0), (30.0, 0.0), [])
        self.assertEqual(planner.last_peers, [((8.0, 0.0), (0.0, 1.4))])

    def test_something_far_away_is_not_shown(self):
        far = MovingObject("c", "vehicle", 60.0, 0.0, radius=2.5)
        planner, leg = self._leg([2.0, 0.0], [far])
        leg.velocity((0.0, 0.0), (30.0, 0.0), [])
        self.assertIsNone(planner.last_peers)

    def test_a_body_in_the_way_takes_the_closing_speed_out(self):
        car = MovingObject("c", "vehicle", 4.0, 0.0, radius=2.5)           # 4 m ahead: inside radius + clearance (4.5 m)
        planner, leg = self._leg([2.0, 0.0], [car])
        vx, vy = leg.velocity((0.0, 0.0), (30.0, 0.0), [])
        self.assertLess(vx, 0.1)                                            # it no longer drives at the car

    def test_the_clearance_is_the_bodys_radius_plus_a_margin(self):
        v = keep_separation(np.array([0.0, 0.0]), np.array([2.0, 0.0]), [(4.0, 0.0)], 2.5 + MOVER_CLEAR_M)
        self.assertLessEqual(float(v[0]), 0.0)                              # at 4 m from a 4.5 m limit it is pushed back

    def test_a_fast_oncoming_car_is_given_more_room_than_a_parked_one(self):
        parked = MovingObject("c", "vehicle", 14.0, 0.0, radius=2.5)
        oncoming = MovingObject("c", "vehicle", 14.0, 0.0, vx=-10.0, vy=0.0, radius=2.5)     # 12 m/s closing with the drone
        _, leg = self._leg([2.0, 0.0], [parked])
        self.assertGreater(leg.velocity((0.0, 0.0), (30.0, 0.0), [])[0], 1.8)               # 14 m away: still near full speed (the slowing has only just begun)
        _, leg = self._leg([2.0, 0.0], [oncoming])
        self.assertLess(leg.velocity((0.0, 0.0), (30.0, 0.0), [])[0], 0.5)                  # but not of one coming at it

    def test_an_oncoming_car_makes_the_aircraft_step_aside(self):
        from fics_drone.planners.navrl_planner import sidestep_movers
        car = MovingObject("c", "vehicle", 20.0, 0.0, vx=-6.0, vy=0.0, radius=2.0)         # dead ahead, coming at the drone
        v = sidestep_movers(np.array([0.0, 0.0]), np.array([2.0, 0.0]), [car])
        self.assertLess(v[1], -0.5)                                                         # it steps to its right (-y when heading +x)
        self.assertAlmostEqual(v[0], 2.0)                                                   # the sideways step is at right angles

    def test_a_car_that_will_pass_wide_is_left_alone(self):
        from fics_drone.planners.navrl_planner import sidestep_movers
        car = MovingObject("c", "vehicle", 20.0, 12.0, vx=-6.0, vy=0.0, radius=2.0)        # passes 12 m to the side
        v = sidestep_movers(np.array([0.0, 0.0]), np.array([2.0, 0.0]), [car])
        self.assertTrue(np.allclose(v, [2.0, 0.0]))

    def test_the_step_goes_away_from_the_side_it_passes_on(self):
        from fics_drone.planners.navrl_planner import sidestep_movers
        left = MovingObject("c", "vehicle", 20.0, 1.0, vx=-6.0, vy=0.0, radius=2.0)         # will pass 1 m to its left
        v = sidestep_movers(np.array([0.0, 0.0]), np.array([2.0, 0.0]), [left])
        self.assertLess(v[1], 0.0)                                                          # so step right
        right = MovingObject("c", "vehicle", 20.0, -1.0, vx=-6.0, vy=0.0, radius=2.0)
        v = sidestep_movers(np.array([0.0, 0.0]), np.array([2.0, 0.0]), [right])
        self.assertGreater(v[1], 0.0)                                                       # so step left

    def test_a_standing_body_is_left_to_the_separation_filter(self):
        from fics_drone.planners.navrl_planner import sidestep_movers
        parked = MovingObject("c", "vehicle", 20.0, 0.0, radius=2.0)
        v = sidestep_movers(np.array([0.0, 0.0]), np.array([0.0, 0.0]), [parked])           # the aircraft is hovering too
        self.assertTrue(np.allclose(v, [0.0, 0.0]))

    def test_a_car_moving_away_is_not_given_extra_room(self):
        leaving = MovingObject("c", "vehicle", 8.0, 0.0, vx=6.0, vy=0.0, radius=2.5)         # faster than the drone: the gap grows
        _, leg = self._leg([2.0, 0.0], [leaving])
        self.assertAlmostEqual(leg.velocity((0.0, 0.0), (30.0, 0.0), [])[0], 2.0)

    def test_only_what_is_as_tall_as_the_aircraft_is_low_counts(self):
        from fics_drone.core.moving import low_enough
        person = MovingObject("p", "pedestrian", 0.0, 0.0, height=1.8)
        self.assertEqual(low_enough([person], 4.0, 4.0), [person])
        self.assertEqual(low_enough([person], 12.0, 4.0), [])

    def test_a_clear_road_changes_nothing(self):
        planner, leg = self._leg([2.0, 0.0], [])
        vx, vy = leg.velocity((0.0, 0.0), (30.0, 0.0), [])
        self.assertAlmostEqual(vx, 2.0)
        self.assertAlmostEqual(vy, 0.0)


if __name__ == "__main__":
    unittest.main()


class StaticKeepOutTests(unittest.TestCase):
    def test_closing_on_a_keepout_is_cut(self):
        from fics_drone.planners.navrl_planner import keep_clear_of_rects
        v = keep_clear_of_rects(np.array([0.0, 0.0]), np.array([0.0, 2.0]), [(-1.0, 1.0, 2.0, 3.0)], real_speed=0.0)
        self.assertLess(v[1], 0.2)                      # a wall 2 m ahead: the closing speed is gone

    def test_moving_away_and_sideways_are_kept(self):
        from fics_drone.planners.navrl_planner import keep_clear_of_rects
        away = keep_clear_of_rects(np.array([0.0, 0.0]), np.array([0.0, -2.0]), [(-1.0, 1.0, 2.0, 3.0)])
        self.assertAlmostEqual(float(away[1]), -2.0, places=3)
        along = keep_clear_of_rects(np.array([-6.0, 0.0]), np.array([2.0, 0.0]), [(-1.0, 1.0, 5.0, 6.0)])
        self.assertAlmostEqual(float(along[0]), 2.0, places=3)

    def test_far_keepout_changes_nothing(self):
        from fics_drone.planners.navrl_planner import keep_clear_of_rects
        v = keep_clear_of_rects(np.array([0.0, 0.0]), np.array([1.5, 1.5]), [(30.0, 31.0, 30.0, 31.0)], real_speed=2.0)
        self.assertEqual(list(v), [1.5, 1.5])

    def test_faster_aircraft_is_cut_earlier(self):
        from fics_drone.planners.navrl_planner import keep_clear_of_rects
        slow = keep_clear_of_rects(np.array([0.0, 0.0]), np.array([0.0, 2.0]), [(-1.0, 1.0, 6.0, 7.0)], real_speed=0.0)
        fast = keep_clear_of_rects(np.array([0.0, 0.0]), np.array([0.0, 2.0]), [(-1.0, 1.0, 6.0, 7.0)], real_speed=2.0)
        self.assertLess(fast[1], slow[1])


class PassingIsSlowedNotStoppedTests(unittest.TestCase):
    def _leg(self, ped):
        from fics_drone.planners.navrl_planner import NavRLPlanner
        pl = NavRLPlanner()
        pl.movers_fn = lambda: [ped]

        class A:
            def get_position(self):
                return (0, 0, 3.0)
        return pl.begin_leg((0.0, 0.0), (-60.0, 0.0), A())

    def test_a_body_that_will_be_passed_wide_is_slowed_but_the_aircraft_keeps_moving(self):
        # the pedestrian is 6 m ahead and 4 m to one side, walking at the aircraft: a wide pass, so slow down and go on
        ped = MovingObject("p", "pedestrian", -6.0, 4.0, vx=1.4, vy=0.0, radius=0.4, height=1.8)
        leg = self._leg(ped)
        vx, vy = leg.velocity((0.0, 0.0), (-60.0, 0.0), [])
        self.assertGreater(float(np.hypot(vx, vy)), 0.3)

    def test_a_body_dead_ahead_is_still_stopped_for(self):
        ped = MovingObject("p", "pedestrian", -3.0, 0.0, vx=1.4, vy=0.0, radius=0.4, height=1.8)
        leg = self._leg(ped)
        vx, vy = leg.velocity((0.0, 0.0), (-60.0, 0.0), [])
        self.assertLess(vx, -0.0 + 0.5)               # no longer closing at any speed: the old cut is unchanged


class CarShapeTests(unittest.TestCase):
    def test_a_car_reaches_less_to_the_side_than_to_the_front(self):
        car = MovingObject("c", "vehicle", 0.0, 0.0, radius=2.06, height=1.5, half_width=0.9, half_length=1.9, yaw=0.0)
        self.assertAlmostEqual(car.reach(0.0, 10.0), 0.9, places=2)      # beside it
        self.assertAlmostEqual(car.reach(10.0, 0.0), 1.9, places=2)      # ahead of it
        self.assertLess(car.reach(0.0, 10.0), car.radius)

    def test_a_car_without_a_shape_is_the_circle_it_was(self):
        car = MovingObject("c", "vehicle", 0.0, 0.0, radius=2.06)
        self.assertEqual(car.reach(0.0, 10.0), 2.06)

    def test_the_slowing_is_eased_in_not_a_step(self):
        from fics_drone.planners.navrl_planner import NavRLPlanner
        ped = MovingObject("p", "pedestrian", -14.0, 2.5, vx=1.4, vy=0.0, radius=0.5, height=1.8)
        pl = NavRLPlanner()
        cur = {"p": ped}
        pl.movers_fn = lambda: [cur["p"]]

        class A:
            def get_position(self):
                return (0, 0, 3.0)
        leg = pl.begin_leg((0.0, 0.0), (-60.0, 0.0), A())
        import time as _t
        speeds = []
        for k in range(8):
            cur["p"] = MovingObject("p", "pedestrian", -14.0 + 1.5 * k, 2.5, vx=1.4, vy=0.0, radius=0.5, height=1.8)
            vx, vy = leg.velocity((0.0, 0.0), (-60.0, 0.0), [])
            speeds.append(float(np.hypot(vx, vy)))
            _t.sleep(0.1)
        steps = [abs(a - b) for a, b in zip(speeds, speeds[1:])]
        self.assertLess(max(steps), 0.5)             # no tick changes the speed by more than half a metre a second
