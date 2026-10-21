#!/usr/bin/env python3
"""Tests for the mission world: trajectories, targets, and the exact facts of a flight.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 4's exit is judged entirely by what `mission_world.observe` says
happened. A detection that fires on a 1.9 s dwell, a zone entry a tick late,
a relay that counts a drone out of range -- any of them would make the
scripted controller look feasible, or infeasible, for the wrong reason. So
each fact is checked against a number worked out by hand, on trajectories
built by hand, and then on real mock flights, whose trace must be exact.
"""

import dataclasses
import math
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.clock import RealClock, SimClock  # noqa: E402
from agentic_uav.core.models import Position, PrimitiveCommand  # noqa: E402
from agentic_uav.core.scenario import BatterySpec, DetectionSpec, TargetSpec  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.team_flight import exit_plan, fly_team  # noqa: E402
from agentic_uav.simulator.mission_world import (  # noqa: E402
    Connectivity,
    Target,
    battery,
    detections,
    observe,
    place_targets,
    separations,
    zone_entries,
)
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.observer import PollingObserver, mock_trajectories  # noqa: E402
from agentic_uav.simulator.trajectory import Knot, Trajectory, breakpoints  # noqa: E402

G = MOCK_GROUND_Z
CANONICAL = scenarios.load_scenario("search_relay_001")
DETECT = DetectionSpec(radius_m=10.0, min_observation_s=2.0)


def path(drone, *points, airborne=True):
    """A trajectory through (t, x, y, altitude) points, all airborne unless told."""
    return Trajectory(drone, [Knot(t, x, y, h, airborne) for t, x, y, h in points])


def straight(drone, y=0.0, speed=5.0, x0=0.0, x1=100.0, altitude=10.0, t0=0.0):
    """Level flight along +x at `y`, from x0 at t0 to x1."""
    return path(drone, (t0, x0, y, altitude), (t0 + (x1 - x0) / speed, x1, y, altitude))


class TrajectoryTests(unittest.TestCase):

    def test_interpolation_and_the_ends(self):
        t = path("D", (0, 0, 0, 0), (10, 100, 0, 20))
        self.assertEqual(t.position_at(5), (50, 0, 10))
        self.assertEqual(t.position_at(-1), (0, 0, 0))          # before: the first knot
        self.assertEqual(t.position_at(99), (100, 0, 20))       # after: the last

    def test_a_jump_takes_no_time(self):
        t = Trajectory("D", [Knot(0, 0, 0, 10, True), Knot(4, 0, 0, 10, True),
                             Knot(4, 0, 0, 0, False), Knot(8, 0, 0, 0, False)])
        self.assertEqual(t.position_at(4), (0, 0, 0))           # after the jump
        self.assertEqual(t.leg_over(3, 4).p1, (0, 0, 10))       # before it, from the left
        self.assertEqual(t.leg_over(4, 5).p0, (0, 0, 0))
        self.assertTrue(t.airborne_at(3.9))
        self.assertFalse(t.airborne_at(4))

    def test_bad_trajectories_are_refused(self):
        with self.assertRaises(ValueError):
            Trajectory("D", [])
        with self.assertRaises(ValueError):
            path("D", (5, 0, 0, 0), (4, 1, 0, 0))

    def test_breakpoints_are_every_knot_in_the_window(self):
        a = path("A", (0, 0, 0, 0), (3, 1, 0, 0), (9, 2, 0, 0))
        b = path("B", (0, 0, 0, 0), (5, 1, 0, 0))
        self.assertEqual(breakpoints((a, b), 1, 8), [1, 3, 5, 8])


