#!/usr/bin/env python3
"""Tests for the model-choice benchmark (Phase 12, step 5): recorded decisions, each model asked the same.

    python -m unittest discover -s tests -p test_llm_bench.py

WHY THESE EXIST
---------------
The model the exit flies is chosen from this benchmark, so it must measure
what it says: an echo of the rule policy must come out valid, possible and in
full agreement; a model that answers garbage must come out as fallbacks after
one correction; a hold of any allowed length must count as possible. And the
collected requests must be the exact messages a flight would send.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.llm_tools import reply_for  # noqa: E402
from agentic_uav.experiments import llm_bench as B  # noqa: E402
from agentic_uav.planners.llm_ask import EchoAsk  # noqa: E402


class BenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import llm_bench as script
        cls.out = tempfile.mkdtemp()
        with redirect_stdout(io.StringIO()):
            assert script.main(["collect", "--seeds", "17", "--out", cls.out]) == 0
        (name,) = os.listdir(cls.out)
        with open(os.path.join(cls.out, name), encoding="utf-8") as h:
            rows = [json.loads(line) for line in h]
        cls.header, cls.requests = rows[0], [r for r in rows if r["kind"] == "request"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_collected_from_both_flights_of_the_seed(self):
        self.assertEqual(self.header["requests"], len(self.requests))
        self.assertEqual({(r["seed"], r["flight"]) for r in self.requests}, {(17, "no stop"), (17, "Drone1 stopped")})
        self.assertGreater(len(self.requests), 100)
        self.assertTrue(all(r["messages"][0]["role"] == "system" for r in self.requests))

    def test_the_echo_is_valid_possible_and_agrees_every_time(self):
        s = B.summarize(B.run(self.requests, EchoAsk(), "echo"))
        n = len(self.requests)
        self.assertEqual((s["valid_first"], s["usable_after_one_correction"], s["fallback"], s["agreed"]), (n, n, 0, n))

    def test_garbage_falls_back_after_one_correction(self):
        calls = []
        rows = B.run(self.requests[:5], lambda r: calls.append(1) or "no", "garbage")
        self.assertEqual(len(calls), 10)
        self.assertTrue(all(not r["usable"] and len(r["replies"]) == 2 for r in rows))

    def test_a_correction_that_works_is_counted(self):
        state = {"n": 0}

        def once(request):
            state["n"] += 1
            return "{" if state["n"] % 2 else request["meta"]["rule_reply"]
        s = B.summarize(B.run(self.requests[:6], once, "x"))
        self.assertEqual((s["valid_first"], s["corrected"], s["fallback"]), (0, 6, 0))

    def test_a_hold_of_any_allowed_length_is_possible(self):
        offered = {("hold", json.dumps({"duration_s": 10.0})), ("continue_task", "{}")}
        self.assertTrue(B.possible("hold", {"duration_s": 5}, offered))
        self.assertFalse(B.possible("hold", {"duration_s": 31}, offered))
        self.assertFalse(B.possible("return_home", {}, offered))
        self.assertTrue(B.possible("continue_task", {}, offered))

    def test_an_action_not_offered_is_not_possible(self):
        r = self.requests[0]
        rows = B.run([r], lambda q: reply_for("act_as_relay", {"teammate": "Drone9"}), "x")
        self.assertIn("not among the actions offered", rows[0]["problems"][0])

    def test_sample_is_even_and_complete_when_asked_for_all(self):
        self.assertEqual(B.sample(list(range(10)), 5), [0, 2, 4, 6, 8])
        self.assertEqual(B.sample(list(range(3)), None), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
