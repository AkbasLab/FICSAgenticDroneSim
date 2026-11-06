#!/usr/bin/env python3
"""Tests for the message types and the common envelope (AUV-07, 7.1-7.2).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 7's exit -- team beliefs update only when messages are delivered --
rests on every message being exactly what it says: of a known type, from a
named sender to named recipients, with a sequence number and a lifetime an
agent can reason about, and carrying a payload whose every field is checked.
These hold the envelope to AUV-07's fields, refuse each way a message can be
malformed, refuse types no phase has given a payload yet, and keep the
module inside the boundary agents are held to, since agents will import it.
"""

import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.core.messages import (  # noqa: E402
    BROADCAST,
    DEFAULT_TTL_S,
    SCHEMAS,
    AgentMessage,
    MessageType,
    new_message,
    payload_problems,
)

BEAT = {"position": [40.0, -12.0, 12.0], "airborne": True, "battery": 97.4, "task": "search S1", "stage": "searching"}
STATUS = {"task": "search S1", "stage": "searching", "skill": "SEARCH_REGION",
          "position": [60.0, -30.0, 12.0], "battery": 88.0, "degraded": False}


def beat(**kw):
    args = dict(message_type=MessageType.HEARTBEAT, sender_id="Drone1", recipient_ids=BROADCAST,
                mission_id="search_relay_001", at=12.5, sequence_number=13, payload=dict(BEAT))
    args.update(kw)
    return new_message(**args)


class TypeTests(unittest.TestCase):

    def test_the_thirteen_types_auv_07_names(self):
        # AUV-07 says "fourteen" and names thirteen; these are the thirteen.
        self.assertEqual([t.name for t in MessageType],
                         ["HEARTBEAT", "STATUS_UPDATE", "TASK_ANNOUNCEMENT", "TASK_BID", "TASK_AWARD", "TASK_ACCEPT",
                          "TASK_RELEASE", "TASK_COMPLETE", "INTENT_UPDATE", "TARGET_FOUND", "HELP_REQUEST",
                          "ROLE_CHANGE", "MISSION_UPDATE"])
        self.assertTrue(all(t.value == t.name.lower() for t in MessageType))

    def test_schemas_and_lifetimes_only_for_the_types_in_use(self):
        # Phase 7's two, from Phase 8 the six of the contract-net, Phase 9's and Phase 13's; nothing else yet.
        task = {MessageType.TASK_ANNOUNCEMENT, MessageType.TASK_BID, MessageType.TASK_AWARD, MessageType.TASK_ACCEPT,
                MessageType.TASK_RELEASE, MessageType.TASK_COMPLETE}
        later = task | {MessageType.ROLE_CHANGE}                         # Phase 9's
        later |= {MessageType.MISSION_UPDATE}                            # Phase 13's, the base controller's
        self.assertEqual(set(SCHEMAS), {MessageType.HEARTBEAT, MessageType.STATUS_UPDATE} | later)
        self.assertEqual(DEFAULT_TTL_S, {MessageType.HEARTBEAT: 3.0, MessageType.STATUS_UPDATE: 10.0,
                                         **{t: 10.0 for t in later}})
        # Phase 7's two schemas are as they were.
        self.assertEqual(SCHEMAS[MessageType.HEARTBEAT], {"position": "point", "airborne": "flag", "battery": "number",
                                                          "task": "text_or_none", "stage": "text_or_none"})
        self.assertEqual(SCHEMAS[MessageType.STATUS_UPDATE], {"task": "text_or_none", "stage": "text_or_none",
                                                              "skill": "text_or_none", "position": "point",
                                                              "battery": "number", "degraded": "flag"})

    def test_a_type_with_no_schema_yet_is_refused(self):
        for t in set(MessageType) - set(SCHEMAS):
            with self.subTest(type=t.name):
                self.assertEqual(payload_problems(t, {}), [f"{t.value} has no payload schema yet: no phase sends it so far"])
                with self.assertRaisesRegex(ValueError, "no payload schema yet"):
                    AgentMessage("Drone1#1", t, "Drone1", BROADCAST, "m", 0.0, 1, 5.0, {})
                with self.assertRaisesRegex(ValueError, "no default time to live yet"):
                    new_message(t, "Drone1", BROADCAST, "m", 0.0, 1, {})


