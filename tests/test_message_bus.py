#!/usr/bin/env python3
"""Tests for the message bus and the handle an agent gets (AUV-07, 7.3).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 7's exit -- team beliefs update only when messages are delivered -- is
only as good as the bus's word on what was delivered. These hold it to
Phase 7's perfect communication: a direct link within range, judged when the
message is sent, no loss, no delay, nothing after it expires; each recipient
its own copy; a record of every delivery and why any was not. And they hold
the handle to AUV-07's two functions: no spoofing, no way back to the bus,
no peek.
"""

import dataclasses
import os
import sys
import threading
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.core.messages import BROADCAST, Comms, MessageType, new_message  # noqa: E402
from agentic_uav.simulator.message_bus import (  # noqa: E402
    DELIVERED,
    EXPIRED,
    OUT_OF_RANGE,
    PENDING,
    MessageBus,
)

DRONES = ("Drone1", "Drone2", "Drone3")


class World:
    """Where each drone is; the test moves them."""

    def __init__(self, **at):
        self.at = {d: (0.0, 0.0, 10.0) for d in DRONES}
        self.at.update(at)

    def __call__(self, drone):
        return self.at[drone]


def beat(sender, seq=1, to=BROADCAST, at=0.0, battery=90.0):
    return new_message(MessageType.HEARTBEAT, sender, to, "m", at, seq,
                       {"position": [0.0, 0.0, 10.0], "airborne": True, "battery": battery,
                        "task": None, "stage": None})


def make(range_m=100.0, **at):
    clock = SimClock()
    world = World(**at)
    return MessageBus(DRONES, clock, world, range_m, mission_id="m"), clock, world


