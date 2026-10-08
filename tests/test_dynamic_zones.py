"""GMB: no-fly zones that appear, expire and drift during a mission (Decisions 1-3 in
projects/akbas-lab/GMB_DYNAMIC_BOUNDARIES.md: scheduled change, read from the scenario,
steer out if already inside). Mock-only: nothing flies."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, SelfState
from fics_drone.agents.safety_guardian import (
    Command, FallbackAction, GuardianOutcome, SafetyGuardian, SafetyLimits,
)
from fics_drone.core.scenario import NoFlyZone, load_scenario
from fics_drone.evaluation.metrics import _score_no_fly
from fics_drone.telemetry.recorder import Sample

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


def _belief(position=(0.0, 0.0, 8.0), t=0.0):
    return Belief(self_state=SelfState(position=position, elapsed_s=t, battery_s=1000.0),
                  mission=MissionBelief(sector_id="A", search_queue=[]))


def _guardian(*zones):
    return SafetyGuardian(limits=SafetyLimits(restricted_zones=list(zones), geofence_half_extent_m=200.0))


def _fly(x, y, z=8.0):
    return Command(kind="fly", target=(x, y, z), speed_mps=5.0, timeout_s=30.0)


# a zone that switches on at t=60 s and off at t=120 s
def _scheduled():
    return NoFlyZone("Z", 20.0, 40.0, 20.0, 40.0, active_from_s=60.0, active_until_s=120.0)


class TestZoneGeometry(unittest.TestCase):
    def test_static_zone_is_unchanged_and_not_dynamic(self):
        z = NoFlyZone("S", 0, 10, 0, 10)
        self.assertFalse(z.is_dynamic)
        self.assertTrue(z.contains(5, 5))
        self.assertTrue(z.contains(5, 5, 9999.0))   # always active
        self.assertFalse(z.contains(50, 5, 0.0))

    def test_schedule(self):
        z = _scheduled()
        self.assertTrue(z.is_dynamic)
        self.assertFalse(z.contains(30, 30, 59.9))
        self.assertTrue(z.contains(30, 30, 60.0))
        self.assertTrue(z.contains(30, 30, 119.9))
        self.assertFalse(z.contains(30, 30, 120.0))

    def test_no_time_means_always_active_the_conservative_reading(self):
        self.assertTrue(_scheduled().contains(30, 30))

    def test_drift_starts_when_the_zone_activates(self):
        z = NoFlyZone("D", 0, 10, 0, 10, active_from_s=10.0, vx=2.0)
        self.assertEqual(z.bounds_at(10.0), (0, 10, 0, 10))
        self.assertEqual(z.bounds_at(15.0), (10, 20, 0, 10))
        self.assertTrue(z.contains(15, 5, 15.0))
        self.assertFalse(z.contains(5, 5, 15.0))   # the zone has moved off this point


class TestGuardianUsesMissionTime(unittest.TestCase):
    def test_waypoint_in_zone_is_legal_before_and_after_but_not_during(self):
        g = _guardian(_scheduled())
        for t, expect_ok in ((30.0, True), (90.0, False), (150.0, True)):
            ev = _guardian(_scheduled()).evaluate(_fly(30, 30), _belief(t=t))
            self.assertEqual(ev.outcome == GuardianOutcome.APPROVE, expect_ok, f"t={t}: {ev.reason}")
        self.assertIsNotNone(g)

    def test_rejection_names_the_zone(self):
        ev = _guardian(_scheduled()).evaluate(_fly(30, 30), _belief(t=90.0))
        self.assertEqual(ev.outcome, GuardianOutcome.REJECT_AND_REPLAN)
        self.assertIn("restricted_zones", ev.failed_checks)

    def test_landing_site_is_time_aware_too(self):
        land = Command(kind="land", target=(30.0, 30.0, 0.0), timeout_s=30.0, purpose="land")
        self.assertIn("landing_site", _guardian(_scheduled()).evaluate(land, _belief(t=90.0)).failed_checks)
        self.assertNotIn("landing_site", _guardian(_scheduled()).evaluate(land, _belief(t=30.0)).failed_checks)

    def test_preview_sees_the_same_zone_state_as_evaluate(self):
        g = _guardian(_scheduled())
        self.assertEqual([c.name for c in g.preview(_fly(30, 30), _belief(t=90.0))], ["restricted_zones"])
        self.assertEqual(g.preview(_fly(30, 30), _belief(t=30.0)), [])


class TestSteerOutWhenAlreadyInside(unittest.TestCase):
    def test_drone_inside_a_zone_that_just_activated_is_steered_out(self):
        belief = _belief(position=(30.0, 30.0, 8.0), t=70.0)   # zone Z is active, drone sits in it
        ev = _guardian(_scheduled()).evaluate(_fly(0, 0), belief)   # the policy's own proposal is ignored
        self.assertEqual(ev.outcome, GuardianOutcome.EXECUTE_SAFE_FALLBACK)
        self.assertEqual(ev.fallback, FallbackAction.EXIT_ZONE)
        tx, ty, tz = ev.command.target
        self.assertFalse(_scheduled().contains(tx, ty, 70.0), "exit point must be outside the zone")
        self.assertEqual(tz, 8.0)   # altitude held

    def test_exit_goes_to_the_nearest_edge(self):
        belief = _belief(position=(22.0, 30.0, 8.0), t=70.0)   # 2 m from the x_min edge
        ev = _guardian(_scheduled()).evaluate(_fly(0, 0), belief)
        self.assertEqual(ev.command.target[:2], (17.0, 30.0))   # x_min - 3 m margin

    def test_not_inside_means_normal_evaluation(self):
        ev = _guardian(_scheduled()).evaluate(_fly(0, 0), _belief(position=(5.0, 5.0, 8.0), t=70.0))
        self.assertEqual(ev.outcome, GuardianOutcome.APPROVE)

    def test_static_zones_never_trigger_the_exit_path(self):
        static = NoFlyZone("S", 0, 100, 0, 100)
        ev = _guardian(static).evaluate(_fly(-50, -50), _belief(position=(10.0, 10.0, 8.0), t=70.0))
        self.assertNotEqual(ev.fallback, FallbackAction.EXIT_ZONE)

    def test_a_drifting_zone_that_runs_over_a_drone_triggers_the_exit(self):
        z = NoFlyZone("D", 0, 10, 0, 10, vx=2.0)           # active from t=0, moving +x
        g = _guardian(z)
        belief = _belief(position=(15.0, 5.0, 8.0), t=0.0)  # clear at t=0
        self.assertEqual(g.evaluate(_fly(15, 5), belief).outcome, GuardianOutcome.APPROVE)
        g.command_completed()
        belief = _belief(position=(15.0, 5.0, 8.0), t=7.5)  # zone now spans x in [15, 25]
        self.assertEqual(g.evaluate(_fly(15, 5), belief).fallback, FallbackAction.EXIT_ZONE)

    def test_no_clear_exit_falls_back_to_the_escalated_return_home(self):
        # a zone covering the whole geofence leaves nowhere to exit to
        huge = NoFlyZone("H", -500, 500, -500, 500, active_from_s=10.0)
        g = SafetyGuardian(limits=SafetyLimits(restricted_zones=[huge], geofence_half_extent_m=50.0))
        ev = g.evaluate(_fly(0, 0), _belief(position=(30.0, 30.0, 8.0), t=20.0))
        self.assertEqual(ev.outcome, GuardianOutcome.EXECUTE_SAFE_FALLBACK)
        self.assertEqual(ev.fallback, FallbackAction.RETURN_HOME)


class TestScorerAndLoading(unittest.TestCase):
    def test_scorer_counts_entry_only_while_the_zone_is_active(self):
        scenario = load_scenario(SCENARIO_PATH)
        scenario.no_fly_zones = [_scheduled()]
        log = {"Drone1": [Sample(t=30.0, position=(30.0, 30.0, 8.0)),    # before: fine
                          Sample(t=90.0, position=(30.0, 30.0, 8.0)),    # during: violation
                          Sample(t=130.0, position=(30.0, 30.0, 8.0))]}  # after: fine
        violations, passed = _score_no_fly(scenario, log)
        self.assertFalse(passed)
        self.assertEqual(violations, ["Drone1 entered Z at t=90.0s"])

    def test_an_old_scenario_file_without_the_new_fields_still_loads_static(self):
        zones = load_scenario(SCENARIO_PATH).no_fly_zones
        self.assertTrue(zones)
        self.assertFalse(any(z.is_dynamic for z in zones))

    def test_new_fields_load_from_json(self):
        with open(SCENARIO_PATH) as f:
            data = json.load(f)
        data["no_fly_zones"].append({"id": "DZ", "x_min": 0, "x_max": 5, "y_min": 0, "y_max": 5,
                                     "active_from_s": 60, "active_until_s": 120, "vx": 1.0})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            dz = [z for z in load_scenario(path).no_fly_zones if z.id == "DZ"][0]
            self.assertEqual((dz.active_from_s, dz.active_until_s, dz.vx), (60, 120, 1.0))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
