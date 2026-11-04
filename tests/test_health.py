#!/usr/bin/env python3
"""Tests for agentic_uav.coordination.health: teammate-failure detection (AUV-09, 9.2).

    python -m unittest discover tests

WHY THESE EXIST
---------------
A team that treats every silence as a death thrashes its tasks; one that
treats every death as a silence strands them. The ladder -- HEALTHY,
SUSPECTED, UNREACHABLE, FAILED, RECOVERED -- is built only from how long a
drone has heard nothing from a teammate, at thresholds in a manifest. These
pin it on scripted silences: one missed heartbeat changes nothing; each rung
at its threshold and not before; rungs crossed in order even when a tick
skips one; a teammate heard again recovers, and is healthy after a steady
while; the manifest refuses a typo; the belief shows the ladder only for a
drone that has one, and the knowledge log knows where it came from.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.coordination.health import FailureDetector, Health, HealthConfig  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.knowledge import source_of  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery, parse_recovery  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
MATES = ["Drone2", "Drone3", "Drone4"]


def links(**last):
    return {m: {"last_heard": t} for m, t in last.items()}


class Ladder:
    """A detector fed a timeline: Drone2's last-heard times as given, the others heard every tick."""

    def __init__(self, config=HealthConfig()):
        self.d = FailureDetector("Drone1", ["Drone1"] + MATES, config, start=0.0)

    def at(self, now, drone2_last):
        return self.d.update(links(Drone2=drone2_last, Drone3=now, Drone4=now), now)


class LadderTests(unittest.TestCase):

    def test_one_missed_heartbeat_changes_nothing(self):
        lad = Ladder()
        for now in [x * 0.5 for x in range(0, 6)]:                         # heard every second, to 2.5 s
            lad.at(now, float(int(now)))
        self.assertEqual(lad.at(2.5, 1.0), [])                              # 1.5 s since: one heartbeat missed
        self.assertEqual(lad.d.state("Drone2"), Health.HEALTHY)

    def test_each_rung_at_its_threshold_and_not_before(self):
        lad = Ladder()
        seen = []
        t = 0.0
        while t <= 35.0:
            for tr in lad.at(t, 5.0 if t >= 5.0 else t):                  # silent from 5 s
                seen.append((tr.at, tr.before.value, tr.after.value, tr.silence_s))
            t = round(t + 0.5, 3)
        self.assertEqual(seen, [(8.0, "healthy", "suspected", 3.0), (15.0, "suspected", "unreachable", 10.0),
                                (35.0, "unreachable", "failed", 30.0)])
        self.assertEqual(lad.d.state("Drone2"), Health.FAILED)
        self.assertEqual(lad.d.in_state(Health.FAILED), ("Drone2",))
        self.assertEqual(lad.d.state("Drone3"), Health.HEALTHY)            # the others never suspected

    def test_a_skipped_tick_still_crosses_every_rung_in_order(self):
        lad = Ladder()
        lad.at(0.0, 0.0)
        out = lad.at(40.0, 0.0)                                             # nothing between: 40 s of silence
        self.assertEqual([(t.before.value, t.after.value) for t in out],
                         [("healthy", "suspected"), ("suspected", "unreachable"), ("unreachable", "failed")])
        self.assertTrue(all(t.at == 40.0 for t in out))

    def test_heard_again_it_recovers_then_is_healthy(self):
        lad = Ladder()
        lad.at(0.0, 0.0)
        lad.at(12.0, 0.0)                                                   # unreachable
        out = lad.at(12.5, 12.4)                                            # heard at 12.4
        self.assertEqual([(t.before.value, t.after.value, t.at) for t in out], [("unreachable", "recovered", 12.4)])
        self.assertEqual(lad.at(14.0, 14.0), [])                            # recovered, not yet steady
        out = lad.at(15.5, 15.0)
        self.assertEqual([(t.before.value, t.after.value) for t in out], [("recovered", "healthy")])

    def test_a_recovered_teammate_silent_again_climbs_from_the_bottom(self):
        lad = Ladder()
        lad.at(0.0, 0.0)
        lad.at(5.0, 0.0)                                                    # suspected
        lad.at(5.5, 5.5)                                                    # recovered
        out = lad.at(9.0, 5.5)                                              # 3.5 s silent again
        self.assertEqual([(t.before.value, t.after.value) for t in out], [("recovered", "suspected")])

    def test_never_heard_at_all_climbs_from_the_start(self):
        d = FailureDetector("Drone1", ["Drone1", "Drone2"], HealthConfig(), start=100.0)
        self.assertEqual(d.update({}, 102.9), [])
        self.assertEqual([t.after.value for t in d.update({}, 103.0)], ["suspected"])

    def test_a_teammate_that_finished_is_not_watched(self):
        d = FailureDetector("Drone1", ["Drone1"] + MATES, HealthConfig(), start=0.0)
        d.update(links(Drone2=10.0, Drone3=10.0, Drone4=10.0), 10.0, finished=["Drone2"])
        self.assertEqual(d.update(links(Drone2=10.0, Drone3=60.0, Drone4=60.0), 60.0, finished=["Drone2"]), [])
        self.assertEqual(d.states()["Drone2"], "finished")
        self.assertEqual(d.finished, {"Drone2": 10.0})
        self.assertEqual(d.in_state(Health.HEALTHY), ("Drone3", "Drone4"))
        self.assertEqual(d.as_json()["finished"], {"Drone2": 10.0})

    def test_the_owner_is_not_on_its_own_ladder(self):
        d = FailureDetector("Drone1", ["Drone1"] + MATES, HealthConfig(), start=0.0)
        self.assertEqual(sorted(d.states()), MATES)

    def test_its_json(self):
        lad = Ladder()
        lad.at(0.0, 0.0)
        lad.at(4.0, 0.0)
        row = lad.d.as_json()
        self.assertEqual(row["config"], {"suspected_s": 3.0, "unreachable_s": 10.0, "failed_s": 30.0})
        self.assertEqual(row["log"], [{"at": 4.0, "teammate": "Drone2", "before": "healthy", "after": "suspected",
                                       "silence_s": 4.0}])