class DeliveryTests(unittest.TestCase):

    def test_in_range_it_is_waiting_at_once(self):
        bus, clock, _ = make(Drone2=(60.0, 0.0, 10.0))
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        got = bus.comms("Drone2").receive_available()
        self.assertEqual([m.message_id for m in got], ["Drone1#1"])
        self.assertEqual(bus.comms("Drone2").receive_available(), ())             # read once
        self.assertEqual(bus.comms("Drone3").receive_available(), ())             # not for it
        self.assertEqual(bus.comms("Drone1").receive_available(), ())             # nor for its sender
        (d,) = bus.deliveries()
        self.assertEqual((d.recipient, d.status, d.sent_at, d.scheduled_at, d.delivered_at, d.distance_m),
                         ("Drone2", DELIVERED, 0.0, 0.0, 0.0, 60.0))

    def test_a_broadcast_reaches_everyone_but_the_sender(self):
        bus, _, _ = make()
        bus.comms("Drone2").send(beat("Drone2"))
        self.assertEqual(sorted(d.recipient for d in bus.deliveries()), ["Drone1", "Drone3"])
        self.assertEqual([len(bus.comms(d).receive_available()) for d in DRONES], [1, 0, 1])

    def test_out_of_range_it_never_arrives_and_the_record_says_so(self):
        bus, _, _ = make(Drone2=(100.0, 0.0, 10.0), Drone3=(80.0, 60.0, 10.001))
        bus.comms("Drone1").send(beat("Drone1"))
        self.assertEqual(len(bus.comms("Drone2").receive_available()), 1)        # exactly 100 m: in range
        self.assertEqual(bus.comms("Drone3").receive_available(), ())             # 100 m and a millimetre up: not
        by = {d.recipient: d for d in bus.deliveries()}
        self.assertEqual((by["Drone3"].status, by["Drone3"].scheduled_at), (OUT_OF_RANGE, None))
        self.assertGreater(by["Drone3"].distance_m, 100.0)

    def test_unlimited_range_for_protocol_tests(self):
        bus, _, _ = make(range_m=None, Drone2=(5000.0, 0.0, 10.0))
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        self.assertEqual(len(bus.comms("Drone2").receive_available()), 1)

    def test_range_is_judged_when_it_is_sent(self):
        bus, clock, world = make(Drone2=(50.0, 0.0, 10.0), Drone3=(500.0, 0.0, 10.0))
        bus.comms("Drone1").send(beat("Drone1"))
        world.at["Drone2"], world.at["Drone3"] = (500.0, 0.0, 10.0), (50.0, 0.0, 10.0)   # they swap places
        clock.sleep(0.5)
        self.assertEqual(len(bus.comms("Drone2").receive_available()), 1)        # it was in range when sent
        self.assertEqual(bus.comms("Drone3").receive_available(), ())             # it was not

    def test_a_fixed_delay_holds_it_back(self):
        clock, world = SimClock(), World()
        bus = MessageBus(DRONES, clock, world, 100.0, delay_s=0.1)
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        clock.sleep(0.09)
        self.assertEqual(bus.comms("Drone2").receive_available(), ())             # not yet
        on_time = MessageBus(DRONES, SimClock(), world, 100.0, delay_s=0.1)
        on_time.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        on_time.clock.sleep(0.1)                                                   # (0.09 + 0.01 falls short in floats)
        self.assertEqual(len(on_time.comms("Drone2").receive_available()), 1)     # at exactly the delay
        (d,) = on_time.deliveries()
        self.assertEqual((d.sent_at, d.scheduled_at, d.delivered_at), (0.0, 0.1, 0.1))
        for bad in (-0.1, float("inf"), float("nan")):
            with self.subTest(delay_s=bad), self.assertRaisesRegex(ValueError, "delay_s must be zero or more"):
                MessageBus(DRONES, clock, world, 100.0, delay_s=bad)

    def test_nothing_after_it_expires(self):
        bus, clock, _ = make()
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))                   # expires at 3.0
        clock.sleep(2.99)
        self.assertEqual(len(bus.comms("Drone2").receive_available()), 1)
        bus.comms("Drone1").send(beat("Drone1", seq=2, to=("Drone2",), at=2.99))   # expires at 5.99
        clock.sleep(3.0)                                                           # now 5.99: expired, exactly
        self.assertEqual(bus.comms("Drone2").receive_available(), ())
        self.assertEqual([d.status for d in bus.deliveries()], [DELIVERED, EXPIRED])

    def test_oldest_first_and_pending_until_read(self):
        bus, clock, _ = make()
        for seq in (1, 2, 3):
            bus.comms("Drone1").send(beat("Drone1", seq=seq, to=("Drone2",), at=clock.now()))
            clock.sleep(0.1)
        self.assertEqual({d.status for d in bus.deliveries()}, {PENDING})
        self.assertEqual([m.sequence_number for m in bus.comms("Drone2").receive_available()], [1, 2, 3])
        self.assertEqual({d.delivered_at for d in bus.deliveries()}, {clock.now()})

    def test_ties_at_one_instant_are_read_by_sender_then_sequence(self):
        # Phase 8: whatever order their threads sent them in, messages of one instant read the same way.
        bus, clock, _ = make()
        for sender, seq in (("Drone3", 2), ("Drone1", 7), ("Drone3", 1)):
            bus.comms(sender).send(beat(sender, seq=seq, to=("Drone2",), at=clock.now()))
        clock.sleep(0.1)
        bus.comms("Drone1").send(beat("Drone1", seq=8, to=("Drone2",), at=clock.now()))
        got = [(m.sender_id, m.sequence_number) for m in bus.comms("Drone2").receive_available()]
        self.assertEqual(got, [("Drone1", 7), ("Drone3", 1), ("Drone3", 2), ("Drone1", 8)])


class CopyTests(unittest.TestCase):

    def test_each_recipient_its_own_copy(self):
        bus, _, _ = make()
        sent = beat("Drone1")
        bus.comms("Drone1").send(sent)
        (a,), (b,) = bus.comms("Drone2").receive_available(), bus.comms("Drone3").receive_available()
        self.assertEqual(a, sent)
        a.payload["battery"] = 1.0
        a.payload["position"][0] = 999.0
        self.assertEqual((b.payload["battery"], b.payload["position"][0]), (90.0, 0.0))
        self.assertEqual((sent.payload["battery"], sent.payload["position"][0]), (90.0, 0.0))
        self.assertIsNot(a.payload, sent.payload)


