#!/usr/bin/env python3
"""Tests for agentic_uav.coordination.bids and the allocation manifest (AUV-08, 8.3).

    python -m unittest discover tests

WHY THESE EXIST
---------------
Who wins a task is decided by bids, so a bid must be transparent and
deterministic: every term kept, the same inputs giving the same number, the
lowest winning and the vehicle id breaking ties. A bid must also cost what
the drone will really fly -- the rule policy's own lanes -- or the drone that
"wins" would not be the one that finishes soonest. And the weights must come
from a manifest that refuses a typo rather than falling back to a default.
"""

import dataclasses
import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.rule_policy import RulePolicy  # noqa: E402
from agentic_uav.coordination.bids import (  # noqa: E402
    BATTERY_MARGIN,
    AllocationConfig,
    Bid,
    Bidder,
    BidWeights,
    bid_for,
    rank,
    search_lanes,
)
from agentic_uav.coordination.tasks import tasks_from_brief  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation, parse_allocation  # noqa: E402

TEAM = scenarios.load_scenario("search_relay_001")
BRIEF = TEAM.brief()
TASKS = {t.task_id: t for t in tasks_from_brief(BRIEF)}
W = BidWeights()


def bidder(drone="Drone1", x=0.0, y=0.0, **changes):
    base = Bidder(drone, x, y, 100.0, (x, y), 900.0, 12.0, 5.0)
    return dataclasses.replace(base, **changes)


class LanesTests(unittest.TestCase):

    def test_a_bid_costs_the_lanes_the_rule_policy_flies(self):
        for height in (12.0, 16.0, 20.0, 24.0):
            for sector in BRIEF.sectors:
                with self.subTest(sector=sector.id, height=height):
                    policy = RulePolicy(altitude_m=height)
                    belief = BeliefState.start(BRIEF, "Drone1", Observation(0.0, 0, 0, 0, False, 100.0, (), True,
                                                                             None, 0, None))
                    policy.decide(belief, (Event(Trigger.TASK_ASSIGNED, 0.0, {"task": f"search {sector.id}"}),))
                    self.assertEqual(search_lanes(BRIEF, sector.region, height, policy.speed_mps), policy.lanes)


