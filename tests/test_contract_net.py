#!/usr/bin/env python3
"""Tests for agentic_uav.coordination.contract_net: the protocol as pure logic (AUV-08, 8.2, 8.4, 8.5).

    python -m unittest discover tests

WHY THESE EXIST
---------------
The contract-net is how four drones divide one mission with nobody in
charge, and it has to come out the same however the messages fall. These run
it with no flight at all: drones exchange real messages over a small wire in
the test -- what one says at a tick the others hear at the next, unless a
test drops it -- so every case can be made to happen on purpose: everyone
hearing every bid; everyone claiming at once; a bid lost; two equal bids; a
holder falling silent until its lease runs out; a late claim for an old
version; a task released, completed, or learned of only from its progress.
"""

import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.coordination.bids import AllocationConfig, Bidder, BidWeights, bid_for  # noqa: E402
from agentic_uav.coordination.contract_net import ContractNet, Out  # noqa: E402
from agentic_uav.coordination.tasks import TaskStatus, tasks_from_brief  # noqa: E402
from agentic_uav.core.messages import BROADCAST, MessageType, new_message  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
BRIEF = TEAM.brief()
TICK = 0.5
DELIBERATING = AllocationConfig(BidWeights(), 1.0, 2.0, 10.0)
CONTESTED = AllocationConfig(BidWeights(), 0.0, 2.0, 10.0)
EXPECTED = {"Drone4": "search S2", "Drone3": "search S1", "Drone2": "search S4", "Drone1": "search S3"}


class Wire:
    """Four drones' contract-nets, and the messages between them, a tick at a time."""

    def __init__(self, config, drones=("Drone1", "Drone2", "Drone3", "Drone4"), where=None, drop=None):
        self.nets = {d: ContractNet(d, tasks_from_brief(BRIEF), config) for d in drones}
        self.where = where or {v.id: (v.start_x, v.start_y) for v in TEAM.vehicles}
        self.drop = drop or (lambda message, recipient: False)
        self.silent: set[str] = set()
        self.seq = {d: 0 for d in drones}
        self.queue = []
        self.sent = []
        self.now = 0.0

    def bid_fn(self, drone):
        x, y = self.where[drone]
        me = Bidder(drone, x, y, 100.0, (x, y), 900.0 - self.now, 12.0, 5.0)
        return lambda task: bid_for(task, me, BRIEF, BidWeights())

    def envelope(self, drone, out):
        payload = dict(out.payload)
        if out.kind is MessageType.STATUS_UPDATE:
            x, y = self.where[drone]
            payload.update(task=None, stage=None, skill=None, position=[x, y, 12.0], battery=90.0, degraded=False)
        self.seq[drone] += 1
        return new_message(out.kind, drone, BROADCAST, BRIEF.scenario_id, self.now, self.seq[drone], payload)

    def send(self, drone, outs):
        if drone in self.silent:
            return
        for out in outs:
            m = self.envelope(drone, out)
            self.queue.append(m)
            self.sent.append(m)

    def step(self, progress=0.3):
        """Deliver what was sent at the last tick, then let every drone tick."""
        arriving, self.queue = self.queue, []
        for d, net in self.nets.items():
            for m in arriving:
                if m.is_for(d) and not self.drop(m, d):
                    self.send(d, net.receive(m, self.now))
        for d, net in self.nets.items():
            self.send(d, net.tick(self.now, self.bid_fn(d), progress))
        self.now += TICK

    def run(self, seconds):
        for _ in range(round(seconds / TICK)):
            self.step()

    def holders(self, view=None):
        """Who holds what, as `view`'s book has it (default: as each says of itself)."""
        if view is None:
            return {d: net.holding for d, net in self.nets.items()}
        return {t.task_id: t.assigned_agent for t in self.nets[view].book.tasks()}

    def sent_of(self, kind):
        return [m for m in self.sent if m.message_type is kind]


