#!/usr/bin/env python3
"""Tests for docs/CONDITIONS.md's calibration rule as implemented (Phase 17, AUV-16 17.3).

    python -m unittest discover -s tests -p test_calibration.py

WHY THESE EXIST
---------------
The rule was pre-registered before the sweep; its code must be shown right
before the sweep too, or a mistake could be "found" after seeing which levels
it picks. Each of the four conditions is driven here, on hand-built seeds, to
both sides of its line.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments import calibration as C  # noqa: E402


def runs(arch, level, failure, success, times, p3=None, team=4):
    out = []
    for i, t in enumerate(times):
        v = {"P1.success": i < success, "P2.completion_s": t}
        if p3 is not None:
            v["P3.continuity_retention"] = p3
        out.append({"run_id": f"{team}-{arch}-{level}-{failure}-{i}", "values": v,
                    "config": {"team_size": team, "network": level, "failure": failure, "architecture": arch}})
    return out


def batch(level_runs, nominal_t=100.0):
    rows = []
    for arch in ("A", "C"):
        for f in ("none", "stop"):
            rows += runs(arch, "nominal", f, 10, [nominal_t] * 10, p3=None)
    return rows + level_runs


def delivery(rows, got=90, lost=10):
    return {r["run_id"]: (got, lost) for r in rows}


class RuleTests(unittest.TestCase):

    def verdict(self, rows, **kw):
        return C.judge(rows, delivery(rows, **kw))["levels"]["4"]["severe"]

    def level(self, a_success=10, c_success=10, a_t=100.0, c_t=100.0, a_p3=1.0, c_p3=1.0):
        out = []
        for f in ("none", "stop"):
            out += runs("A", "severe", f, a_success, [a_t] * 10, a_p3)
            out += runs("C", "severe", f, c_success, [c_t] * 10, c_p3)
        return out

    def test_a_level_that_changes_nothing_is_trivially_easy(self):
        v = self.verdict(batch(self.level()))
        self.assertFalse(v["checks"]["not_trivially_easy"])
        self.assertFalse(v["meaningful"])

    def test_slower_by_ten_percent_is_not_easy(self):
        v = self.verdict(batch(self.level(a_t=110.0, c_t=100.0)))
        self.assertTrue(v["checks"]["not_trivially_easy"])
        v = self.verdict(batch(self.level(a_t=109.0, c_t=109.0)))
        self.assertFalse(v["checks"]["not_trivially_easy"])

    def test_everyone_failing_is_trivially_hard(self):
        v = self.verdict(batch(self.level(a_success=0, c_success=0)))
        self.assertFalse(v["checks"]["not_trivially_hard"])
        self.assertTrue(self.verdict(batch(self.level(a_success=1, c_success=0)))["checks"]["not_trivially_hard"])

    def test_distinguishable_by_success_completion_or_retention(self):
        self.assertTrue(self.verdict(batch(self.level(a_success=10, c_success=8)))["checks"]["distinguishable"])
        self.assertFalse(self.verdict(batch(self.level(a_success=10, c_success=9)))["checks"]["distinguishable"])
        self.assertTrue(self.verdict(batch(self.level(a_t=120.0, c_t=100.0)))["checks"]["distinguishable"])
        self.assertTrue(self.verdict(batch(self.level(a_p3=0.90, c_p3=0.96)))["checks"]["distinguishable"])
        self.assertFalse(self.verdict(batch(self.level(a_p3=0.93, c_p3=0.96)))["checks"]["distinguishable"])

    def test_a_completion_gap_inside_the_seed_spread_is_not_distinguishable(self):
        rows = []
        for f in ("none", "stop"):
            rows += runs("A", "severe", f, 10, [100, 105, 110, 115, 120, 125, 130, 135, 140, 145])
            rows += runs("C", "severe", f, 10, [115, 120, 125, 130, 135, 140, 145, 150, 155, 160])
        v = self.verdict(batch(rows))
        self.assertFalse(v["checks"]["distinguishable"])      # medians 122.5 vs 137.5: 12 %, but ranges overlap

    def test_communication_must_still_be_useful(self):
        rows = batch(self.level(a_success=10, c_success=5))
        self.assertTrue(self.verdict(rows, got=50, lost=50)["checks"]["communication_useful"])
        self.assertFalse(self.verdict(rows, got=49, lost=51)["checks"]["communication_useful"])

    def test_the_pilot_level_prefers_severe_then_moderate(self):
        good = self.level(a_success=10, c_success=5)
        moderate = [dict(r, run_id=r["run_id"] + "m", config=dict(r["config"], network="moderate")) for r in good]
        v = C.judge(batch(good + moderate), delivery(batch(good + moderate)))
        self.assertEqual(v["pilot"]["4"], "severe")
        self.assertEqual(v["phase18"]["4"], ["nominal", "moderate", "severe"])
        easy = self.level()
        v = C.judge(batch(easy + moderate), delivery(batch(easy + moderate)))
        self.assertEqual(v["pilot"]["4"], "moderate")
        v = C.judge(batch(easy), delivery(batch(easy)))
        self.assertIsNone(v["pilot"]["4"])


if __name__ == "__main__":
    unittest.main()
