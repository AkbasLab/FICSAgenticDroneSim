#!/usr/bin/env python3
"""Tests for the belief state's full schema: AUV-06's six blocks (6.1).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 6's exit is a logger that shows exactly what an agent knew and did not
know, and it can only show what the belief holds. These check each block
holds what AUV-06 asks, from where it should come: velocity and heading
estimated from the drone's own positions and labelled so; health from its
own skill results, each counted once; constraints, zones and the roster from
the public brief; the link's unmeasured qualities held as unknown, never as
a zero that would claim a perfect link; assumptions replaced by key and aged.
And that Phase 5's decisions do not move: the belief grew, the agent did not
change its mind.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import (  # noqa: E402
    ESTIMATED,
    SCHEMA_VERSION,
    BeliefState,
    Observation,
)
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.single_agent import TROUBLES, fly_agent_on_mock  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")          # four drones
ONE = scenarios.load_scenario("search_single_001")
RECORD = os.path.join(ROOT, "phases", "phase-05-persistent-agent", "results",
                      "single-agent-exit-20261021-215820-exit.jsonl")


def obs(at, x=0.0, y=0.0, alt=0.0, airborne=False, battery=100.0, link=True,
        skill=None, serial=0, status=None, last=None):
    return Observation(at, x, y, alt, airborne, battery, (), link, skill, serial, status, last)


def fresh(scenario=TEAM, drone="Drone1"):
    return BeliefState.start(scenario.brief(), drone, obs(0.0))


class SchemaTests(unittest.TestCase):

    def test_the_six_blocks_and_the_version(self):
        snap = fresh().snapshot()
        self.assertEqual(snap["schema"], SCHEMA_VERSION)
        self.assertEqual(set(snap) - {"schema"},
                         {"self", "mission", "local_map", "team", "communication", "assumptions"})
        for key in ("vehicle_id", "position", "velocity", "heading_deg", "battery", "health",
                    "current_skill", "current_task"):
            self.assertIn(key, snap["self"])
        for key in ("mission_id", "objective", "constraints", "deadline_in_s", "progress"):
            self.assertIn(key, snap["mission"])
        for key in ("searched_regions", "observed_targets", "known_hazards", "restricted_zones"):
            self.assertIn(key, snap["local_map"])
        for key in ("estimated_latency_s", "recent_loss_rate", "connected_peers", "base_reachable"):
            self.assertIn(key, snap["communication"])

    def test_the_snapshot_is_plain_data(self):
        snap = fresh().snapshot()
        self.assertEqual(json.loads(json.dumps(snap)), snap)


class SelfTests(unittest.TestCase):

    def test_motion_is_unknown_until_two_readings(self):
        snap = fresh().snapshot()["self"]
        self.assertEqual(snap["velocity"], "unknown")
        self.assertEqual(snap["heading_deg"], "unknown")
        self.assertEqual(snap["motion_source"], ESTIMATED)

    def test_velocity_and_heading_from_own_positions(self):
        belief = fresh()
        belief.update(obs(0.5, alt=1.0, airborne=True))
        belief.update(obs(1.0, x=2.0, alt=1.0, airborne=True))           # 2 m along +x in 0.5 s
        self.assertEqual(belief.self_.velocity, (4.0, 0.0, 0.0))
        self.assertEqual(belief.self_.heading_deg, 0.0)
        belief.update(obs(1.5, x=2.0, y=-1.5, alt=2.0, airborne=True))    # 1.5 m along -y, climbing 2 m/s
        self.assertEqual(belief.self_.velocity, (0.0, -3.0, 2.0))
        self.assertEqual(belief.self_.heading_deg, 270.0)

    def test_heading_is_unknown_when_hovering(self):
        belief = fresh()
        belief.update(obs(0.5, alt=10.0, airborne=True))                  # climbing straight up
        self.assertIsNone(belief.self_.heading_deg)
        belief.update(obs(1.0, x=0.05, alt=10.0, airborne=True))          # 0.1 m/s: below the floor
        self.assertIsNone(belief.self_.heading_deg)
        self.assertEqual(belief.snapshot()["self"]["heading_deg"], "unknown")

    def test_no_estimate_from_a_repeated_instant(self):
        belief = fresh()
        belief.update(obs(1.0, x=4.0))
        before = belief.self_.velocity
        belief.update(obs(1.0, x=9.0))                                     # same instant: no division by zero
        self.assertEqual(belief.self_.velocity, before)

    def test_health_from_own_skill_results(self):
        belief = fresh()
        h = belief.self_.health
        belief.update(obs(1.0, serial=1, status="success", last="TAKE_OFF"))
        self.assertEqual((h.skill_failures, h.degraded), (0, False))
        belief.update(obs(2.0, serial=2, status="failed", last="FOLLOW_WAYPOINTS"))
        belief.update(obs(2.5, serial=2, status="failed", last="FOLLOW_WAYPOINTS"))   # same skill, seen again
        self.assertEqual((h.skill_failures, h.degraded), (1, True))
        self.assertEqual((h.last_failure, h.last_failure_at), ("FOLLOW_WAYPOINTS failed", 2.0))
        belief.update(obs(3.0, serial=3, status="aborted", last="SEARCH_REGION"))     # its own abort is no fault
        self.assertEqual((h.skill_failures, h.degraded), (1, False))
        belief.update(obs(4.0, serial=4, status="timeout", last="RETURN_HOME"))
        self.assertEqual((h.skill_failures, h.degraded, h.last_failure), (2, True, "RETURN_HOME timeout"))
        belief.update(obs(5.0, serial=5, status="success", last="RETURN_HOME"))
        self.assertFalse(h.degraded)
        self.assertEqual(belief.snapshot()["self"]["health"]["skill_failures"], 2)


class BriefTests(unittest.TestCase):

    def test_constraints_and_zones_from_the_brief(self):
        snap = fresh().snapshot()
        self.assertEqual(snap["mission"]["constraints"],
                         {"restricted_zones": ["R1"], "reserve": TEAM.battery.reserve,
                          "min_separation_m": TEAM.safety.min_separation_m, "deadline_s": TEAM.mission.deadline_s})
        r1 = TEAM.restricted_zones[0].polygon.vertices
        self.assertEqual(snap["local_map"]["restricted_zones"], {"R1": [list(p) for p in r1]})

    def test_the_roster_without_itself_and_never_heard(self):
        self.assertEqual(fresh(TEAM, "Drone3").snapshot()["team"],
                         {"Drone1": "never heard", "Drone2": "never heard", "Drone4": "never heard"})
        self.assertEqual(fresh(ONE).snapshot()["team"], {})


class CommunicationTests(unittest.TestCase):

    def test_unmeasured_qualities_are_unknown_not_zero(self):
        comm = fresh().snapshot()["communication"]
        for key in ("estimated_latency_s", "recent_loss_rate", "connected_peers"):
            self.assertEqual(comm[key], "unknown")

    def test_the_base_link_and_how_long_it_has_held(self):
        belief = fresh()
        belief.update(obs(5.0, link=True))
        self.assertEqual(belief.snapshot()["communication"]["base_reachable_for_s"], 5.0)
        belief.update(obs(7.0, link=False))
        belief.update(obs(10.0, link=False))
        comm = belief.snapshot()["communication"]
        self.assertEqual((comm["base_reachable"], comm["base_reachable_for_s"]), (False, 3.0))


class AssumptionTests(unittest.TestCase):

    def test_recorded_replaced_by_key_aged_and_dropped(self):
        belief = fresh()
        belief.assume("speed", "makes 5 m/s", "the plan", at=0.0, confidence=0.5)
        belief.assume("link", "reports reach the base once in range", "the brief's radio", at=1.0, confidence=0.9)
        belief.assume("speed", "makes 2.5 m/s", "measured over 40 s", at=2.0, confidence=0.9)
        belief.update(obs(6.0))
        held = belief.snapshot()["assumptions"]
        self.assertEqual([a["key"] for a in held], ["link", "speed"])
        self.assertEqual(held[1], {"key": "speed", "statement": "makes 2.5 m/s", "evidence": "measured over 40 s",
                                   "age_s": 4.0, "confidence": 0.9})
        belief.drop_assumption("link")
        belief.drop_assumption("never held")
        self.assertEqual([a["key"] for a in belief.snapshot()["assumptions"]], ["speed"])

    def test_confidence_is_a_probability(self):
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                fresh().assume("k", "s", "e", at=0.0, confidence=bad)


class InFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        once = next(t for t in TROUBLES if t.name == "fault once")
        cls.flight = fly_agent_on_mock(ONE, label=once.name, prepare=once.prepare)

    def test_health_follows_the_failure_and_the_recovery(self):
        by_reason = {e.decision.reason.split(":")[0]: e.belief for e in self.flight.trace}
        retried = by_reason["retry 1"]["self"]["health"]                  # what it knew deciding to retry
        self.assertEqual((retried["degraded"], retried["skill_failures"]), (True, 1))
        self.assertEqual(retried["last_failure"], "FOLLOW_WAYPOINTS failed")
        searching = by_reason["at S3"]["self"]["health"]                   # after the retry succeeded
        self.assertEqual((searching["degraded"], searching["skill_failures"]), (False, 1))

    def test_motion_estimated_in_flight(self):
        searching = next(e.belief for e in self.flight.trace if e.decision.reason == "S3 searched")
        speed = sum(v * v for v in searching["self"]["velocity"][:2]) ** 0.5
        self.assertGreater(speed, 0.0)
        self.assertLessEqual(speed, 5.0 + 1e-6)                            # never above the planned speed


class PhaseFiveUnchangedTests(unittest.TestCase):
    """The belief grew; the decisions must not have moved."""

    def test_seed_17_decides_as_the_phase_5_record(self):
        with open(RECORD, encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        saved = next(r for r in rows if r.get("kind") == "nominal" and r["seed"] == 17)
        import dataclasses
        run = fly_agent_on_mock(dataclasses.replace(ONE, random_seed=17))
        now = json.loads(json.dumps(run.as_json(), default=str))          # as the record was written
        self.assertEqual(now["report"], saved["report"])
        self.assertEqual([(e["at"], e["decision"], e["verdict"], e["action"]) for e in now["trace"]],
                         [(e["at"], e["decision"], e["verdict"], e["action"]) for e in saved["trace"]])
        self.assertEqual(saved["trace"][0]["belief"].get("schema"), None)          # Phase 5's three blocks
        self.assertEqual(now["trace"][0]["belief"]["schema"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