class DeliberatingTests(unittest.TestCase):

    def setUp(self):
        self.wire = Wire(DELIBERATING)
        self.wire.run(3.0)

    def test_every_drone_gets_one_task_and_nobody_assigned_them(self):
        self.assertEqual(self.wire.holders(), EXPECTED)

    def test_every_book_agrees(self):
        books = [self.wire.holders(view=d) for d in self.wire.nets]
        self.assertTrue(all(b == books[0] for b in books))
        self.assertEqual(books[0], {t: d for d, t in EXPECTED.items()})
        for net in self.wire.nets.values():
            self.assertEqual({t.status for t in net.book.tasks()}, {TaskStatus.CLAIMED})

    def test_bids_then_claims_after_the_window_and_no_conflicts(self):
        bids, claims = self.wire.sent_of(MessageType.TASK_BID), self.wire.sent_of(MessageType.TASK_AWARD)
        self.assertEqual(len(bids), 16)                                   # four drones, four tasks
        self.assertEqual({m.timestamp for m in bids}, {0.0})
        self.assertEqual(len(claims), 4)
        self.assertEqual({m.timestamp for m in claims}, {1.0})            # the window: every bid heard first
        self.assertEqual([c for n in self.wire.nets.values() for c in n.corrections], [])
        self.assertEqual(self.wire.sent_of(MessageType.TASK_RELEASE), [])

    def test_every_claim_made_on_every_bid_for_it(self):
        for d, net in self.wire.nets.items():
            (made,) = net.claims_made
            self.assertEqual(made.task_id, EXPECTED[d])
            self.assertEqual(set(made.heard), set(self.wire.nets))
            self.assertEqual(made.value, min(made.heard.values()) if d == "Drone4" else made.heard[d])

    def test_each_claim_acknowledged_by_the_others(self):
        accepts = self.wire.sent_of(MessageType.TASK_ACCEPT)
        self.assertEqual(len(accepts), 12)
        for d, task in EXPECTED.items():
            self.assertEqual({m.sender_id for m in accepts if m.payload["task_id"] == task},
                             set(self.wire.nets) - {d})
            self.assertEqual(self.wire.nets[d].acks[(task, 1)], set(self.wire.nets) - {d})

    def test_a_lease_runs_from_the_claim_and_reports_a_period_on(self):
        # Settled at 1.5, from claims sent at 1.0: the lease is the claim's, not the settling's.
        for d, net in self.wire.nets.items():
            for task_id, holder in self.wire.holders(view=d).items():
                if holder != d:
                    self.assertEqual(net.book.log[[e.task_id for e in net.book.log].index(task_id)]
                                     .after["lease_expires_at"], 11.0)
        self.wire.run(2.0)
        first = {}
        for m in self.wire.sent_of(MessageType.STATUS_UPDATE):
            first.setdefault(m.sender_id, m.timestamp)
        self.assertEqual(first, {d: 3.0 for d in self.wire.nets})        # the claim at 1.0 counts as the first

    def test_progress_renews_every_lease(self):
        self.wire.run(60.0)
        self.assertEqual(self.wire.holders(), EXPECTED)
        for net in self.wire.nets.values():
            for t in net.book.tasks():
                self.assertEqual(t.status, TaskStatus.CLAIMED)
                self.assertGreater(t.lease_expires_at, self.wire.now)
        progress = self.wire.sent_of(MessageType.STATUS_UPDATE)
        self.assertTrue(all(m.payload["task_progress"] == 0.3 for m in progress))
        self.assertEqual(self.wire.sent_of(MessageType.TASK_ANNOUNCEMENT), [])


