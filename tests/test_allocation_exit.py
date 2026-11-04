#!/usr/bin/env python3
"""Tests for Phase 8's exit: agentic_uav.experiments.allocation_exit and scripts/allocation_exit.py.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Each check of the exit must be able to fail, or a pass means nothing. So
each is run on a real seed's flights, where it passes, and then on the same
flights altered to break exactly what it checks: a drone told a sector, a
claim that did not rest on its own bid, a sector searched twice, two books
disagreeing, a conflict logged for the wrong winner, a loser that never let
go, a lease run out, a holder gone quiet, two flights that differ, a belief
that is wrong.
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

from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.allocation_exit import (  # noqa: E402
    CHECKS,
    allocation_flights,
    conflicts_resolved,
    deterministic,
    exit_checks,
    hundred_metre_finding,
    known_exactly,
    leases_renewed,
    no_central_assignment,
    one_holder_each,
)

TEAM = scenarios.load_scenario("search_relay_001")
CONFIG = load_allocation()
TASKS = ["search S1", "search S2", "search S3", "search S4"]


def with_nets(run, change):
    nets = copy.deepcopy(run.nets)
    change(nets)
    return dataclasses.replace(run, nets=nets)


def with_team(run, **changes):
    return dataclasses.replace(run, team=dataclasses.replace(run.team, **changes))


class RealSeedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flights = allocation_flights(TEAM, 17, CONFIG)
        cls.checks = exit_checks(cls.flights, TEAM)
        cls.deliberating, cls.contested = cls.flights["deliberating"], cls.flights["contested"]

    def test_every_check_passes(self):
        for name in CHECKS:
            with self.subTest(check=name):
                self.assertTrue(self.checks[name]["ok"], self.checks[name]["problems"][:5])
        self.assertTrue(self.checks["all"])

    def test_the_flights_are_what_they_say(self):
        self.assertEqual(sorted(self.flights), ["contested", "contested again", "deliberating", "deliberating again"])
        for mode in ("deliberating", "contested"):                 # flown again, not the same flight twice
            self.assertIsNot(self.flights[f"{mode} again"], self.flights[mode])
            self.assertIsNot(self.flights[f"{mode} again"].team.traces, self.flights[mode].team.traces)
        self.assertEqual(self.deliberating.config.bid_window_s, 1.0)
        self.assertEqual(self.contested.config.bid_window_s, 0.0)
        (conflict,) = self.checks["conflicts_resolved"]["conflicts"]
        self.assertEqual((conflict["task_id"], conflict["winner"], len(conflict["claims"])), ("search S2", "Drone4", 4))
        self.assertGreater(self.checks["known_exactly"]["decisions"], 50)

    # ------------------------------------------------- no central assignment

    def test_a_drone_told_a_sector(self):
        trace = list(self.deliberating.team.traces["Drone2"])
        trace[0] = dataclasses.replace(trace[0], events=(Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S4"}),))
        run = with_team(self.deliberating, traces={**self.deliberating.team.traces, "Drone2": tuple(trace)})
        self.assertIn("Drone2 was told", " ".join(no_central_assignment(run, True)))

    def test_a_claim_not_on_its_own_bid(self):
        def change(nets):
            nets["Drone3"]["claims_made"][0]["heard"]["Drone3"] += 5.0
        self.assertIn("did not rest on its own bid", " ".join(no_central_assignment(with_nets(self.deliberating, change), True)))

    def test_a_deliberate_claim_without_every_bid(self):
        def change(nets):
            nets["Drone1"]["claims_made"][0]["heard"].pop("Drone4")
        problems = no_central_assignment(with_nets(self.deliberating, change), True)
        self.assertIn("having heard only", " ".join(problems))
        self.assertEqual(no_central_assignment(self.contested, False), [])       # contested claims on less, by design

    def test_the_exit_holds_the_deliberating_flight_to_every_bid(self):
        def change(nets):
            nets["Drone1"]["claims_made"][0]["heard"].pop("Drone4")
        flights = dict(self.flights, deliberating=with_nets(self.deliberating, change))
        checks = exit_checks(flights, TEAM)
        self.assertFalse(checks["no_central_assignment"]["ok"])
        self.assertIn("having heard only", " ".join(checks["no_central_assignment"]["problems"]))

    def test_flying_what_it_did_not_last_claim(self):
        run = dataclasses.replace(self.deliberating, searched={**self.deliberating.searched, "Drone1": ["search S1"]})
        self.assertIn("not its last claim", " ".join(no_central_assignment(run, True)))

    # ------------------------------------------------------- one holder each

    def test_a_sector_searched_twice_or_not_at_all(self):
        twice = dataclasses.replace(self.deliberating, searched={**self.deliberating.searched,
                                                                 "Drone1": ["search S2"]})
        self.assertIn("not each of", " ".join(one_holder_each(twice, TASKS)))

    def test_books_that_disagree(self):
        def change(nets):
            nets["Drone2"]["book"]["tasks"][0]["assigned_agent"] = "Drone1"
        self.assertIn("Drone2's book ends with search S1", " ".join(one_holder_each(with_nets(self.deliberating, change), TASKS)))

    # ---------------------------------------------------- conflicts resolved

    def test_a_contested_flight_that_contested_nothing(self):
        _, problems = conflicts_resolved(self.deliberating, contested_flight=True)
        self.assertIn("contested nothing", " ".join(problems))

    def test_a_deliberating_flight_with_a_conflict(self):
        _, problems = conflicts_resolved(self.contested, contested_flight=False)
        self.assertIn("a deliberating flight had conflicts", " ".join(problems))

    def test_a_conflict_logged_for_the_wrong_winner(self):
        def change(nets):
            nets["Drone1"]["corrections"][0]["kept"] = "Drone3"
        _, problems = conflicts_resolved(with_nets(self.contested, change), contested_flight=True)
        self.assertIn("Drone1's book logged", " ".join(problems))

    def test_a_loser_that_never_let_go(self):
        kept = tuple(d for d in self.contested.team.deliveries
                     if not (d.message.message_type.value == "task_release" and d.message.sender_id == "Drone2"))
        _, problems = conflicts_resolved(with_team(self.contested, deliveries=kept), contested_flight=True)
        self.assertIn("Drone2 lost search S2 v1 and never released it", problems)

    # --------------------------------------------------------- leases renewed

    def test_a_lease_that_ran_out(self):
        def change(nets):
            nets["Drone1"]["book_log"].append({"at": 50.0, "task_id": "search S4", "before": {}, "after": {},
                                               "why": "Drone2's lease ran out at 50.000"})
        self.assertIn("lease ran out", " ".join(leases_renewed(with_nets(self.deliberating, change))))

    def test_a_holder_gone_quiet(self):
        kept = tuple(d for d in self.deliberating.team.deliveries
                     if not (d.message.sender_id == "Drone3" and d.message.message_type.value == "status_update"
                             and 40.0 < d.message.timestamp < 60.0))
        problems = leases_renewed(with_team(self.deliberating, deliveries=kept))
        self.assertIn("Drone3's reports on search S1 left a gap", " ".join(problems))

    # ---------------------------------------------------------- deterministic

    def test_two_flights_that_differ(self):
        def change(nets):
            nets["Drone4"]["claims_made"][0]["at"] += 0.5
        problems = deterministic(self.deliberating, with_nets(self.deliberating, change))
        self.assertIn("the books differ", " ".join(problems))
        self.assertEqual(deterministic(self.deliberating, self.flights["deliberating again"]), [])

    # ---------------------------------------------------------- known exactly

    def test_a_belief_that_is_wrong(self):
        trace = list(self.deliberating.team.traces["Drone1"])
        belief = copy.deepcopy(trace[3].belief)
        belief["self"]["position"][0] += 5.0
        trace[3] = dataclasses.replace(trace[3], belief=belief)
        run = with_team(self.deliberating, traces={**self.deliberating.team.traces, "Drone1": tuple(trace)})
        self.assertFalse(known_exactly(run, TEAM)["ok"])

    def test_one_failing_check_fails_the_seed(self):
        flights = dict(self.flights, contested=self.flights["deliberating"])
        checks = exit_checks(flights, TEAM)
        self.assertFalse(checks["conflicts_resolved"]["ok"])
        self.assertFalse(checks["all"])


class FindingTests(unittest.TestCase):

    def test_the_100_m_radio_finding(self):
        f = hundred_metre_finding(TEAM, CONFIG)
        self.assertEqual(f["range_m"], 100.0)
        self.assertGreater(f["lease_expiries"], 0)
        self.assertGreater(f["searches"], f["sectors"])
        self.assertEqual(f["sectors"], 4)
        self.assertTrue(all("lease ran out" in e["why"] for e in f["first_expiries"]))


class ScriptTests(unittest.TestCase):

    def test_a_failing_seed_fails_the_run(self):
        import allocation_exit
        from unittest import mock
        real = allocation_exit.exit_checks

        def failing(flights, scenario):
            checks = real(flights, scenario)
            checks["met"] = {"ok": False, "problems": ["a test: the mission not met"]}
            checks["all"] = False
            return checks

        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with mock.patch.object(allocation_exit, "exit_checks", failing), redirect_stdout(buffer):
                code = allocation_exit.main(["--seeds", "17", "--out", out])
            self.assertEqual(code, 1)
            self.assertIn("**Exit criterion: NOT MET**", buffer.getvalue())
            self.assertIn("a test: the mission not met", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_one_seed_writes_its_record(self):
        import allocation_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = allocation_exit.main(["--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            jsonl = next(f for f in os.listdir(out) if f.endswith(".jsonl"))
            with open(os.path.join(out, jsonl), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            head = rows[0]
            self.assertTrue(head["exit_criterion_met"])
            self.assertEqual(head["manifest"], "configs/allocation/default.toml")
            self.assertEqual(head["config"], CONFIG.as_json())
            self.assertEqual(head["network"], "every message delivered (range unlimited)")
            self.assertGreater(head["finding_100m"]["lease_expiries"], 0)
            kinds = [r["kind"] for r in rows]
            self.assertEqual(kinds.count("seed"), 1)
            self.assertEqual(kinds.count("books"), 2)
            self.assertGreater(kinds.count("message"), 100)
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