class TargetPlacementTests(unittest.TestCase):

    def test_seed_17_is_fixed_forever(self):
        # Pinned: results cite search_relay_001; a change here moves every one.
        t1, t2 = place_targets(CANONICAL)
        self.assertEqual((t1.id, t1.sector, round(t1.x, 6), round(t1.y, 6)), ("T1", "S3", 184.535262, -3.160418))
        self.assertEqual((t2.id, t2.sector, round(t2.x, 6), round(t2.y, 6)), ("T2", "S2", 101.288595, 56.337589))

    def test_every_seed_obeys_the_rules(self):
        sectors_used = set()
        for seed in range(300):
            s = dataclasses.replace(CANONICAL, random_seed=seed)
            targets = place_targets(s)
            self.assertEqual(targets, place_targets(s))          # deterministic
            self.assertEqual(len(targets), 2)
            for t in targets:
                sector = next(x for x in s.sectors if x.id == t.sector)
                self.assertTrue(sector.region.contains(t.x, t.y))
                self.assertFalse(any(z.polygon.contains(t.x, t.y) for z in s.restricted_zones))
                sectors_used.add(t.sector)
            self.assertGreaterEqual(math.hypot(targets[0].x - targets[1].x, targets[0].y - targets[1].y), 20.0)
        self.assertEqual(sectors_used, {"S1", "S2", "S3", "S4"})

    def test_never_in_a_zone_that_lies_inside_a_sector(self):
        # R1 overlaps no sector, so the canonical file cannot show this: a zone
        # over most of S1 must still never hold a target.
        from agentic_uav.core.geometry import Polygon
        from agentic_uav.core.scenario import RestrictedZone
        big = RestrictedZone("Z", Polygon(((40.0, -80.0), (110.0, -80.0), (110.0, -10.0), (40.0, -10.0))))
        s = dataclasses.replace(CANONICAL, restricted_zones=(big,))
        for seed in range(100):
            for t in place_targets(dataclasses.replace(s, random_seed=seed)):
                self.assertFalse(big.polygon.contains(t.x, t.y), (seed, t))

    def test_seeds_differ(self):
        layouts = {place_targets(dataclasses.replace(CANONICAL, random_seed=s)) for s in range(20)}
        self.assertEqual(len(layouts), 20)

    def test_fixed_and_impossible_placements(self):
        fixed = dataclasses.replace(CANONICAL, targets=TargetSpec(2, "fixed", ((60.0, -40.0), (160.0, 40.0))))
        self.assertEqual(place_targets(fixed), (Target("T1", 60.0, -40.0, "S1"), Target("T2", 160.0, 40.0, "S4")))
        crowded = dataclasses.replace(CANONICAL, targets=TargetSpec(2, "random_in_sectors", (), 1000.0))
        with self.assertRaises(ValueError):
            place_targets(crowded)