class ContestedTests(unittest.TestCase):

    def setUp(self):
        self.wire = Wire(CONTESTED)
        self.wire.run(3.0)

    def test_everyone_claims_at_once(self):
        first = [m for m in self.wire.sent_of(MessageType.TASK_AWARD) if m.timestamp == 0.0]
        self.assertEqual(len(first), 4)
        self.assertEqual({m.payload["task_id"] for m in first}, {"search S2"})     # each its own best

    def test_settled_by_the_lowest_bid_in_every_book(self):
        self.assertEqual(self.wire.holders(), EXPECTED)
        for d, net in self.wire.nets.items():
            # Every book, the winner's too, logs each losing claim against the true winner, once.
            self.assertEqual(sorted((c.task_id, c.kept, c.displaced, c.rule, c.at) for c in net.corrections),
                             [("search S2", "Drone4", loser, "lowest valid bid", 0.5)
                              for loser in ("Drone1", "Drone2", "Drone3")], d)

    def test_losers_release_and_claim_again(self):
        releases = self.wire.sent_of(MessageType.TASK_RELEASE)
        self.assertEqual({m.sender_id for m in releases}, {"Drone1", "Drone2", "Drone3"})
        self.assertEqual(len(releases), 3)
        self.assertTrue(all(m.payload["task_id"] == "search S2" and "lost to Drone4" in m.payload["why"]
                            for m in releases))
        for d in ("Drone1", "Drone2", "Drone3"):
            self.assertEqual([c.task_id for c in self.wire.nets[d].claims_made], ["search S2", EXPECTED[d]])

    def test_deterministic(self):
        again = Wire(CONTESTED)
        again.run(3.0)
        self.assertEqual([m.as_json() for m in again.sent], [m.as_json() for m in self.wire.sent])
        self.assertEqual([[c.as_json() for c in n.corrections] for n in again.nets.values()],
                         [[c.as_json() for c in n.corrections] for n in self.wire.nets.values()])


class ConflictRuleTests(unittest.TestCase):

    def test_equal_bids_go_to_the_lower_agent_id(self):
        same = {d: (6.0, 0.0) for d in ("Drone1", "Drone2", "Drone3", "Drone4")}
        wire = Wire(CONTESTED, where=same)
        wire.run(3.0)
        first = {m.sender_id for m in wire.sent_of(MessageType.TASK_AWARD) if m.timestamp == 0.0}
        self.assertEqual(first, set(same))
        self.assertEqual(wire.holders(view="Drone4")["search S2"], "Drone1")
        self.assertTrue(all(c.kept == "Drone1" and c.rule == "lower agent id"
                            for n in wire.nets.values() for c in n.corrections))
        self.assertEqual(len(set(wire.holders().values())), 4)

    def test_a_lost_bid_makes_a_conflict_and_the_rules_settle_it(self):
        # Drone3 never hears Drone4's bids: it thinks S2 is its own.
        wire = Wire(DELIBERATING, drop=lambda m, to: m.message_type is MessageType.TASK_BID
                    and m.sender_id == "Drone4" and to == "Drone3")
        wire.run(4.0)
        self.assertEqual(wire.nets["Drone3"].claims_made[0].task_id, "search S2")
        self.assertTrue(any(c.kept == "Drone4" and c.displaced == "Drone3" for c in wire.nets["Drone1"].corrections))
        books = [wire.holders(view=d) for d in wire.nets]
        self.assertTrue(all(b == books[0] for b in books))
        self.assertEqual(len(set(wire.holders().values())), 4)
        self.assertEqual(books[0]["search S2"], "Drone4")

    def test_a_claim_for_an_old_version_is_refused_and_logged(self):
        wire = Wire(DELIBERATING)
        wire.run(3.0)
        net = wire.nets["Drone1"]
        t = net.book.get("search S4")
        net.book.update(t.reopened(), wire.now, "a test: back in the pool")         # now version 2
        stale = new_message(MessageType.TASK_AWARD, "Drone2", BROADCAST, BRIEF.scenario_id, wire.now, 99,
                            {"task_id": "search S4", "version": 1, "value": 1.0})
        self.assertEqual(net.receive(stale, wire.now), [])
        self.assertEqual(net.book.get("search S4").status, TaskStatus.OPEN)
        self.assertEqual(net.corrections[-1].as_json()["rule"], "task version")
        self.assertEqual(net.corrections[-1].displaced, "Drone2")


