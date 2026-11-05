#!/usr/bin/env python3
"""Tests for the keep-out check: Phase 9's stops flown with the keep-out, and each check shown able to fail.

    python -m unittest discover -s tests -p test_keepout_check.py

WHY THESE EXIST
---------------
The keep-out is the fix for a live collision; the check is what says it
works. These fly one seed and then plant each failure the check must see: a
survivor's path through the keep-out, an intervention by the guardian, a no-stop
flight that changed -- and show the check says so. And they show the fix is
needed at all: without it, on the same seed, the survivor flies straight
through the stopped drone's column.
"""

import copy
import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.coordination.keepout import parse_keepout  # noqa: E402
from agentic_uav.experiments import keepout_check as C  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.simulator.trajectory import Knot, Trajectory  # noqa: E402

KO = parse_keepout(load_toml(os.path.join(ROOT, "configs", "keepout", "default.toml")))
SC, TWIN = load_scenario("search_relay_001"), load_scenario(C.TWIN_SCENARIO)


class KeepOutCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flights = C.keepout_flights(SC, TWIN, 17, load_allocation(), load_recovery(), load_guardian(), KO)
        cls.checks = C.keepout_checks(cls.flights, KO)

    def test_all_hold_on_seed_17(self):
        self.assertTrue(self.checks["all"], {k: v["problems"] for k, v in self.checks.items() if k != "all"})

    def test_the_findings_measure_every_survivor_of_every_stop(self):
        f = C.keepout_findings(self.flights, KO)
        self.assertEqual(sorted(f), sorted([f"four, {v.id} stopped" for v in SC.vehicles] + ["twin, Drone2 stopped"]))
        self.assertEqual(len(f["four, Drone1 stopped"]["passes"]), 3)
        self.assertTrue(all(p["closest_to_heard_m"] >= KO.half_width_m for x in f.values() for p in x["passes"]))

    def test_without_the_fix_the_twin_flies_through_the_column(self):
        tw = dataclasses.replace(TWIN, random_seed=17)
        run = fly_recovery_on_mock(tw, load_allocation(), load_recovery(), "x", {"Drone2": 17.0})
        (p,) = C.passes(run, "Drone2", KO)
        self.assertTrue(p["entered"])
        self.assertLess(p["closest_to_true_m"], 1.0)

    def test_a_path_into_the_keep_out_is_caught(self):
        run = self.flights["pair"]["Drone2 stopped"]
        x, y, _, at = C.last_heard(run, "Drone2")
        trajs = dict(run.team.trajectories)
        knots = list(trajs["Drone1"].knots)
        knots.append(Knot(knots[-1].t + 30.0, x, y, 12.0, True))
        trajs["Drone1"] = Trajectory("Drone1", knots)
        bad = dataclasses.replace(run, team=dataclasses.replace(run.team, trajectories=trajs))
        flights = dict(self.flights, pair=dict(self.flights["pair"], **{"Drone2 stopped": bad}))
        checks = C.keepout_checks(flights, KO)
        self.assertFalse(checks["kept_out"]["ok"])
        self.assertIn("Drone1 entered the keep-out round Drone2", checks["kept_out"]["problems"][0])

    def test_an_intervention_is_caught(self):
        run = self.flights["four"]["Drone3 stopped"]
        guardians = copy.deepcopy(run.guardians)
        guardians["Drone4"]["log"].append({"drone": "Drone4", "outcome": "reject_and_replan", "at": 1.0,
                                           "checks": ["keep_out"], "reasons": ["x"]})
        flights = dict(self.flights, four=dict(self.flights["four"],
                                               **{"Drone3 stopped": dataclasses.replace(run, guardians=guardians)}))
        self.assertFalse(C.keepout_checks(flights, KO)["no_interventions"]["ok"])

    def test_a_changed_no_stop_flight_is_caught(self):
        run = self.flights["four"]["no stop"]
        policies = copy.deepcopy(run.policies)
        policies["Drone1"]["x"] = 1
        flights = dict(self.flights, four=dict(self.flights["four"],
                                               **{"no stop": dataclasses.replace(run, policies=policies)}))
        self.assertFalse(C.keepout_checks(flights, KO)["no_stop_unchanged"]["ok"])

    def test_last_heard_is_the_latest_delivered_report(self):
        run = self.flights["four"]["Drone1 stopped"]
        x, y, alt, at = C.last_heard(run, "Drone1")
        self.assertLessEqual(at - run.team.start, 60.0 + 1e-6)
        self.assertGreater(alt, 3.0)
        self.assertIsNone(C.last_heard(run, "Drone9"))


if __name__ == "__main__":
    unittest.main()