class DetectionTests(unittest.TestCase):

    def test_a_pass_detects_after_the_minimum_observation(self):
        # 5 m off the track: in view for |x - 50| <= sqrt(100 - 25) = 8.660 m.
        target = Target("T1", 50.0, 5.0, "S1")
        (d,) = detections([straight("D")], [target], DETECT, 0, 20)
        self.assertAlmostEqual(d.in_view_at, (50 - math.sqrt(75)) / 5.0)
        self.assertAlmostEqual(d.detected_at, d.in_view_at + 2.0)

    def test_a_dwell_short_of_the_minimum_is_not_a_detection(self):
        # 9.5 m off: a 6.24 m chord, 1.25 s at 5 m/s.
        self.assertEqual(detections([straight("D")], [Target("T1", 50.0, 9.5, "S1")], DETECT, 0, 20), [])

    def test_the_boundary_dwell(self):
        # A 10 m chord is exactly 2 s: offset sqrt(75) detects, a centimetre more does not.
        exact = Target("T1", 50.0, math.sqrt(75.0), "S1")
        beyond = Target("T2", 50.0, math.sqrt(75.0) + 0.01, "S1")
        found = detections([straight("D")], [exact, beyond], DETECT, 0, 20)
        self.assertEqual([d.target for d in found], ["T1"])

    def test_a_dwell_carries_over_a_knot(self):
        # Edge 3 m into view, hover 1 s, turn back: 0.6 s + 1 s + 0.6 s over
        # three legs, none enough alone, 2.2 s together.
        t = path("D", (0, 0, 0, 10), (7.6, 38, 0, 10), (8.6, 38, 0, 10), (16.2, 0, 0, 10))
        (d,) = detections([t], [Target("T1", 45.0, 0.0, "S1")], DETECT, 0, 17)
        self.assertAlmostEqual(d.in_view_at, 7.0)
        self.assertAlmostEqual(d.detected_at, 9.0)

    def test_in_view_when_the_leg_begins(self):
        # Already 5 m short of it at t = 0, flying on: the dwell starts at 0,
        # not where the line would have entered had it been flown earlier.
        t = path("D", (0, 45, 0, 10), (10, 95, 0, 10))
        (d,) = detections([t], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 10)
        self.assertEqual((d.in_view_at, d.detected_at), (0.0, 2.0))

    def test_hovering_over_it_detects(self):
        t = path("D", (0, 50, 0, 10), (5, 50, 0, 10))
        (d,) = detections([t], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 5)
        self.assertEqual((d.in_view_at, d.detected_at), (0.0, 2.0))

    def test_a_drone_on_the_ground_sees_nothing(self):
        t = path("D", (0, 50, 0, 0), (60, 50, 0, 0), airborne=False)
        self.assertEqual(detections([t], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 60), [])

    def test_height_does_not_matter_and_the_window_does(self):
        high = straight("D", altitude=100.0)
        self.assertEqual(len(detections([high], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 20)), 1)
        self.assertEqual(detections([high], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 9.0), [])

    def test_first_per_drone_and_target(self):
        there_and_back = path("D", (0, 0, 0, 10), (20, 100, 0, 10), (40, 0, 0, 10))
        other = straight("E", t0=10.0)
        found = detections([there_and_back, other], [Target("T1", 50.0, 0.0, "S1")], DETECT, 0, 40)
        self.assertEqual([(d.drone, round(d.detected_at, 6)) for d in found], [("D", 10.0), ("E", 20.0)])


class ZoneTests(unittest.TestCase):

    def zone(self):
        return CANONICAL.restricted_zones

    def test_entry_is_timed_exactly(self):
        (e,) = zone_entries([straight("D")], self.zone(), 0, 20)
        self.assertEqual((e.zone, e.at, e.x, e.y), ("R1", 3.0, 15.0, 0.0))

    def test_going_round_it_is_not_an_entry(self):
        t = path("D", (0, 8, 0, 10), (4, 8, -20, 10), (28, 128, -20, 10))
        self.assertEqual(zone_entries([t], self.zone(), 0, 28), [])

    def test_clipping_the_corner_is_an_entry(self):
        # The dog-leg via (25, -25) from Drone3's start: Phase 4 step 1's finding.
        t = path("D", (0, 8, 0, 10), (10, 25, -25, 10))
        (e,) = zone_entries([t], self.zone(), 0, 10)
        self.assertAlmostEqual(e.x, 15.0)
        self.assertAlmostEqual(e.at, 10 * 7 / 17)

    def test_the_first_edge_crossed_not_the_last(self):
        # Westward through R1: in at x = 35, out at x = 15.
        (e,) = zone_entries([path("D", (0, 50, 0, 10), (10, 0, 0, 10))], self.zone(), 0, 10)
        self.assertAlmostEqual(e.x, 35.0)
        self.assertAlmostEqual(e.at, 3.0)

    def test_along_an_edge_enters_where_the_edge_begins(self):
        poly = self.zone()[0].polygon
        self.assertAlmostEqual(poly.entry_fraction((0, 15), (50, 15)), 0.3)
        self.assertAlmostEqual(poly.entry_fraction((50, -15), (0, -15)), 0.3)
        self.assertIsNone(poly.entry_fraction((0, 16), (50, 16)))

    def test_starting_inside_is_an_entry_at_the_start(self):
        t = path("D", (0, 20, 0, 10), (10, 70, 0, 10))
        (e,) = zone_entries([t], self.zone(), 2, 10)
        self.assertEqual(e.at, 2)


