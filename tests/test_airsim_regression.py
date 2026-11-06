#!/usr/bin/env python3
"""Tests for the AirSim regression set's own judging (AUV-15, 16.3) -- the flights themselves are flown by hand.

    python -m unittest discover -s tests -p test_airsim_regression.py

WHY THESE EXIST
---------------
A live check is only as good as the rule that reads its record. These hold the
five checks to AUV-15's list and the `reassign` check to the three things it
is for -- the stop detected, the task taken in flight, the keep-out kept --
and not to the whole mission, which Phase 9's live flights did not meet.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import airsim_regression as R  # noqa: E402


class RegressionTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def record(self, checks):
        path = os.path.join(self.dir, "recovery-live-x.jsonl")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(json.dumps({"kind": "header", "checks": {k: {"ok": v} for k, v in checks.items()}}) + "\n")
        return path

    def test_the_five_checks_auv_15_names(self):
        self.assertEqual([c.name for c in R.CHECKS],
                         ["single-waypoint", "pair-apart", "four-search", "reassign", "return-home"])
        for c in R.CHECKS:
            self.assertEqual(c.live[:2], ("--sim", "airsim"), c.name)
            self.assertNotIn("airsim", c.mock, c.name)                      # the dry run never needs the simulator
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "scripts", c.script)), c.script)
        self.assertIn("--keep-out", R.BY_NAME["reassign"].live)
        self.assertIn("--fault-once", R.BY_NAME["return-home"].live)

    def test_reassign_is_judged_on_what_it_is_for(self):
        check = R.BY_NAME["reassign"]
        good = self.record({"detected": True, "reassigned": True, "kept_out": True, "continued": False})
        self.assertTrue(R.verdict(check, 1, good, live=True)[0])            # the mission unmet does not fail it
        bad = self.record({"detected": True, "reassigned": False, "kept_out": True})
        ok, why = R.verdict(check, 0, bad, live=True)
        self.assertFalse(ok)
        self.assertIn("reassigned", why)
        self.assertFalse(R.verdict(check, 0, self.record({"detected": True}), live=True)[0])   # a check missing
        self.assertFalse(R.verdict(check, 0, None, live=True)[0])                              # no record

    def test_the_others_and_every_dry_run_go_by_the_scripts_exit_code(self):
        for name in ("single-waypoint", "pair-apart", "four-search", "return-home"):
            check = R.BY_NAME[name]
            self.assertTrue(R.verdict(check, 0, None, live=True)[0])
            self.assertFalse(R.verdict(check, 1, None, live=True)[0])
        self.assertFalse(R.verdict(R.BY_NAME["reassign"], 1, None, live=False)[0])

    def test_the_latest_record_is_the_one_read(self):
        old = self.record({"detected": True})
        os.utime(old, (1, 1))
        new = os.path.join(self.dir, "recovery-live-y.jsonl")
        with io.open(new, "w", encoding="utf-8") as h:
            h.write("{}\n")
        self.assertEqual(R.latest_record(self.dir, "*.jsonl"), new)


if __name__ == "__main__":
    unittest.main()