class BidTests(unittest.TestCase):

    def test_every_term_kept_and_the_sum_its_value(self):
        b = bid_for(TASKS["search S1"], bidder(), BRIEF, W)
        self.assertEqual(set(b.terms), {"D", "B", "L", "C", "R"})
        self.assertTrue(b.eligible)
        self.assertIsNone(b.why_not)
        self.assertAlmostEqual(b.value, sum(getattr(W, f"w_{k.lower()}") * v for k, v in b.terms.items()))
        self.assertEqual((b.task_id, b.version, b.bidder), ("search S1", 1, "Drone1"))

    def test_d_is_the_seconds_to_the_task_and_through_it(self):
        b = bid_for(TASKS["search S1"], bidder(), BRIEF, W)
        self.assertAlmostEqual(b.terms["D"], (b.detail["to_task_m"] + b.detail["lanes_m"]) / 5.0, places=2)
        far = bid_for(TASKS["search S3"], bidder(), BRIEF, W)
        self.assertGreater(far.terms["D"], b.terms["D"])                 # the far sectors cost the trip out
        # Slower costs more -- not exactly twice: the lanes themselves depend
        # on the speed (spacing and overrun come from the detection rule).
        slow = bid_for(TASKS["search S1"], bidder(speed_mps=2.5), BRIEF, W)
        self.assertAlmostEqual(slow.terms["D"], (slow.detail["to_task_m"] + slow.detail["lanes_m"]) / 2.5, places=2)
        self.assertGreater(slow.terms["D"], 1.9 * b.terms["D"])

    def test_the_battery_is_costed_with_the_way_home(self):
        b = bid_for(TASKS["search S3"], bidder(), BRIEF, W)
        lanes = search_lanes(BRIEF, TASKS["search S3"].region, 12.0, 5.0)
        self.assertGreaterEqual(b.detail["home_m"], math.dist(lanes[-1], (0.0, 0.0)) - 1e-6)
        metres = b.detail["to_task_m"] + b.detail["lanes_m"] + b.detail["home_m"]
        self.assertAlmostEqual(b.detail["seconds_with_home"], metres / 5.0, places=2)
        cost = BRIEF.battery.hover_drain_per_s * metres / 5.0 + BRIEF.battery.move_drain_per_m * metres
        self.assertAlmostEqual(b.detail["battery_cost"], cost, places=2)
        # Just enough for the task and the way home is eligible; a little less is not.
        need = cost + BRIEF.battery.reserve + BATTERY_MARGIN
        self.assertTrue(bid_for(TASKS["search S3"], bidder(battery=need + 0.01), BRIEF, W).eligible)
        self.assertFalse(bid_for(TASKS["search S3"], bidder(battery=need - 0.01), BRIEF, W).eligible)

    def test_each_weight_weighs_its_term(self):
        b = bid_for(TASKS["search S2"], bidder(committed_s=30.0), BRIEF, W)
        for name, term in (("w_d", "D"), ("w_l", "L"), ("w_c", "C")):
            heavier = bid_for(TASKS["search S2"], bidder(committed_s=30.0), BRIEF,
                              dataclasses.replace(W, **{name: getattr(W, name) + 1.0}))
            with self.subTest(weight=name):
                self.assertAlmostEqual(heavier.value - b.value, b.terms[term])

    def test_a_nearer_drone_bids_lower(self):
        here = bid_for(TASKS["search S1"], bidder(x=12.0), BRIEF, W)
        there = bid_for(TASKS["search S1"], bidder(x=0.0), BRIEF, W)
        self.assertLess(here.value, there.value)

    def test_l_is_the_work_already_committed(self):
        free = bid_for(TASKS["search S1"], bidder(), BRIEF, W)
        busy = bid_for(TASKS["search S1"], bidder(committed_s=40.0), BRIEF, W)
        self.assertEqual((free.terms["L"], busy.terms["L"]), (0.0, 40.0))
        self.assertAlmostEqual(busy.value - free.value, 40.0)

    def test_c_is_logged_and_not_weighed(self):
        near = bid_for(TASKS["search S1"], bidder(), BRIEF, W)
        far = bid_for(TASKS["search S3"], bidder(), BRIEF, W)
        self.assertGreater(far.terms["C"], near.terms["C"])                 # S3 lies beyond the base's 100 m
        # S1 is partly within reach: some of its lanes count, not all.
        self.assertGreater(near.terms["C"], 0.0)
        self.assertLess(near.terms["C"], near.detail["lanes_m"] / 5.0 - 1.0)
        self.assertEqual(W.w_c, 0.0)
        weighed = bid_for(TASKS["search S3"], bidder(), BRIEF, dataclasses.replace(W, w_c=1.0))
        self.assertAlmostEqual(weighed.value - far.value, far.terms["C"])

    def test_not_eligible_on_battery(self):
        b = bid_for(TASKS["search S3"], bidder(battery=40.0), BRIEF, W)
        self.assertFalse(b.eligible)
        self.assertIsNone(b.value)
        self.assertIn("battery", b.why_not)
        self.assertLess(b.detail["battery_left"], BRIEF.battery.reserve + BATTERY_MARGIN)
        self.assertTrue(bid_for(TASKS["search S3"], bidder(), BRIEF, W).eligible)

    def test_not_eligible_past_the_deadline(self):
        b = bid_for(TASKS["search S1"], bidder(time_left=60.0), BRIEF, W)
        self.assertFalse(b.eligible)
        self.assertIn("deadline", b.why_not)

    def test_not_eligible_without_the_capability(self):
        b = bid_for(TASKS["search S1"], bidder(capabilities=frozenset({"relay"})), BRIEF, W)
        self.assertFalse(b.eligible)
        self.assertEqual(b.why_not, "lacks search")

    def test_the_same_inputs_the_same_bid(self):
        self.assertEqual(bid_for(TASKS["search S2"], bidder(), BRIEF, W), bid_for(TASKS["search S2"], bidder(), BRIEF, W))

    def test_its_json(self):
        row = json.loads(json.dumps(bid_for(TASKS["search S2"], bidder(), BRIEF, W).as_json()))
        self.assertEqual(set(row), {"task_id", "version", "bidder", "value", "terms", "detail", "why_not"})
        self.assertEqual(set(row["detail"]), {"to_task_m", "lanes_m", "home_m", "battery_cost", "battery_left",
                                              "seconds_with_home", "time_left"})


