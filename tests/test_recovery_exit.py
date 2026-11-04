#!/usr/bin/env python3
"""Tests for Phase 9's exit: agentic_uav.experiments.recovery_exit and scripts/recovery_exit.py.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Each check of the exit must be able to fail. Each is run on a real seed's
flights, where it passes, and on the same flights altered to break exactly
what it checks: a ladder out of order or early, an alarm about a live drone,
a task nobody took back, a mission not met, a drone told a task, a role with
no cause or not announced, two flights that differ, a wrong belief. And the
reprioritization flight and the 9.4 report, which stand beside the exit.
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
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.recovery_exit import (  # noqa: E402
    CHECKS,
    continued,
    detected,
    deterministic,
    emergence_report,
    exit_checks,
    judge_reprioritization,
    known_exactly,
    no_false_alarm,
    no_new_command,
    reassigned,
    recovery_flights,
    reprioritization,
    roles_from_interactions,
    validated,
)

TEAM = scenarios.load_scenario("search_relay_001")
CONFIG, HEALTH = load_allocation(), load_recovery()


def with_policies(run, change):
    policies = copy.deepcopy(run.policies)
    change(policies)
    return dataclasses.replace(run, policies=policies)


def with_team(run, **changes):
    return dataclasses.replace(run, team=dataclasses.replace(run.team, **changes))


class RealSeedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flights = recovery_flights(TEAM, 17, CONFIG, HEALTH)
        cls.checks = exit_checks(cls.flights, TEAM)
        cls.stopped = cls.flights["Drone1 stopped"]

    def test_every_check_passes(self):
        for name in CHECKS:
            with self.subTest(check=name):
                self.assertTrue(self.checks[name]["ok"], self.checks[name]["problems"][:5])
        self.assertTrue(self.checks["all"])

    def test_the_flights_are_what_they_say(self):
        self.assertEqual(sorted(self.flights), sorted(["no stop"] + [f"Drone{i} stopped{a}" for i in range(1, 5)
                                                                     for a in ("", " again")]))
        for i in range(1, 5):
            f = self.flights[f"Drone{i} stopped"]
            self.assertEqual(f.stopped, {f"Drone{i}": 60.0})
            self.assertIsNot(self.flights[f"Drone{i} stopped again"], f)
        self.assertEqual(self.flights["no stop"].stopped, {})
        self.assertEqual(len(self.checks["reassigned"]["reassignments"]), 4)
        self.assertTrue(all(validated(f) for f in self.flights.values()))

    # ----------------------------------------------------------------- detected

    def test_a_ladder_out_of_order_or_early(self):
        def skip(p):
            p["Drone2"]["health"]["log"] = [t for t in p["Drone2"]["health"]["log"] if t["after"] != "unreachable"]
        self.assertIn("not the three rungs in order", " ".join(detected(with_policies(self.stopped, skip))))

        def early(p):
            p["Drone3"]["health"]["log"][0]["silence_s"] = 1.0
        self.assertIn("after 1.0 s of silence, not 3", " ".join(detected(with_policies(self.stopped, early))))

    def test_an_alarm_about_a_live_drone(self):
        def alarm(p):
            p["Drone2"]["health"]["log"].append({"at": 70.0, "teammate": "Drone3", "before": "healthy",
                                                 "after": "suspected", "silence_s": 3.0})
        self.assertIn("Drone3, which was not stopped", " ".join(no_false_alarm(with_policies(self.stopped, alarm))))

    # --------------------------------------------------------------- reassigned

    def test_a_task_nobody_took_back(self):
        run = dataclasses.replace(self.stopped, searched={**self.stopped.searched, "Drone4": ["search S2"]})
        self.assertIn("searched by no survivor", " ".join(reassigned(run)[1]))

    def test_a_book_that_never_saw_the_lease_run_out(self):
        def forget(p):
            p["Drone3"]["net"]["book_log"] = [e for e in p["Drone3"]["net"]["book_log"] if "lease ran out" not in e["why"]]
        self.assertIn("never saw Drone1's lease", " ".join(reassigned(with_policies(self.stopped, forget))[1]))

    # -------------------------------------------------------- continued, told

    def test_a_survivor_that_did_not_end_its_part(self):
        run = with_team(self.stopped, finished={**self.stopped.team.finished, "Drone2": False})
        self.assertIn("Drone2 did not end its part itself", continued(run))

    def test_a_drone_told_a_task(self):
        trace = list(self.stopped.team.traces["Drone3"])
        trace[0] = dataclasses.replace(trace[0], events=(Event(Trigger.TASK_ASSIGNED, 0.0, {"task": "search S3"}),))
        run = with_team(self.stopped, traces={**self.stopped.team.traces, "Drone3": tuple(trace)})
        self.assertIn("Drone3 was told", " ".join(no_new_command(run)))

    # ----------------------------------------------------------------- roles

    def test_a_role_with_no_cause(self):
        def stray(p):
            p["Drone2"]["roles"]["log"].append({"at": 40.0, "before": "scout", "after": "relay", "why": "?"})
        self.assertIn("Drone2 became a relay at 40.0 s with nothing of its own",
                      " ".join(roles_from_interactions(with_policies(self.stopped, stray))))

    def test_a_relay_that_begins_as_a_reserve_comes_free(self):
        # The live variant: the survivor finishes while the stopped drone is unreachable, not yet failed.
        from agentic_uav.experiments.recovery import fly_recovery_on_mock
        live = scenarios.load_scenario("search_relay_live_small")
        run = fly_recovery_on_mock(live, CONFIG, HEALTH, "Drone2 stopped", {"Drone2": 17.0})
        self.assertIn("relay", [c["after"] for c in run.policies["Drone1"]["roles"]["log"]])
        self.assertEqual(roles_from_interactions(run), [])
        self.assertTrue(run.met)

    def test_a_role_change_not_announced(self):
        kept = tuple(d for d in self.stopped.team.deliveries
                     if not (d.message.message_type.value == "role_change" and d.message.sender_id == "Drone4"))
        self.assertIn("was not announced", " ".join(roles_from_interactions(with_team(self.stopped, deliveries=kept))))

    # ------------------------------------------------- deterministic, known

    def test_two_flights_that_differ(self):
        def move(p):
            p["Drone4"]["roles"]["log"][0]["at"] += 0.5
        self.assertIn("the records differ", " ".join(deterministic(self.stopped, with_policies(self.stopped, move))))
        self.assertEqual(deterministic(self.stopped, self.flights["Drone1 stopped again"]), [])

    def test_a_belief_that_is_wrong(self):
        trace = list(self.stopped.team.traces["Drone2"])
        belief = copy.deepcopy(trace[3].belief)
        belief["self"]["position"][0] += 5.0
        trace[3] = dataclasses.replace(trace[3], belief=belief)
        self.assertFalse(known_exactly(with_team(self.stopped, traces={**self.stopped.team.traces,
                                                                       "Drone2": tuple(trace)}), TEAM)["ok"])

    def test_one_failing_check_fails_the_seed(self):
        flights = dict(self.flights, **{"Drone1 stopped again": self.flights["Drone2 stopped"]})
        checks = exit_checks(flights, TEAM)
        self.assertFalse(checks["deterministic"]["ok"])
        self.assertFalse(checks["all"])


class BesideTheExitTests(unittest.TestCase):

    def test_reprioritization(self):
        short = dataclasses.replace(TEAM, mission=dataclasses.replace(TEAM.mission, deadline_s=250.0))
        from agentic_uav.experiments.recovery import fly_recovery_on_mock
        run = fly_recovery_on_mock(short, CONFIG, HEALTH, "trouble", {"Drone1": 60.0})
        self.assertEqual(judge_reprioritization(run, "Drone1", 250.0), reprioritization(TEAM, CONFIG, HEALTH))

        def kept(p):
            p["Drone3"]["net"]["abandoned"] = []
        bad = judge_reprioritization(with_policies(run, kept), "Drone1", 250.0)
        self.assertFalse(bad["ok"])
        self.assertIn("Drone3 abandoned [], not search S3 alone", bad["problems"])
        chased = dataclasses.replace(run, searched={**run.searched, "Drone4": ["search S2", "search S3"]})
        self.assertIn("search S3 was chased after it was abandoned", judge_reprioritization(chased, "Drone1", 250.0)["problems"])
        r = reprioritization(TEAM, CONFIG, HEALTH)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual((r["stopped"], r["task"], r["deadline_s"]), ("Drone1", "search S3", 250.0))
        self.assertEqual(sorted(r["abandoned"]), ["Drone2", "Drone3", "Drone4"])
        self.assertFalse(r["mission_met"])
        self.assertLessEqual(r["ended_s"], 250.0)

    def test_the_emergence_report(self):
        rows = [{"checks": {k: {"ok": True} for k in CHECKS}, "validated": True,
                 "division": {"Drone1": ["search S3"], "Drone2": ["search S4"], "Drone3": ["search S1"],
                              "Drone4": ["search S2"]}}] * 3
        rep = emergence_report(rows, TEAM)
        self.assertEqual(len(rep["conditions"]), 5)
        self.assertTrue(all(v["held"] for v in rep["conditions"].values()))
        px = rep["proxies"]
        self.assertEqual(px["assignment distance from one drone per sector"]["drones_off_the_naive_assignment"],
                         ["Drone1", "Drone2", "Drone3", "Drone4"])
        self.assertEqual(px["allocation divergence across seeds"]["distinct_divisions"], 1)
        other = dict(rows[0], division={"Drone1": ["search S1"], "Drone2": ["search S2"], "Drone3": ["search S3"],
                                         "Drone4": ["search S4"]})
        self.assertEqual(emergence_report(rows + [other], TEAM)["proxies"]["allocation divergence across seeds"]
                         ["distinct_divisions"], 2)
        failing = [dict(rows[0], checks={**rows[0]["checks"], "no_new_command": {"ok": False}})]
        self.assertFalse(emergence_report(failing, TEAM)["conditions"]["a team-level objective"]["held"])

    def test_the_flight_code_gives_no_task(self):
        # 9.4's "no central controller", in the code: the flights call assign_team and never assign.
        import ast
        for name in ("recovery.py", "recovery_exit.py", "allocation.py"):
            path = os.path.join(ROOT, "agentic_uav", "experiments", name)
            with open(path, encoding="utf-8") as h:
                tree = ast.parse(h.read())
            calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            with self.subTest(module=name):
                self.assertNotIn("assign", calls)


class ScriptTests(unittest.TestCase):

    def run_failing(self, **patches):
        import recovery_exit
        from unittest import mock
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with mock.patch.multiple(recovery_exit, **patches), redirect_stdout(buffer):
                code = recovery_exit.main(["--seeds", "17", "--out", out])
            return code, buffer.getvalue()
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_a_failing_seed_fails_the_run(self):
        import recovery_exit
        real = recovery_exit.exit_checks

        def failing(flights, scenario):
            checks = real(flights, scenario)
            checks["continued"] = {"ok": False, "problems": ["a test: not continued"]}
            checks["all"] = False
            return checks
        code, text = self.run_failing(exit_checks=failing)
        self.assertEqual(code, 1)
        self.assertIn("**Exit criterion: NOT MET**", text)

    def test_a_failed_reprioritization_fails_the_run(self):
        import recovery_exit
        real = recovery_exit.reprioritization

        def failing(*a, **k):
            return dict(real(*a, **k), ok=False, problems=["a test: chased"])
        code, text = self.run_failing(reprioritization=failing)
        self.assertEqual(code, 1)
        self.assertIn("a test: chased", text)

    def test_one_seed_writes_its_record(self):
        import recovery_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = recovery_exit.main(["--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            jsonl = next(f for f in os.listdir(out) if f.endswith(".jsonl"))
            with open(os.path.join(out, jsonl), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            head = rows[0]
            self.assertTrue(head["exit_criterion_met"])
            self.assertEqual((head["allocation_manifest"], head["recovery_manifest"]),
                             ("configs/allocation/default.toml", "configs/recovery/default.toml"))
            self.assertEqual(head["health"], HEALTH.as_json())
            self.assertTrue(head["reprioritization"]["ok"])
            self.assertEqual(len(head["emergence"]["conditions"]), 5)
            self.assertEqual([r["kind"] for r in rows].count("records"), 1)
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
