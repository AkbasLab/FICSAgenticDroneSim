#!/usr/bin/env python3
"""Tests for the LLM channel: a decision written as text, and read back (Phase 11, step 4).

    python -m unittest discover -s tests -p test_proposal.py

WHY THESE EXIST
---------------
From Phase 12 every decision an LLM makes reaches the drone through
`parse_proposal`. Two things must hold. A well-formed answer must come back
as exactly the decision it states: a channel that bent a decision on the way
would put the bend down to the model. And a badly-formed one must never
raise and never be guessed at -- it comes back INVALID, with the text and
every problem, for the guardian to refuse. These try the round trip over
every kind of command the policies issue, and each way a model's text can go
wrong that the exit injects, and more.
"""

import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.decision import Decision, DecisionKind  # noqa: E402
from agentic_uav.agents.proposal import parse_proposal, render_proposal  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.safety.guardian import problem_check  # noqa: E402

W = Waypoint(80.0, -40.0, 12.0)
EVERY_SKILL = (
    S.TakeOffCommand(altitude_m=12.0, speed_mps=5.0),
    S.GoToWaypointCommand(W, heading_deg=90.0),
    S.FollowWaypointsCommand((W, Waypoint(13.0, -17.5, 12.0)), speed_mps=5.0, timeout_s=60.0),
    S.SearchRegionCommand(region=Region(40.0, -80.0, 120.0, 0.0), altitude_m=12.0, spacing_m=17.32),
    S.InspectPointCommand(target=Waypoint(65.0, -25.0, 0.0)),
    S.HoldPositionCommand(duration_s=5.0),
    S.RendezvousCommand(W, arrive_by=30.0, hold_until=40.0),
    S.ActAsRelayCommand(W, duration_s=12.5),
    S.ReturnHomeCommand(altitude_m=16.0),
    S.LandCommand(),
    S.EmergencyHoldCommand(),
)


def checks_of(decision):
    return sorted(problem_check(p) for p in decision.reason.split("; "))


class RoundTripTests(unittest.TestCase):
    def test_every_skill_comes_back_as_it_went(self):
        self.assertEqual({c.skill for c in EVERY_SKILL}, set(S.SkillName))
        for cmd in EVERY_SKILL:
            with self.subTest(skill=cmd.skill.value):
                d = Decision.start(cmd, "an objective", "a reason")
                text = render_proposal(d)
                back = parse_proposal(text, issued_at=12.5)
                self.assertEqual(back.kind, DecisionKind.START)
                self.assertEqual((back.command, back.objective, back.reason), (cmd, d.objective, d.reason))
                self.assertEqual((back.issued_at, back.raw), (12.5, text))

    def test_the_other_kinds_come_back(self):
        for d in (Decision.carry_on("o", "r"), Decision.abort(None, "r"), Decision.finish("o", "")):
            back = parse_proposal(render_proposal(d))
            self.assertEqual((back.kind, back.objective, back.reason, back.command), (d.kind, d.objective, d.reason, None))

    def test_a_number_written_as_an_integer_is_the_same_number(self):
        text = json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                           "parameters": {"waypoint": {"x": 80, "y": -40, "altitude_m": 12}}})
        self.assertEqual(parse_proposal(text).command, S.GoToWaypointCommand(W))

    def test_omitted_parameters_take_the_skills_defaults(self):
        text = json.dumps({"decision": "start", "skill": "TAKE_OFF"})
        self.assertEqual(parse_proposal(text).command, S.TakeOffCommand())

    def test_the_rendering_is_sorted_and_plain_json(self):
        text = render_proposal(Decision.start(S.FollowWaypointsCommand((W,)), "o"))
        self.assertEqual(text, json.dumps(json.loads(text), sort_keys=True))
        self.assertEqual(json.loads(text)["parameters"]["waypoints"], [{"x": 80.0, "y": -40.0, "altitude_m": 12.0}])