class RankTests(unittest.TestCase):

    def test_lowest_wins_and_the_vehicle_id_breaks_ties(self):
        def b(who, value):
            return Bid("search S1", 1, who, value, {}, {})
        ranked = sorted([b("Drone3", 50.0), b("Drone1", 60.0), b("Drone2", 50.0)], key=rank)
        self.assertEqual([x.bidder for x in ranked], ["Drone2", "Drone3", "Drone1"])
        # Equal to a micro-second's work is equal: no float noise decides a tie.
        self.assertEqual(sorted([b("Drone2", 50.0), b("Drone1", 50.0 + 1e-9)], key=rank)[0].bidder, "Drone1")

    def test_an_ineligible_bid_is_never_ranked(self):
        with self.assertRaises(ValueError):
            rank(Bid("search S1", 1, "Drone1", None, {}, {}, "lacks search"))


class ManifestTests(unittest.TestCase):

    def test_the_default_manifest(self):
        config = load_allocation()
        self.assertEqual(config, AllocationConfig(BidWeights(1.0, 1.0, 1.0, 0.0, 1.0), 1.0, 2.0, 10.0))
        self.assertEqual(config.as_json(), {"weights": {"w_d": 1.0, "w_b": 1.0, "w_l": 1.0, "w_c": 0.0, "w_r": 1.0},
                                            "bid_window_s": 1.0, "progress_period_s": 2.0, "lease_s": 10.0})

    def test_a_typo_is_refused_not_defaulted(self):
        good = {"weights": {"w_d": 1, "w_b": 1, "w_l": 1, "w_c": 0, "w_r": 1},
                "protocol": {"bid_window_s": 1, "progress_period_s": 2, "lease_s": 10}}
        self.assertEqual(parse_allocation(good), load_allocation())
        for bad in ({**good, "extra": {}}, {"weights": good["weights"]},
                    {**good, "weights": {**good["weights"], "w_dd": 1}},
                    {**good, "weights": {k: v for k, v in good["weights"].items() if k != "w_c"}},
                    {**good, "protocol": {**good["protocol"], "lease_s": "10"}},
                    {**good, "protocol": {**good["protocol"], "bid_window_s": True}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_allocation(bad)

    def test_bad_values_are_refused(self):
        for make in (lambda: BidWeights(w_d=-1.0), lambda: BidWeights(w_c=math.inf), lambda: BidWeights(w_b=True),
                     lambda: AllocationConfig(bid_window_s=-0.1), lambda: AllocationConfig(progress_period_s=0.0),
                     lambda: AllocationConfig(lease_s=2.0), lambda: AllocationConfig(weights={"w_d": 1})):
            with self.assertRaises(ValueError):
                make()
        self.assertEqual(AllocationConfig(bid_window_s=0.0).bid_window_s, 0.0)        # contested: allowed

    def test_a_manifest_by_path(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "x.toml")
        with open(path, "w", encoding="utf-8") as h:
            h.write("[weights]\nw_d = 2.0\nw_b = 1.0\nw_l = 1.0\nw_c = 0.0\nw_r = 1.0\n"
                    "[protocol]\nbid_window_s = 0.0\nprogress_period_s = 2.0\nlease_s = 10.0\n")
        try:
            config = load_allocation(path)
            self.assertEqual((config.weights.w_d, config.bid_window_s), (2.0, 0.0))
        finally:
            os.remove(path)
            os.rmdir(folder)


if __name__ == "__main__":
    unittest.main()
