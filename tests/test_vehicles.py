#!/usr/bin/env python3
"""Tests for the rule that no flight shares the scene with another flight's drones.

    python -m unittest discover tests

WHY THESE EXIST
---------------
A drone spawned at runtime stays in the simulator until it restarts.
`client.reset()` puts it back at its spawn pose rather than removing it, and
AirSim 1.8.1's Python API has no call that removes a vehicle. Spawn poses run
along +X at SPACING metres, which is the direction every forward mission
flies -- so a leftover Drone2 is parked 4 m in front of Drone1.

On 2026-10-19 M01-M09 were flown after M10 without a restart. 17 of 27 runs
flew into the leftover drones, flights stretched to 61-201 s, aircraft were
left pinned or hanging up to 11 m above ground, and every contact was recorded
as an ordinary obstacle. Nothing warned.

These pin the rule both guards enforce: the per-flight check in
`ensure_vehicles`, and the whole-series check the runner makes before the first
takeoff. Pure -- no simulator.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "baseline"))

import open_loop_agent as agent  # noqa: E402  (path set above)
from run_missions import series_conflicts  # noqa: E402


def mission(mission_id, drones=1):
    return {"id": mission_id, "drones": drones}


SINGLES = [mission(f"M0{i}") for i in range(1, 9)]
M09 = mission("M09", 2)
M10 = mission("M10", 4)


class ForeignVehicleTests(unittest.TestCase):

    def test_exactly_the_flight_roster_is_clean(self):
        self.assertEqual(agent.foreign_vehicles(["Drone1"], ["Drone1"]), [])

    def test_drones_still_to_be_spawned_are_not_foreign(self):
        # Going up in count is the normal case: M09 arrives with only Drone1
        # in the scene and spawns Drone2 itself.
        self.assertEqual(agent.foreign_vehicles(["Drone1"], ["Drone1", "Drone2"]), [])

    def test_leftovers_from_a_larger_mission_are_foreign(self):
        # The 2026-10-19 case: M10's drones, then a one-drone mission.
        present = ["Drone1", "Drone2", "Drone3", "Drone4"]
        self.assertEqual(agent.foreign_vehicles(present, ["Drone1"]),
                         ["Drone2", "Drone3", "Drone4"])

    def test_result_is_sorted(self):
        # Stable output, so error messages and logs compare cleanly.
        self.assertEqual(agent.foreign_vehicles(["Drone4", "Drone2", "Drone1"], ["Drone1"]),
                         ["Drone2", "Drone4"])

    def test_a_declared_fleet_larger_than_the_mission_is_foreign_too(self):
        # A settings.json declaring four drones leaves them parked exactly where
        # runtime spawning would. Declared or spawned, they are in the way.
        self.assertEqual(agent.foreign_vehicles(["Drone1", "Drone2"], ["Drone1"]),
                         ["Drone2"])


class SeriesConflictTests(unittest.TestCase):

    def test_the_protocol_order_is_clean_on_a_fresh_simulator(self):
        # M01-M08, then M09, then M10, starting from the one declared drone.
        self.assertEqual(series_conflicts(["Drone1"], SINGLES + [M09, M10]), [])

    def test_singles_after_m10_in_the_same_scene_are_refused(self):
        # What block 2 actually flew: a fresh invocation, but M10's drones
        # still in the scene from the previous one.
        conflicts = series_conflicts(["Drone1", "Drone2", "Drone3", "Drone4"], SINGLES)
        self.assertEqual(len(conflicts), 8)
        self.assertEqual(conflicts[0], ("M01", ["Drone2", "Drone3", "Drone4"]))

    def test_a_bad_order_inside_one_series_is_caught_before_takeoff(self):
        # M10 first leaves three drones behind for M01.
        conflicts = series_conflicts(["Drone1"], [M10, mission("M01")])
        self.assertEqual(conflicts, [("M01", ["Drone2", "Drone3", "Drone4"])])

    def test_m09_after_m10_meets_the_two_extra_drones(self):
        conflicts = series_conflicts(["Drone1"], [M10, M09])
        self.assertEqual(conflicts, [("M09", ["Drone3", "Drone4"])])

    def test_repeating_the_largest_mission_is_fine(self):
        # M10 after M10 -- the rate measurements -- reuses the same four drones.
        self.assertEqual(series_conflicts(["Drone1"], [M10, M10]), [])
        self.assertEqual(
            series_conflicts(["Drone1", "Drone2", "Drone3", "Drone4"], [M10]), [])

    def test_m10_after_m09_after_singles_resumes_cleanly(self):
        # Resuming a session where M09 was the last thing flown.
        self.assertEqual(series_conflicts(["Drone1", "Drone2"], [M10]), [])

    def test_missions_without_a_drone_count_mean_one(self):
        self.assertEqual(series_conflicts(["Drone1", "Drone2"], [{"id": "M01"}]),
                         [("M01", ["Drone2"])])


if __name__ == "__main__":
    unittest.main()
