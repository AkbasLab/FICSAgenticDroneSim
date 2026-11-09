"""A named NavRL profile fills in unset NAVRL_* variables, never overrides ones already set, and an unknown name fails loudly."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.navrl_profile import PROFILES_PATH, apply_profile


class NavrlProfileTests(unittest.TestCase):
    def test_sets_unset_variables(self):
        env = {}
        applied = apply_profile("limit5", environ=env)
        self.assertEqual(env["NAVRL_ACTION_LIMIT"], "5")
        self.assertEqual(env["NAVRL_GOVERNOR"], "1")
        self.assertEqual(env["NAVRL_MIN_SPEED"], "1.5")
        self.assertEqual(applied, {k: v for k, v in env.items()})
        self.assertNotIn("_about", env)

    def test_an_explicit_variable_wins(self):
        env = {"NAVRL_TREE_MARGIN": "3.0"}
        apply_profile("limit5", environ=env)
        self.assertEqual(env["NAVRL_TREE_MARGIN"], "3.0")

    def test_no_profile_changes_nothing(self):
        env = {}
        self.assertEqual(apply_profile(None, environ=env), {})
        self.assertEqual(env, {})

    def test_the_name_can_come_from_the_environment(self):
        env = {"NAVRL_PROFILE": "limit5_medium"}
        apply_profile(environ=env)
        self.assertEqual(env["NAVRL_LANE_INSET"], "4.5")

    def test_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            apply_profile("nope", environ={})

    def test_the_shipped_profiles_only_use_known_switches(self):
        known = {"NAVRL_ACTION_LIMIT", "NAVRL_VEL_INPUT", "NAVRL_GOVERNOR", "NAVRL_DOWN_ROW", "NAVRL_TREE_MARGIN",
                 "NAVRL_LANE_INSET", "NAVRL_MIN_SPEED", "NAVRL_GOV_CLEAR", "NAVRL_GOV_DIV"}
        with open(PROFILES_PATH) as f:
            profiles = json.load(f)
        for name, values in profiles.items():
            self.assertLessEqual({k for k in values if not k.startswith("_")}, known, name)


if __name__ == "__main__":
    unittest.main()
