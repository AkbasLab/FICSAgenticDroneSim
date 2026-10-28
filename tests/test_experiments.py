"""Experiment layer tests: config validation, zone profiles, the agent-clock
shift that scoring depends on, and the conditions() import that
run_dynamic_zone_llm.py relies on. No simulation runs here."""

import os
import sys
import unittest
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.evaluation.metrics import _score_no_fly
from fics_drone.experiments.event_log import EventType, derive_events
from fics_drone.experiments.experiment_config import (
    ZONE_PROFILES, ExperimentConfig, apply_zones)
from fics_drone.experiments.experiment_runner import _exposure_s, _to_agent_clock
from scripts.run_dynamic_zone_study import DEFAULT_SCENARIO, conditions


@dataclass
class _S:
    t: float
    position: tuple


def _base():
    return load_scenario(DEFAULT_SCENARIO)


class ConfigTests(unittest.TestCase):
    def test_defaults_validate(self):
        ExperimentConfig(experiment_id="x").validate()

    def test_rejects_bad_values(self):
        for bad in ({"zone_profile": "nope"}, {"zone_monitor": "nope"},
                    {"repeats": 0}, {"policy": "nope"},
                    {"comms_estimates": True, "policy": "scripted"},
                    {"kill_vehicle": "Drone1", "zone_monitor": "tick"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                ExperimentConfig(experiment_id="x", **bad).validate()


class ZoneProfileTests(unittest.TestCase):
    def test_conditions_keeps_its_keyword_signature(self):
        # run_dynamic_zone_llm.py calls it with these keywords
        got = conditions(_base(), appear_s=5.0, expire_s=12.0, drift_s=3.0)
        self.assertEqual(set(got), set(ZONE_PROFILES))

    def test_conditions_matches_apply_zones(self):
        base = _base()
        want = apply_zones(base, "appear", 5.0, 12.0, 3.0).no_fly_zones
        self.assertEqual(conditions(base)["appear"].no_fly_zones, want)
        self.assertTrue(any(z.active_from_s == 5.0 for z in want))


class AgentClockTests(unittest.TestCase):
    """Zone schedules run on the agents clock; the recorder clock starts
    about 3 s earlier on the allocation path. Zone is live 5 s to 12 s."""

    OFF = {"Drone2": 3.01}

    def setUp(self):
        self.scenario = apply_zones(_base(), "appear_expire", 5.0, 12.0, 3.0)

    def _counts(self, t):
        log = {"Drone2": [_S(t, (32.0, 32.0, -10.0))]}
        raw = len(_score_no_fly(self.scenario, log)[0])
        fixed = _to_agent_clock(log, self.OFF)
        return raw, len(_score_no_fly(self.scenario, fixed)[0])

    def test_before_zone_appears_is_not_a_violation(self):
        self.assertEqual(self._counts(6.0), (1, 0))

    def test_inside_window_is_a_violation_either_way(self):
        self.assertEqual(self._counts(9.0), (1, 1))

    def test_after_expiry_is_still_a_violation_on_agent_clock(self):
        self.assertEqual(self._counts(13.0), (0, 1))

    def test_zero_offset_changes_nothing(self):
        log = {"Drone2": [_S(6.0, (32.0, 32.0, -10.0))]}
        self.assertEqual(_to_agent_clock(log, {}), log)

    def test_positions_kept_and_input_not_mutated(self):
        log = {"Drone2": [_S(6.0, (1.0, 2.0, 3.0))]}
        out = _to_agent_clock(log, self.OFF)
        self.assertEqual(out["Drone2"][0].position, (1.0, 2.0, 3.0))
        self.assertAlmostEqual(out["Drone2"][0].t, 2.99)
        self.assertEqual(log["Drone2"][0].t, 6.0)


class ExposureAndEventTests(unittest.TestCase):
    def setUp(self):
        self.scenario = apply_zones(_base(), "appear_expire", 5.0, 12.0, 3.0)
        self.log = {"Drone2": [_S(6.0, (32.0, 32.0, -10.0))]}
        self.fixed = _to_agent_clock(self.log, {"Drone2": 3.01})

    def test_exposure_follows_the_clock_it_is_given(self):
        self.assertGreater(_exposure_s(self.scenario, self.log), 0)
        self.assertEqual(_exposure_s(self.scenario, self.fixed), 0)

    def test_zone_entered_events_follow_the_log_they_are_given(self):
        raw = derive_events({}, {}, self.scenario, self.log, 0)
        self.assertEqual([e.type for e in raw], [EventType.ZONE_ENTERED])
        self.assertEqual(derive_events({}, {}, self.scenario, self.fixed, 0), [])


if __name__ == "__main__":
    unittest.main()