class LateClaimTests(unittest.TestCase):

    def test_each_losing_claim_is_logged_once(self):
        net = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        net.stop()                                       # it only listens here
        for at, who, value in ((0.0, "Drone2", 100.0), (0.5, "Drone3", 120.0), (1.0, "Drone4", 130.0)):
            claim = new_message(MessageType.TASK_AWARD, who, BROADCAST, BRIEF.scenario_id, at, 1,
                                {"task_id": "search S1", "version": 1, "value": value})
            net.receive(claim, at)
            net.tick(at + 0.25, lambda task: None)
        self.assertEqual([(c.kept, c.displaced) for c in net.corrections], [("Drone2", "Drone3"), ("Drone2", "Drone4")])
        self.assertEqual(net.book.get("search S1").assigned_agent, "Drone2")


class StaleBidTests(unittest.TestCase):

    def test_a_bid_counts_only_while_it_is_current(self):
        # Only S2 is open; Drone2 bid lower for it, then never claimed (busy, unheard, or gone).
        net = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        for seq, (who, task) in enumerate((("Drone3", "search S1"), ("Drone4", "search S3"), ("Drone5", "search S4")), 1):
            net.receive(new_message(MessageType.TASK_AWARD, who, BROADCAST, BRIEF.scenario_id, 0.0, seq,
                                    {"task_id": task, "version": 1, "value": 50.0}), 0.0)
        net.receive(new_message(MessageType.TASK_BID, "Drone2", BROADCAST, BRIEF.scenario_id, 0.0, 9,
                                {"task_id": "search S2", "version": 1, "value": 1.0,
                                 "d": 1.0, "b": 0.0, "l": 0.0, "c": 0.0, "r": 0.0}), 0.0)
        me = Bidder("Drone1", 0.0, 0.0, 100.0, (0.0, 0.0), 900.0, 12.0, 5.0)
        claimed_at, bids_sent = None, []
        t = 0.0
        while t <= 12.0 and claimed_at is None:
            for out in net.tick(t, lambda task: bid_for(task, me, BRIEF, BidWeights())):
                if out.kind is MessageType.TASK_AWARD:
                    claimed_at, claimed = t, out.payload["task_id"]
                if out.kind is MessageType.TASK_BID and out.payload["task_id"] == "search S2":
                    bids_sent.append(t)
            t += TICK
        self.assertEqual(claimed_at, 11.0)                  # held back until its bid lapsed (10 s), then a window
        self.assertEqual(claimed, "search S2")
        self.assertEqual(bids_sent, [0.0, 10.0])            # and its own bid, lapsed too, made again
        # (The other three holders, never renewing in this test, lost their leases at 10 s too.)
        self.assertEqual(net.claims_made[-1].heard, {"Drone1": net.claims_made[-1].value})


