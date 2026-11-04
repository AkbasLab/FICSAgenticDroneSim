#!/usr/bin/env python3
"""Tests for Phase 10 step 1: the network model, its four conditions, and the bus that carries it.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 10's exit -- the same mission replayed under four conditions with
reproducible delivery -- is only as good as the model's word on each message.
These hold each mechanism to what it says: latency never below its floor and
exactly the mean without jitter; loss drawn from a generator keyed by the
message itself, so the order drones send in changes nothing; a rate limit
that refuses a message to everyone; bandwidth that queues a drone's messages;
range; partitions that cut only between their groups and only in their
interval -- on the bus, in a drone's base-link reading and in the judge's
exact connectivity alike. They hold the four manifests to the levels the plan
fixed, and the bus without a model to exactly what it was. Statistical
verification over thousands of messages is step 4's.
"""

import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.conditions import CONDITIONS, load_network, parse_network  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.recovery_exit import known_exactly  # noqa: E402
from agentic_uav.experiments.single_agent import MESSAGE_DELAY_S  # noqa: E402
from agentic_uav.simulator.message_bus import (  # noqa: E402
    DELIVERED,
    EXPIRED,
    LOST,
    OUT_OF_RANGE,
    PARTITIONED,
    PENDING,
    RATE_LIMITED,
    MessageBus,
)
from agentic_uav.simulator.mission_world import Connectivity, _cut  # noqa: E402
from agentic_uav.simulator.trajectory import Knot, Trajectory  # noqa: E402
from agentic_uav.simulator.network import (  # noqa: E402
    PARTITION_TOL_S,
    NetworkModel,
    Partition,
    Transmitter,
)
from agentic_uav.simulator.sensing import _reach_base  # noqa: E402

DRONES = ("Drone1", "Drone2", "Drone3")
SPLIT = Partition((frozenset({"Drone1", "base"}), frozenset({"Drone2", "Drone3"})), 60.0, 120.0)


def beat(sender, seq=1, to=BROADCAST, at=0.0):
    return new_message(MessageType.HEARTBEAT, sender, to, "m", at, seq,
                       {"position": [0.0, 0.0, 10.0], "airborne": True, "battery": 90.0, "task": None, "stage": None})


def model(**kw):
    base = dict(name="t", latency_mean_s=0.1)
    base.update(kw)
    return NetworkModel(**base)


def bus_with(net, **at):
    clock = SimClock()
    where = {d: (0.0, 0.0, 10.0) for d in DRONES}
    where.update(at)
    return MessageBus(DRONES, clock, lambda d: where[d], None, mission_id="m", network=net.seeded(7)), clock


def fates(bus):
    return {(d.message.message_id, d.recipient): (d.status, d.scheduled_at) for d in bus.deliveries()}


