"""GMB: the hold that confirms a sighting tolerates ordinary hover jitter (live drones wander 1 to 2 m while hovering), but
still fails a hold that really drifts away. Mock-only."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents import persistent_agent
from fics_drone.control import skills
from fics_drone.control.skills import SkillStatus, hold_position


class _JitterAdapter:
    """Hovers, but its reported position sits `offset` metres from where the hold started measuring."""

    def __init__(self, offset):
        self.offset = offset
        self.calls = 0

    def start_hover(self):
        pass

    def get_position(self):
        self.calls += 1
        return (0.0, 0.0, 8.0) if self.calls == 1 else (self.offset, 0.0, 8.0)


class ReportHoldTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(skills, SKILL_SETTLE_SECS=0.0, SKILL_POLL_INTERVAL_S=0.01)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_jitter_fails_the_default_hold_but_not_the_report_hold(self):
        default = hold_position(_JitterAdapter(1.8), 0.05)
        self.assertEqual(default.status, SkillStatus.FAILED)
        report = hold_position(_JitterAdapter(1.8), 0.05, drift_tolerance=persistent_agent.AGENT_REPORT_DRIFT_M)
        self.assertEqual(report.status, SkillStatus.SUCCESS)

    def test_a_real_drift_still_fails_the_report_hold(self):
        report = hold_position(_JitterAdapter(6.0), 0.05, drift_tolerance=persistent_agent.AGENT_REPORT_DRIFT_M)
        self.assertEqual(report.status, SkillStatus.FAILED)

    def test_the_agent_passes_the_report_tolerance_at_both_hold_sites(self):
        src = open(persistent_agent.__file__).read()
        self.assertEqual(src.count("drift_tolerance=AGENT_REPORT_DRIFT_M"), 2)
        self.assertEqual(src.count("hold_position(self.adapter, AGENT_REPORT_HOLD_S"), 2)


if __name__ == "__main__":
    unittest.main()