class EnvelopeTests(unittest.TestCase):

    def test_auv_07s_fields(self):
        m = beat()
        self.assertEqual(list(m.as_json()), ["message_id", "message_type", "sender_id", "recipient_ids", "mission_id",
                                             "timestamp", "sequence_number", "time_to_live_s", "payload", "confidence"])
        self.assertEqual((m.message_id, m.time_to_live_s, m.expires_at, m.confidence), ("Drone1#13", 3.0, 15.5, None))

    def test_a_status_update(self):
        m = new_message(MessageType.STATUS_UPDATE, "Drone2", ("Drone1", "Drone3"), "m", 40.0, 7, dict(STATUS))
        self.assertEqual((m.time_to_live_s, m.recipient_ids), (10.0, ("Drone1", "Drone3")))
        none_known = dict(STATUS, task=None, stage=None, skill=None)
        self.assertIsNone(new_message(MessageType.STATUS_UPDATE, "Drone2", BROADCAST, "m", 0.0, 1, none_known).payload["task"])

    def test_read_back_the_same_and_its_size(self):
        m = beat(confidence=0.9)
        row = json.loads(json.dumps(m.as_json()))
        self.assertEqual(AgentMessage.from_json(row), m)
        compact = json.dumps(m.as_json(), separators=(",", ":"), sort_keys=True)
        self.assertEqual(m.size_bytes(), len(compact.encode("utf-8")))
        self.assertEqual(beat(confidence=0.9).size_bytes(), m.size_bytes())        # the same message, the same size

    def test_expiry_at_exactly_its_end(self):
        m = beat()                                                                # 12.5 + 3.0
        self.assertFalse(m.expired(15.49))
        self.assertTrue(m.expired(15.5))

    def test_who_it_is_for(self):
        everyone = beat()
        self.assertEqual([everyone.is_for(d) for d in ("Drone1", "Drone2", "Drone4")], [False, True, True])
        some = beat(recipient_ids=("Drone3",))
        self.assertEqual([some.is_for(d) for d in ("Drone1", "Drone2", "Drone3")], [False, False, True])

    def test_the_sender_keeps_its_own_payload(self):
        payload = dict(BEAT, position=[1.0, 2.0, 3.0])
        m = new_message(MessageType.HEARTBEAT, "Drone1", BROADCAST, "m", 0.0, 1, payload)
        payload["battery"] = 5.0
        payload["position"][0] = 999.0
        self.assertEqual((m.payload["battery"], m.payload["position"][0]), (97.4, 1.0))


class MalformedTests(unittest.TestCase):

    def refused(self, words, **change):
        args = dict(message_id="Drone1#1", message_type=MessageType.HEARTBEAT, sender_id="Drone1",
                    recipient_ids=BROADCAST, mission_id="m", timestamp=1.0, sequence_number=1, time_to_live_s=3.0,
                    payload=dict(BEAT), confidence=None)
        args.update(change)
        with self.assertRaisesRegex(ValueError, words):
            AgentMessage(**args)

    def test_the_envelope(self):
        cases = [
            ("unknown message type", dict(message_type="heartbeat")),
            ("sender_id must be a non-empty string", dict(sender_id="")),
            ("message_id must be a non-empty string", dict(message_id="")),
            ("mission_id must be a non-empty string", dict(mission_id=None)),
            ("recipient_ids must be a tuple", dict(recipient_ids=["Drone2"])),
            ("no recipients", dict(recipient_ids=())),
            ("a drone does not send to itself", dict(recipient_ids=("Drone1",))),
            ("a recipient is named twice", dict(recipient_ids=("Drone2", "Drone2"))),
            ("or BROADCAST alone", dict(recipient_ids=("Drone2", "*"))),
            ("timestamp must be a finite number", dict(timestamp=math.inf)),
            ("timestamp must be a finite number", dict(timestamp=True)),
            ("sequence_number must be an integer from 1", dict(sequence_number=0)),
            ("sequence_number must be an integer from 1", dict(sequence_number=1.0)),
            ("sequence_number must be an integer from 1", dict(sequence_number=True)),
            ("time_to_live_s must be positive", dict(time_to_live_s=0.0)),
            ("confidence must be in", dict(confidence=1.5)),
            ("confidence must be in", dict(confidence=-0.1)),
        ]
        for words, change in cases:
            with self.subTest(change=change):
                self.refused(words, **change)

    def test_the_payload(self):
        cases = [
            ("missing battery", {k: v for k, v in BEAT.items() if k != "battery"}),
            ("unknown field note", dict(BEAT, note="hi")),
            ("position is not a point", dict(BEAT, position=[1.0, 2.0])),
            ("position is not a point", dict(BEAT, position=[1.0, 2.0, "3"])),
            ("payload is not plain JSON", dict(BEAT, position=[1.0, 2.0, math.nan])),      # NaN is not JSON
            ("battery is not a number", dict(BEAT, battery=True)),
            ("airborne is not a flag", dict(BEAT, airborne=1)),
            ("payload must be a dict", ["not", "a", "dict"]),
            ("payload is not plain JSON", dict(BEAT, battery=object())),
        ]
        for words, payload in cases:
            with self.subTest(words=words):
                self.refused(words, payload=payload)
        self.assertIn("task is not a text_or_none: ''",
                      payload_problems(MessageType.STATUS_UPDATE, dict(STATUS, task="")))
        with self.assertRaisesRegex(ValueError, "not a valid heartbeat payload: missing airborne"):
            new_message(MessageType.HEARTBEAT, "Drone1", BROADCAST, "m", 0.0, 1, {"position": [0, 0, 0], "battery": 1.0})


