#!/usr/bin/env python3
"""Tests for agentic_uav.coordination.roles: scout, relay, reserve (AUV-09, 9.1).

    python -m unittest discover tests

WHY THESE EXIST
---------------
A role must follow from the drone's own belief and nothing else -- what it
holds, what it hears of its teammates -- or role changes would not "result
from agent interactions" (AUV-09, 9.4). These pin each role's trigger, their
priority (a task in hand outranks a relay, a relay outranks waiting), that
only a change is logged, where a relay holds, and the message that announces
a change.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.coordination.roles import Role, RoleKeeper, choose_role, relay_point  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message, payload_problems  # noqa: E402


class ChooseTests(unittest.TestCase):

    def test_the_three_roles(self):
        self.assertEqual({r.value for r in Role}, {"scout", "relay", "reserve"})

    def test_a_task_in_hand_makes_a_scout(self):
        self.assertEqual(choose_role("search S2", ()), (Role.SCOUT, "holds search S2"))

    def test_a_task_outranks_a_relay(self):
        self.assertEqual(choose_role("search S2", ("Drone3",))[0], Role.SCOUT)

    def test_free_with_a_teammate_unreachable_makes_a_relay(self):
        role, why = choose_role(None, ("Drone4", "Drone3"))
        self.assertEqual(role, Role.RELAY)
        self.assertEqual(why, "Drone3, Drone4 unreachable, not failed: bridge toward it")

    def test_free_with_nothing_calling_makes_a_reserve(self):
        self.assertEqual(choose_role(None, ()), (Role.RESERVE, "holds no task: available for one returned"))

    def test_a_relay_holds_half_way_to_the_silent_teammate(self):
        self.assertEqual(relay_point((-8.0, 0.0), (152.0, -40.0)), (72.0, -20.0))


class KeeperTests(unittest.TestCase):

    def test_it_starts_a_reserve_and_logs_only_changes(self):
        k = RoleKeeper("Drone2", start=0.0)
        self.assertEqual(k.role, Role.RESERVE)
        self.assertIsNone(k.update(0.0, None, ()))
        c = k.update(1.0, "search S4", ())
        self.assertEqual((c.before, c.after, c.at), (Role.RESERVE, Role.SCOUT, 1.0))
        self.assertIsNone(k.update(1.5, "search S4", ("Drone3",)))         # still a scout
        k.update(120.0, None, ("Drone3",))
        k.update(140.0, None, ())
        k.update(150.0, "search S1", ())
        self.assertEqual([(c.before.value, c.after.value) for c in k.log],
                         [("reserve", "scout"), ("scout", "relay"), ("relay", "reserve"), ("reserve", "scout")])
        self.assertEqual((k.role, k.since), (Role.SCOUT, 150.0))

    def test_its_json(self):
        k = RoleKeeper("Drone2", start=0.0)
        k.update(1.25, "search S4", ())
        self.assertEqual(k.as_json(), {"owner": "Drone2", "role": "scout",
                                       "log": [{"at": 1.25, "before": "reserve", "after": "scout",
                                                "why": "holds search S4"}]})


class MessageTests(unittest.TestCase):

    def test_a_role_change_message(self):
        m = new_message(MessageType.ROLE_CHANGE, "Drone2", BROADCAST, "m", 1.0, 3,
                        {"role": "scout", "previous": "reserve", "why": "holds search S4"})
        self.assertEqual((m.time_to_live_s, m.payload["role"]), (10.0, "scout"))
        self.assertTrue(any("missing why" in p for p in payload_problems(MessageType.ROLE_CHANGE,
                                                                        {"role": "scout", "previous": "reserve"})))
        self.assertTrue(any("role is not a text" in p for p in payload_problems(
            MessageType.ROLE_CHANGE, {"role": "", "previous": "reserve", "why": "x"})))
        self.assertTrue(any("role is not a text" in p for p in payload_problems(        # a role is always named
            MessageType.ROLE_CHANGE, {"role": None, "previous": "reserve", "why": "x"})))


class BoundaryTests(unittest.TestCase):

    def test_roles_reach_no_ground_truth(self):
        from test_sensing import boundary_violations
        path = os.path.join(ROOT, "agentic_uav", "coordination", "roles.py")
        self.assertEqual(boundary_violations(path, "agentic_uav.coordination"), [])


if __name__ == "__main__":
    unittest.main()