class ModelTests(unittest.TestCase):

    def test_what_is_refused(self):
        for kw, why in ((dict(latency_floor_s=0.0), "floor"), (dict(latency_mean_s=0.01), "at least the floor"),
                        (dict(latency_jitter_s=-1.0), "jitter"), (dict(loss_probability=1.0), "loss"),
                        (dict(rate_limit_per_s=0.0), "rate limit"), (dict(bandwidth_bytes_per_s=-5.0), "bandwidth"),
                        (dict(range_m=0.0), "range")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                model(**kw)
        for part, why in ((Partition((frozenset({"a"}),), 0.0, 1.0), "two groups"),
                          (Partition((frozenset({"a"}), frozenset({"a", "b"})), 0.0, 1.0), "in two groups"),
                          (Partition((frozenset({"a"}), frozenset()), 0.0, 1.0), "empty"),
                          (Partition((frozenset({"a"}), frozenset({"b"})), 5.0, 5.0), "forward")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                model(partitions=(part,))

    def test_a_draw_needs_a_seed(self):
        with self.assertRaisesRegex(RuntimeError, "no seed"):
            model().draw("Drone1", "Drone2", 1)

    def test_a_draw_is_the_messages_own(self):
        net = model(loss_probability=0.5, latency_jitter_s=0.2).seeded(3)
        keys = [(s, r, q) for s in DRONES for r in DRONES for q in range(1, 30) if s != r]
        forward = {k: net.draw(*k) for k in keys}
        backward = {k: net.draw(*k) for k in reversed(keys)}
        self.assertEqual(forward, backward)                          # the order asked changes nothing
        self.assertNotEqual(forward, {k: model(loss_probability=0.5, latency_jitter_s=0.2).seeded(4).draw(*k)
                                      for k in keys})               # another seed, another network
        self.assertTrue(0 < sum(lost for lost, _ in forward.values()) < len(keys))

    def test_latency_is_the_mean_without_jitter_and_never_below_the_floor(self):
        flat = model(latency_mean_s=0.1).seeded(1)
        self.assertEqual({flat.draw("Drone1", "Drone2", q)[1] for q in range(1, 200)}, {0.1})
        wide = model(latency_mean_s=0.1, latency_jitter_s=1.0, latency_floor_s=0.05).seeded(1)
        got = [wide.draw("Drone1", "Drone2", q)[1] for q in range(1, 500)]
        self.assertEqual(min(got), 0.05)
        self.assertGreater(max(got), 1.0)

    def test_no_loss_loses_nothing(self):
        net = model().seeded(1)
        self.assertFalse(any(net.draw("Drone1", "Drone2", q)[0] for q in range(1, 1000)))

    def test_a_partition_is_in_force_strictly_inside_its_interval(self):
        net = model(partitions=(SPLIT,))
        self.assertTrue(net.partitioned("Drone1", "Drone2", 60.0))           # a decision "at" its start: inside
        self.assertTrue(net.partitioned("Drone1", "Drone2", 119.0))
        self.assertFalse(net.partitioned("Drone1", "Drone2", 120.0))         # "at" its end: outside
        self.assertFalse(net.partitioned("Drone1", "Drone2", 59.0))
        self.assertFalse(net.partitioned("Drone2", "Drone3", 90.0))          # within a group
        self.assertTrue(net.partitioned("Drone3", "base", 90.0))
        self.assertFalse(net.partitioned("Drone1", "base", 90.0))
        self.assertEqual(net.windows("Drone1", "Drone3"), [(60.0 - PARTITION_TOL_S, 120.0 - PARTITION_TOL_S)])
        self.assertEqual(net.windows("Drone2", "Drone3"), [])
        with self.assertRaisesRegex(ValueError, "none of the partition's groups"):
            net.partitioned("Drone9", "Drone1", 90.0)

    def test_the_roster_must_be_the_partitions_own(self):
        net = model(partitions=(SPLIT,))
        net.check_roster(DRONES)
        with self.assertRaisesRegex(ValueError, "the roster and base"):
            net.check_roster(DRONES + ("Drone4",))

    def test_the_rate_limit_is_a_bucket_of_one_seconds_worth(self):
        tx = Transmitter(model(rate_limit_per_s=2.0), start=0.0)
        self.assertEqual([tx.admit(0.0), tx.admit(0.0), tx.admit(0.0)], [True, True, False])
        self.assertEqual([tx.admit(0.5), tx.admit(0.5)], [True, False])                # half a second, one token
        self.assertEqual([tx.admit(10.0), tx.admit(10.0), tx.admit(10.0)], [True, True, False])   # never above two
        self.assertTrue(all(Transmitter(model(), 0.0).admit(0.0) for _ in range(100)))   # no limit

    def test_bandwidth_queues_a_drones_messages(self):
        tx = Transmitter(model(bandwidth_bytes_per_s=4000.0), start=0.0)
        self.assertEqual([tx.sent_by(0.0, 4000), tx.sent_by(0.0, 2000), tx.sent_by(5.0, 400)], [1.0, 1.5, 5.1])
        self.assertEqual(Transmitter(model(), 0.0).sent_by(3.0, 10 ** 6), 3.0)

    def test_its_record(self):
        j = model(partitions=(SPLIT,)).seeded(5).as_json()
        self.assertEqual((j["name"], j["seed"], j["partitions"][0]["groups"]), ("t", 5, [["Drone1", "base"], ["Drone2", "Drone3"]]))


class BusTests(unittest.TestCase):

    def test_a_model_needs_its_seed_and_owns_range_and_latency(self):
        clock = SimClock()
        with self.assertRaisesRegex(ValueError, "no seed"):
            MessageBus(DRONES, clock, lambda d: (0, 0, 0), None, network=model())
        with self.assertRaisesRegex(ValueError, "range and latency are the model's"):
            MessageBus(DRONES, clock, lambda d: (0, 0, 0), 100.0, network=model().seeded(1))
        with self.assertRaisesRegex(ValueError, "range and latency are the model's"):
            MessageBus(DRONES, clock, lambda d: (0, 0, 0), None, delay_s=0.1, network=model().seeded(1))
        with self.assertRaisesRegex(ValueError, "the roster and base"):
            MessageBus(DRONES[:2], clock, lambda d: (0, 0, 0), None, network=model(partitions=(SPLIT,)).seeded(1))

    def test_nominal_is_phase_7s_bus(self):
        clock_a, clock_b = SimClock(), SimClock()
        old = MessageBus(DRONES, clock_a, lambda d: (0, 0, 0), None, mission_id="m", delay_s=MESSAGE_DELAY_S)
        new = MessageBus(DRONES, clock_b, lambda d: (0, 0, 0), None, mission_id="m",
                         network=load_network("nominal").seeded(17))
        for bus, clock in ((old, clock_a), (new, clock_b)):
            for q in range(1, 6):
                for d in DRONES:
                    bus.comms(d).send(beat(d, q, at=clock.now()))
                clock.advance(0.5)
                for d in DRONES:
                    bus.comms(d).receive_available()
        key = [(d.message.message_id, d.recipient, d.sent_at, d.scheduled_at, d.status, d.delivered_at) for d in old.deliveries()]
        self.assertEqual(key, [(d.message.message_id, d.recipient, d.sent_at, d.scheduled_at, d.status, d.delivered_at)
                               for d in new.deliveries()])

    def test_latency_holds_a_message_until_it_arrives(self):
        bus, clock = bus_with(model(latency_mean_s=0.4))
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        clock.advance(0.39)
        self.assertEqual(bus.comms("Drone2").receive_available(), ())
        clock.advance(0.02)
        self.assertEqual([m.message_id for m in bus.comms("Drone2").receive_available()], ["Drone1#1"])
        (d,) = bus.deliveries()
        self.assertEqual((d.status, d.scheduled_at), (DELIVERED, 0.4))

    def test_a_lost_message_is_recorded_and_never_arrives(self):
        bus, clock = bus_with(model(loss_probability=0.5))
        for q in range(1, 41):
            bus.comms("Drone1").send(beat("Drone1", q))
        clock.advance(1.0)
        got = {m.message_id for d in ("Drone2", "Drone3") for m in bus.comms(d).receive_available()}
        lost = {d.message.message_id for d in bus.deliveries() if d.status == LOST}
        self.assertTrue(lost)
        self.assertEqual(sum(d.status == LOST for d in bus.deliveries()) + sum(d.status == DELIVERED for d in bus.deliveries()), 80)
        self.assertTrue(all(d.scheduled_at is None for d in bus.deliveries() if d.status == LOST))
        self.assertTrue(got)

    def test_the_order_drones_send_in_changes_no_fate(self):
        net = model(loss_probability=0.3, latency_jitter_s=0.1)
        a, _ = bus_with(net)
        b, _ = bus_with(net)
        for q in range(1, 30):
            for d in DRONES:
                a.comms(d).send(beat(d, q))
            for d in reversed(DRONES):
                b.comms(d).send(beat(d, q))
        self.assertEqual(fates(a), fates(b))

    def test_over_the_rate_limit_a_message_reaches_nobody(self):
        bus, clock = bus_with(model(rate_limit_per_s=2.0))
        for q in range(1, 4):
            bus.comms("Drone1").send(beat("Drone1", q))                     # a broadcast is one transmission
        statuses = {(d.message.message_id, d.recipient): d.status for d in bus.deliveries()}
        self.assertEqual(statuses, {("Drone1#1", "Drone2"): PENDING, ("Drone1#1", "Drone3"): PENDING,
                                    ("Drone1#2", "Drone2"): PENDING, ("Drone1#2", "Drone3"): PENDING,
                                    ("Drone1#3", "Drone2"): RATE_LIMITED, ("Drone1#3", "Drone3"): RATE_LIMITED})
        bus.comms("Drone2").send(beat("Drone2"))                             # another drone's own bucket
        self.assertEqual(bus.deliveries()[-1].status, PENDING)

    def test_bandwidth_delays_what_queues_behind(self):
        bus, _ = bus_with(model(bandwidth_bytes_per_s=1000.0))
        bus.comms("Drone1").send(beat("Drone1", 1, to=("Drone2",)))
        bus.comms("Drone1").send(beat("Drone1", 2, to=("Drone2",)))
        first, second = bus.deliveries()
        self.assertGreater(second.scheduled_at - first.scheduled_at, 0.1)   # a heartbeat is a few hundred bytes

    def test_range_is_the_models(self):
        bus, _ = bus_with(model(range_m=50.0), Drone2=(60.0, 0.0, 10.0))
        bus.comms("Drone1").send(beat("Drone1"))
        self.assertEqual({d.recipient: d.status for d in bus.deliveries()}, {"Drone2": OUT_OF_RANGE, "Drone3": PENDING})

    def test_a_partition_cuts_only_between_its_groups_and_only_in_its_interval(self):
        bus, clock = bus_with(model(partitions=(SPLIT,)))
        seq = iter(range(1, 100))
        for t in (0.0, 60.0, 90.0, 120.0):
            clock.advance(t - clock.now())
            for d in DRONES:
                bus.comms(d).send(beat(d, next(seq), at=t))
        got = {}
        for d in bus.deliveries():
            got.setdefault(d.sent_at, {})[(d.message.sender_id, d.recipient)] = d.status
        self.assertNotIn(PARTITIONED, got[0.0].values())
        self.assertNotIn(PARTITIONED, got[120.0].values())
        for t in (60.0, 90.0):
            self.assertEqual({k for k, s in got[t].items() if s == PARTITIONED},
                             {("Drone1", "Drone2"), ("Drone1", "Drone3"), ("Drone2", "Drone1"), ("Drone3", "Drone1")})

    def test_a_message_that_outlives_its_lifetime_is_expired(self):
        bus, clock = bus_with(model(latency_mean_s=5.0))                    # a heartbeat lives 3 s
        bus.comms("Drone1").send(beat("Drone1", to=("Drone2",)))
        clock.advance(6.0)
        self.assertEqual(bus.comms("Drone2").receive_available(), ())
        self.assertEqual(bus.deliveries()[0].status, EXPIRED)


class BaseLinkTests(unittest.TestCase):

    def test_no_chain_crosses_a_partition(self):
        points = {"Drone1": (50.0, 0.0, 10.0), "Drone2": (140.0, 0.0, 10.0)}           # Drone2 only via Drone1
        base = (0.0, 0.0, 0.0)
        self.assertEqual(_reach_base(points, base, 100.0), {"Drone1", "Drone2"})
        net = model(partitions=(Partition((frozenset({"Drone1", "base"}), frozenset({"Drone2"})), 0.0, 10.0),))
        self.assertEqual(_reach_base(points, base, 100.0, lambda a, b: net.partitioned(a, b, 5.0)), {"Drone1"})
        cut_base = model(partitions=(Partition((frozenset({"base"}), frozenset({"Drone1", "Drone2"})), 0.0, 10.0),))
        self.assertEqual(_reach_base(points, base, 100.0, lambda a, b: cut_base.partitioned(a, b, 5.0)), set())

    def test_cut_removes_the_open_window(self):
        self.assertEqual(_cut([(0.0, 200.0)], [(60.0, 120.0)]), [(0.0, 60.0), (120.0, 200.0)])
        self.assertEqual(_cut([(0.0, 50.0), (130.0, 140.0)], [(60.0, 120.0)]), [(0.0, 50.0), (130.0, 140.0)])
        self.assertEqual(_cut([(70.0, 80.0)], [(60.0, 120.0)]), [])
        self.assertEqual(_cut([(0.0, 60.0)], [(60.0, 120.0)]), [(0.0, 60.0)])           # up at its very edge
        self.assertEqual(_cut([(0.0, 120.5)], [(60.0, 120.0)]), [(0.0, 60.0), (120.0, 120.5)])   # up again just after
        self.assertEqual(_cut([(90.0, 120.0)], [(60.0, 120.0)]), [(120.0, 120.0)])       # up at its far edge, too

    def test_the_judge_cuts_the_base_link_where_the_sensing_does(self):
        start = 1000.0
        near = Trajectory("Drone1", [Knot(start, 10.0, 0.0, 10.0, True)])
        net = model(partitions=(Partition((frozenset({"base"}), frozenset({"Drone1"})), 60.0, 120.0),))
        radio = Connectivity([near], (0.0, 0.0), 100.0, start, start + 200.0, net)
        for t, up in ((0.0, True), (59.9, True), (60.0, False), (90.0, False), (119.9, False), (120.0, True), (200.0, True)):
            with self.subTest(t=t):
                self.assertEqual(radio.connected_at("Drone1", start + t), up)
                self.assertEqual(not net.partitioned("Drone1", "base", t), up)
        self.assertEqual(Connectivity([near], (0.0, 0.0), 100.0, start, start + 200.0).spans("Drone1"),
                         [(start, start + 200.0)])


class BoundaryTests(unittest.TestCase):

    def test_an_agent_on_a_degraded_network_reaches_nothing_of_it(self):
        # Mid-flight on a partitioned, lossy bus: the agent holds its comms and its sensors, and through
        # neither reaches the model; the same walk from the bus does reach it, so the walk can see one.
        import threading
        from test_sensing import ground_truth_reached
        from agentic_uav.agents.drone_agent import DroneAgent
        from agentic_uav.agents.rule_policy import RulePolicy
        from agentic_uav.control.action_executor import ActionExecutor
        from agentic_uav.control.skills import SkillRunner
        from agentic_uav.core.models import Position
        from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld
        from agentic_uav.simulator.sensing import mock_sensors
        sc = scenarios.load_scenario("search_relay_001")
        roster = [v.id for v in sc.vehicles]
        world = MockWorld(declared=roster)
        for v in sc.vehicles:
            MockVehicleAdapter(world).place_vehicle(v.id, Position(v.start_x, v.start_y, world.ground_z))
        net = dataclasses.replace(load_network("partitioned"), loss_probability=0.2).seeded(1)
        bus = MessageBus(roster, world.clock, lambda d: (0.0, 0.0, 0.0), None, mission_id=sc.scenario_id, network=net)
        executor = ActionExecutor(SkillRunner(MockVehicleAdapter(world), "Drone1", world.clock))
        out = {}

        def fly():
            with world.clock.participate():
                agent = DroneAgent(sc.brief(), mock_sensors(world, sc, "Drone1", network=net), executor, RulePolicy(),
                                   comms=bus.comms("Drone1"))
                agent.assign("search S1")
                for _ in range(20):
                    agent.step()
                    world.clock.sleep(agent.tick_s)
                out["agent"] = agent

        thread = threading.Thread(target=fly)
        thread.start()
        thread.join()
        executor.close()
        self.assertEqual(ground_truth_reached(out["agent"]), [])
        self.assertIn("NetworkModel", [name for name, _ in ground_truth_reached(dict(vars(bus)))])


class ConditionTests(unittest.TestCase):

    def test_the_four_levels_as_fixed(self):
        got = {c: load_network(c) for c in CONDITIONS}
        self.assertEqual({c: (m.latency_mean_s, m.latency_jitter_s, m.loss_probability, m.rate_limit_per_s,
                              m.bandwidth_bytes_per_s, m.range_m) for c, m in got.items()},
                         {"nominal": (0.1, 0.0, 0.0, None, None, None),
                          "moderate": (0.3, 0.1, 0.1, None, None, None),
                          "severe": (1.0, 0.5, 0.3, 2.0, 4000.0, None),
                          "partitioned": (0.1, 0.0, 0.0, None, None, None)})
        self.assertEqual(got["nominal"].latency_mean_s, MESSAGE_DELAY_S)          # the network Phases 7-9 flew
        (p,) = got["partitioned"].partitions
        self.assertEqual((sorted(map(sorted, p.groups)), p.start_s, p.end_s),
                         ([["Drone1", "Drone2", "base"], ["Drone3", "Drone4"]], 60.0, 120.0))
        self.assertTrue(all(not m.partitions for c, m in got.items() if c != "partitioned"))

    def test_a_manifest_is_read_strictly(self):
        good = {"latency": {"mean_s": 0.1}}
        self.assertEqual(parse_network(good, "x").latency_floor_s, 0.05)
        for bad, why in (({}, "missing mean_s"), ({"latency": {"mean_s": 0.1, "typo": 1}}, "unknown key typo"),
                         ({**good, "radio": {}}, r"unknown section \[radio\]"),
                         ({"latency": {"mean_s": "fast"}}, "not a number"),
                         ({**good, "partition": [{"groups": [["a"], ["b"]], "start_s": 1.0}]}, "missing end_s"),
                         ({**good, "partition": [{"groups": "ab", "start_s": 1.0, "end_s": 2.0}]}, "lists of names")):
            with self.subTest(why=why), self.assertRaisesRegex(ValueError, why):
                parse_network(bad, "x")


class FlightTests(unittest.TestCase):
    """The canonical mission flown under each condition, the condition never told to an agent."""

    @classmethod
    def setUpClass(cls):
        cls.sc = scenarios.load_scenario("search_relay_001")
        cls.A, cls.H = load_allocation(), load_recovery()
        cls.phase9 = fly_recovery_on_mock(cls.sc, cls.A, cls.H, "no stop")
        cls.flights = {c: fly_recovery_on_mock(cls.sc, cls.A, cls.H, "no stop", network=load_network(c)) for c in CONDITIONS}

    @staticmethod
    def canonical(run):
        return sorted((d.sent_at, d.message.sender_id, d.message.sequence_number, d.recipient, d.scheduled_at, d.status,
                       d.delivered_at) for d in run.team.deliveries)

    def test_nominal_is_phase_9(self):
        self.assertEqual(self.flights["nominal"].policies, self.phase9.policies)
        self.assertEqual(self.canonical(self.flights["nominal"]), self.canonical(self.phase9))

    def test_flown_again_every_message_meets_the_same_fate(self):
        for c in ("moderate", "partitioned"):
            with self.subTest(condition=c):
                again = fly_recovery_on_mock(self.sc, self.A, self.H, "no stop", network=load_network(c))
                self.assertEqual(self.canonical(again), self.canonical(self.flights[c]))

    def test_each_condition_shows_in_the_record(self):
        def count(c, status):
            return sum(d.status == status for d in self.flights[c].team.deliveries)
        self.assertEqual([count("nominal", s) for s in (LOST, RATE_LIMITED, PARTITIONED)], [0, 0, 0])
        self.assertGreater(count("moderate", LOST), 0)
        self.assertEqual(count("moderate", RATE_LIMITED), 0)
        self.assertGreater(count("severe", LOST), count("moderate", LOST))
        self.assertGreater(count("severe", RATE_LIMITED), 0)
        cut = [d for d in self.flights["partitioned"].team.deliveries if d.status == PARTITIONED]
        start = self.flights["partitioned"].team.start
        self.assertTrue(cut)
        self.assertTrue(all(60.0 - 1e-6 < d.sent_at - start < 120.0 for d in cut))
        sides = {"Drone1": 0, "Drone2": 0, "Drone3": 1, "Drone4": 1}
        self.assertTrue(all(sides[d.message.sender_id] != sides[d.recipient] for d in cut))

    def test_the_run_carries_its_seeded_model_and_the_brief_does_not(self):
        run = self.flights["severe"]
        self.assertEqual((run.network.name, run.network.seed), ("severe", self.sc.random_seed))
        self.assertIsNone(self.phase9.network)
        self.assertEqual(dataclasses.asdict(self.sc.brief().network), {"profile": "perfect", "communication_range_m": 100.0})

    def test_every_decision_is_known_exactly_under_every_condition(self):
        # The base link a drone reads in a partition is the judge's, decision by decision.
        for c, run in self.flights.items():
            with self.subTest(condition=c):
                k = known_exactly(run, self.sc)
                self.assertTrue(k["ok"], k["problems"][:3])

    def test_a_partition_cuts_the_far_group_from_the_base(self):
        run = self.flights["partitioned"]
        start = run.team.start
        from agentic_uav.experiments.knowledge import Truth
        truth = Truth(self.sc, run.team.trajectories, start, run.team.report.until, run.network)
        for t in (61.0, 90.0, 119.0):
            self.assertFalse(truth.base_link("Drone3", start + t))
            self.assertFalse(truth.base_link("Drone4", start + t))
        # And the flight's own judge saw the same: the same trajectories judged without the network have
        # the far group reaching the base inside the window -- so the cut is the partition's, not the range's.
        from agentic_uav.experiments.evaluation import evaluate
        plain = evaluate(self.sc, run.team.trajectories, start, run.team.report.until, failed=list(run.stopped))

        def inside(spans):
            return [(s0, s1) for s0, s1 in spans if s0 < start + 120.0 - 1e-6 and s1 > start + 60.0]
        self.assertTrue(any(inside(plain.facts.connected[d]) for d in ("Drone3", "Drone4")))
        for d in ("Drone3", "Drone4"):
            self.assertEqual(inside(run.team.report.facts.connected[d]), [], d)

if __name__ == "__main__":
    unittest.main()
