#!/usr/bin/env python3
"""Tests for Phase 10 step 5: the exit -- one mission replayed under the conditions, delivery reproducible.

    python -m unittest discover tests

WHY THESE EXIST
---------------
The exit's four checks must each be able to fail, or a pass means nothing.
Each passes on a real seed's flights -- nominal and partitioned, both ways,
twice, and Phase 9's own -- and fails on them altered to break it: a second
flight whose deliveries, records or decisions differ; a network that did not
do what its condition says, message by message (a loss the model did not
draw, an arrival off its draw, a refusal no bucket made, a delivery across
the partition, a message out of range on a network without one); nominal
drifting from Phase 9; a decision knowing what it could not. The findings are
held to what they count, and the script to its record and its verdict.
"""

import copy
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

from agentic_uav.experiments import network_exit as ne  # noqa: E402
from agentic_uav.experiments import scenarios  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.conditions import load_network  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.simulator.message_bus import DELIVERED, LOST, OUT_OF_RANGE, PARTITIONED, RATE_LIMITED  # noqa: E402

SC = scenarios.load_scenario("search_relay_001")
MODELS = {c: load_network(c) for c in ("nominal", "partitioned")}


def with_deliveries(run, change):
    ds = [dataclasses.replace(d) for d in run.team.deliveries]
    change(ds)
    return dataclasses.replace(run, team=dataclasses.replace(run.team, deliveries=tuple(ds)))


class ExitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.flights = ne.network_flights(SC, 17, load_allocation(), load_recovery(), MODELS)
        cls.part = cls.flights["flown"][("partitioned", "Drone1 stopped")]

    def test_the_flights_are_what_they_say(self):
        flown = self.flights["flown"]
        self.assertEqual(sorted(flown), [(c, v) for c in ("nominal", "partitioned") for v in ("Drone1 stopped", "no stop")])
        for (c, label), (a, b) in flown.items():
            self.assertEqual((a.network.name, a.network.seed, a.team.label), (c, 17, label))
            self.assertEqual(a.stopped != {}, label == "Drone1 stopped")
        self.assertEqual({k: r.network for k, r in self.flights["phase9"].items()}, {"no stop": None, "Drone1 stopped": None})

    def test_every_check_passes_on_a_real_seed(self):
        checks = ne.exit_checks(self.flights, SC)
        for name in ne.CHECKS:
            with self.subTest(check=name):
                self.assertTrue(checks[name]["ok"], checks[name]["problems"][:3])
        self.assertTrue(checks["all"])

    # ---------------------------------------------------------- reproducible

    def test_a_second_flight_with_another_fate(self):
        a, b = self.part

        def one_lost(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            d.status, d.delivered_at = LOST, None
        self.assertIn("the deliveries differ", " ".join(ne.reproducible(a, with_deliveries(b, one_lost))))

    def test_a_second_flight_with_another_record_or_decision(self):
        a, b = self.part
        policies = copy.deepcopy(b.policies)
        policies["Drone2"]["roles"]["log"].pop()
        self.assertIn("the drones' records differ", ne.reproducible(a, dataclasses.replace(b, policies=policies)))
        traces = dict(b.team.traces)
        traces["Drone2"] = traces["Drone2"][:-1]
        other = dataclasses.replace(b, team=dataclasses.replace(b.team, traces=traces))
        self.assertIn("the decisions differ", ne.reproducible(a, other))

    def test_the_comparison_ignores_the_order_threads_sent_in(self):
        a, b = self.part
        shuffled = dataclasses.replace(b, team=dataclasses.replace(b.team, deliveries=tuple(reversed(b.team.deliveries))))
        self.assertEqual(ne.reproducible(a, shuffled), [])

    # --------------------------------------------------------- as configured

    def test_a_loss_the_model_did_not_draw(self):
        run = self.part[0]

        def lose(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            d.status, d.scheduled_at, d.delivered_at = LOST, None, None
        self.assertIn("the model's draw says not lost", " ".join(ne.as_configured(with_deliveries(run, lose))))

    def test_an_arrival_off_its_draw(self):
        run = self.part[0]

        def late(ds):
            next(d for d in ds if d.status == DELIVERED).scheduled_at += 0.01
        self.assertIn("the model says", " ".join(ne.as_configured(with_deliveries(run, late))))

    def test_a_delivery_across_the_partition(self):
        run = self.part[0]

        def leak(ds):
            d = next(d for d in ds if d.status == PARTITIONED)
            d.status, d.scheduled_at, d.delivered_at = DELIVERED, d.sent_at + 0.1, d.sent_at + 0.5
        self.assertIn("partition:", " ".join(ne.as_configured(with_deliveries(run, leak))))

    def test_a_refusal_no_bucket_made(self):
        run = self.part[0]

        def refuse(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            for x in ds:
                if x.message.message_id == d.message.message_id:
                    x.status = RATE_LIMITED
        self.assertIn("rate limit:", " ".join(ne.as_configured(with_deliveries(run, refuse))))

    def test_out_of_range_on_a_network_without_one(self):
        run = self.part[0]

        def far(ds):
            next(d for d in ds if d.status == DELIVERED).status = OUT_OF_RANGE
        self.assertIn("without a range", " ".join(ne.as_configured(with_deliveries(run, far))))

    def test_a_delivery_past_its_lifetime(self):
        run = self.part[0]

        def stale(ds):
            d = next(d for d in ds if d.status == DELIVERED)
            d.delivered_at = d.message.expires_at + 1.0
        self.assertIn("past its lifetime", " ".join(ne.as_configured(with_deliveries(run, stale))))

    # ------------------------------------------------------ nominal, known

    def test_nominal_drifting_from_phase_9(self):
        nominal = self.flights["flown"][("nominal", "no stop")][0]
        phase9 = self.flights["phase9"]["no stop"]
        self.assertEqual(ne.nominal_is_phase_9(nominal, phase9), [])

        def lose(ds):
            next(d for d in ds if d.status == DELIVERED).status = LOST
        self.assertIn("the deliveries differ", " ".join(ne.nominal_is_phase_9(with_deliveries(nominal, lose), phase9)))
        policies = copy.deepcopy(nominal.policies)
        policies["Drone1"]["completed"] = []
        self.assertIn("records differ", " ".join(ne.nominal_is_phase_9(dataclasses.replace(nominal, policies=policies), phase9)))
        self.assertIn("decisions differ", " ".join(ne.nominal_is_phase_9(
            nominal, self.flights["flown"][("partitioned", "no stop")][0])))

    def test_a_decision_that_knew_too_much_fails_the_exit(self):
        from agentic_uav.experiments.recovery_exit import known_exactly
        run = self.part[0]
        e = run.team.traces["Drone3"][-1]
        bad = dataclasses.replace(e, belief=copy.deepcopy(e.belief))
        bad.belief["self"]["position"][0] += 3.0
        traces = dict(run.team.traces)
        traces["Drone3"] = traces["Drone3"][:-1] + (bad,)
        bad_run = dataclasses.replace(run, team=dataclasses.replace(run.team, traces=traces))
        self.assertFalse(known_exactly(bad_run, SC)["ok"])
        # And through the exit itself: the seed fails, on that check alone.
        flown = dict(self.flights["flown"])
        flown[("partitioned", "Drone1 stopped")] = (bad_run, self.part[1])
        checks = ne.exit_checks({**self.flights, "flown": flown}, SC)
        self.assertFalse(checks["known_exactly"]["ok"])
        self.assertTrue(checks["nominal_is_phase_9"]["ok"])
        self.assertFalse(checks["all"])

    # -------------------------------------------------------------- findings

    def test_the_findings(self):
        f = ne.findings(self.part[0])
        self.assertTrue(f["met"])
        self.assertEqual(f["estimated_loss"], 0.0)                      # a partition is silence, not loss
        self.assertGreater(f["deliveries"][PARTITIONED], 0)
        self.assertTrue(f["detected"])
        self.assertGreater(sum(f["false_alarms"].values()), 0)            # the far side, taken for failed
        self.assertEqual(sorted(ne.findings(self.part[0])), sorted(f))
        self.assertNotIn("detected", ne.findings(self.flights["flown"][("nominal", "no stop")][0]))

    def test_a_stop_nobody_noticed_is_found_undetected(self):
        run = self.part[0]
        policies = copy.deepcopy(run.policies)
        for d in run.survivors:
            policies[d]["health"]["log"] = [t for t in policies[d]["health"]["log"] if t["teammate"] != "Drone1"]
        self.assertFalse(ne.findings(dataclasses.replace(run, policies=policies))["detected"])

    def test_a_lease_counted_once_however_many_books_logged_it(self):
        run = self.flights["flown"][("nominal", "Drone1 stopped")][0]
        logged = sum("lease ran out" in e["why"] for p in run.policies.values() for e in p["net"]["book_log"])
        self.assertGreater(logged, 1)
        self.assertEqual(ne.lease_expiries(run), 1)
        # A book that noticed later is the same expiry, not another.
        policies = copy.deepcopy(run.policies)
        late = next(e for e in policies["Drone2"]["net"]["book_log"] if "lease ran out" in e["why"])
        late["at"] += 0.5
        self.assertEqual(ne.lease_expiries(dataclasses.replace(run, policies=policies)), 1)

    def test_searched_twice_counts_the_searches_beyond_the_first(self):
        run = self.part[0]
        twice = dataclasses.replace(run, searched={"Drone1": ["search S1"], "Drone2": ["search S1", "search S2"],
                                                   "Drone3": ["search S1"]})
        self.assertEqual(ne.searched_twice(twice), 2)

    def test_false_alarms_leave_out_the_stopped_drone(self):
        run = self.part[0]
        about_stopped = sum(1 for d in run.survivors for t in run.policies[d]["health"]["log"] if t["teammate"] == "Drone1")
        self.assertGreater(about_stopped, 0)
        total = sum(1 for d in run.survivors for t in run.policies[d]["health"]["log"])
        self.assertEqual(sum(ne.false_alarms(run).values()), total - about_stopped)


class ScriptTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_the_conditions_must_include_nominal_and_be_known(self):
        import network_exit
        self.assertEqual(network_exit.conditions_arg("nominal,severe"), ("nominal", "severe"))
        for bad in ("severe", "nominal,radio"):
            with self.assertRaises(Exception):
                network_exit.conditions_arg(bad)

    def test_one_seed_writes_its_record(self):
        import network_exit
        with redirect_stdout(io.StringIO()) as buffer:
            code = network_exit.main(["--seeds", "17", "--conditions", "nominal,partitioned", "--out", self.out,
                                      "--block", "t"])
        self.assertEqual(code, 0, buffer.getvalue()[-1500:])
        files = sorted(os.listdir(self.out))
        self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["jsonl", "md"])
        with open(os.path.join(self.out, files[0]), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        head = rows[0]
        self.assertEqual((head["kind"], head["seeds"], head["exit_criterion_met"]), ("header", [17], True))
        self.assertEqual(sorted(head["conditions"]), ["nominal", "partitioned"])
        self.assertEqual(head["manifests"]["partitioned"], "configs/network/partitioned.toml")
        self.assertEqual(head["lifetimes_s"]["heartbeat"], 3.0)
        self.assertEqual(sorted(head["findings"]), ["nominal / Drone1 stopped", "nominal / no stop",
                                                    "partitioned / Drone1 stopped", "partitioned / no stop"])
        self.assertEqual([r["kind"] for r in rows[1:]], ["seed"] + ["records"] * 4)
        self.assertIn("**Exit criterion: MET**", buffer.getvalue())

    def test_a_failing_seed_fails_the_run(self):
        import network_exit
        real = network_exit.exit_checks

        def broken(flights, scenario):
            c = real(flights, scenario)
            c["reproducible"] = {"ok": False, "problems": ["made to fail"]}
            c["all"] = False
            return c
        with mock.patch.object(network_exit, "exit_checks", side_effect=broken), redirect_stdout(io.StringIO()) as buffer:
            code = network_exit.main(["--seeds", "17", "--conditions", "nominal", "--out", self.out])
        self.assertEqual(code, 1)
        self.assertIn("**Exit criterion: NOT MET**", buffer.getvalue())
        self.assertIn("made to fail", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
