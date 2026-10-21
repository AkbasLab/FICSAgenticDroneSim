#!/usr/bin/env python3
"""Tests for routing, the scripted controller, and Phase 4's exit run.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 4's exit is that a scripted, non-agentic controller completes the
canonical mission. These check that the controller is what that claims --
planned from the brief alone, deterministic, clear of the zones by its
clearance, lanes the detection rule can see between, refused before take-off
when it cannot make the reserve or the deadline -- and that the exit can
fail: lanes too wide, or a landing that does not land, must not pass.
"""

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.control import scripted  # noqa: E402
from agentic_uav.control.routing import NoRouteError, grown, length, route  # noqa: E402
from agentic_uav.control.skills import SearchRegionCommand  # noqa: E402
from agentic_uav.core.geometry import Polygon  # noqa: E402
from agentic_uav.core.scenario import BatterySpec, DetectionSpec, RestrictedZone  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.search_relay import EXIT_SEEDS, fly_on_mock  # noqa: E402
from agentic_uav.experiments.team_flight import SkillRecord  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
R1 = CANONICAL.restricted_zones[0].polygon


class RoutingTests(unittest.TestCase):

    def test_straight_when_clear(self):
        self.assertEqual(route((0, 0), (-5, 30), [R1]), [(0, 0), (-5, 30)])

    def test_round_the_grown_corner(self):
        path = route((8, 0), (120, -72), [R1])
        self.assertEqual(len(path), 3)
        corner = path[1]
        self.assertAlmostEqual(corner[0], 15 - 2.0 * 1.05)       # the corner, 2 m out, plus the margin
        self.assertAlmostEqual(corner[1], -15 - 2.0 * 1.05)
        self.assertLess(length(path), 140)

    def test_every_leg_keeps_the_clearance(self):
        guard = grown(R1, 2.0)
        self.assertEqual(guard.vertices, ((13.0, -17.0), (37.0, -17.0), (37.0, 17.0), (13.0, 17.0)))
        for start, goal in (((0, 0), (200, 8)), ((12, 0), (40, 8)), ((120, 72), (4, 0)), ((50, 0), (0, 0))):
            path = route(start, goal, [R1])
            for a, b in zip(path, path[1:]):
                with self.subTest(start=start, goal=goal, leg=(a, b)):
                    self.assertFalse(guard.crosses(a, b))

    def test_too_close_to_start_or_finish(self):
        with self.assertRaisesRegex(NoRouteError, "the start .* within 2.0 m"):
            route((14, 0), (100, 0), [R1])                       # 1 m from the zone
        with self.assertRaisesRegex(NoRouteError, "the goal .* within 2.0 m"):
            route((0, 0), (25, 0), [R1])

    def test_the_shorter_way_round(self):
        # From y = 5, over the top is shorter than under: two corners either way.
        path = route((0, 5), (50, 5), [R1])
        self.assertTrue(all(y > 0 for _, y in path[1:-1]), path)
        top = 17.1
        expected = 2 * ((12.9 ** 2 + (top - 5) ** 2) ** 0.5) + 24.2
        self.assertAlmostEqual(length(path), expected, places=6)

    def test_every_edge_moves_out_by_the_clearance(self):
        # A triangle, given clockwise: corners that are not right angles, and
        # an orientation the growing must correct.
        tri = Polygon(((0, 0), (10, 30), (40, 0)))
        g = grown(tri, 2.0)

        def off_line(p, a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            return abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / (dx * dx + dy * dy) ** 0.5

        for a, b in tri.edges():
            # Exactly one grown edge is parallel to it, 2 m out: both its ends 2 m from its line.
            twins = [e for e in g.edges()
                     if all(abs(off_line(p, a, b) - 2.0) < 1e-9 for p in e)]
            self.assertEqual(len(twins), 1, (a, b))
        for v in g.vertices:
            self.assertFalse(tri.contains(*v))
        for v in tri.vertices:
            self.assertTrue(g.contains(*v))

    def test_a_concave_zone(self):
        # An L: the shortest way past turns at its convex corners, never the notch.
        ell = Polygon(((20, -10), (40, -10), (40, 0), (30, 0), (30, 20), (20, 20)))
        path = route((0, 5), (60, 5), [ell])
        guard = grown(ell, 2.0)
        for a, b in zip(path, path[1:]):
            self.assertFalse(ell.crosses(a, b))
            self.assertFalse(guard.crosses(a, b))


class ControllerTests(unittest.TestCase):

    def setUp(self):
        self.plan = scripted.plan_mission(CANONICAL.brief())

    def test_only_a_brief(self):
        with self.assertRaises(TypeError):
            scripted.plan_mission(CANONICAL)

    def test_the_seed_cannot_change_the_plan(self):
        other = dataclasses.replace(CANONICAL, random_seed=99)
        self.assertEqual(scripted.plan_mission(other.brief()), self.plan)

    def test_one_drone_per_sector_each_at_its_own_height(self):
        self.assertEqual({d: p.sectors for d, p in self.plan.items()},
                         {"Drone1": ("S1",), "Drone2": ("S2",), "Drone3": ("S3",), "Drone4": ("S4",)})
        self.assertEqual([p.altitude_m for p in self.plan.values()], [12.0, 16.0, 20.0, 24.0])

    def test_lanes_the_detection_rule_can_see_between(self):
        self.assertAlmostEqual(scripted.detection_half_width(CANONICAL.detection, 5.0), 75 ** 0.5)
        self.assertEqual(scripted.lane_spacing(80.0, CANONICAL.detection, 5.0), 16.0)
        for p in self.plan.values():
            searches = [c for c in p.commands if isinstance(c, SearchRegionCommand)]
            self.assertEqual([c.spacing_m for c in searches], [16.0])
        with self.assertRaises(scripted.PlanError):
            scripted.detection_half_width(DetectionSpec(10.0, 2.0), 10.0)   # 20 m chord > radius
        # Held 3 s: half chord 7.5 m, half width 6.61 m, at most 12.56 m apart: 7 lanes.
        self.assertAlmostEqual(scripted.lane_spacing(80.0, DetectionSpec(10.0, 3.0), 5.0), 80 / 7)

    def test_the_whole_track_keeps_clear_of_the_zone(self):
        guard = grown(R1, scripted.ZONE_CLEARANCE_M)
        for d, p in self.plan.items():
            self.assertEqual(p.path[0], p.path[-1])                        # pad to pad
            for a, b in zip(p.path, p.path[1:]):
                with self.subTest(drone=d, leg=(a, b)):
                    self.assertFalse(guard.crosses(a, b))

    def test_refused_before_take_off(self):
        weak = dataclasses.replace(CANONICAL, battery=BatterySpec(100.0, 0.4, 0.02, 20.0))
        with self.assertRaises(scripted.PlanError):
            scripted.plan_mission(weak.brief())
        short = dataclasses.replace(CANONICAL, mission=dataclasses.replace(CANONICAL.mission, deadline_s=120.0))
        with self.assertRaises(scripted.PlanError):
            scripted.plan_mission(short.brief())

    def test_a_lane_through_a_zone_is_refused(self):
        inside = RestrictedZone("Z", Polygon(((60.0, -50.0), (70.0, -50.0), (70.0, -40.0), (60.0, -40.0))))
        s = dataclasses.replace(CANONICAL, restricted_zones=CANONICAL.restricted_zones + (inside,))
        with self.assertRaises(scripted.PlanError):
            scripted.plan_mission(s.brief())


class ExitTests(unittest.TestCase):

    def test_the_canonical_seed_is_met(self):
        run = fly_on_mock(CANONICAL)
        self.assertTrue(run.met, run.report.summary())
        self.assertTrue(run.skills_ok)
        self.assertEqual(sorted(run.trajectories), ["Drone1", "Drone2", "Drone3", "Drone4"])

    def test_deterministic(self):
        self.assertEqual(json.dumps(fly_on_mock(CANONICAL).as_json(), sort_keys=True),
                         json.dumps(fly_on_mock(CANONICAL).as_json(), sort_keys=True))

    def test_two_drones_take_two_sectors_each(self):
        # AUV-05: two to four drones. Two fly all four sectors, in time and battery.
        two = dataclasses.replace(CANONICAL, vehicles=CANONICAL.vehicles[:2])
        run = fly_on_mock(two)
        self.assertEqual({d: p.sectors for d, p in run.plan.items()},
                         {"Drone1": ("S1", "S3"), "Drone2": ("S2", "S4")})
        self.assertTrue(run.met, run.report.summary())

    def test_lanes_too_wide_fail_the_exit(self):
        # The negative control: 20 m lanes leave strips no pass holds for 2 s.
        old = scripted.LANE_MARGIN
        scripted.LANE_MARGIN = 1.2
        try:
            run = fly_on_mock(CANONICAL)
        finally:
            scripted.LANE_MARGIN = old
        self.assertEqual(run.plan["Drone1"].lane_spacing_m, 20.0)
        self.assertFalse(run.met)
        self.assertFalse(run.report.criterion("C1").passed)

    def test_a_landing_that_does_not_land_fails_the_exit(self):
        def stuck(world):
            world.faults.stuck_land.add("Drone2")
        run = fly_on_mock(CANONICAL, prepare=stuck)
        self.assertFalse(run.skills_ok)
        self.assertFalse(run.met)
        self.assertFalse(run.report.criterion("C6").passed)

    def test_drones_start_on_their_pads(self):
        # Pads that are not the mock's spawn layout: the run must place them.
        moved = dataclasses.replace(CANONICAL, vehicles=(
            dataclasses.replace(CANONICAL.vehicles[0], start_x=0.0, start_y=-4.0),
            dataclasses.replace(CANONICAL.vehicles[1], start_x=0.0, start_y=4.0)))
        run = fly_on_mock(moved)
        for v in moved.vehicles:
            x, y, h = run.trajectories[v.id].position_at(run.report.start)
            self.assertEqual((x, y, h), (v.start_x, v.start_y, 0.0))

    def test_a_rescued_run_is_not_met(self):
        # A safety landing, or a skill skipped, is not the script completing the
        # mission, even if the mission report succeeds.
        run = fly_on_mock(CANONICAL)
        last = run.records["Drone1"][-1]
        for extra in (SkillRecord("Drone1", 9, last.command, last.result, safety=True),
                      SkillRecord("Drone1", 9, last.command, None)):
            records = {**run.records, "Drone1": run.records["Drone1"] + [extra]}
            rescued = dataclasses.replace(run, records=records)
            with self.subTest(extra=extra):
                self.assertTrue(rescued.report.success)
                self.assertFalse(rescued.skills_ok)
                self.assertFalse(rescued.met)

    def test_the_exit_seeds_are_fixed(self):
        self.assertEqual(EXIT_SEEDS, tuple(range(1, 21)))
        self.assertIn(CANONICAL.random_seed, EXIT_SEEDS)


class ExitScriptTests(unittest.TestCase):

    def test_one_seed_writes_its_record(self):
        import search_relay_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = search_relay_exit.main(["--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            files = sorted(os.listdir(out))
            self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
            with open(os.path.join(out, files[0]), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            self.assertEqual(rows[0]["seeds"], [17])
            self.assertTrue(rows[0]["exit_criterion_met"])
            self.assertEqual(rows[1]["seed"], 17)
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_seed_lists(self):
        import search_relay_exit
        self.assertEqual(search_relay_exit.seeds_arg("1-3,7"), (1, 2, 3, 7))


if __name__ == "__main__":
    unittest.main()
