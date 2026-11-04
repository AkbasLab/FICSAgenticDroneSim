#!/usr/bin/env python3
"""Tests for Phase 10 step 3: each drone's estimate of its links, from what arrived (AUV-10, 10.5).

    python -m unittest discover tests

WHY THESE EXIST
---------------
"Agents must not read the configured packet-loss probability. They estimate
from heartbeat arrival rate, observed round-trip time, missing sequence
numbers, recent delivery acknowledgments." These hold each estimate to what
it is computed from -- arrivals in a window, gaps in a teammate's sequence
numbers, a claim and its acknowledgement -- and the estimates, flown, to the
conditions they were never told: no loss on nominal, about a tenth on
moderate, about three tenths on severe, and a partition showing as silence,
not as loss. And every earlier snapshot to staying as it was: an agent not
on Phase 10's network keeps no such estimate.
"""

import os
import statistics
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.conditions import CONDITIONS, load_network  # noqa: E402
from agentic_uav.experiments.recovery import LINK_WINDOW_S, fly_recovery_on_mock, load_recovery  # noqa: E402

SC = scenarios.load_scenario("search_relay_001")


def belief(window=10.0):
    b = BeliefState.start(SC.brief(), "Drone1", Observation(0.0, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None))
    b.listening = True
    b.team.members.update({"Drone2": None, "Drone3": None})
    if window is not None:
        b.link_window_s = window
    return b


class EstimateTests(unittest.TestCase):

    def test_from_what_arrived(self):
        b = belief()
        for k, seq in enumerate((1, 2, 4, 5, 6, 8, 9, 10)):            # 3 and 7 never came
            b.heard("Drone2", seq, sent_at=float(k), now=k + 0.5, heartbeat=True)
        got = b.link_estimates(10.0)
        self.assertEqual(got["Drone3"], "never heard")
        d2 = got["Drone2"]
        self.assertEqual(d2["loss_rate"], 0.2)                           # 2 of 10 missing
        self.assertEqual(d2["heartbeat_rate_hz"], 0.8)                   # 8 heard in 10 s
        self.assertEqual(d2["latency_s"], 0.5)
        self.assertEqual(d2["round_trip_s"], "unknown")
        self.assertEqual(d2["heard_s_ago"], 2.5)

    def test_only_the_window_counts(self):
        b = belief(window=4.0)
        for k in range(10):
            b.heard("Drone2", k + 1, sent_at=float(k), now=float(k), heartbeat=True)
        self.assertEqual(b.link_estimates(9.0)["Drone2"]["heartbeat_rate_hz"], 1.0)   # 6..9: four in four seconds
        self.assertEqual(b.link_estimates(30.0)["Drone2"]["loss_rate"], "unknown")    # nothing in the window
        self.assertEqual(b.link_estimates(30.0)["Drone2"]["heartbeat_rate_hz"], 0.0)

    def test_a_window_not_yet_full_counts_what_it_has(self):
        b = belief(window=10.0)
        for k in range(3):
            b.heard("Drone2", k + 1, sent_at=float(k), now=float(k) + 0.1, heartbeat=True)
        self.assertEqual(b.link_estimates(3.0)["Drone2"]["heartbeat_rate_hz"], 1.0)   # 3 in the 3 s it has listened

    def test_only_heartbeats_make_the_heartbeat_rate(self):
        b = belief()
        b.heard("Drone2", 1, 0.0, 0.5, heartbeat=True)
        b.heard("Drone2", 2, 0.0, 0.5, heartbeat=False)
        self.assertEqual(b.link_estimates(10.0)["Drone2"]["heartbeat_rate_hz"], 0.1)

    def test_a_round_trip_is_its_claim_acknowledged(self):
        b = belief()
        b.heard("Drone2", 1, 0.0, 0.5)
        b.acknowledged("Drone2", 1.25)
        self.assertEqual(b.link_estimates(1.0)["Drone2"]["round_trip_s"], 1.25)

    def test_without_a_window_nothing_new_is_kept_or_shown(self):
        b = belief(window=None)
        b.heard("Drone2", 1, 0.0, 0.5, heartbeat=True)
        b.acknowledged("Drone2", 1.0)
        self.assertNotIn("arrivals", b.links["Drone2"])
        self.assertNotIn("round_trip_s", b.links["Drone2"])
        self.assertNotIn("links", b.snapshot()["communication"])
        self.assertIn("links", belief().snapshot()["communication"])