TASK_PAYLOADS = {
    MessageType.TASK_ANNOUNCEMENT: {"task_id": "search S1", "version": 2, "why": "Drone2's lease ran out"},
    MessageType.TASK_BID: {"task_id": "search S1", "version": 1, "value": 113.6, "d": 113.6, "b": 0.0, "l": 0.0,
                           "c": 51.2, "r": 0.0},
    MessageType.TASK_AWARD: {"task_id": "search S1", "version": 1, "value": 113.6},
    MessageType.TASK_ACCEPT: {"task_id": "search S1", "version": 1, "holder": "Drone3"},
    MessageType.TASK_RELEASE: {"task_id": "search S1", "version": 1, "why": "lost to Drone4"},
    MessageType.TASK_COMPLETE: {"task_id": "search S1", "version": 1},
}
PROGRESS = {"task_id": "search S1", "task_version": 1, "task_progress": 0.4}


class TaskMessageTests(unittest.TestCase):
    """Phase 8: the contract-net's six types, and a holder's progress on its status update."""

    def test_each_task_message(self):
        for kind, payload in TASK_PAYLOADS.items():
            with self.subTest(kind=kind.name):
                m = beat(message_type=kind, payload=payload)
                self.assertEqual((m.message_type, m.payload, m.time_to_live_s), (kind, payload, 10.0))
                self.assertEqual(AgentMessage.from_json(m.as_json()), m)

    def test_task_messages_refused_for_their_reasons(self):
        for kind, payload, why in (
                (MessageType.TASK_BID, {**TASK_PAYLOADS[MessageType.TASK_BID], "version": 0}, "version is not a version"),
                (MessageType.TASK_BID, {**TASK_PAYLOADS[MessageType.TASK_BID], "version": 1.0}, "version is not a version"),
                (MessageType.TASK_BID, {**TASK_PAYLOADS[MessageType.TASK_BID], "version": True}, "version is not a version"),
                (MessageType.TASK_AWARD, {**TASK_PAYLOADS[MessageType.TASK_AWARD], "task_id": ""}, "task_id is not a text"),
                (MessageType.TASK_AWARD, {**TASK_PAYLOADS[MessageType.TASK_AWARD], "task_id": None}, "task_id is not a text"),
                (MessageType.TASK_ACCEPT, {"task_id": "search S1", "version": 1}, "missing holder"),
                (MessageType.TASK_COMPLETE, {**TASK_PAYLOADS[MessageType.TASK_COMPLETE], "value": 1.0},
                 "unknown field value"),
                (MessageType.TASK_BID, {**TASK_PAYLOADS[MessageType.TASK_BID], "c": float("nan")}, "not plain JSON")):
            with self.subTest(kind=kind.name, why=why):
                self.assertTrue(any(why in problem for problem in payload_problems(kind, payload)),
                                payload_problems(kind, payload))

    def test_a_status_update_with_progress(self):
        m = beat(message_type=MessageType.STATUS_UPDATE, payload={**STATUS, **PROGRESS})
        self.assertEqual(m.payload["task_progress"], 0.4)
        self.assertEqual(payload_problems(MessageType.STATUS_UPDATE, STATUS), [])     # without it, as in Phase 7

    def test_the_progress_group_comes_together_or_not_at_all(self):
        for part in ({"task_id": "search S1"}, {"task_id": "search S1", "task_version": 1},
                     {"task_progress": 0.4}):
            with self.subTest(part=part):
                problems = payload_problems(MessageType.STATUS_UPDATE, {**STATUS, **part})
                self.assertTrue(any("come together or not at all" in p for p in problems), problems)
        for bad, why in (({**PROGRESS, "task_progress": 1.5}, "task_progress is not a fraction"),
                         ({**PROGRESS, "task_progress": -0.1}, "task_progress is not a fraction"),
                         ({**PROGRESS, "task_version": 0}, "task_version is not a version"),
                         ({**PROGRESS, "task_id": ""}, "task_id is not a text")):
            with self.subTest(bad=bad):
                problems = payload_problems(MessageType.STATUS_UPDATE, {**STATUS, **bad})
                self.assertTrue(any(why in p for p in problems), problems)

    def test_a_heartbeat_takes_no_progress(self):
        problems = payload_problems(MessageType.HEARTBEAT, {**BEAT, **PROGRESS})
        self.assertEqual(sorted(problems), ["unknown field task_id", "unknown field task_progress",
                                            "unknown field task_version"])


class BoundaryTests(unittest.TestCase):

    def test_agents_may_import_it(self):
        # Held to the same rules as agent code: it will be imported by agents.
        from test_sensing import boundary_violations
        path = os.path.join(ROOT, "agentic_uav", "core", "messages.py")
        self.assertEqual(boundary_violations(path, "agentic_uav.core"), [])


if __name__ == "__main__":
    unittest.main()
