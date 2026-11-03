#!/usr/bin/env python3
"""Tests for Phase 7's exit: each check passes on real flights, and fails when what it guards is broken.

    python -m unittest discover tests

WHY THESE EXIST
---------------
The exit -- four agents exchange heartbeats and status, and their team
beliefs update only when messages are delivered -- is shown by six checks on
the same seed flown talking, blocked and silent. A check that cannot fail
shows nothing, so each is held here to a real flight altered to break it: a
record that came in no delivered message, or too late, or from the wrong
drone, or carrying the wrong task or age; something undelivered believed; an
agent that sent or heard nothing of a kind; a blocked flight that heard
something; talking that changed a decision. And the knowledge log's rule for
teammates that are heard: a teammate's position may stand in its own record,
true to where it was when it spoke, and nowhere else.
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
from agentic_uav.experiments.knowledge import Truth, entry_json, knowledge_entry  # noqa: E402
from agentic_uav.experiments.message_log import message_log  # noqa: E402
from agentic_uav.experiments.messaging import (  # noqa: E402
    BLOCKED_RANGE_M,
    exchanged,
    exit_checks,
    messaging_flights,
    only_on_delivery,
    team_beliefs,
)

TEAM = scenarios.load_scenario("search_relay_001")


def retrace(run, drone, index, change):
    """`run` with one decision's belief altered by `change`."""
    entries = list(run.traces[drone])
    belief = copy.deepcopy(entries[index].belief)
    change(belief)
    entries[index] = dataclasses.replace(entries[index], belief=belief)
    return dataclasses.replace(run, traces={**run.traces, drone: tuple(entries)})


class RealFlightTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flights = messaging_flights(TEAM, 17)
        cls.talk = cls.flights["talking"]
        cls.rows = message_log(cls.talk.deliveries, cls.talk.traces, cls.talk.start)
        cls.checks = exit_checks(cls.flights, TEAM)
        # A decision of Drone1's whose belief holds a heard record of Drone2.
        cls.heard_at = next(i for i, e in enumerate(cls.talk.traces["Drone1"])
                            if isinstance(e.belief["team"]["Drone2"], dict))

    def test_every_check_passes(self):
        for name in ("met", "exchanged", "only_on_delivery", "known_exactly", "blocked_moves_nothing", "steers_nothing"):
            with self.subTest(check=name):
                self.assertTrue(self.checks[name]["ok"], self.checks[name]["problems"][:5])
        self.assertTrue(self.checks["all"])
        self.assertGreater(self.checks["only_on_delivery"]["records_checked"], 200)

    def test_the_three_flights_are_what_they_say(self):
        self.assertEqual(BLOCKED_RANGE_M, 1.0)
        self.assertEqual(self.checks["blocked_moves_nothing"]["delivered"], 0)
        self.assertGreater(self.checks["blocked_moves_nothing"]["sent"], 1000)
        self.assertEqual(self.flights["silent"].deliveries, ())

    # ----------------------------------------------------- only on delivery

    def broken(self, change, drone="Drone1"):
        run = retrace(self.talk, drone, self.heard_at, change)
        return " ".join(only_on_delivery(run, self.rows)[1])

    def test_a_record_from_no_delivered_message(self):
        self.assertIn("was never delivered to it", self.broken(lambda b: b["team"]["Drone2"].update(message_id="Drone2#9999")))

    def test_a_record_from_another_drones_message(self):
        mid = next(r["message_id"] for r in self.rows if r["sender"] == "Drone3" and r["recipient"] == "Drone1"
                   and r["status"] == "delivered")
        self.assertIn("is not Drone2's", self.broken(lambda b: b["team"]["Drone2"].update(message_id=mid)))

    def test_a_record_delivered_after_the_decision(self):
        late = next(r for r in self.rows if r["recipient"] == "Drone1" and r["sender"] == "Drone2"
                    and r["status"] == "delivered" and r["delivered_s"] > 60.0)
        self.assertIn("was delivered after the decision",
                      self.broken(lambda b: b["team"]["Drone2"].update(message_id=late["message_id"])))

    def test_the_wrong_task_or_age(self):
        self.assertIn("but Drone2 was told 'search S2'", self.broken(lambda b: b["team"]["Drone2"].update(task="search S4")))
        self.assertIn("aged", self.broken(lambda b: b["team"]["Drone2"].update(age_s=b["team"]["Drone2"]["age_s"] + 1.0)))

    def test_something_undelivered_believed(self):
        rows = copy.deepcopy(self.rows)
        far = next(r for r in rows if r["status"] == "out_of_range")
        far["in_belief_at_s"] = 50.0
        self.assertIn(f"believed or read {far['message_id']}, which was out_of_range",
                      " ".join(only_on_delivery(self.talk, rows)[1]))

    def test_no_record_at_all_is_not_a_pass(self):
        silent = self.flights["silent"]
        checked, problems = only_on_delivery(silent, message_log(silent.deliveries, silent.traces, silent.start))
        self.assertEqual((checked, problems), (0, []))
        checks = exit_checks({**self.flights, "talking": dataclasses.replace(silent, label="talking")}, None)
        self.assertFalse(checks["only_on_delivery"]["ok"])
        self.assertIn("no teammate record was ever held", checks["only_on_delivery"]["problems"])

    # -------------------------------------------------------- the others

    def test_an_agent_that_sent_or_heard_nothing_of_a_kind(self):
        no_status = [r for r in self.rows if not (r["sender"] == "Drone3" and r["type"] == "status_update")]
        self.assertIn("Drone3 sent no status_update", exchanged(no_status, ["Drone1", "Drone2", "Drone3", "Drone4"]))
        deaf = [r for r in self.rows if not (r["recipient"] == "Drone4" and r["type"] == "heartbeat")]
        self.assertIn("Drone4 received no heartbeat", exchanged(deaf, ["Drone1", "Drone2", "Drone3", "Drone4"]))

    def test_a_blocked_flight_that_sent_nothing_shows_nothing(self):
        checks = exit_checks({**self.flights, "blocked": self.flights["silent"]})
        self.assertFalse(checks["blocked_moves_nothing"]["ok"])
        self.assertIn("the blocked flight sent nothing", checks["blocked_moves_nothing"]["problems"])

    def test_a_blocked_flight_that_heard_something(self):
        checks = exit_checks({**self.flights, "blocked": self.talk})
        self.assertFalse(checks["blocked_moves_nothing"]["ok"])
        self.assertTrue(any("believed Drone" in p for p in checks["blocked_moves_nothing"]["problems"]))

    def test_talking_that_changed_a_decision(self):
        talk = self.talk
        entries = list(talk.traces["Drone2"])
        entries[1] = dataclasses.replace(entries[1], action="something else")
        changed = dataclasses.replace(talk, traces={**talk.traces, "Drone2": tuple(entries)})
        checks = exit_checks({**self.flights, "talking": changed})
        self.assertFalse(checks["steers_nothing"]["ok"])
        self.assertTrue(checks["met"]["ok"])
        self.assertFalse(checks["all"])                     # one check failing fails the seed
        self.assertIn("talking's decisions differ from the silent flight's", checks["steers_nothing"]["problems"])

    def test_a_flight_that_did_not_meet_its_tasks(self):
        checks = exit_checks({**self.flights, "talking": dataclasses.replace(self.talk, finished={"Drone1": False})})
        self.assertFalse(checks["met"]["ok"])

    def test_team_beliefs_compact_and_in_order(self):
        rows = team_beliefs(self.talk)
        self.assertEqual(len(rows), sum(len(t) for t in self.talk.traces.values()))
        self.assertEqual([(r["at_s"], r["drone"]) for r in rows], sorted((r["at_s"], r["drone"]) for r in rows))
        heard = next(r for r in rows if r["drone"] == "Drone1" and isinstance(r["team"]["Drone2"], dict))
        self.assertEqual(set(heard["team"]["Drone2"]), {"message_id", "task", "age_s", "current"})

    # ------------------------------------------- the knowledge log, heard teammates

    def knowledge(self, change=None, index=None):
        row = entry_json(self.talk.traces["Drone1"][self.heard_at if index is None else index])
        if change:
            change(row["belief"])
        truth = Truth(TEAM, self.talk.trajectories, self.talk.start, self.talk.report.until)
        return " ".join(knowledge_entry(row, "Drone1", truth).problems)

    def test_a_heard_teammates_position_is_allowed_in_its_own_record(self):
        self.assertEqual(self.knowledge(), "")

    def test_a_record_that_says_the_wrong_place(self):
        def move(b):
            b["team"]["Drone2"]["position"][0] += 2.0
        self.assertIn("incorrect: its record of Drone2 is 2.000 m from where Drone2 was when it spoke", self.knowledge(move))

    def test_a_record_older_than_it_says(self):
        # At a decision where Drone2 was really moving when it spoke, a record
        # claiming to be a second fresher than it is cannot be true.
        truth = Truth(TEAM, self.talk.trajectories, self.talk.start, self.talk.report.until)
        import math

        def moving(i):
            e = self.talk.traces["Drone1"][i]
            r = e.belief["team"]["Drone2"]
            if not isinstance(r, dict):
                return False
            spoke = e.at - r["age_s"]
            return math.dist(truth.position("Drone2", spoke), truth.position("Drone2", spoke + 1.0)) > 2.0
        index = next(i for i in range(len(self.talk.traces["Drone1"])) if moving(i))
        self.assertEqual(self.knowledge(index=index), "")
        self.assertIn("incorrect: its record of Drone2", self.knowledge(
            lambda b: b["team"]["Drone2"].update(age_s=b["team"]["Drone2"]["age_s"] - 1.0), index=index))

    def test_one_teammates_place_in_anothers_record_is_a_leak(self):
        # Drone2's record may say where Drone2 is; it may not say where Drone3 is.
        truth = Truth(TEAM, self.talk.trajectories, self.talk.start, self.talk.report.until)
        at = self.talk.traces["Drone1"][self.heard_at].at
        x, y, _ = truth.position("Drone3", at)
        self.assertIn("leak: it knew where Drone3 really was, beyond what it heard from it",
                      self.knowledge(lambda b: b["team"]["Drone2"].update(role=[round(x, 3), round(y, 3)])))

    def test_a_teammates_position_anywhere_else_is_a_leak(self):
        truth = Truth(TEAM, self.talk.trajectories, self.talk.start, self.talk.report.until)
        at = self.talk.traces["Drone1"][self.heard_at].at
        x, y, _ = truth.position("Drone3", at)
        self.assertIn("leak: it knew where Drone3 really was, beyond what it heard from it",
                      self.knowledge(lambda b: b["mission"]["progress"].update(hint=[round(x, 3), round(y, 3)])))


class ScriptTests(unittest.TestCase):

    def test_one_seed_writes_its_record(self):
        import messaging_exit
        out = tempfile.mkdtemp()
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = messaging_exit.main(["--seeds", "17", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            files = sorted(os.listdir(out))
            self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
            with open(os.path.join(out, files[0]), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            self.assertEqual(rows[0]["kind"], "header")
            self.assertTrue(rows[0]["exit_criterion_met"])
            self.assertEqual((rows[0]["range_m"], rows[0]["blocked_range_m"], rows[0]["delay_s"]), (100.0, 1.0, 0.1))
            seed = next(r for r in rows if r["kind"] == "seed")
            self.assertTrue(seed["checks"]["all"])
            self.assertEqual(len([r for r in rows if r["kind"] == "message"]), seed["checks"]["messages"]["deliveries"])
            self.assertIn("**Exit criterion: MET**", buffer.getvalue())
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