class ConfigTests(unittest.TestCase):

    def test_the_default_manifest(self):
        self.assertEqual(load_recovery(), HealthConfig(3.0, 10.0, 30.0))

    def test_thresholds_must_rise(self):
        for bad in ((0.0, 10.0, 30.0), (3.0, 3.0, 30.0), (3.0, 10.0, 10.0), (10.0, 3.0, 30.0), (3.0, 10.0, float("inf"))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                HealthConfig(*bad)

    def test_a_typo_is_refused_not_defaulted(self):
        good = {"health": {"suspected_s": 3, "unreachable_s": 10, "failed_s": 30}}
        self.assertEqual(parse_recovery(good), load_recovery())
        for bad in ({**good, "extra": {}}, {}, {"health": {"suspected_s": 3, "unreachable_s": 10}},
                    {"health": {**good["health"], "failed": 30}}, {"health": {**good["health"], "failed_s": "30"}},
                    {"health": {**good["health"], "suspected_s": True}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_recovery(bad)


class BeliefTests(unittest.TestCase):

    def belief(self):
        return BeliefState.start(TEAM.brief(), "Drone1", Observation(0.0, 0, 0, 0, False, 100.0, (), True, None, 0, None))

    def test_only_a_drone_with_a_detector_shows_the_ladder(self):
        b = self.belief()
        self.assertNotIn("teammate_health", b.snapshot()["communication"])     # every earlier snapshot as it was
        b.teammate_health = {"Drone3": "suspected", "Drone2": "healthy"}
        self.assertEqual(b.snapshot()["communication"]["teammate_health"], {"Drone2": "healthy", "Drone3": "suspected"})

    def test_the_knowledge_log_knows_its_source(self):
        self.assertEqual(source_of("communication.teammate_health.Drone2"),
                         "its own failure detector, from what it heard (Phase 9)")


class BoundaryTests(unittest.TestCase):

    def test_the_detector_reaches_no_ground_truth(self):
        from test_sensing import boundary_violations
        path = os.path.join(ROOT, "agentic_uav", "coordination", "health.py")
        self.assertEqual(boundary_violations(path, "agentic_uav.coordination"), [])


if __name__ == "__main__":
    unittest.main()