class FlightTests(unittest.TestCase):
    """The canonical mission under each condition: what the drones estimated, never told."""

    @classmethod
    def setUpClass(cls):
        a, h = load_allocation(), load_recovery()
        cls.phase9 = fly_recovery_on_mock(SC, a, h, "no stop")
        cls.flights = {c: fly_recovery_on_mock(SC, a, h, "no stop", network=load_network(c)) for c in CONDITIONS}

    def samples(self, condition, key, after_s=15.0, before_s=None):
        run = self.flights[condition]
        out = []
        for trace in run.team.traces.values():
            for e in trace:
                t = e.at - run.team.start
                if t < after_s or (before_s is not None and t > before_s):
                    continue
                for mate, link in e.as_json()["belief"]["communication"]["links"].items():
                    if isinstance(link, dict) and isinstance(link[key], (int, float)):
                        out.append(link[key])
        return out

    def test_the_estimates_track_the_conditions_they_were_never_told(self):
        loss = {c: statistics.mean(self.samples(c, "loss_rate")) for c in CONDITIONS}
        self.assertEqual(loss["nominal"], 0.0)
        self.assertEqual(loss["partitioned"], 0.0)                  # a partition is silence, not loss
        self.assertTrue(0.05 < loss["moderate"] < 0.15, loss)        # configured 0.10
        self.assertTrue(0.20 < loss["severe"] < 0.40, loss)          # configured 0.30, and the rate limit's gaps
        rate = {c: statistics.mean(self.samples(c, "heartbeat_rate_hz")) for c in CONDITIONS}
        self.assertTrue(0.9 < rate["nominal"] <= 1.05, rate)         # one heartbeat a second, and nothing else counted
        self.assertTrue(rate["nominal"] > rate["moderate"] > rate["severe"], rate)
        latency = {c: statistics.mean(self.samples(c, "latency_s")) for c in CONDITIONS}
        self.assertGreater(latency["severe"], latency["moderate"])
        self.assertGreater(latency["severe"], 1.0)

    def test_a_partition_shows_as_silence_across_it(self):
        run = self.flights["partitioned"]
        for e in run.team.traces["Drone1"]:
            t = e.at - run.team.start
            if 70.0 < t < 118.0:
                links = e.as_json()["belief"]["communication"]["links"]
                for far in ("Drone3", "Drone4"):
                    self.assertGreater(links[far]["heard_s_ago"], 9.0, (t, far))
                self.assertLess(links["Drone2"]["heard_s_ago"], 1.5, t)    # its own side, heard as ever

    def test_round_trips_are_measured_on_claims(self):
        # A claim is read at the teammates' next tick, their acknowledgement at the claimant's next: on nominal,
        # a round trip of a few ticks -- a duration, not a time of day.
        nominal = self.samples("nominal", "round_trip_s", after_s=0.0)
        self.assertTrue(nominal)
        self.assertEqual(set(nominal), {1.0})                       # two ticks, every one
        self.assertGreater(statistics.mean(self.samples("severe", "round_trip_s", after_s=0.0)),
                           statistics.mean(self.samples("nominal", "round_trip_s", after_s=0.0)))

    def test_estimating_changes_no_decision(self):
        # The estimates are shown, not acted on (recommendation 1): nominal decides exactly as Phase 9.
        def actions(run):
            return {d: [(e.at, e.action) for e in t] for d, t in run.team.traces.items()}
        self.assertEqual(actions(self.flights["nominal"]), actions(self.phase9))
        self.assertEqual(self.flights["nominal"].policies, self.phase9.policies)

    def test_only_an_agent_on_a_network_keeps_them(self):
        e = self.phase9.team.traces["Drone1"][0]
        self.assertNotIn("links", e.as_json()["belief"]["communication"])
        self.assertEqual(LINK_WINDOW_S, 10.0)


if __name__ == "__main__":
    unittest.main()
