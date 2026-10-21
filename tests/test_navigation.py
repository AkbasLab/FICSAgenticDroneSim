#!/usr/bin/env python3
"""Tests for agentic_uav.control.navigation: the skill layer's only sign handling.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-04 (3.2) asks for NED handling "inside the skill layer, once, where it can
be unit-tested". Phase 1 shows what happens otherwise: plan altitudes sent as
NED z flew every altitude 29.25 m too high for two weeks, and nothing raised.
These pin the conversion with the numbers Phase 1 actually measured, and the
geometry the skills rely on: headings, the tolerance test, the stand-off point
and coverage paths.
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control import navigation as nav  # noqa: E402
from agentic_uav.core.models import Position  # noqa: E402

TOWN10HD_GROUND = 29.25     # NED z of the ground at Drone1's spawn, Phase 1


class AltitudeTests(unittest.TestCase):

    def test_phase_1_numbers(self):
        # M10's 12 m leg flies to +17.25; 30 m is -0.75, not -30.
        self.assertEqual(nav.altitude_to_z(12.0, TOWN10HD_GROUND), 17.25)
        self.assertEqual(nav.altitude_to_z(30.0, TOWN10HD_GROUND), -0.75)
        self.assertEqual(nav.altitude_to_z(0.0, TOWN10HD_GROUND), TOWN10HD_GROUND)

    def test_up_is_more_negative(self):
        self.assertLess(nav.altitude_to_z(20.0, TOWN10HD_GROUND), nav.altitude_to_z(10.0, TOWN10HD_GROUND))

    def test_round_trip_over_different_grounds(self):
        # M10's spawn points stood on 29.25, 29.28 and 27.29.
        for ground in (29.25, 29.28, 27.29, 0.0, -5.0):
            for altitude in (0.0, 0.5, 12.0, 30.0, 119.9):
                with self.subTest(ground=ground, altitude=altitude):
                    self.assertAlmostEqual(
                        nav.z_to_altitude(nav.altitude_to_z(altitude, ground), ground), altitude)

    def test_below_ground_is_refused(self):
        with self.assertRaises(ValueError):
            nav.altitude_to_z(-1.0, TOWN10HD_GROUND)
        with self.assertRaises(ValueError):
            nav.Waypoint(0, 0, -0.1)

    def test_a_waypoint_reaches_ned_only_through_the_ground(self):
        wp = nav.Waypoint(10.0, -5.0, 18.0)
        self.assertEqual(wp.to_position(TOWN10HD_GROUND), Position(10.0, -5.0, 11.25))
        self.assertFalse(hasattr(wp, "z"))
        back = nav.Waypoint.from_position(Position(10.0, -5.0, 11.25), TOWN10HD_GROUND)
        self.assertEqual(back, wp)

    def test_from_position_never_goes_underground(self):
        # A drone resting slightly below its measured ground reads altitude 0.
        self.assertEqual(nav.Waypoint.from_position(Position(0, 0, 29.4), 29.25).altitude_m, 0.0)


class ToleranceTests(unittest.TestCase):

    def test_sphere(self):
        target = Position(10, 0, -5)
        self.assertTrue(nav.reached(Position(10.3, 0.3, -5), target, 0.5))    # 0.424 m
        self.assertFalse(nav.reached(Position(10.3, 0.5, -5), target, 0.5))   # 0.583 m
        self.assertTrue(nav.reached(target, target, 0.0))

    def test_cylinder(self):
        target = Position(0, 0, -10)
        # 0.4 m off horizontally, 1.5 m off vertically
        self.assertFalse(nav.reached(Position(0.4, 0, -8.5), target, 0.5))
        self.assertTrue(nav.reached(Position(0.4, 0, -8.5), target, 0.5, vertical_tolerance_m=2.0))
        self.assertFalse(nav.reached(Position(0.4, 0, -8.5), target, 0.5, vertical_tolerance_m=1.0))

    def test_negative_tolerance_is_refused(self):
        with self.assertRaises(ValueError):
            nav.reached(Position(0, 0, 0), Position(0, 0, 0), -0.1)

    def test_distances(self):
        a, b = Position(0, 0, 0), Position(3, 4, 12)
        self.assertEqual(nav.horizontal_distance(a, b), 5.0)
        self.assertEqual(nav.distance(a, b), 13.0)


class HeadingTests(unittest.TestCase):

    def test_airsim_convention(self):
        o = Position(0, 0, 0)
        self.assertEqual(nav.heading_to(o, Position(10, 0, 0)), 0.0)       # +x
        self.assertEqual(nav.heading_to(o, Position(0, 10, 0)), 90.0)      # +y
        self.assertEqual(nav.heading_to(o, Position(0, -10, 0)), -90.0)
        self.assertEqual(nav.heading_to(o, Position(-10, 0, 0)), 180.0)    # (-180, 180]
        self.assertAlmostEqual(nav.heading_to(o, Position(10, 10, -50)), 45.0)  # height ignored

    def test_no_heading_straight_up(self):
        with self.assertRaises(ValueError):
            nav.heading_to(Position(1, 1, 0), Position(1, 1, -30))

    def test_normalise(self):
        for raw, want in [(0, 0), (180, 180), (-180, 180), (190, -170), (-190, 170),
                          (360, 0), (720.5, 0.5), (-540, 180), (359.9, -0.1)]:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(nav.normalise_heading(raw), want)

    def test_shortest_turn(self):
        self.assertEqual(nav.heading_error(170, -170), 20)       # across the seam, not -340
        self.assertEqual(nav.heading_error(-170, 170), -20)
        self.assertEqual(nav.heading_error(10, 100), 90)
        self.assertEqual(nav.heading_error(0, 180), 180)


class StandoffTests(unittest.TestCase):

    def test_on_the_line_back_towards_the_origin(self):
        p = nav.standoff_point(Position(20, 0, 29), Position(0, 0, 10), 5.0)
        self.assertEqual(p, Position(15.0, 0.0, 10))
        self.assertAlmostEqual(nav.horizontal_distance(p, Position(20, 0, 0)), 5.0)

    def test_diagonal(self):
        p = nav.standoff_point(Position(10, 10, 0), Position(0, 0, -5), math.sqrt(2))
        self.assertAlmostEqual(p.x, 9.0)
        self.assertAlmostEqual(p.y, 9.0)

    def test_from_directly_above(self):
        self.assertEqual(nav.standoff_point(Position(3, 4, 0), Position(3, 4, -20), 2.0),
                         Position(5.0, 4.0, -20))


class LawnmowerTests(unittest.TestCase):

    def assert_covers(self, region, spacing, path):
        # Every point of the region is within spacing/2 of some leg.
        legs = sorted({wp.y for wp in path})
        steps = 50
        for i in range(steps + 1):
            y = region.y_min + (region.y_max - region.y_min) * i / steps
            nearest = min(abs(y - leg) for leg in legs)
            self.assertLessEqual(nearest, spacing / 2 + 1e-9, (region, spacing, y, legs))

    def test_covers_regions_of_many_widths(self):
        for width in (0.0, 3.0, 10.0, 10.1, 20.0, 37.0, 100.0):
            for spacing in (4.0, 10.0, 25.0):
                region = nav.Region(0, 0, 50, width)
                with self.subTest(width=width, spacing=spacing):
                    path = nav.lawnmower(region, spacing, 15.0)
                    self.assert_covers(region, spacing, path)
                    self.assertTrue(all(region.contains(wp.x, wp.y) for wp in path))
                    self.assertTrue(all(wp.altitude_m == 15.0 for wp in path))

    def test_boustrophedon(self):
        path = nav.lawnmower(nav.Region(0, 0, 40, 20), 10.0, 12.0)
        self.assertEqual([(wp.x, wp.y) for wp in path],
                         [(0, 5), (40, 5), (40, 15), (0, 15)])

    def test_deterministic(self):
        r = nav.Region(-30, -10, 30, 45)
        self.assertEqual(nav.lawnmower(r, 7.5, 20), nav.lawnmower(r, 7.5, 20))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            nav.lawnmower(nav.Region(0, 0, 10, 10), 0.0, 10)
        with self.assertRaises(ValueError):
            nav.Region(10, 0, 0, 10)


class TravelTimeTests(unittest.TestCase):

    def test_travel_time(self):
        self.assertEqual(nav.travel_time(25.0, 5.0), 5.0)
        self.assertEqual(nav.travel_time(-25.0, 5.0), 5.0)
        with self.assertRaises(ValueError):
            nav.travel_time(10.0, 0.0)


if __name__ == "__main__":
    unittest.main()