class RefusalTests(unittest.TestCase):

    def test_what_the_bus_will_not_carry(self):
        bus, _, _ = make()
        me = bus.comms("Drone1")
        with self.assertRaisesRegex(ValueError, "Drone1 cannot send a message from Drone2"):
            me.send(beat("Drone2"))
        with self.assertRaisesRegex(ValueError, r"not on the bus's roster: \['Drone9'\]"):
            me.send(beat("Drone1", to=("Drone9",)))
        with self.assertRaisesRegex(TypeError, "not an AgentMessage"):
            me.send({"message_type": "heartbeat"})
        other = new_message(MessageType.HEARTBEAT, "Drone1", BROADCAST, "another mission", 0.0, 1,
                            {"position": [0.0, 0.0, 0.0], "airborne": False, "battery": 100.0,
                             "task": None, "stage": None})
        with self.assertRaisesRegex(ValueError, "the bus carries m"):
            me.send(other)
        self.assertEqual(bus.deliveries(), ())                                     # nothing refused was recorded

    def test_the_bus_itself(self):
        clock, world = SimClock(), World()
        with self.assertRaisesRegex(ValueError, "each drone once"):
            MessageBus(("Drone1", "Drone1"), clock, world, 100.0)
        with self.assertRaisesRegex(ValueError, "each drone once"):
            MessageBus((), clock, world, 100.0)
        for bad in (0.0, -5.0, float("inf")):
            with self.subTest(range_m=bad), self.assertRaisesRegex(ValueError, "range_m must be positive"):
                MessageBus(DRONES, clock, world, bad)
        with self.assertRaisesRegex(ValueError, "Drone9 is not on the bus's roster"):
            MessageBus(DRONES, clock, world, 100.0).comms("Drone9")

    def test_many_senders_at_once(self):
        bus, _, _ = make()

        def chatter(drone):
            for seq in range(1, 201):
                bus.comms(drone).send(beat(drone, seq=seq))

        threads = [threading.Thread(target=chatter, args=(d,)) for d in DRONES]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(bus.deliveries()), 3 * 200 * 2)
        self.assertEqual([len(bus.comms(d).receive_available()) for d in DRONES], [400, 400, 400])

    def test_a_message_sent_while_its_recipient_reads_is_not_lost(self):
        # Found by a surviving mutation: without the lock around sending, a
        # message landing between receive_available's two steps -- taking
        # what is ready, keeping the rest -- vanished from the inbox while the
        # record still said pending. Probed at 200,000 messages: 2,248 lost.
        # Python switches threads only every 5 ms by default, so the window is
        # rarely hit at any size worth waiting for; switching every
        # microsecond makes it hit on every run.
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        self.addCleanup(sys.setswitchinterval, old)
        bus, _, _ = make(range_m=None)
        got, done, failed = [], threading.Event(), []

        def sender():
            # The flag is set however the sender ends: a first version left it
            # unset when sending raised, and the reader waited for ever (found
            # when a mutation broke every heartbeat and the suite hung).
            try:
                for seq in range(1, 5001):
                    bus.comms("Drone1").send(beat("Drone1", seq=seq, to=("Drone2",)))
            except Exception as exc:
                failed.append(exc)
            finally:
                done.set()

        def reader():
            while not done.wait(0):
                got.extend(bus.comms("Drone2").receive_available())
            got.extend(bus.comms("Drone2").receive_available())

        threads = [threading.Thread(target=sender), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60.0)
        self.assertFalse(any(t.is_alive() for t in threads), "a thread did not finish")
        self.assertEqual(failed, [])
        self.assertEqual(len(got), 5000)
        self.assertEqual([m.sequence_number for m in got], list(range(1, 5001)))
        self.assertEqual({d.status for d in bus.deliveries()}, {DELIVERED})


class HandleTests(unittest.TestCase):
    """AUV-07, 7.3: send and receive_available, and nothing that leads to the bus."""

    def test_two_plain_functions_and_a_name(self):
        bus, _, _ = make()
        comms = bus.comms("Drone2")
        self.assertIsInstance(comms, Comms)
        self.assertEqual([f.name for f in dataclasses.fields(Comms)], ["drone", "send", "receive_available"])
        self.assertEqual(comms.drone, "Drone2")
        for name in ("send", "receive_available"):
            fn = getattr(comms, name)
            self.assertIsInstance(fn, types.FunctionType)
            self.assertFalse(hasattr(fn, "__self__"))                              # no bound method back to the bus
        self.assertFalse(hasattr(comms, "peek"))

    def test_a_holder_of_the_handle_reaches_no_bus(self):
        from test_sensing import ground_truth_reached
        bus, _, _ = make()
        holder = types.SimpleNamespace(comms=bus.comms("Drone1"), notes=[bus.comms("Drone2")])
        self.assertEqual(ground_truth_reached(holder), [])
        self.assertEqual([name for name, _ in ground_truth_reached(types.SimpleNamespace(bus=bus))], ["MessageBus"])


if __name__ == "__main__":
    unittest.main()
