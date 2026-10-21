#!/usr/bin/env python3
"""Tests for coverage and the evaluator: AUV-05's six success criteria, each with its number.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 4's exit criterion is that a scripted controller "can complete the
canonical mission", and the evaluator is what says whether it did. So it is
tested on a mission flown by hand that must pass, and then broken one way at
a time -- a sector skipped, a zone crossed, a pair too close, a drone left in
the air, the deadline missed -- each of which must fail exactly the criterion
it breaks and no other.
"""

import dataclasses
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control.navigation import lawnmower  # noqa: E402
from agentic_uav.core.geometry import Polygon  # noqa: E402
from agentic_uav.core.scenario import BatterySpec, MissionSpec, RestrictedZone  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.evaluation import RETURN_RADIUS_M, Contact, evaluate  # noqa: E402
from agentic_uav.simulator.coverage import coverage, covered_at, searchable_cells  # noqa: E402
from agentic_uav.simulator.mission_world import Target, detections  # noqa: E402
from agentic_uav.simulator.trajectory import Knot, Trajectory  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
SPEED, CLIMB = 5.0, 2.0
LANE_M = 16.0                                 # under the 17.32 m a 2 s dwell allows at 5 m/s
ALTITUDES = {"Drone1": 12.0, "Drone2": 16.0, "Drone3": 20.0, "Drone4": 24.0}
SECTOR_OF = {"Drone1": "S1", "Drone2": "S2", "Drone3": "S3", "Drone4": "S4"}


def flight(drone, xy_path, altitude, t0=0.0, land=True):
    """Climb at the first point, fly the path level, descend and land at the last."""
    (x, y), t = xy_path[0], t0
    knots = [Knot(t, x, y, 0.0, False)]
    t += 0.5
    knots.append(Knot(t, x, y, 0.0, True))
    t += altitude / CLIMB
    knots.append(Knot(t, x, y, altitude, True))
    for nx, ny in xy_path[1:]:
        t += math.hypot(nx - x, ny - y) / SPEED
        x, y = nx, ny
        knots.append(Knot(t, x, y, altitude, True))
    if land:
        t += altitude / CLIMB
        knots.append(Knot(t, x, y, 0.0, True))
        knots.append(Knot(t, x, y, 0.0, False))
    return Trajectory(drone, knots)


def sector_route(scenario, drone):
    """Pad, sideways clear of R1, round it at x = 40, a lawnmower, and back the same way."""
    v = scenario.vehicle(drone)
    sector = next(s for s in scenario.sectors if s.id == SECTOR_OF[drone])
    side = -20.0 if sector.region.y_max <= 0 else 20.0
    lanes = [(w.x, w.y) for w in lawnmower(sector.region, LANE_M, 1.0)]
    out = [(v.start_x, v.start_y), (v.start_x, side), (40.0, side)]
    return out + lanes + out[::-1]


def hand_flown(scenario=CANONICAL, drones=("Drone1", "Drone2", "Drone3", "Drone4")):
    return [flight(d, sector_route(scenario, d), ALTITUDES[d]) for d in drones]


def failing(report):
    return [c.id for c in report.criteria if not c.passed]


