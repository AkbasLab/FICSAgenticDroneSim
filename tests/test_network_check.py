#!/usr/bin/env python3
"""Tests for Phase 10 step 4: the network model's statistical verification (AUV-10, 10.6).

    python -m unittest discover tests

WHY THESE EXIST
---------------
A verification that cannot fail verifies nothing. Each check here passes on a
real stream through the bus and fails on that stream altered to break it: a
loss rate off its interval, latencies from another distribution, a message
admitted that the bucket would refuse, a delivery across a partition, one
delivered past its lifetime or left pending, a record that changes with the
order drones send in. The KS statistic is held to known cases, ties and
steps included -- the two float traps this step met -- and the script's
verdict to its rule: a statistical check may reject on a few seeds by
chance, an exact one on none.
"""

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.experiments import network_check as nc  # noqa: E402
from agentic_uav.experiments.conditions import load_network  # noqa: E402
from agentic_uav.simulator.message_bus import DELIVERED, EXPIRED, LOST, PARTITIONED, PENDING, RATE_LIMITED  # noqa: E402


def altered(stream, change):
    """The stream with its deliveries copied, one changed by `change(deliveries)`."""
    ds = [dataclasses.replace(d) for d in stream["deliveries"]]
    change(ds)
    return {**stream, "deliveries": tuple(ds)}


class StreamTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.moderate = nc.send_stream(load_network("moderate"), 17, duration_s=300.0)
        cls.nominal = nc.send_stream(load_network("nominal"), 17, duration_s=100.0)
        cls.partitioned = nc.send_stream(load_network("partitioned"), 17, duration_s=200.0)
        cls.burst = nc.send_stream(load_network("severe"), 17, period_s=nc.BURST_PERIOD_S, duration_s=30.0)

    def test_the_stream_is_what_it_says(self):
        self.assertEqual(len(self.nominal["deliveries"]), 100 * 4 * 3)
        self.assertEqual(nc.statuses(self.nominal)[DELIVERED], 1200)
        self.assertEqual(nc.statuses(self.nominal)[PENDING], 0)                   # drained

    def test_loss(self):
        self.assertTrue(nc.loss_check(self.moderate)["ok"])
        self.assertTrue(nc.loss_check(self.nominal)["ok"])

        def lose_more(ds):
            for d in ds[:400]:
                d.status = LOST
        self.assertFalse(nc.loss_check(altered(self.moderate, lose_more))["ok"])

        def lose_one(ds):
            ds[0].status = LOST
        self.assertFalse(nc.loss_check(altered(self.nominal, lose_one))["ok"])     # with p = 0, none at all

    def test_loss_is_held_to_its_interval_exactly(self):
        # Half an interval off the configured rate holds; one and a half does not.
        n, p = len(self.moderate["deliveries"]), 0.1
        half = nc.Z99 * (p * (1 - p) / n) ** 0.5

        def exactly(count):
            def change(ds):
                for i, d in enumerate(ds):
                    d.status = LOST if i < count else DELIVERED
            return change
        self.assertTrue(nc.loss_check(altered(self.moderate, exactly(round((p + 0.5 * half) * n))))["ok"])
        self.assertFalse(nc.loss_check(altered(self.moderate, exactly(round((p + 1.5 * half) * n))))["ok"])

    def test_what_the_network_did_not_decide_by_chance_is_not_counted(self):
        # Rate-limited messages were never sent: counted as not lost, they would halve severe's loss.
        self.assertGreater(nc.statuses(self.burst)[RATE_LIMITED], 0)
        got = nc.loss_check(self.burst)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["n"], len(self.burst["deliveries"]) - nc.statuses(self.burst)[RATE_LIMITED])

    def test_latency(self):
        self.assertTrue(nc.latency_check(self.moderate)["ok"])
        self.assertTrue(nc.latency_check(self.nominal)["ok"])
        other = dict(self.moderate, model=dataclasses.replace(self.moderate["model"], latency_mean_s=0.32))
        self.assertFalse(nc.latency_check(other)["ok"])                           # 0.02 s off the mean is seen

        def late(ds):
            for d in ds[::3]:
                if d.scheduled_at is not None:
                    d.scheduled_at += 0.01
        self.assertFalse(nc.latency_check(altered(self.nominal, late))["ok"])

    def test_rate_limit(self):
        got = nc.rate_check(self.burst)
        self.assertTrue(got["ok"])
        self.assertGreater(got["refused"], 0)

        def admit_one(ds):
            next(d for d in ds if d.status == RATE_LIMITED).status = DELIVERED
        self.assertFalse(nc.rate_check(altered(self.burst, admit_one))["ok"])

        def refuse_one(ds):
            next(d for d in ds if d.status == DELIVERED).status = RATE_LIMITED
        self.assertFalse(nc.rate_check(altered(self.burst, refuse_one))["ok"])

    def test_the_bucket_never_holds_more_than_a_seconds_worth(self):
        # After ten idle seconds, a drone limited to two a second still sends only two at once.
        from types import SimpleNamespace
        from agentic_uav.simulator.network import NetworkModel
        model = NetworkModel("t", 0.1, rate_limit_per_s=2.0).seeded(1)
        sends = [(0.0, False), (0.0, False), (0.0, True), (10.0, False), (10.0, False), (10.0, True)]
        ds = [SimpleNamespace(message=SimpleNamespace(sender_id="Drone1", sequence_number=i + 1), sent_at=t,
                              status=RATE_LIMITED if refused else DELIVERED) for i, (t, refused) in enumerate(sends)]
        self.assertTrue(nc.rate_check({"model": model, "start": 0.0, "deliveries": ds})["ok"])
        ds[-1].status = DELIVERED                                                  # as if it had saved up
        self.assertFalse(nc.rate_check({"model": model, "start": 0.0, "deliveries": ds})["ok"])

    def test_partitions(self):
        got = nc.partition_check(self.partitioned)
        self.assertTrue(got["ok"])
        self.assertEqual(got["cut"], 60 * 4 * 2)                                  # 60 s, each drone to the 2 across

        def leak(ds):
            next(d for d in ds if d.status == PARTITIONED).status = DELIVERED
        self.assertFalse(nc.partition_check(altered(self.partitioned, leak))["ok"])

        def later_clock(ds):                         # the same flight on a clock that did not start at zero
            for d in ds:
                d.sent_at += 1000.0
        shifted = altered(self.partitioned, later_clock)
        self.assertTrue(nc.partition_check({**shifted, "start": self.partitioned["start"] + 1000.0})["ok"])

        def cut_within(ds):
            d = next(d for d in ds if d.message.sender_id == "Drone1" and d.recipient == "Drone2"
                     and d.sent_at - self.partitioned["start"] > 70.0)
            d.status = PARTITIONED
        self.assertFalse(nc.partition_check(altered(self.partitioned, cut_within))["ok"])

    def test_expiry(self):
        self.assertTrue(nc.expiry_check(self.moderate)["ok"])

        def deliver_late(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            d.delivered_at = d.message.expires_at + 0.5
        self.assertFalse(nc.expiry_check(altered(self.moderate, deliver_late))["ok"])

        def left_pending(ds):
            ds[0].status = PENDING
        self.assertFalse(nc.expiry_check(altered(self.moderate, left_pending))["ok"])

        def arrived_late_yet_delivered(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            d.scheduled_at = d.message.expires_at + 1.0
        self.assertFalse(nc.expiry_check(altered(self.moderate, arrived_late_yet_delivered))["ok"])


class SeedTests(unittest.TestCase):

    def test_the_same_seed_the_same_order_free_another_seed_another(self):
        got = nc.seed_check(load_network("moderate"), 17, duration_s=30.0)
        self.assertEqual((got["same_seed_same"], got["order_free"], got["other_seed_differs"], got["ok"]),
                         (True, True, True, True))
        flat = nc.seed_check(load_network("nominal"), 17, duration_s=30.0)
        self.assertEqual((flat["other_seed_differs"], flat["ok"]), (None, True))   # it draws nothing

    def test_it_fails_when_the_order_matters(self):
        real = nc.send_stream

        def order_matters(model, seed, period_s=1.0, duration_s=1000.0, reverse=False, roster=nc.ROSTER):
            s = real(model, seed, period_s, duration_s)
            return s if not reverse else {**s, "deliveries": s["deliveries"][1:]}
        with mock.patch.object(nc, "send_stream", side_effect=order_matters):
            got = nc.seed_check(load_network("moderate"), 17, duration_s=20.0)
        self.assertFalse(got["ok"])
        self.assertIn("reverse order", " ".join(got["problems"]))

    def test_it_fails_when_another_seed_changes_nothing(self):
        real = nc.send_stream
        with mock.patch.object(nc, "send_stream", side_effect=lambda m, s, **kw: real(m, 17, **kw)):
            got = nc.seed_check(load_network("moderate"), 17, duration_s=20.0)
        self.assertIn("another seed gave the same record", got["problems"])


class StatisticTests(unittest.TestCase):

    def test_ks_on_known_cases(self):
        uniform = [(i + 0.5) / 1000 for i in range(1000)]
        self.assertLess(nc.ks_statistic(uniform, lambda x: min(max(x, 0.0), 1.0)), 0.001)
        self.assertAlmostEqual(nc.ks_statistic(uniform, lambda x: min(max(x - 0.1, 0.0), 1.0)), 0.1, places=2)

    def test_a_sample_below_its_place_is_seen_from_the_left(self):
        # One value at 0.9 against a uniform: the empirical CDF is 0 just before it, where F is 0.9.
        self.assertAlmostEqual(nc.ks_statistic([0.9], lambda x: min(max(x, 0.0), 1.0)), 0.9, places=5)

    def test_ties_are_one_step(self):
        # 100 values at one point, against a step there: no distance at all.
        self.assertEqual(nc.ks_statistic([0.1] * 100, lambda x: 1.0 if x >= 0.1 else 0.0), 0.0)

    def test_the_cdf_has_its_floor_and_its_step(self):
        cdf = nc.latency_cdf
        self.assertEqual(cdf(0.049, 1.0, 0.5, 0.05), 0.0)
        self.assertAlmostEqual(cdf(0.05 - 1e-12, 1.0, 0.5, 0.05), 0.0287, places=4)  # a hair under the floor is the floor
        self.assertAlmostEqual(cdf(0.05, 1.0, 0.5, 0.05), 0.0287, places=4)     # the point mass at the floor
        self.assertAlmostEqual(cdf(1.0, 1.0, 0.5, 0.05), 0.5)
        self.assertEqual(cdf(0.1 - 1e-12, 0.1, 0.0, 0.05), 1.0)                   # a hair under the mean is the mean
        self.assertEqual(cdf(0.09, 0.1, 0.0, 0.05), 0.0)

    def test_a_latency_drawn_at_the_floor_comes_back_at_it(self):
        s = nc.send_stream(load_network("severe"), 3, duration_s=200.0)
        at_floor = [x for x in nc.latencies(s) if abs(x - 0.05) < 1e-6]
        self.assertTrue(at_floor)
        self.assertEqual(set(at_floor), {0.05})                                   # one value: a tie, not a spread


class StressTests(unittest.TestCase):

    def test_the_stress_networks_hold(self):
        got = nc.check_stress(17, burst_s=20.0)
        self.assertTrue(got["all"], got)
        self.assertGreater(got["slow"]["statuses"][EXPIRED], 0)

    def test_a_slow_network_where_nothing_expires_tests_nothing(self):
        from agentic_uav.simulator.network import NetworkModel
        with mock.patch.object(nc, "slow_model", lambda: NetworkModel("slow", latency_mean_s=0.1)):
            self.assertFalse(nc.check_stress(17, burst_s=20.0)["all"])


class VerdictTests(unittest.TestCase):

    @staticmethod
    def row(seed, **bad):
        r = {"condition": "moderate", "seed": seed}
        for k in ("loss", "latency", "rate_limit", "partitions", "expiry", "seeds"):
            r[k] = {"ok": k not in bad}
        return r

    def test_a_statistical_check_may_reject_on_a_few_seeds_an_exact_one_on_none(self):
        import network_check
        rows = [self.row(1, latency=1), self.row(2, latency=1)] + [self.row(s) for s in range(3, 21)]
        self.assertTrue(network_check.verdict(rows)["moderate"]["all"])
        rows[2] = self.row(3, latency=1)
        self.assertFalse(network_check.verdict(rows)["moderate"]["latency"]["ok"])
        one_exact = [self.row(1, partitions=1)] + [self.row(s) for s in range(2, 21)]
        v = network_check.verdict(one_exact)["moderate"]
        self.assertEqual((v["partitions"]["failed_seeds"], v["all"]), ([1], False))


class ScriptTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_one_seed_writes_its_record(self):
        import network_check
        with redirect_stdout(io.StringIO()) as buffer:
            code = network_check.main(["--seeds", "17", "--out", self.out, "--block", "t"])
        self.assertEqual(code, 0, buffer.getvalue()[-1500:])
        files = sorted(os.listdir(self.out))
        self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
        with open(os.path.join(self.out, files[0]), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        head = rows[0]
        self.assertEqual((head["kind"], head["seeds"], head["all"]), ("header", [17], True))
        self.assertEqual(sorted(head["verdict"]), ["moderate", "nominal", "partitioned", "severe"])
        self.assertEqual(head["manifests"]["severe"], "configs/network/severe.toml")
        self.assertEqual([r["kind"] for r in rows[1:]], ["condition"] * 4 + ["stress"])
        self.assertIn("**10.6: VERIFIED**", buffer.getvalue())

    def test_a_failing_check_fails_the_run(self):
        import network_check
        real = network_check.check_condition

        def broken(model, seed):
            r = real(model, seed, duration_s=50.0, burst_s=10.0)
            if model.name == "severe":
                r["rate_limit"] = {**r["rate_limit"], "ok": False, "problems": ["made to fail"]}
            return r
        with mock.patch.object(network_check, "check_condition", side_effect=broken), \
                mock.patch.object(network_check, "check_stress", side_effect=lambda s: nc.check_stress(s, burst_s=10.0)), \
                redirect_stdout(io.StringIO()) as buffer:
            code = network_check.main(["--seeds", "17", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("**10.6: NOT VERIFIED**", buffer.getvalue())
        self.assertIn("made to fail", buffer.getvalue())

    def test_a_failing_stress_network_fails_the_run(self):
        import network_check
        real = network_check.check_condition

        def stress_fails(seed):
            r = nc.check_stress(seed, burst_s=10.0)
            r["all"] = False
            return r
        with mock.patch.object(network_check, "check_condition",
                               side_effect=lambda m, s: real(m, s, duration_s=50.0, burst_s=10.0)), \
                mock.patch.object(network_check, "check_stress", side_effect=stress_fails), \
                redirect_stdout(io.StringIO()) as buffer:
            self.assertEqual(network_check.main(["--seeds", "17", "--out", self.out]), 1)
        self.assertIn("**10.6: NOT VERIFIED**", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
