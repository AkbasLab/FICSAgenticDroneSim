#!/usr/bin/env python3
"""Tests for the baseline agent's plan validator.

    python -m unittest discover tests

WHY THESE EXIST
---------------
`validate()` is the gate between a language model and an aircraft. It is the
one place in the baseline that decides a plan is unflyable, and the one place
that silently rewrites a plan -- a positive altitude is normalised rather than
obeyed, because obeying it would fly the drone into the ground.

It also sits inside a component that is deliberately FROZEN: once the mission
set has been run, every result cites this behaviour. A subtle change here does
not break anything visibly, it just makes the recorded numbers describe a
system that no longer exists. Tests are what make that change loud.

No simulator, no model, no network: the validator is pure, so these run in
milliseconds anywhere. stdlib unittest rather than pytest, so a fresh clone
needs no test dependency at all.

WHAT IS NOT TESTED HERE, AND WHY
--------------------------------
* plan_for()     -- calls a language model; non-deterministic and slow
* DroneRunner    -- needs a simulator; covered by flight tests in Phase 16
* write_settings -- writes to the Documents folder, which a test should not
                    touch. Testing it properly needs the function to accept a
                    target directory, and changing the baseline's signature for
                    the convenience of a test is the wrong trade while the
                    mission set is still unrun.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baseline"))

import open_loop_agent as agent  # noqa: E402  (path set above)


class ShapeTests(unittest.TestCase):
    """The plan must be an object with a non-empty 'plan' array."""

    def test_accepts_a_minimal_plan(self):
        steps, notes = agent.validate({"plan": [{"action": "land"}]})
        self.assertEqual([s["action"] for s in steps], ["land"])
        self.assertEqual(notes, [])

    def test_rejects_a_missing_plan_key(self):
        with self.assertRaises(agent.PlanError):
            agent.validate({"steps": [{"action": "land"}]})

    def test_rejects_a_non_dict(self):
        with self.assertRaises(agent.PlanError):
            agent.validate([{"action": "land"}])

    def test_rejects_an_empty_plan(self):
        # A model that returns {"plan": []} has answered nothing. Flying it
        # would arm the aircraft, take off and immediately hover.
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": []})

    def test_rejects_a_step_that_is_not_an_object(self):
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": ["land"]})

    def test_rejects_an_unknown_action(self):
        # The schema's enum should prevent this, but validate() does not trust
        # the schema: a hand-written or differently-generated plan reaches here
        # too.
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "barrel_roll", "duration": 2}]})


class DurationTests(unittest.TestCase):
    """Timed actions need a positive, bounded duration."""

    TIMED = ("fly_straight", "fly_backward", "fly_left", "fly_right", "hover")

    def test_accepts_a_normal_duration(self):
        for action in self.TIMED:
            with self.subTest(action=action):
                steps, _ = agent.validate({"plan": [{"action": action, "duration": 5}]})
                self.assertEqual(steps[0]["duration"], 5)

    def test_rejects_a_missing_duration(self):
        for action in self.TIMED:
            with self.subTest(action=action):
                with self.assertRaises(agent.PlanError):
                    agent.validate({"plan": [{"action": action}]})

    def test_rejects_zero_and_negative(self):
        # Zero is a step that does nothing; negative is meaningless. Both
        # indicate the model misunderstood, so neither should reach a vehicle.
        for value in (0, -3):
            with self.subTest(duration=value):
                with self.assertRaises(agent.PlanError):
                    agent.validate({"plan": [{"action": "hover", "duration": value}]})

    def test_rejects_a_duration_over_the_leg_limit(self):
        too_long = agent.MAX_DURATION + 1
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "fly_straight", "duration": too_long}]})

    def test_rejects_a_non_numeric_duration(self):
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "hover", "duration": "three"}]})


class AltitudeTests(unittest.TestCase):
    """NED: negative is up. This is where the agent protects itself."""

    def test_accepts_a_negative_altitude(self):
        steps, notes = agent.validate({"plan": [{"action": "set_altitude", "z": -20}]})
        self.assertEqual(steps[0]["z"], -20.0)
        self.assertEqual(notes, [])

    def test_normalises_a_positive_altitude_and_says_so(self):
        # The model meant "20 metres up" and wrote z=20, which in NED is 20
        # metres underground. The value is corrected AND reported: a silent fix
        # would hide a real model failure mode from the results.
        steps, notes = agent.validate({"plan": [{"action": "set_altitude", "z": 20}]})
        self.assertEqual(steps[0]["z"], -20.0)
        self.assertEqual(len(notes), 1)
        self.assertIn("negative is up", notes[0])

    def test_rejects_ground_level(self):
        # Above MIN_ALTITUDE is at or below the ground in NED terms.
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "set_altitude", "z": -1}]})

    def test_rejects_above_the_ceiling(self):
        too_high = agent.MAX_ALTITUDE - 10       # more negative = higher
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "set_altitude", "z": too_high}]})

    def test_rejects_a_missing_z(self):
        with self.assertRaises(agent.PlanError):
            agent.validate({"plan": [{"action": "set_altitude"}]})


class FlyToTests(unittest.TestCase):
    """fly_to needs a coordinate; z is optional and defaults to cruise."""

    def test_accepts_a_full_coordinate(self):
        steps, _ = agent.validate({"plan": [{"action": "fly_to", "x": 10, "y": -5, "z": -15}]})
        self.assertEqual((steps[0]["x"], steps[0]["y"], steps[0]["z"]), (10, -5, -15.0))

    def test_defaults_z_to_cruise_altitude(self):
        # "Return home" plans routinely omit z. Cruise height is the safe
        # assumption -- defaulting to 0 would mean ground level.
        steps, _ = agent.validate({"plan": [{"action": "fly_to", "x": 0, "y": 0}]})
        self.assertEqual(steps[0]["z"], agent.CRUISE_ALTITUDE)

    def test_normalises_a_positive_z(self):
        steps, notes = agent.validate({"plan": [{"action": "fly_to", "x": 0, "y": 0, "z": 15}]})
        self.assertEqual(steps[0]["z"], -15.0)
        self.assertEqual(len(notes), 1)

    def test_rejects_a_missing_coordinate(self):
        for missing in ("x", "y"):
            step = {"action": "fly_to", "x": 1, "y": 2}
            del step[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(agent.PlanError):
                    agent.validate({"plan": [step]})


class SequenceTests(unittest.TestCase):
    """Whole plans, in the shapes the mission set actually produces."""

    def test_a_realistic_multi_step_plan(self):
        # M03: go up to 15 metres, fly forward for 5 seconds, then land.
        plan = {"plan": [
            {"action": "set_altitude", "z": -15},
            {"action": "fly_straight", "duration": 5},
            {"action": "land"},
        ]}
        steps, notes = agent.validate(plan)
        self.assertEqual([s["action"] for s in steps], ["set_altitude", "fly_straight", "land"])
        self.assertEqual(notes, [])

    def test_one_bad_step_rejects_the_whole_plan(self):
        # All-or-nothing: a plan is flown to the end without reconsideration,
        # so a single unflyable step makes the entire plan unflyable.
        plan = {"plan": [
            {"action": "fly_straight", "duration": 5},
            {"action": "hover", "duration": -1},
            {"action": "land"},
        ]}
        with self.assertRaises(agent.PlanError):
            agent.validate(plan)

    def test_step_numbers_in_errors_are_one_based(self):
        # Error messages are read against a plan a human is looking at, where
        # the first step is step 1.
        plan = {"plan": [
            {"action": "land"},
            {"action": "hover", "duration": 0},
        ]}
        with self.assertRaises(agent.PlanError) as caught:
            agent.validate(plan)
        self.assertIn("step 2", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