class CoverageTests(unittest.TestCase):

    def test_one_lane_searches_a_strip_17_32_m_wide(self):
        # Along y = -40 through S1, starting and ending outside it: cell rows at
        # 0.5, 1.5 ... 8.5 m either side are within 8.66 m: 18 rows of 80 cells.
        lane = flight("Drone1", [(20.0, -40.0), (140.0, -40.0)], 10.0, land=False)
        cov = coverage(CANONICAL, [lane], 0, 100)
        self.assertAlmostEqual(cov.by_sector["S1"], 18 * 80 / 6400)

    def test_searched_means_a_target_there_is_detected(self):
        # Coverage and detection cannot disagree, cell by cell.
        trajs = hand_flown(drones=("Drone1",))
        cells, _ = searchable_cells(CANONICAL)
        times = covered_at(cells, trajs, 10.0, 2.0, 0, 1000)
        rng = np.random.default_rng(5)
        picks = rng.choice(len(cells), 300, replace=False)
        targets = [Target(f"T{i}", float(cells[i, 0]), float(cells[i, 1]), "S1") for i in picks]
        found = {d.target: d.detected_at for d in detections(trajs, targets, CANONICAL.detection, 0, 1000)}
        for i in picks:
            with self.subTest(cell=i):
                if np.isfinite(times[i]):
                    self.assertAlmostEqual(found[f"T{i}"], times[i])
                else:
                    self.assertNotIn(f"T{i}", found)

    def test_two_half_dwells_are_not_a_search(self):
        # sqrt(91) m off the track: a 6 m chord, 1.2 s at 5 m/s. Drone2 takes the
        # point over the instant Drone1 loses it -- 2.4 s together, 1.2 s each.
        cell = np.array([[80.0, -40.0 + math.sqrt(91.0)]])
        a = Trajectory("Drone1", [Knot(0.0, 60, -40, 10, True), Knot(8.0, 100, -40, 10, True)])
        b = Trajectory("Drone2", [Knot(1.2, 60, -40, 14, True), Knot(9.2, 100, -40, 14, True)])
        self.assertTrue(np.isinf(covered_at(cell, [a, b], 10.0, 2.0, 0, 10)[0]))
        slow = Trajectory("Drone1", [Knot(0.0, 60, -40, 10, True), Knot(16.0, 100, -40, 10, True)])
        self.assertTrue(np.isfinite(covered_at(cell, [slow], 10.0, 2.0, 0, 16)[0]))   # 2.4 s alone

    def test_hovering_searches_and_standing_does_not(self):
        cell = np.array([[80.0, -40.0]])
        hover = Trajectory("Drone1", [Knot(0.0, 80, -40, 10, True), Knot(3.0, 80, -40, 10, True)])
        stand = Trajectory("Drone1", [Knot(0.0, 80, -40, 0, False), Knot(60.0, 80, -40, 0, False)])
        self.assertEqual(covered_at(cell, [hover], 10.0, 2.0, 0, 3)[0], 2.0)
        self.assertTrue(np.isinf(covered_at(cell, [stand], 10.0, 2.0, 0, 60)[0]))

    def test_time_to_is_when_the_fraction_was_actually_reached(self):
        cov = coverage(CANONICAL, hand_flown(), 0, 1000)
        times = np.array(cov.covered_times)
        for f in (0.3 + 0.3 / cov.cells, 0.5, 0.95 + 0.7 / cov.cells):
            t = cov.time_to(f)
            with self.subTest(fraction=f):
                self.assertGreaterEqual((times <= t).sum() / cov.cells, f)
                self.assertLess((times < t).sum() / cov.cells, f)

    def test_a_zone_inside_a_sector_is_not_searchable(self):
        zone = RestrictedZone("Z", Polygon(((40.0, -80.0), (60.0, -80.0), (60.0, -60.0), (40.0, -60.0))))
        s = dataclasses.replace(CANONICAL, restricted_zones=(zone,))
        cells, _ = searchable_cells(s)
        self.assertEqual(len(cells), 4 * 6400 - 400)

    def test_time_to(self):
        cov = coverage(CANONICAL, hand_flown(), 0, 1000)
        t95 = cov.time_to(0.95)
        self.assertIsNotNone(t95)
        self.assertLess(cov.time_to(0.5), t95)
        self.assertIsNone(cov.time_to(1.0))                    # lane ends are never quite searched