class LeaseTests(unittest.TestCase):

    def test_a_silent_holder_loses_its_task_to_the_pool(self):
        wire = Wire(DELIBERATING)
        wire.run(3.0)
        wire.silent.add("Drone2")                       # S4's holder says nothing more
        quiet_from = wire.now
        wire.run(12.0)
        for d in ("Drone1", "Drone3", "Drone4"):
            t = wire.nets[d].book.get("search S4")
            self.assertEqual((t.status, t.version), (TaskStatus.OPEN, 2), d)
        announced = wire.sent_of(MessageType.TASK_ANNOUNCEMENT)
        self.assertTrue(announced)
        self.assertEqual({m.payload["version"] for m in announced}, {2})
        self.assertTrue(all("Drone2's lease ran out" in m.payload["why"] for m in announced))
        # Within a lease and a tick of its last claim or report, not before.
        renewing = [m.timestamp for m in wire.sent if m.sender_id == "Drone2"
                    and m.message_type in (MessageType.TASK_AWARD, MessageType.STATUS_UPDATE)]
        last = max(renewing)
        self.assertLess(last, quiet_from)
        self.assertGreaterEqual(min(m.timestamp for m in announced), last + 10.0)
        self.assertLessEqual(min(m.timestamp for m in announced), last + 10.0 + TICK)

    def test_the_returned_task_goes_to_a_drone_that_comes_free(self):
        wire = Wire(DELIBERATING)
        wire.run(3.0)
        wire.silent.add("Drone2")
        wire.run(12.0)
        wire.send("Drone1", wire.nets["Drone1"].complete(wire.now))    # Drone1 finished S3: free again
        wire.run(3.0)
        self.assertEqual(wire.nets["Drone1"].holding, "search S4")
        for d in ("Drone3", "Drone4"):
            t = wire.nets[d].book.get("search S4")
            self.assertEqual((t.status, t.assigned_agent, t.version), (TaskStatus.CLAIMED, "Drone1", 2))
            self.assertEqual(wire.nets[d].book.get("search S3").status, TaskStatus.COMPLETE)

    def test_the_silent_holder_learns_it_lost_the_task(self):
        wire = Wire(DELIBERATING)
        wire.run(3.0)
        wire.silent.add("Drone2")
        wire.run(12.0)
        news = wire.nets["Drone2"].take_news()
        lost = [n for n in news if n["what"] == "lost"]
        self.assertEqual([n["task"] for n in lost], ["search S4"])            # it heard the task go back
        # Then, free and still the best bidder, it claimed the new version (its claim unheard, being silent).
        self.assertEqual(wire.nets["Drone2"].claims_made[-1].version, 2)


