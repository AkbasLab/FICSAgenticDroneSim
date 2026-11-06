#!/usr/bin/env python3
"""Tests for architecture A's two halves, on their own: the base controller and the follower drone.

    python -m unittest discover -s tests -p test_central.py

WHY THESE EXIST
---------------
A's flights (test_architecture) show the whole: every flown task awarded by
the base, a stopped drone's task reassigned. They never reach the corners the
controller must still get right -- a drone it has not heard from lately, a
drone giving its task back on the way home, an award the drone already
confirmed, reassignment switched off (the leases ablation, for A) -- nor a
follower handed an award meant for another drone. Each is driven here
directly, message by message.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.follower_policy import FollowerPolicy  # noqa: E402
from agentic_uav.control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M  # noqa: E402
from agentic_uav.coordination.central import RESEND_S, CentralController  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402

SC = load_scenario("search_relay_001")
BRIEF = SC.brief()
ROSTER = tuple(v.id for v in SC.vehicles)
HEIGHTS = {v.id: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, v in enumerate(SC.vehicles)}
PADS = {v.id: (v.start_x, v.start_y) for v in BRIEF.vehicles}
HEALTH = load_recovery()
_seq = [0]


def beat(drone, task=None, stage=None):
    _seq[0] += 1
    x, y = PADS[drone]
    return new_message(MessageType.HEARTBEAT, drone, BROADCAST, "m", 0.0, _seq[0],
                       {"position": [x, y, HEIGHTS[drone]], "airborne": True, "battery": 100.0, "task": task,
                        "stage": stage})


def awards(out):
    return {s.to[0]: s.payload["task_id"] for s in out if s.kind is MessageType.TASK_AWARD}


class ControllerTests(unittest.TestCase):

    def controller(self, reassign=True):
        return CentralController(BRIEF, ROSTER, load_allocation(), HEALTH, HEIGHTS, reassign=reassign)

    def started(self, reassign=True):
        """Every drone heard at t=0 and given a task."""
        c = self.controller(reassign)
        for d in ROSTER:
            c.receive(beat(d), 0.0)
        given = awards(c.tick(0.0))
        self.assertEqual(set(given), set(ROSTER))
        self.assertEqual(len(set(given.values())), len(ROSTER))           # one task each
        return c, given

    def test_an_award_is_resent_until_the_drone_confirms_it(self):
        c, given = self.started()
        self.assertEqual(awards(c.tick(RESEND_S / 2)), {})                # not yet due
        self.assertEqual(awards(c.tick(RESEND_S)), given)                 # due, and unconfirmed: again
        for d in ROSTER:
            c.receive(beat(d, task=given[d], stage="to_sector"), RESEND_S + 0.2)
        self.assertEqual(awards(c.tick(2 * RESEND_S)), {})                # confirmed: never again
        self.assertEqual(awards(c.tick(5 * RESEND_S)), {})

    def test_a_drone_not_heard_lately_is_given_nothing(self):
        c = self.controller()
        for d in ROSTER[:3]:
            c.receive(beat(d), 0.0)
        c.receive(beat(ROSTER[3]), -(HEALTH.suspected_s + 1.0))            # last heard too long ago
        self.assertEqual(set(awards(c.tick(0.0))), set(ROSTER[:3]))

    def test_a_silent_holders_task_is_reassigned_unless_reassignment_is_off(self):
        for reassign in (True, False):
            with self.subTest(reassign=reassign):
                c, given = self.started(reassign)
                t = 0.0
                while t < HEALTH.unreachable_s + 1.0:                       # Drone1 falls silent; the rest report
                    t += RESEND_S
                    for d in ROSTER[1:]:
                        c.receive(beat(d, task=given[d], stage="searching"), t)
                    c.tick(t)
                moved = [e for e in c.log if e["what"] == "reassigned"]
                if reassign:
                    self.assertEqual([(e["task"], e["from"]) for e in moved], [(given["Drone1"], "Drone1")])
                else:
                    self.assertEqual(moved, [])
                    self.assertEqual(c.as_json()["tasks"][given["Drone1"]]["holder"], "Drone1")

    def test_a_task_given_back_on_the_way_home_reopens_and_the_drone_gets_no_more(self):
        c, given = self.started()
        c.receive(beat("Drone1", task=None, stage="going_home"), 1.0)     # it gave up (its battery, say)
        for d in ROSTER[1:]:
            c.receive(beat(d, task=given[d], stage="searching"), 1.0)
        out = c.tick(1.0)
        self.assertEqual([(e["what"], e["task"]) for e in c.log if e["what"] == "given back"],
                         [("given back", given["Drone1"])])
        self.assertIsNone(c.as_json()["tasks"][given["Drone1"]]["holder"])
        self.assertNotIn("Drone1", awards(out))                         # going home: not free
        self.assertNotIn("Drone1", awards(c.tick(1.0 + RESEND_S)))


class FollowerTests(unittest.TestCase):

    def test_a_follower_takes_only_an_award_addressed_to_it_and_only_from_the_base(self):
        p = FollowerPolicy(altitude_m=12.0)
        b = BeliefState.start(BRIEF, "Drone1", Observation(0.0, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None))
        payload = {"task_id": "search S1", "version": 1, "value": 1.0}
        to_other = new_message(MessageType.TASK_AWARD, "base", ("Drone2",), "m", 1.0, 1, payload)
        from_mate = new_message(MessageType.TASK_AWARD, "Drone3", ("Drone1",), "m", 1.0, 1, payload)
        p.coordinate(b, [to_other, from_mate], 1.0)
        self.assertIsNone(p.pending)
        p.coordinate(b, [new_message(MessageType.TASK_AWARD, "base", ("Drone1",), "m", 1.0, 2, payload)], 1.0)
        self.assertEqual(p.pending, ("search S1", 1))


if __name__ == "__main__":
    unittest.main()
