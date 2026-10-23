#!/usr/bin/env python3
"""Tests for Phase 6's exit: the knowledge log, and the two independent agents it is shown on.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-06's exit: "the experiment logger can show, for each decision, exactly
what the agent knew and what it did not know." The log makes three claims
about every decision -- it is complete, what the agent knew was true, and
nothing of the truth gap leaked into it -- and each claim is a check. These
make sure the checks pass on real flights and, as much, that each FAILS
when its claim is broken: an unsourced field, a missing block, a position,
battery, link or sighting the agent could not have had, an unseen target's
place or a teammate's true position in what it knew. Two checks were
caught wrong while this was written (the flight's end, and a descending
drone's velocity read as a position); both are pinned here.
"""

import copy
import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.knowledge import (  # noqa: E402
    BLOCKS,
    Truth,
    entry_json,
    knowledge_entry,
    knowledge_log,
    source_of,
    summary,
)
from agentic_uav.experiments.single_agent import PAIR_TASKS, fly_agent_on_mock, fly_agents_on_mock  # noqa: E402

SINGLE = scenarios.load_scenario("search_single_001")
PAIR = scenarios.load_scenario("search_pair_001")


class PairScenarioTests(unittest.TestCase):

    def test_it_is_the_canonical_mission_cut_to_two_drones_and_s1_s2(self):
        canonical = scenarios.load_scenario("search_relay_001")
        self.assertEqual(PAIR.vehicles, canonical.vehicles[:2])
        self.assertEqual([s.id for s in PAIR.sectors], ["S1", "S2"])
        self.assertEqual(PAIR.sectors, canonical.sectors[:2])
        for field in ("mission", "base", "network", "detection", "battery", "safety", "targets",
                      "restricted_zones", "random_seed"):
            with self.subTest(field=field):
                self.assertEqual(getattr(PAIR, field), getattr(canonical, field))


class IndependentAgentsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.team = fly_agents_on_mock(PAIR)

    def test_each_completes_its_own_task(self):
        self.assertTrue(self.team.met, self.team.report.summary())
        self.assertEqual(self.team.tasks, PAIR_TASKS)
        self.assertEqual(self.team.finished, {"Drone1": True, "Drone2": True})
        for drone, skills in self.team.skills.items():
            with self.subTest(drone=drone):
                self.assertEqual(skills[0], ("TAKE_OFF", "success"))
                self.assertEqual(skills[-1], ("LAND", "success"))
                self.assertTrue(all(status == "success" for _, status in skills))

    def test_each_flies_at_its_own_height(self):
        cruise = {d: max(k.altitude_m for k in t.knots) for d, t in self.team.trajectories.items()}
        self.assertEqual(cruise, {"Drone1": 12.0, "Drone2": 16.0})

    def test_neither_ever_hears_the_other(self):
        for drone, other in (("Drone1", "Drone2"), ("Drone2", "Drone1")):
            with self.subTest(drone=drone):
                self.assertTrue(all(e.belief["team"] == {other: "never heard"} for e in self.team.traces[drone]))

    def test_deterministic(self):
        again = fly_agents_on_mock(PAIR)
        self.assertEqual(again.report.as_json(), self.team.report.as_json())
        for drone in PAIR_TASKS:
            self.assertEqual([(e.at, e.decision.as_json()) for e in again.traces[drone]],
                             [(e.at, e.decision.as_json()) for e in self.team.traces[drone]])

    def test_only_drones_on_the_roster(self):
        with self.assertRaisesRegex(ValueError, "not on search_pair_001's roster"):
            fly_agents_on_mock(PAIR, {"Drone3": "search S1"})

    def test_met_needs_every_agent_to_end_its_own_task(self):
        self.assertTrue(self.team.met)
        unfinished = dataclasses.replace(self.team, finished={"Drone1": True, "Drone2": False})
        self.assertFalse(unfinished.met)


class SingleLogTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flight = fly_agent_on_mock(SINGLE)
        cls.truth = Truth(SINGLE, cls.flight.trajectories, cls.flight.report.start, cls.flight.report.until)
        cls.log = knowledge_log({"Drone1": cls.flight.trace}, cls.truth)

    def test_every_decision_is_logged_and_passes(self):
        self.assertEqual(len(self.log), len(self.flight.trace))
        s = summary(self.log)
        self.assertEqual((s["ok"], s["problems"]), (len(self.log), []))

    def test_known_items_carry_a_source_and_ages_where_they_have_one(self):
        entry = self.log[-1]
        self.assertTrue(all(k["source"] for k in entry.known))
        by_what = {k["what"]: k for k in entry.known}
        self.assertEqual(by_what["self.battery"]["source"], "sensing, now")
        self.assertEqual(by_what["self.velocity"]["source"], "estimated from own positions")
        self.assertEqual(by_what["mission.constraints.targets_to_find"]["source"], "the brief")
        self.assertEqual(by_what["assumptions.battery_model"]["source"], "assumed")
        self.assertIn("age_s", by_what["assumptions.battery_model"])
        seen = [k for k in entry.known if k["what"].startswith("local_map.observed_targets.")]
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(k["age_s"] > 0 for k in seen))

    def test_what_it_did_not_know_before_searching(self):
        before = next(e for e in self.log if e.decision["reason"] == "at S3")
        whats = {u["what"]: u["why"] for u in before.unknown}
        self.assertEqual(whats["targets"], "where 2 more target(s) are; it has seen 0")
        self.assertEqual(whats["sector S3"], "not searched by this drone")
        self.assertEqual(whats["communication.estimated_latency_s"], "not measured until Phase 7")
        gap = {g["what"]: g for g in before.gap}
        self.assertEqual(set(gap), {"target T1", "target T2"})
        for name, g in gap.items():
            self.assertEqual(g["believed"], "not seen")
            self.assertEqual(g["truth"]["sector"], "S3")
            self.assertGreater(g["truth"]["first_seen_by_this_drone_s"], before.at_s)   # it will see it, later

    def test_one_found_one_still_to_find(self):
        halfway = next(e for e in self.log
                       if len([k for k in e.known if k["what"].startswith("local_map.observed_targets.")]) == 1)
        whats = {u["what"]: u["why"] for u in halfway.unknown}
        self.assertEqual(whats["targets"], "where 1 more target(s) are; it has seen 1")
        self.assertEqual(len([g for g in halfway.gap if g["what"].startswith("target")]), 1)

    def test_the_first_sighting_counts_from_the_flights_start(self):
        # On the mock every flight starts at 0. Shift the whole flight 1000 s
        # on, as a live clock would be: the log must not move.
        from agentic_uav.simulator.trajectory import Knot, Trajectory
        shift = 1000.0
        moved = {d: Trajectory(d, [Knot(k.t + shift, k.x, k.y, k.altitude_m, k.airborne) for k in t.knots])
                 for d, t in self.flight.trajectories.items()}
        later = Truth(SINGLE, moved, self.flight.report.start + shift, self.flight.report.until + shift)
        row = entry_json(self.flight.trace[2])
        row["at"] += shift
        here, there = knowledge_entry(self.flight.trace[2], "Drone1", self.truth), knowledge_entry(row, "Drone1", later)
        self.assertEqual(here.at_s, there.at_s)
        self.assertEqual(here.gap, there.gap)
        self.assertEqual(here.gap[0]["truth"]["first_seen_by_this_drone_s"],
                         round(self.truth.first_seen("Drone1", here.gap[0]["what"].split()[-1]) - self.truth.start, 3))

    def test_after_the_search_nothing_is_left_unseen(self):
        ending = next(e for e in self.log if e.decision["reason"] == "S3 searched")
        self.assertEqual(ending.gap, [])                                  # both targets seen by then
        self.assertNotIn("targets", {u["what"] for u in ending.unknown})
        # The belief is taken BEFORE each decision, and this is the decision
        # that marks S3 searched: the next one knows it.
        self.assertIn("sector S3", {u["what"] for u in ending.unknown})
        after = self.log[self.log.index(ending) + 1]
        self.assertNotIn("sector S3", {u["what"] for u in after.unknown})

    def test_the_last_decision_at_the_flights_end(self):
        # Found while writing this: the last knot fell a rounding short of
        # the clock's end, so a truth ending there called the landed drone
        # cut off from the base it was beside.
        last = self.log[-1]
        self.assertTrue(last.ok, last.problems)
        self.assertLess(self.flight.trajectories["Drone1"].knots[-1].t, self.flight.report.until)
        early = Truth(SINGLE, self.flight.trajectories, self.flight.report.start,
                      self.flight.trajectories["Drone1"].knots[-1].t)
        self.assertIn("incorrect: believed base link True", " ".join(knowledge_entry(self.flight.trace[-1], "Drone1", early).problems))

    def test_a_logged_entry_reads_back_the_same(self):
        row = entry_json(self.flight.trace[5])
        self.assertEqual(knowledge_entry(row, "Drone1", self.truth).as_json(),
                         knowledge_entry(self.flight.trace[5], "Drone1", self.truth).as_json())


class PairLogTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.team = fly_agents_on_mock(PAIR)
        cls.truth = Truth(PAIR, cls.team.trajectories, cls.team.start, cls.team.report.until)
        cls.log = knowledge_log(cls.team.traces, cls.truth)

    def test_every_decision_of_both_is_logged_and_passes(self):
        self.assertEqual(len(self.log), sum(len(t) for t in self.team.traces.values()))
        self.assertEqual(summary(self.log)["problems"], [])
        self.assertEqual({e.drone for e in self.log}, {"Drone1", "Drone2"})

    def test_the_two_agents_decisions_in_time_order(self):
        times = [(e.at_s, e.drone) for e in self.log]
        self.assertEqual(times, sorted(times))
        self.assertNotEqual([e.drone for e in self.log[:4]], ["Drone1"] * 4)     # interleaved, not one then the other

    def test_a_teammate_heard_and_then_expired(self):
        # No flight delivers a report yet (Phase 7), so the log is fed the
        # belief's own view of one: current, then expired.
        row = entry_json(next(e for e in self.team.traces["Drone2"] if e.decision.reason == "at S2"))
        heard = {"position": [10.0, -20.0, 12.0], "role": "unknown", "task": "search S1", "status": "unknown",
                 "source": "message", "age_s": 3.0, "received_age_s": 1.0, "confidence": 0.7,
                 "expires_in_s": 7.0, "current": True}
        row["belief"]["team"]["Drone1"] = heard
        current = knowledge_entry(row, "Drone2", self.truth)
        self.assertIn({"what": "team.Drone1.task", "value": "search S1", "source": "a teammate report"}, current.known)
        self.assertNotIn("teammate Drone1 now", {u["what"] for u in current.unknown})
        self.assertIn({"what": "team.Drone1.role", "why": "not in its last report"}, current.unknown)
        row["belief"]["team"]["Drone1"] = dict(heard, age_s=12.0, expires_in_s=-2.0, current=False, confidence=0.0)
        expired = knowledge_entry(row, "Drone2", self.truth)
        self.assertIn({"what": "teammate Drone1 now", "why": "its last report has expired"}, expired.unknown)
        gap = next(g for g in expired.gap if g["what"] == "teammate Drone1")
        self.assertEqual(gap["believed"], {"position": [10.0, -20.0, 12.0], "age_s": 12.0, "current": False})

    def test_a_teammate_never_heard_against_where_it_really_was(self):
        mid = [e for e in self.log if e.drone == "Drone2" and 60.0 < e.at_s < 120.0][0]
        self.assertIn({"what": "teammate Drone1", "why": "never heard from"}, mid.unknown)
        gap = next(g for g in mid.gap if g["what"] == "teammate Drone1")
        self.assertEqual(gap["believed"], "never heard")
        x, y, alt = self.team.trajectories["Drone1"].position_at(mid.at_s + self.team.start)
        self.assertEqual(gap["truth"]["position"], [round(x, 3), round(y, 3), round(alt, 3)])
        self.assertGreater(alt, 0.0)                                       # it was flying, unknown to Drone2

    def test_each_drone_does_not_know_the_others_sector(self):
        last = [e for e in self.log if e.drone == "Drone1"][-1]
        self.assertIn({"what": "sector S2", "why": "not searched by this drone"}, last.unknown)
        self.assertNotIn("sector S1", {u["what"] for u in last.unknown})

    def test_its_own_velocity_is_not_a_teammates_position(self):
        # Found while writing this: on every seed, at 154.5 s, Drone2 was
        # descending at [0.0, 0.0, -1.0] while Drone1 hung over its pad at
        # [0.0, 0.0, 1.0], and the velocity read as Drone1's position.
        case = [e for e in self.log if e.drone == "Drone2"
                and any(k["what"] == "self.velocity" and k["value"][:2] == [0.0, 0.0] for k in e.known)
                and next(g for g in e.gap if g["what"] == "teammate Drone1")["truth"]["position"][:2] == [0.0, 0.0]]
        self.assertEqual([e.at_s for e in case], [154.5])                 # the case is in this flight
        self.assertTrue(case[0].ok, case[0].problems)


