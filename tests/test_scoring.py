#!/usr/bin/env python3
"""Tests for mission scoring.

    python -m unittest discover tests

Scoring decides what every result in this study means, so the rules are worth
pinning down: exact sequence match, no partial credit, extra steps counted
separately rather than forgiven.

Pure and fast -- no model, no simulator.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "baseline"))

from run_missions import score  # noqa: E402  (path set above)


class ScoreTests(unittest.TestCase):

    def test_exact_match_is_correct(self):
        correct, extra = score(["hover", "land"], ["hover", "land"])
        self.assertTrue(correct)
        self.assertEqual(extra, 0)

    def test_wrong_order_is_incorrect(self):
        # M07 exists because ordering is a real failure mode: "before flying
        # forward, hover" must produce hover first.
        correct, _ = score(["fly_straight", "hover"], ["hover", "fly_straight"])
        self.assertFalse(correct)

    def test_a_missing_step_is_incorrect(self):
        # The classic unconstrained-model failure: asked to hover then land, it
        # returns only the hover and the aircraft never comes down.
        correct, extra = score(["hover"], ["hover", "land"])
        self.assertFalse(correct)
        self.assertEqual(extra, 0)

    def test_invented_steps_are_counted(self):
        # M05's known failure shape: a two-action request answered with six.
        # Incorrect, and the surplus is quantified rather than just noted.
        correct, extra = score(
            ["fly_straight", "fly_to", "land", "fly_straight", "fly_to", "land"],
            ["fly_straight", "fly_straight"],
        )
        self.assertFalse(correct)
        self.assertEqual(extra, 4)

    def test_no_partial_credit(self):
        # Two of three steps right is not two thirds of a mission: the drone
        # ends up somewhere it should not be. Correctness stays binary.
        correct, _ = score(["set_altitude", "fly_straight"],
                           ["set_altitude", "fly_straight", "land"])
        self.assertFalse(correct)

    def test_a_rejected_plan_scores_as_empty(self):
        # run_one() passes [] when the plan failed validation, so an invalid
        # plan scores incorrect rather than being dropped from the series.
        correct, extra = score([], ["hover", "land"])
        self.assertFalse(correct)
        self.assertEqual(extra, 0)

    def test_an_unscoreable_mission_has_no_expectation(self):
        # M08 is ambiguous by design; its `expected` is empty. Any plan is
        # "incorrect" against nothing, which is why the runner never scores it.
        correct, extra = score(["set_altitude", "hover", "land"], [])
        self.assertFalse(correct)
        self.assertEqual(extra, 3)


if __name__ == "__main__":
    unittest.main()