class BatteryTests(unittest.TestCase):

    SPEC = BatterySpec(capacity=100.0, hover_drain_per_s=0.05, move_drain_per_m=0.02, reserve=20.0)

    def test_the_arithmetic(self):
        # 20 s on the ground, then 100 s airborne flying 500 m.
        t = Trajectory("D", [Knot(0, 0, 0, 0, False), Knot(20, 0, 0, 0, True),
                             Knot(120, 500, 0, 0, True)])
        b = battery(t, self.SPEC, 0, 120)
        self.assertAlmostEqual(b.airborne_s, 100)
        self.assertAlmostEqual(b.flown_m, 500)
        self.assertAlmostEqual(b.used, 100 * 0.05 + 500 * 0.02)
        self.assertIsNone(b.below_reserve_at)

    def test_the_reserve_and_flat_are_timed_and_not_enforced(self):
        # 0.05/s hovering: 80 % used at 1600 s, 100 % at 2000 s.
        t = path("D", (0, 0, 0, 10), (3000, 0, 0, 10))
        b = battery(t, self.SPEC, 0, 3000)
        self.assertAlmostEqual(b.below_reserve_at, 1600)
        self.assertAlmostEqual(b.depleted_at, 2000)
        self.assertAlmostEqual(b.remaining, -50)

    def test_a_jump_drains_nothing(self):
        # Motors cut at 10 m: the fall is a jump, not 10 m flown.
        t = Trajectory("D", [Knot(0, 0, 0, 10, True), Knot(10, 0, 0, 10, True),
                             Knot(10, 0, 0, 0, False), Knot(20, 0, 0, 0, False)])
        b = battery(t, self.SPEC, 0, 20)
        self.assertAlmostEqual(b.flown_m, 0)
        self.assertAlmostEqual(b.used, 0.5)


class ConnectivityTests(unittest.TestCase):

    BASE = (-8.0, 0.0)

    def test_direct_range_is_exact(self):
        # Along the ground from x = 0 at 5 m/s: out of range at x = 92, t = 18.4.
        c = Connectivity([straight("D", altitude=0.0, x1=200.0)], self.BASE, 100.0, 0, 40)
        (span,) = c.spans("D")
        self.assertEqual(span[0], 0)
        self.assertAlmostEqual(span[1], 18.4)
        self.assertFalse(c.connected_at("D", 18.5))

    def test_a_relay_joins_a_far_drone_to_the_base(self):
        far = path("Far", (0, 150, 0, 0), (10, 150, 0, 0))
        relay = path("Relay", (0, 70, 0, 0), (10, 70, 0, 0))
        self.assertEqual(Connectivity([far], self.BASE, 100, 0, 10).spans("Far"), [])
        c = Connectivity([far, relay], self.BASE, 100, 0, 10)
        self.assertEqual(c.spans("Far"), [(0, 10)])

    def test_a_relay_that_leaves_breaks_the_chain_when_it_goes(self):
        # The relay drifts from x = 70 to 120 over 10 s; the base link breaks at x = 92, t = 4.4.
        far = path("Far", (0, 150, 0, 0), (10, 150, 0, 0))
        relay = path("Relay", (0, 70, 0, 0), (10, 120, 0, 0))
        (span,) = Connectivity([far, relay], self.BASE, 100, 0, 10).spans("Far")
        self.assertAlmostEqual(span[1], 4.4)

    def test_reported_when_it_comes_back_in_range(self):
        # Detects far out, flies home: reported when it reaches x = 92 on the way back.
        s = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:1])
        t = path("Drone1", (0, 0, 0, 0), (40, 200, 0, 0), (80, 0, 0, 0))
        facts = observe(s, [t], 0, 80, targets=(Target("T1", 184.5, -3.2, "S3"),))
        (r,) = facts.reports
        self.assertGreater(r.detected_at, 18.4)
        self.assertAlmostEqual(r.reported_at, 40 + (200 - 92) / 5.0)