class ChecksCanFailTests(unittest.TestCase):
    """Each check, on a real decision altered to break it."""

    @classmethod
    def setUpClass(cls):
        cls.team = fly_agents_on_mock(PAIR)
        cls.truth = Truth(PAIR, cls.team.trajectories, cls.team.start, cls.team.report.until)
        trace = cls.team.traces["Drone2"]
        cls.row = entry_json(next(e for e in trace if e.decision.reason == "at S2"))      # flying, nothing seen yet

    def problems(self, change):
        row = copy.deepcopy(self.row)
        change(row["belief"])
        return " ".join(knowledge_entry(row, "Drone2", self.truth).problems)

    def test_the_real_decision_passes(self):
        self.assertEqual(self.problems(lambda b: None), "")

    def test_complete(self):
        self.assertIn("no known source for self.mood", self.problems(lambda b: b["self"].update(mood="calm")))
        self.assertIn("the team block is missing", self.problems(lambda b: b.pop("team")))
        self.assertEqual(set(BLOCKS), set(self.row["belief"]) - {"schema"})
        self.assertIsNone(source_of("nonsense.path"))

    def test_correct(self):
        def nudge(b):
            b["self"]["position"][0] += 1.0
        self.assertIn("incorrect: believed position", self.problems(nudge))
        self.assertIn("incorrect: believed battery", self.problems(lambda b: b["self"].update(battery=b["self"]["battery"] - 1)))
        self.assertIn("incorrect: believed base link", self.problems(lambda b: b["self"].update(base_link=not b["self"]["base_link"])))
        t1 = next(t for t in self.truth.targets if t.id == "T1")
        self.assertIn("incorrect: believed sightings ['T1']",
                      self.problems(lambda b: b["local_map"]["observed_targets"].update(T1=[t1.x, t1.y, 1.0])))

    def test_a_sighting_it_had_made_cannot_be_missing(self):
        late = entry_json([e for e in self.team.traces["Drone2"]][-1])        # landed, after the search
        self.assertTrue(late["belief"]["local_map"]["observed_targets"])
        late["belief"]["local_map"]["observed_targets"] = {}
        self.assertIn("incorrect: believed sightings []", " ".join(knowledge_entry(late, "Drone2", self.truth).problems))

    def test_no_leak(self):
        t = next(t for t in self.truth.targets if t.sector == "S2")
        where = [round(t.x, 3), round(t.y, 3)]
        self.assertIn(f"leak: it knew something of target {t.id}",
                      self.problems(lambda b: b["local_map"]["known_hazards"].append(where)))
        self.assertIn(f"leak: it knew something of target {t.id}",
                      self.problems(lambda b: b["mission"]["progress"].update(hint=t.id)))
        at = self.row["at"]
        x, y, _ = self.truth.position("Drone1", at)
        self.assertIn("leak: it knew where Drone1 really was",
                      self.problems(lambda b: b["mission"]["progress"].update(hint=[round(x, 3), round(y, 3)])))


class ScriptTests(unittest.TestCase):

    def test_one_seed_writes_its_record(self):
        import knowledge_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = knowledge_exit.main(["--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            files = sorted(os.listdir(out))
            self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
            with open(os.path.join(out, files[0]), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            self.assertEqual(rows[0]["kind"], "header")
            self.assertTrue(rows[0]["exit_criterion_met"])
            self.assertEqual([(r["set"], r["seed"]) for r in rows if r["kind"] == "flight"], [("single", 17), ("pair", 17)])
            decisions = [r for r in rows if r["kind"] == "decision"]
            self.assertEqual(len(decisions), rows[0]["decisions"])
            self.assertTrue(all(r["checks"]["ok"] for r in decisions))
            self.assertEqual({r["drone"] for r in decisions if r["set"] == "pair"}, {"Drone1", "Drone2"})
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
