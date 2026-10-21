#!/usr/bin/env python3
"""Tests for Phase 4 step 5: lanes that run past the sector, the live variant, a live flight's record.

    python -m unittest discover tests
    AUV_SLOW_TESTS=1 python -m unittest discover tests     # also fly_live, ~40 s in real time

WHY THESE EXIST
---------------
A target in the corner of a sector went undetected because lanes stopped at
the sector's edge; the controller now runs them on. These hold that fix, keep
the live variant inside the airspace that has actually been flown, and check
that a live flight is kept so that it can be judged, saved and judged again
with the same verdicts. A live flight cannot run here; the same code runs
on the mock in real time when AUV_SLOW_TESTS is set.
"""

import dataclasses
import io
import json
import math
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
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.core.scenario import TargetSpec  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.evaluation import Contact  # noqa: E402
from agentic_uav.experiments.search_relay import (  # noqa: E402
    EXIT_SEEDS,
    LiveFlight,
    check_live_pads,
    compare_to_mock,
    distance_to_path,
    exit_runs,
    fly_live,
    fly_on_mock,
    measured_grounds,
    skills_json,
)
from agentic_uav.simulator.mock_adapter import MOCK_GROUND_Z, MockVehicleAdapter, MockWorld  # noqa: E402

CANONICAL = scenarios.load_scenario("search_relay_001")
LIVE = scenarios.load_scenario("search_relay_live_small")
G = MOCK_GROUND_Z


CLOCK_ORIGIN = 1000.0         # a monotonic clock is never at 0 when a flight starts


def live_from_mock(run, scenario, contacts=()):
    """A LiveFlight made from a mock run's exact trace, as a poller would have kept it.

    Shifted by CLOCK_ORIGIN, so that anything that forgets to count from the
    flight's start shows.
    """
    t0 = CLOCK_ORIGIN
    samples = {d: [(t0 + k.t, k.x, k.y, G - k.altitude_m) for k in t.knots] for d, t in run.trajectories.items()}
    return LiveFlight(scenario, run.plan, skills_json(run.records), run.skills_ok, samples,
                      {d: G for d in samples}, tuple(contacts), t0 + run.report.start, t0 + run.report.until, 10.0)


class LaneEndTests(unittest.TestCase):

    def test_the_overrun_is_half_the_observation_chord(self):
        self.assertEqual(scripted.lane_end_overrun(CANONICAL.detection, 5.0), 5.0)

    def test_lanes_run_on_where_the_zones_allow(self):
        plan = scripted.plan_mission(CANONICAL.brief())
        flown = {d: [(r.x_min, r.x_max) for r in p.searched] for d, p in plan.items()}
        # S1 and S2 start at x = 40: 5 m back would come within 2 m of R1's
        # grown edge at x = 37, so only their far ends run on.
        self.assertEqual(flown, {"Drone1": [(40.0, 125.0)], "Drone2": [(40.0, 125.0)],
                                 "Drone3": [(115.0, 205.0)], "Drone4": [(115.0, 205.0)]})

    def test_a_target_in_the_far_corner_is_found(self):
        # The corners furthest from anything: S3's and S4's outer corners.
        corners = dataclasses.replace(CANONICAL, targets=TargetSpec(2, "fixed", ((199.9, -79.9), (199.9, 79.9))))
        run = fly_on_mock(corners)
        self.assertTrue(run.report.criterion("C2").passed, run.report.summary())

    def test_the_live_variant_stays_in_the_airspace_flown(self):
        # Its lanes run between points M09 and M10 reached live, at most 26.9 m out.
        plan = scripted.plan_mission(LIVE.brief())
        points = [p for d in plan.values() for p in d.path]
        self.assertEqual(min(x for x, _ in points), -8.0)
        self.assertEqual(max(x for x, _ in points), 20.0)
        self.assertEqual(max(abs(y) for _, y in points), 18.0)
        self.assertLess(max(math.hypot(x, y) for x, y in points), 27.0)
        self.assertEqual([p.altitude_m for p in plan.values()], [12.0, 16.0])

    def test_the_live_variant_passes_its_mock_gate(self):
        runs = exit_runs(LIVE)
        self.assertEqual(sum(r.met for r in runs), len(EXIT_SEEDS))
        # And every target, on every seed, reached the base: none only detected.
        self.assertTrue(all(r.report.facts.first_report(t.id) for r in runs for t in r.report.facts.targets))


