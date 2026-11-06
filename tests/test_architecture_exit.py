#!/usr/bin/env python3
"""Tests for Phase 13's exit harness: it passes a real seed, and fails when an arm is not what it claims.

    python -m unittest discover -s tests -p test_architecture_exit.py

WHY THESE EXIST
---------------
An exit check that cannot fail proves nothing. One seed's flights are flown
once; the checks must pass on them, and must each fail when a flight is
swapped for another arm's (D flown as B, C's link-input twin flown as A), when
a mechanism switched off is in fact on (a guardian on the no-guardian arm), or
when a flight is labelled as a configuration it is not.
"""

import dataclasses
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.coordination.keepout import KeepOutConfig  # noqa: E402
from agentic_uav.experiments import architecture_exit as AX  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.architecture import load_architecture  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402

SC = load_scenario("search_relay_001")
PHASE12 = os.path.join(ROOT, "phases", "phase-12-llm-agent-policy", "results", "llm-exit-20261105-150453-exit.jsonl")


class ExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = {"alloc": load_allocation(), "health": load_recovery(), "limits": load_guardian(),
                   "keep_out": KeepOutConfig(5.0, 10.0, 3.0)}
        cls.ctx["phase9"] = fly_recovery_on_mock(dataclasses.replace(SC, random_seed=1), cls.ctx["alloc"],
                                                 cls.ctx["health"], "no stop")
        with open(PHASE12, encoding="utf-8") as h:
            p12 = {(r["seed"], r["flight"]): r for r in map(json.loads, h) if r["kind"] == "flight"}
        cls.flights = AX.seed_flights(SC, 1, cls.ctx, twice=False, phase12=p12)

    def test_a_real_seed_passes_every_check(self):
        c = AX.exit_checks(self.flights, SC, self.ctx)
        self.assertTrue(c["all"], {k: v["problems"] for k, v in c.items() if k != "all"})
        self.assertIn((AX.D70, "no stop"), self.flights)
        self.assertEqual(len(self.flights), 13 * 2 - 1 + 2)

    def test_d_flown_as_b_is_caught(self):
        b = self.flights[("B", "Drone1 stopped")]
        c = AX.exit_checks(
            {**self.flights, ("D", "Drone1 stopped"): [dataclasses.replace(b[0], architecture=load_architecture("D"))]},
            SC, self.ctx)
        self.assertFalse(c["arms_as_claimed"]["ok"])

    def test_a_flight_under_the_wrong_name_is_caught(self):
        c = AX.exit_checks({**self.flights, ("A", "no stop"): self.flights[("C", "no stop")]}, SC, self.ctx)
        self.assertFalse(c["by_configuration"]["ok"])

    def test_a_guardian_on_the_no_guardian_arm_is_caught(self):
        c = AX.exit_checks({**self.flights, ("C-no-guardian", "no stop"): self.flights[("C", "no stop")]},
                           SC, self.ctx)
        self.assertFalse(c["ablations_off"]["ok"])

    def test_link_inputs_off_is_caught(self):
        c = AX.exit_checks({**self.flights, ("C-link-inputs", "no stop"): [dataclasses.replace(
            self.flights[("C", "no stop")][0], architecture=load_architecture("C-link-inputs"))]}, SC, self.ctx)
        self.assertFalse(c["ablations_off"]["ok"])

    def test_a_different_second_flight_is_caught(self):
        c = AX.exit_checks({**self.flights, ("C", "no stop"): [self.flights[("C", "no stop")][0], dataclasses.replace(
            self.flights[("D-no-roles", "no stop")][0], architecture=load_architecture("C"))]}, SC, self.ctx)
        self.assertFalse(c["deterministic"]["ok"])

    def test_findings_summarise_each_arm(self):
        rows = [{"findings": AX.findings(self.flights)}]
        s = AX.by_arm(rows)
        self.assertEqual(s["B / Drone1 stopped"]["met"], 0)
        self.assertEqual(s["C / no stop"]["met"], 1)
        self.assertEqual(s["E / no stop"]["of"], 1)


if __name__ == "__main__":
    unittest.main()