class SeparationTests(unittest.TestCase):

    def test_closest_approach_is_the_true_minimum(self):
        # Crossing tracks, 3 m apart in height, at the same instant: closest 3.0 at t = 10.
        a = path("A", (0, -50, 0, 10), (20, 50, 0, 10))
        b = path("B", (0, 0, -50, 13), (20, 0, 50, 13))
        (s,) = separations([a, b], 2.0, 0, 20)
        self.assertAlmostEqual(s.min_m, 3.0)
        self.assertAlmostEqual(s.at, 10.0)
        self.assertEqual(s.violations, ())

    def test_a_violation_is_timed(self):
        # Head on along x, 1 m apart in height, closing at 10 m/s: under 2 m for
        # |dx| < sqrt(3), i.e. t within sqrt(3)/10 of 10.
        a = path("A", (0, -50, 0, 10), (20, 50, 0, 10))
        b = path("B", (0, 50, 0, 11), (20, -50, 0, 11))
        (s,) = separations([a, b], 2.0, 0, 20)
        ((v0, v1),) = s.violations
        self.assertAlmostEqual(v0, 10 - math.sqrt(3) / 10)
        self.assertAlmostEqual(v1, 10 + math.sqrt(3) / 10)

    def test_one_flying_over_a_landed_one_is_judged(self):
        landed = path("A", (0, 50, 0, 0), (20, 50, 0, 0), airborne=False)
        over = path("B", (0, 0, 0, 1), (20, 100, 0, 1))
        (s,) = separations([landed, over], 2.0, 0, 20)
        self.assertAlmostEqual(s.min_m, 1.0)
        self.assertEqual(len(s.violations), 1)

    def test_diverging_from_the_start(self):
        # 5 m apart and parting: closest at the start, not where the lines
        # would have met had they been flown earlier.
        a = path("A", (0, 0, 0, 10), (10, -50, 0, 10))
        b = path("B", (0, 5, 0, 10), (10, 55, 0, 10))
        (s,) = separations([a, b], 2.0, 0, 10)
        self.assertEqual((s.min_m, s.at), (5.0, 0.0))

    def test_two_landed_drones_are_not_judged(self):
        a = path("A", (0, 0, 0, 0), (10, 0, 0, 0), airborne=False)
        b = path("B", (0, 1, 0, 0), (10, 1, 0, 0), airborne=False)
        (s,) = separations([a, b], 2.0, 0, 10)
        self.assertIsNone(s.min_m)
        self.assertEqual(s.violations, ())


class ObserveTests(unittest.TestCase):

    def test_only_the_scenarios_drones(self):
        with self.assertRaises(ValueError):
            observe(CANONICAL, [straight("Drone9")], 0, 10)
        with self.assertRaises(ValueError):
            observe(CANONICAL, [straight("Drone1"), straight("Drone1")], 0, 10)

    def test_the_json_is_relative_to_the_start(self):
        facts = observe(CANONICAL, [straight("Drone1", t0=100.0)], 100.0, 120.0)
        j = facts.as_json()
        self.assertEqual(j["duration_s"], 20.0)
        self.assertEqual(j["zone_entries"][0]["at_s"], 3.0)
        self.assertEqual(j["random_seed"], 17)
        self.assertEqual([t["id"] for t in j["targets"]], ["T1", "T2"])


def fly_one(world, commands, drone="Drone1"):
    runner = S.SkillRunner(MockVehicleAdapter(world), drone, world.clock)
    for command in commands:
        result = runner.run(command)
        assert result.ok, result