class EvaluatorTests(unittest.TestCase):

    def test_the_hand_flown_mission_succeeds(self):
        report = evaluate(CANONICAL, hand_flown(), 0, 2000)
        self.assertTrue(report.success, report.summary())
        self.assertEqual(failing(report), [])
        self.assertGreaterEqual(report.criterion("C1").measured, 0.95)
        self.assertEqual(report.criterion("C2").measured, 2)
        self.assertEqual(report.criterion("C3").measured, 2)
        self.assertEqual(report.components["safe_return"], 1.0)
        last_landing = max(t.knots[-1].t for t in hand_flown())
        self.assertAlmostEqual(report.completion_s, last_landing)
        j = report.as_json()
        self.assertEqual([c["id"] for c in j["criteria"]], ["C1", "C2", "C3", "C4", "C5", "C6"])
        self.assertEqual(j["observer"], "mock-exact")

    def test_a_sector_left_unsearched(self):
        # Without Drone3, S3 -- and T1, at (184.5, -3.2) -- go unsearched.
        report = evaluate(CANONICAL, hand_flown(drones=("Drone1", "Drone2", "Drone4")), 0, 2000)
        self.assertEqual(failing(report), ["C1", "C2", "C3"])
        self.assertLess(report.criterion("C1").measured, 0.80)
        self.assertEqual(report.criterion("C2").measured, 1)
        self.assertIsNone(report.completion_s)
        self.assertEqual(report.components["target_detection"], 0.5)

    def test_cutting_through_the_restricted_zone(self):
        trajs = hand_flown()
        v = CANONICAL.vehicle("Drone1")
        route = [(v.start_x, v.start_y), (40.0, -20.0)] + sector_route(CANONICAL, "Drone1")[3:]
        trajs[0] = flight("Drone1", route, ALTITUDES["Drone1"])
        report = evaluate(CANONICAL, trajs, 0, 2000)
        self.assertEqual(failing(report), ["C4"])
        self.assertIn("Drone1 entered R1", report.criterion("C4").detail)

    def test_a_collision_but_not_a_landing(self):
        ground = Contact("Drone1", "MockGround", 100.0)
        wall = Contact("Drone2", "SM_Building_12", 50.0)
        self.assertEqual(failing(evaluate(CANONICAL, hand_flown(), 0, 2000, contacts=[ground])), [])
        report = evaluate(CANONICAL, hand_flown(), 0, 2000, contacts=[ground, wall])
        self.assertEqual(failing(report), ["C5"])
        self.assertEqual(report.criterion("C5").measured["collisions"], 1)

    def test_the_spectator_camera_is_not_a_collision(self):
        camera = Contact("Drone1", "SpectatorPawn_0", 50.0)
        report = evaluate(CANONICAL, hand_flown(), 0, 2000, contacts=[camera])
        self.assertEqual(failing(report), [])
        self.assertEqual(report.components["camera_contacts"], 1)

    def test_contacts_outside_the_window_do_not_count(self):
        before = Contact("Drone2", "SM_Building_12", -5.0)
        after = Contact("Drone2", "SM_Building_12", 2500.0)
        self.assertEqual(failing(evaluate(CANONICAL, hand_flown(), 0, 2000, contacts=[before, after])), [])

    def test_mock_contact_rows_are_accepted(self):
        report = evaluate(CANONICAL, hand_flown(), 0, 2000,
                          contacts=[{"drone": "Drone1", "object": "Drone2", "at_s": 10.0}])
        self.assertEqual(failing(report), ["C5"])

    def test_two_drones_at_one_height_too_close(self):
        # Drone3 at Drone1's height, 1.6 s late: it reaches (8, -20) as Drone1
        # passes it, and the two fly on together to x = 40.
        trajs = hand_flown()
        trajs[2] = flight("Drone3", sector_route(CANONICAL, "Drone3"), ALTITUDES["Drone1"], t0=1.6)
        report = evaluate(CANONICAL, trajs, 0, 2000)
        self.assertEqual(failing(report), ["C5"])
        self.assertGreater(report.criterion("C5").measured["separation_violations"], 0)

    def test_left_in_the_air_or_on_the_wrong_pad(self):
        trajs = hand_flown()
        trajs[1] = flight("Drone2", sector_route(CANONICAL, "Drone2"), ALTITUDES["Drone2"], land=False)
        route = sector_route(CANONICAL, "Drone4")[:-1] + [(12.0, -(RETURN_RADIUS_M + 1.0))]
        trajs[3] = flight("Drone4", route, ALTITUDES["Drone4"])
        report = evaluate(CANONICAL, trajs, 0, 2000)
        self.assertEqual(failing(report), ["C6"])
        detail = report.criterion("C6").detail
        self.assertIn("Drone2: still airborne", detail)
        self.assertIn("Drone4: 3.0 m from its pad", detail)
        self.assertEqual(report.criterion("C6").measured, 2)

    def test_a_failed_drone_need_not_return(self):
        trajs = hand_flown()
        trajs[1] = flight("Drone2", sector_route(CANONICAL, "Drone2"), ALTITUDES["Drone2"], land=False)
        report = evaluate(CANONICAL, trajs, 0, 2000, failed=["Drone2"])
        self.assertEqual(failing(report), [])
        self.assertEqual(report.components["drones_failed"], ["Drone2"])
        with self.assertRaises(ValueError):
            evaluate(CANONICAL, trajs, 0, 2000, failed=["Drone9"])

    def test_completion_waits_for_what_a_failed_drone_still_does(self):
        # Drone2 is failed, so its landing is not waited for -- but it still
        # searches S2, 300 s late. The mission completes when coverage and
        # T2's report are both in, after every functioning drone has landed.
        trajs = hand_flown()
        trajs[1] = flight("Drone2", sector_route(CANONICAL, "Drone2"), ALTITUDES["Drone2"], t0=300.0)
        report = evaluate(CANONICAL, trajs, 0, 2000, failed=["Drone2"])
        self.assertTrue(report.success, report.summary())
        t2 = report.facts.first_report("T2").reported_at
        cov95 = report.coverage.time_to(0.95)
        others = max(t.knots[-1].t for t in trajs if t.drone != "Drone2")
        self.assertGreater(min(t2, cov95), others)
        self.assertGreater(cov95, t2)                            # here coverage comes last
        self.assertAlmostEqual(report.completion_s, cov95)
        # With T2 on S2's last lane, 20 m short of S4 so only Drone2 sees it,
        # its report comes last instead: made 130 m out, it reaches the base
        # only on the way home.
        late = (Target("T1", 184.535, -3.16, "S3"), Target("T2", 100.0, 75.0, "S2"))
        report = evaluate(CANONICAL, trajs, 0, 2000, failed=["Drone2"], targets=late)
        self.assertTrue(report.success, report.summary())
        t2 = report.facts.first_report("T2").reported_at
        self.assertGreater(t2, report.coverage.time_to(0.95))
        self.assertAlmostEqual(report.completion_s, t2)

    def test_landing_under_the_reserve_or_flat(self):
        # 0.4 %/s: the far sectors' drones land at 8.8 and 8.5 %; 0.45 %/s runs them flat.
        heavy = dataclasses.replace(CANONICAL, battery=BatterySpec(100.0, 0.4, 0.02, 20.0))
        report = evaluate(heavy, hand_flown(heavy), 0, 2000)
        self.assertEqual(failing(report), ["C6"])
        detail = report.criterion("C6").detail
        self.assertIn("Drone3: battery 8.8% under the 20% reserve", detail)
        self.assertNotIn("Drone1", detail)
        flat = dataclasses.replace(CANONICAL, battery=BatterySpec(100.0, 0.45, 0.02, 20.0))
        self.assertIn("Drone3: battery flat", evaluate(flat, hand_flown(flat), 0, 2000).criterion("C6").detail)

    def test_after_the_deadline_nothing_counts(self):
        last = max(t.knots[-1].t for t in hand_flown())
        tight = dataclasses.replace(CANONICAL, mission=dataclasses.replace(CANONICAL.mission,
                                                                           deadline_s=last - 1.0))
        report = evaluate(tight, hand_flown(tight), 0, 2000)
        self.assertIn("C6", failing(report))                     # still airborne at the deadline
        self.assertEqual(report.until, last - 1.0)
        self.assertIsNone(report.completion_s)

    def test_detected_far_out_and_never_brought_back(self):
        # Drone3 searches S3 and lands there: T1 is detected but never reported.
        trajs = hand_flown()
        route = sector_route(CANONICAL, "Drone3")
        trajs[2] = flight("Drone3", route[:len(route) - 3], ALTITUDES["Drone3"])
        report = evaluate(CANONICAL, trajs, 0, 2000)
        self.assertEqual(failing(report), ["C3", "C6"])
        self.assertIn("detected, never reported: T1", report.criterion("C3").detail)

    def test_a_relay_reports_what_its_neighbour_found(self):
        # Drone3 passes T1 (184.5, -3.2) far out of the base's range, detecting it
        # at about x = 184.5. Drone1 hovers at 10 m. At (100, -10) it is 108.9 m
        # from the base: no relay. At (90, -10) it is 99.0 m from the base and
        # 95.3 m from Drone3 at the detection: a relay, so T1 is reported at once.
        far = Trajectory("Drone3", [Knot(0.0, 150, -3, 20, True), Knot(8.0, 190, -3, 20, True)])
        for park, reported in (((100.0, -10.0), False), ((90.0, -10.0), True)):
            relay = Trajectory("Drone1", [Knot(0.0, *park, 10, True), Knot(8.0, *park, 10, True)])
            report = evaluate(CANONICAL, [relay, far], 0, 8, failed=["Drone1", "Drone3"])
            with self.subTest(park=park):
                self.assertEqual(report.criterion("C2").measured, 1)
                self.assertEqual(report.criterion("C3").measured, int(reported), report.criterion("C3").detail)
                if reported:
                    (r,) = report.facts.reports
                    self.assertEqual(r.reported_at, r.detected_at)

    def test_the_summary_names_every_criterion(self):
        text = evaluate(CANONICAL, hand_flown(), 0, 2000).summary()
        self.assertIn("SUCCESS", text)
        for cid in ("C1", "C2", "C3", "C4", "C5", "C6"):
            self.assertIn(f"PASS  {cid}", text)


if __name__ == "__main__":
    unittest.main()