class EndingsTests(unittest.TestCase):

    def setUp(self):
        self.wire = Wire(DELIBERATING)
        self.wire.run(3.0)

    def test_complete_frees_the_drone_and_is_heard(self):
        w = self.wire
        w.send("Drone4", w.nets["Drone4"].complete(w.now))
        w.run(1.0)
        self.assertIsNone(w.nets["Drone4"].holding)
        for net in w.nets.values():
            t = net.book.get("search S2")
            self.assertEqual((t.status, t.assigned_agent), (TaskStatus.COMPLETE, "Drone4"))
        self.assertTrue(w.nets["Drone4"].idle)                           # nothing open: nothing for it
        self.assertFalse(w.nets["Drone4"].done)

    def test_a_task_completed_by_a_teammate_frees_its_holder(self):
        w = self.wire
        net = w.nets["Drone1"]                                         # holds S3
        done = new_message(MessageType.TASK_COMPLETE, "Drone2", BROADCAST, BRIEF.scenario_id, w.now, 99,
                           {"task_id": "search S3", "version": 1})
        net.take_news()
        net.receive(done, w.now)
        self.assertIsNone(net.holding)
        self.assertEqual(net.book.get("search S3").status, TaskStatus.COMPLETE)
        self.assertEqual([n["what"] for n in net.take_news()], ["lost"])
        self.assertEqual(net.tick(w.now, w.bid_fn("Drone1")), [])          # no progress on a finished task

    def test_an_open_task_abandoned(self):
        net = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        self.assertTrue(net.abandon("search S3", 70.0, "nobody can by the deadline"))
        self.assertFalse(net.abandon("search S3", 71.0, "again"))                     # once
        self.assertEqual(net.book.get("search S3").status, TaskStatus.ABANDONED)
        self.assertEqual(net.abandoned, [{"at": 70.0, "task_id": "search S3", "version": 1,
                                          "why": "nobody can by the deadline"}])
        self.assertEqual(net.take_news(), [{"what": "abandoned", "task": "search S3", "why": "nobody can by the deadline"}])
        self.assertEqual(net.as_json()["abandoned"][0]["task_id"], "search S3")
        self.assertNotIn("abandoned", ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING).as_json())
        held = ContractNet("Drone1", tasks_from_brief(BRIEF), CONTESTED)
        held.tick(0.0, Wire(CONTESTED).bid_fn("Drone1"))
        self.assertFalse(held.abandon(held.holding, 1.0, "not open"))

    def test_a_holder_that_gives_up_returns_its_task(self):
        w = self.wire
        w.send("Drone1", w.nets["Drone1"].release(w.now, "low battery"))
        w.run(1.0)
        self.assertTrue(w.nets["Drone1"].done)
        self.assertIsNone(w.nets["Drone1"].holding)
        for net in w.nets.values():
            t = net.book.get("search S3")
            self.assertEqual((t.status, t.version), (TaskStatus.OPEN, 2))
        # Every other drone holds a task, so nobody is free to bid for it; and Drone1, done, does not.
        self.assertEqual([m for m in w.sent_of(MessageType.TASK_BID) if m.payload["version"] == 2], [])
        self.assertEqual(w.nets["Drone1"].my_bids.get(("search S3", 2)), None)

    def test_a_claim_learned_from_its_progress(self):
        w = Wire(DELIBERATING, drop=lambda m, to: m.message_type is MessageType.TASK_AWARD
                 and m.sender_id == "Drone2" and to == "Drone1")
        w.run(4.0)
        t = w.nets["Drone1"].book.get("search S4")
        self.assertEqual((t.status, t.assigned_agent), (TaskStatus.CLAIMED, "Drone2"))
        self.assertIn("its claim unheard", w.nets["Drone1"].book.log[-1].why
                      if w.nets["Drone1"].book.log[-1].task_id == "search S4" else
                      " ".join(e.why for e in w.nets["Drone1"].book.log if e.task_id == "search S4"))

    def test_nothing_it_could_do_is_idle(self):
        net = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        self.assertFalse(net.idle)                                     # not yet bid: it may yet
        able = Bidder("Drone1", 0.0, 0.0, 100.0, (0.0, 0.0), 900.0, 12.0, 5.0)
        net.tick(0.0, lambda task: bid_for(task, able, BRIEF, BidWeights()))
        self.assertIsNone(net.holding)
        self.assertFalse(net.idle)                                     # bid, waiting out the window: not idle
        net = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        poor = Bidder("Drone1", 0.0, 0.0, 25.0, (0.0, 0.0), 900.0, 12.0, 5.0)
        outs = net.tick(0.0, lambda task: bid_for(task, poor, BRIEF, BidWeights()))
        self.assertEqual(outs, [])                                       # no eligible bid: nothing said
        self.assertTrue(net.idle)
        net2 = ContractNet("Drone1", tasks_from_brief(BRIEF), DELIBERATING)
        net2.stop()
        self.assertEqual(net2.tick(0.0, lambda task: bid_for(task, poor, BRIEF, BidWeights())), [])
        self.assertEqual(net2.my_bids, {})

    def test_every_out_is_a_valid_message(self):
        self.wire.run(2.0)                                                # past the first progress report
        kinds = {m.message_type for m in self.wire.sent}
        self.assertEqual(kinds, {MessageType.TASK_BID, MessageType.TASK_AWARD, MessageType.TASK_ACCEPT,
                                 MessageType.STATUS_UPDATE})
        self.assertIsInstance(Out(MessageType.TASK_COMPLETE, {"task_id": "search S1", "version": 1}), Out)

    def test_its_json(self):
        row = self.wire.nets["Drone1"].as_json()
        self.assertEqual(set(row), {"owner", "holding", "book", "corrections", "claims_made", "book_log"})
        self.assertEqual(row["holding"], "search S3")


if __name__ == "__main__":
    unittest.main()