class MockTraceTests(unittest.TestCase):

    def test_a_mock_flight_measured_exactly(self):
        # Through R1 and past two targets, 5 m and 9.5 m off the track.
        s = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:1],
                                targets=TargetSpec(2, "fixed", ((65.0, 5.0), (65.0, 9.5))))
        world = MockWorld(declared=["Drone1"])
        t0 = world.clock.now()
        fly_one(world, (S.TakeOffCommand(altitude_m=10), S.GoToWaypointCommand(Waypoint(50, 0, 10)),
                        S.GoToWaypointCommand(Waypoint(80, 0, 10)), S.ReturnHomeCommand(), S.LandCommand()))
        facts = observe(s, mock_trajectories(world), t0, world.clock.now())
        (entry,) = facts.zone_entries
        (found,) = facts.detections
        (b,) = facts.batteries
        leg_start = entry.at - 3.0                       # 15 m at 5 m/s to the zone's edge
        self.assertAlmostEqual(entry.x, 15.0)
        self.assertAlmostEqual(entry.y, 0.0)
        self.assertEqual(found.target, "T1")
        # At (50, 0) 10 s later, then in view at x = 65 - sqrt(75), 15 - 8.66 m on.
        self.assertAlmostEqual(found.in_view_at, leg_start + 10.0 + (15.0 - math.sqrt(75)) / 5.0)
        self.assertAlmostEqual(b.flown_m, 180.0)          # 10 up, 50, 30, 80 home, 10 down
        (r,) = facts.reports                              # within 100 m of the base throughout
        self.assertEqual(r.reported_at, found.detected_at)
        self.assertFalse(mock_trajectories(world)["Drone1"].knots[-1].airborne)

    def test_motors_cut_in_the_air_is_a_jump(self):
        world = MockWorld(declared=["Drone1"])
        adapter = MockVehicleAdapter(world)
        adapter.take_control("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_position(0, 0, G - 10, 5.0))
        world.clock.sleep(5.0)                           # holds, then the motors are cut
        adapter.release("Drone1")
        knots = mock_trajectories(world)["Drone1"].knots
        self.assertEqual((knots[-2].altitude_m, knots[-2].airborne), (10.0, True))
        self.assertEqual((knots[-1].altitude_m, knots[-1].airborne, knots[-1].t),
                         (0.0, False, knots[-2].t))

    def test_the_exact_minimum_is_no_larger_than_the_mocks_sampled_one(self):
        world = MockWorld(declared=["Drone1", "Drone2", "Drone3", "Drone4"])
        t0 = world.clock.now()
        fly_team(exit_plan(), lambda: MockVehicleAdapter(world), world.clock)
        facts = observe(CANONICAL, mock_trajectories(world), t0, world.clock.now())
        sampled = world.separation()
        for s in facts.separations:
            with self.subTest(pair=f"{s.a}-{s.b}"):
                ticked = sampled[f"{s.a}-{s.b}"]["min_m"]
                self.assertLessEqual(s.min_m, ticked + 1e-3)
                self.assertGreater(s.min_m, ticked - 0.6)     # a tick at 5 m/s is 0.5 m
                self.assertEqual(s.violations, ())


class PollingObserverTests(unittest.TestCase):

    def test_it_refuses_simulated_time_and_missing_grounds(self):
        with self.assertRaises(ValueError):
            PollingObserver(lambda: None, ["Drone1"], {"Drone1": G}, clock=SimClock())
        with self.assertRaises(ValueError):
            PollingObserver(lambda: None, ["Drone1", "Drone2"], {"Drone1": G})

    def test_it_follows_a_real_time_flight_within_its_sampling(self):
        # The mock in REAL time: about 1.1 s, polled at 20 Hz, compared with the exact trace.
        clock = RealClock()
        world = MockWorld(declared=["Drone1"], clock=clock)
        adapter = MockVehicleAdapter(world)
        observer = PollingObserver(lambda: MockVehicleAdapter(world), ["Drone1"], {"Drone1": G},
                                   clock=clock, hz=20.0)
        observer.start()
        adapter.take_control("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_position(10, 0, G - 5, 10.0))
        observer.stop()
        polled = observer.trajectories()["Drone1"]
        exact = mock_trajectories(world)["Drone1"]
        self.assertGreaterEqual(len(polled.knots), 10)
        for k in polled.knots:
            self.assertLess(math.dist(k.point, exact.position_at(k.t)), 0.5)
        self.assertAlmostEqual(polled.knots[-1].altitude_m, 5.0, places=6)
        self.assertTrue(polled.knots[-1].airborne)
        self.assertFalse(polled.knots[0].airborne)

    def test_a_failure_is_raised_not_swallowed(self):
        def broken():
            raise ConnectionError("no simulator")
        observer = PollingObserver(broken, ["Drone1"], {"Drone1": G})
        observer.start()
        with self.assertRaises(RuntimeError):
            observer.stop()


if __name__ == "__main__":
    unittest.main()