class LiveFlightTests(unittest.TestCase):

    def setUp(self):
        self.mock = fly_on_mock(LIVE)
        self.flight = live_from_mock(self.mock, LIVE)

    def test_pads_must_be_the_spawn_layout(self):
        self.assertEqual(check_live_pads(LIVE), ["Drone1", "Drone2"])
        self.assertEqual(check_live_pads(CANONICAL), ["Drone1", "Drone2", "Drone3", "Drone4"])
        moved = dataclasses.replace(LIVE, vehicles=(LIVE.vehicles[0],
                                                    dataclasses.replace(LIVE.vehicles[1], start_y=4.0)))
        with self.assertRaisesRegex(ValueError, "Drone2 at"):
            check_live_pads(moved)

    def test_judged_like_the_mock(self):
        from agentic_uav.simulator.mission_world import place_targets
        for seed in (1, 15, 17):
            with self.subTest(seed=seed):
                report = self.flight.judge(seed)
                self.assertTrue(self.flight.met(report), report.summary())
                self.assertEqual(report.observer, "polled-10Hz")
                self.assertEqual(report.random_seed, seed)
                self.assertEqual(report.facts.targets, place_targets(dataclasses.replace(LIVE, random_seed=seed)))

    def test_a_failed_skill_fails_every_seed(self):
        broken = dataclasses.replace(self.flight, skills_ok=False)
        self.assertFalse(broken.met(broken.judge(17)))

    def test_saved_and_judged_again_the_same(self):
        row = json.loads(json.dumps(self.flight.as_json()))
        again = LiveFlight.from_json(row, LIVE)
        for seed in EXIT_SEEDS:
            with self.subTest(seed=seed):
                a, b = self.flight.judge(seed), again.judge(seed)
                self.assertEqual(a.success, b.success)
                self.assertAlmostEqual(a.coverage.fraction, b.coverage.fraction, places=4)
        with self.assertRaises(ValueError):
            LiveFlight.from_json(row, CANONICAL)

    def test_contacts_are_kept_relative_to_the_flight(self):
        hit = Contact("Drone1", "SM_Building_3", self.flight.start + 12.5)
        flight = dataclasses.replace(self.flight, contacts=(hit,))
        self.assertFalse(flight.judge(17).criterion("C5").passed)
        row = flight.as_json()
        self.assertEqual(row["contacts"], [{"drone": "Drone1", "object": "SM_Building_3", "at_s": 12.5}])
        self.assertFalse(LiveFlight.from_json(row, LIVE).judge(17).criterion("C5").passed)

    def test_a_landed_drone_reads_1_17_m_up_in_carlaair(self):
        # Phase 3, live: landed drones read 1.16-1.17 m above their take-off
        # ground. They must still count as landed, home on their pads.
        from agentic_uav.control.skills import LANDED_ALTITUDE_M
        from agentic_uav.simulator.observer import DEFAULT_AIRBORNE_ABOVE_M
        self.assertEqual(DEFAULT_AIRBORNE_ABOVE_M, LANDED_ALTITUDE_M)
        last = {d: rows[-1][0] for d, rows in self.flight.samples.items()}
        lifted = {d: [(t, x, y, z) for t, x, y, z in rows] + [(last[d] + 1.0, rows[-1][1], rows[-1][2], G - 1.17)]
                  for d, rows in self.flight.samples.items()}
        flight = dataclasses.replace(self.flight, samples=lifted, end=self.flight.end + 1.0)
        report = flight.judge(17)
        self.assertTrue(report.criterion("C6").passed, report.criterion("C6").detail)

    def test_a_drone_with_no_ground_is_refused(self):
        from agentic_uav.simulator.observer import trajectories_from_samples
        with self.assertRaisesRegex(ValueError, "Drone2"):
            trajectories_from_samples(self.flight.samples, {"Drone1": G})

    def test_grounds_are_what_take_off_measured(self):
        samples = {d: [(0.0, 0.0, 0.0, 99.0)] for d in self.mock.records}
        self.assertEqual(measured_grounds(self.mock.records, samples), {"Drone1": G, "Drone2": G})
        # A drone whose TAKE_OFF never measured falls back to its first resting poll.
        self.assertEqual(measured_grounds({}, samples), {"Drone1": 99.0, "Drone2": 99.0})

    def test_beside_the_mock(self):
        cmp = compare_to_mock(self.flight, self.mock)
        for d, c in cmp["drones"].items():
            with self.subTest(drone=d):
                self.assertLess(c["max_off_track_m"], 1e-6)
                self.assertLess(c["max_height_error_at_cruise_m"], 1e-6)
                self.assertLess(c["pad_error_m"], 1e-6)
        self.assertEqual(cmp["coverage"]["live"], cmp["coverage"]["mock"])
        self.assertEqual(cmp["closest_pair_m"]["live"], 4.0)

    def test_distance_to_path(self):
        path = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))
        self.assertEqual(distance_to_path((5.0, 3.0), path), 3.0)
        self.assertEqual(distance_to_path((13.0, 5.0), path), 3.0)
        self.assertEqual(distance_to_path((-4.0, 3.0), path), 5.0)

    def test_the_script_judges_a_saved_flight(self):
        import search_relay_exit
        out = tempfile.mkdtemp()
        try:
            saved = os.path.join(out, "flight.jsonl")
            with open(saved, "w", encoding="utf-8") as h:
                h.write(json.dumps({"kind": "header"}) + "\n" + json.dumps(self.flight.as_json()) + "\n")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = search_relay_exit.main(["--judge", saved, "--scenario", "search_relay_live_small",
                                               "--seeds", "15,17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            written = sorted(f for f in os.listdir(out) if f.startswith("search-relay-exit-rejudge"))
            self.assertEqual([f.rsplit(".", 1)[1] for f in written], ["jsonl", "md"])
            with open(os.path.join(out, written[0]), encoding="utf-8") as h:
                kinds = [json.loads(line)["kind"] for line in h]
            self.assertEqual(kinds, ["header", "comparison", "seed", "seed"])
            self.assertIn("**MET** — 2 of 2 seeds met", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


@unittest.skipUnless(os.environ.get("AUV_SLOW_TESTS"), "real time: set AUV_SLOW_TESTS=1 (about 40 s)")
class RealTimeLiveFlightTest(unittest.TestCase):

    def test_fly_live_on_the_mock_in_real_time(self):
        # The live code path whole -- reset, runtime spawn, placement, the
        # poller, the monitor, the flight -- with the mock standing in for AirSim.
        clock = RealClock()
        world = MockWorld(declared=("Drone1",), clock=clock)
        with redirect_stdout(io.StringIO()):
            flight = fly_live(LIVE, MockVehicleAdapter(world), lambda: MockVehicleAdapter(world), clock)
        self.assertTrue(flight.skills_ok)
        self.assertEqual(flight.layout["added"], ["Drone2"])
        self.assertEqual(flight.grounds, {"Drone1": G, "Drone2": G})
        self.assertGreater(min(len(v) for v in flight.samples.values()), 200)
        self.assertTrue(all(flight.met(flight.judge(s)) for s in EXIT_SEEDS))


if __name__ == "__main__":
    unittest.main()