class InvalidTests(unittest.TestCase):
    def invalid(self, text, check, word=None):
        d = parse_proposal(text, issued_at=3.0)
        self.assertEqual(d.kind, DecisionKind.INVALID)
        self.assertIsNone(d.command)
        self.assertEqual((d.raw, d.issued_at), (text, 3.0))
        self.assertIn(check, checks_of(d))
        if word:
            self.assertIn(word, d.reason)
        for p in d.reason.split("; "):
            self.assertTrue(p.startswith("[") and "] " in p, p)       # every problem named, none blank
        return d

    def go(self, **params):
        return json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                           "parameters": {"waypoint": {"x": 80, "y": -40, "altitude_m": 12}, **params}})

    def test_not_json(self):
        self.invalid('{"decision": "start", "skill": "GO_TO_WAYPOINT", "parameters": {"waypoint": {"x": 80, "y":',
                     "proposal", "not JSON")
        self.invalid("Sure! I will fly to the sector.", "proposal", "not JSON")
        self.invalid("", "proposal", "not JSON")

    def test_not_one_object(self):
        self.invalid('"start"', "proposal", "not a decision object")
        self.invalid("[]", "proposal", "array")
        self.invalid("[" + self.go() + "]", "proposal", "array")

    def test_two_commands_in_one_answer_conflict(self):
        self.invalid("[" + self.go() + ", " + json.dumps({"decision": "start", "skill": "LAND"}) + "]", "conflict")
        self.invalid(json.dumps({"decision": "abort", "skill": "LAND"}), "conflict")

    def test_an_unknown_skill_kind_or_key(self):
        self.invalid(json.dumps({"decision": "start", "skill": "BARREL_ROLL", "parameters": {}}), "proposal",
                     "BARREL_ROLL")
        self.invalid(json.dumps({"decision": "fly"}), "proposal", "'fly'")
        self.invalid(json.dumps({"decision": "invalid"}), "proposal")
        self.invalid(json.dumps({"skill": "LAND"}), "proposal", "None")
        d = json.loads(self.go())
        d["override_guardian"] = True
        self.invalid(json.dumps(d), "proposal", "override_guardian")
        self.invalid(self.go(altitude_m=30), "proposal", "no parameter 'altitude_m'")

    def test_numbers_that_are_not_numbers(self):
        self.invalid(self.go().replace('"altitude_m": 12', '"altitude_m": NaN'), "proposal", "is nan")
        self.invalid(self.go().replace('"x": 80', '"x": Infinity'), "proposal", "inf")
        self.invalid(self.go().replace('"altitude_m": 12', '"altitude_m": "high"'), "proposal", "'high'")
        self.invalid(self.go(speed_mps=True), "proposal", "True")
        self.invalid(self.go(speed_mps=None), "proposal")

    def test_points_and_regions_must_have_exactly_their_fields(self):
        self.invalid(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                                 "parameters": {"waypoint": {"x": 1, "y": 2}}}), "proposal", "exactly")
        self.invalid(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                                 "parameters": {"waypoint": [1, 2, 3]}}), "proposal", "exactly")
        self.invalid(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                                 "parameters": {"waypoint": {"x": 1, "y": 2, "altitude_m": 12, "z": -12}}}),
                     "proposal", "exactly")
        self.invalid(json.dumps({"decision": "start", "skill": "SEARCH_REGION",
                                 "parameters": {"region": {"x_min": 1, "y_min": 2, "x_max": 0, "y_max": 3}}}),
                     "proposal", "negative size")
        self.invalid(json.dumps({"decision": "start", "skill": "FOLLOW_WAYPOINTS",
                                 "parameters": {"waypoints": {"x": 1}}}), "proposal", "list of points")

    def test_values_the_skill_itself_refuses(self):
        self.invalid(self.go(speed_mps=50), "proposal", "speed 50.0 m/s outside")
        self.invalid(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT"}), "proposal", "Waypoint")
        self.invalid(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                                 "parameters": {"waypoint": {"x": 1, "y": 2, "altitude_m": -5}}}), "proposal")

    def test_every_problem_is_reported_not_only_the_first(self):
        d = json.loads(self.go())
        d.update(extra=1, objective=7)
        d["parameters"]["speed_mps"] = "fast"
        got = self.invalid(json.dumps(d), "proposal")
        self.assertEqual(len(got.reason.split("; ")), 3)

    def test_nothing_raises(self):
        for text in ("null", "1", "true", "{}", '{"decision": null}', '{"decision": "start"}',
                     '{"decision": "start", "skill": null}', '{"decision": "start", "skill": "LAND", "parameters": 3}',
                     '{"decision": "start", "skill": "LAND", "parameters": {"timeout_s": "x; y"}}', "\x00", "{" * 50):
            with self.subTest(text=text):
                d = parse_proposal(text)
                self.assertEqual(d.kind, DecisionKind.INVALID)
                for p in d.reason.split("; "):
                    self.assertTrue(p.startswith("["), p)

    def test_a_valid_answer_is_not_thereby_safe(self):
        d = parse_proposal(json.dumps({"decision": "start", "skill": "GO_TO_WAYPOINT",
                                       "parameters": {"waypoint": {"x": 25, "y": 0, "altitude_m": 90}}}))
        self.assertEqual(d.kind, DecisionKind.START)          # the guardian's to refuse, not the reader's
        self.assertTrue(math.isfinite(d.command.waypoint.altitude_m))


if __name__ == "__main__":
    unittest.main()
