#!/usr/bin/env python3
"""Tests for Phase 10 step 2: message lifetimes, and what the log says of them (AUV-10, 10.4).

    python -m unittest discover tests

WHY THESE EXIST
---------------
"A delayed message may arrive after it is useful." A lifetime per message
class is set by the sender; the bus must never deliver a message past it, and
a team record past it must never be held as current. On Phase 10's network
messages arrive late enough for that to bite -- under the severe condition
heartbeats expire on the way. These hold the table to the classes AUV-10
names, the instant a lifetime ends to one rule (expired, give or take float
rounding), the two guarantees to every flight under every condition, and
AUV-10's diagnostic -- decisions that read a record past its lifetime -- to
counting exactly those.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import TeamRecord  # noqa: E402
from agentic_uav.core.messages import (  # noqa: E402
    BROADCAST,
    DEFAULT_TTL_S,
    EXPIRY_TOL_S,
    MessageType,
    lifetimes,
    new_message,
)
from agentic_uav.core.team import TeamReport  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.conditions import CONDITIONS, load_network  # noqa: E402
from agentic_uav.experiments.message_log import current_late, late, stale_decisions  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402


def beat(at=0.0, seq=1):
    return new_message(MessageType.HEARTBEAT, "Drone1", BROADCAST, "m", at, seq,
                       {"position": [0.0, 0.0, 10.0], "airborne": True, "battery": 90.0, "task": None, "stage": None})


class TableTests(unittest.TestCase):

    def test_every_type_that_can_be_sent_has_its_lifetime_as_fixed(self):
        from agentic_uav.core.messages import SCHEMAS
        self.assertEqual(set(DEFAULT_TTL_S), set(SCHEMAS))                       # a type with a schema has a lifetime
        with self.assertRaises(ValueError):                                      # one without cannot be sent at all
            new_message(MessageType.TARGET_FOUND, "Drone1", BROADCAST, "m", 0.0, 1, {})
        self.assertEqual(lifetimes()["heartbeat"], 3.0)                                    # short
        self.assertEqual({v for k, v in lifetimes().items() if k != "heartbeat"}, {10.0})   # current intent
        self.assertEqual(min(lifetimes().values()), lifetimes()["heartbeat"])

    def test_a_message_carries_its_types_lifetime(self):
        self.assertEqual(beat().time_to_live_s, 3.0)


class InstantTests(unittest.TestCase):

    def test_at_the_instant_its_lifetime_ends_a_message_is_expired(self):
        # On the clock, "the instant" is the expiry give or take float rounding: a tick a hair before it
        # counts as the instant, so the rule decides, not the rounding.
        m = beat(at=302.7)
        for now in (m.expires_at, m.expires_at - 1e-12, m.expires_at + 1e-12):
            self.assertTrue(m.expired(now), now)
        self.assertFalse(m.expired(m.expires_at - 10 * EXPIRY_TOL_S))

    def test_so_is_a_team_record(self):
        rec = TeamRecord(TeamReport("Drone2", at=302.7, source="message", ttl_s=3.0), received_at=303.0)
        for now in (rec.expires_at, rec.expires_at - 1e-12):
            self.assertFalse(rec.current(now), now)
        self.assertTrue(rec.current(rec.expires_at - 10 * EXPIRY_TOL_S))


class LogTests(unittest.TestCase):

    @staticmethod
    def entry(current, read, expires_in=-2.0, mid="Drone2#5"):
        return {"at": 50.0, "action": "continue", "read": [mid] if read else [],
                "belief": {"team": {"Drone2": {"current": current, "message_id": mid, "expires_in_s": expires_in},
                                    "Drone3": "never heard"}}}

    def test_a_stale_decision_is_one_that_read_a_record_past_its_lifetime(self):
        got = stale_decisions({"Drone1": [self.entry(current=False, read=True)]}, start=10.0)
        self.assertEqual(got, [{"drone": "Drone1", "at_s": 40.0, "teammate": "Drone2", "message_id": "Drone2#5",
                                "past_lifetime_s": 2.0, "action": "continue"}])
        self.assertEqual(stale_decisions({"Drone1": [self.entry(current=False, read=False)]}), [])   # held, not read
        self.assertEqual(stale_decisions({"Drone1": [self.entry(current=True, read=True, expires_in=4.0)]}), [])

    def test_a_record_held_current_past_its_lifetime_is_caught(self):
        self.assertEqual(len(current_late({"Drone1": [self.entry(current=True, read=False, expires_in=-1.0)]})), 1)
        self.assertEqual(current_late({"Drone1": [self.entry(current=True, read=False, expires_in=1.0)]}), [])

    def test_a_late_delivery_is_caught(self):
        from types import SimpleNamespace
        m = beat(at=0.0)
        self.assertEqual(len(late([SimpleNamespace(status="delivered", delivered_at=3.0, message=m)])), 1)
        self.assertEqual(late([SimpleNamespace(status="delivered", delivered_at=2.5, message=m),
                               SimpleNamespace(status="expired", delivered_at=None, message=m)]), [])


class FlightTests(unittest.TestCase):
    """The canonical mission under every condition, with and without Drone1 stopped."""

    @classmethod
    def setUpClass(cls):
        sc = scenarios.load_scenario("search_relay_001")
        a, h = load_allocation(), load_recovery()
        cls.flights = {(c, label): fly_recovery_on_mock(sc, a, h, label, stop, network=load_network(c))
                       for c in CONDITIONS for label, stop in (("no stop", None), ("Drone1 stopped", {"Drone1": 60.0}))}

    def test_nothing_is_ever_delivered_late_or_held_current_late(self):
        for key, run in self.flights.items():
            with self.subTest(flight=key):
                self.assertEqual(late(run.team.deliveries), [])
                self.assertEqual(current_late(run.team.traces), [])

    def test_under_severe_latency_messages_expire_on_the_way(self):
        expired = {k: sum(d.status == "expired" for d in r.team.deliveries) for k, r in self.flights.items()}
        self.assertGreater(expired[("severe", "no stop")], 0)
        self.assertEqual({k: v for k, v in expired.items() if k[0] != "severe"},
                         {k: 0 for k in expired if k[0] != "severe"})
        for d in self.flights[("severe", "no stop")].team.deliveries:
            if d.status == "expired":
                self.assertEqual(d.message.message_type, MessageType.HEARTBEAT)       # the shortest-lived

    def test_every_message_sent_carries_its_types_lifetime(self):
        for key, run in self.flights.items():
            with self.subTest(flight=key):
                self.assertTrue(all(d.message.time_to_live_s == DEFAULT_TTL_S[d.message.message_type]
                                    for d in run.team.deliveries))

    def test_no_decision_acted_on_a_stale_record(self):
        # The diagnostic, flight by flight: these policies read only current records -- a relay would not,
        # and none relays here.
        for key, run in self.flights.items():
            with self.subTest(flight=key):
                self.assertEqual(stale_decisions(run.team.traces, run.team.start), [])


if __name__ == "__main__":
    unittest.main()
