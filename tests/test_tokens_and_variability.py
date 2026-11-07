#!/usr/bin/env python3
"""Tests for Phase 17's token counts (metric D12) and the residual-variability protocol (docs/TESTING.md 16.4).

    python -m unittest discover -s tests -p test_tokens_and_variability.py

WHY THESE EXIST
---------------
The first live-model batch is the first time tokens can be counted and a live
model's variability measured; both must be right before GPU time is spent on
them. These hold the model client to reporting what the server counted, the
policy to logging it -- and only where a server counted it, so no echo or
replay record changes -- and the protocol to rebuilding each request exactly,
and to telling agreement from difference.
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments.experiment import ExperimentConfig  # noqa: E402
from agentic_uav.experiments.experiment_run import run_one  # noqa: E402
from agentic_uav.experiments.metrics import load_run, run_metrics  # noqa: E402
from agentic_uav.experiments.variability import ask_again, recorded_decisions  # noqa: E402
from agentic_uav.planners.llm_ask import EchoAsk, OllamaAsk  # noqa: E402


class FakeServer:
    """What an Ollama client returns: the reply, and the counts."""

    def __init__(self, prompt=120, reply=30, text=None):
        self.prompt, self.reply, self.text = prompt, reply, text
        self.calls = 0

    def chat(self, model, messages, format, options):
        self.calls += 1
        return {"message": {"content": self.text}, "prompt_eval_count": self.prompt, "eval_count": self.reply}


class TokenTests(unittest.TestCase):

    def test_the_client_reports_what_the_server_counted(self):
        ask = OllamaAsk.__new__(OllamaAsk)
        import threading
        ask.model, ask.options, ask._lock = "m", {}, threading.Lock()
        ask.client = FakeServer(text='{"tool": "hold"}')
        request = {"messages": [], "meta": {}}
        self.assertEqual(ask(request), '{"tool": "hold"}')
        self.assertEqual(request["meta"]["tokens"], 150)
        ask.client = FakeServer(prompt=None, reply=None, text="x")
        request = {"messages": [], "meta": {}}
        ask(request)
        self.assertNotIn("tokens", request["meta"])                     # nothing counted, nothing claimed

    def test_the_policy_logs_counted_tokens_and_the_metric_sums_them(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        echo = EchoAsk()

        def counting(request):
            request["meta"]["tokens"] = 100
            return echo(request)
        import agentic_uav.experiments.experiment_run as R
        real = R._ask
        R._ask = lambda planner, run, stop, endpoint: (counting, {"planner": "test"}) if planner.kind == "echo" \
            else real(planner, run, stop, endpoint)
        try:
            run = ExperimentConfig(1, "t", "D", "search_pair_001", 2, "nominal", "none", 1, "echo")
            run_one(run, out)
        finally:
            R._ask = real
        values, absent = run_metrics(load_run(os.path.join(out, run.run_id)))
        calls = values["D10.llm_calls"]
        self.assertEqual(values["D12.tokens"], 100 * calls)

    def test_echo_and_replay_records_carry_no_tokens(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        run = ExperimentConfig(1, "t", "D", "search_pair_001", 2, "nominal", "none", 1, "echo")
        run_one(run, out)
        values, absent = run_metrics(load_run(os.path.join(out, run.run_id)))
        self.assertEqual(absent["D12.tokens"][0], "not recorded")


class VariabilityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        run_one(ExperimentConfig(1, "t", "D", "search_relay_001", 4, "nominal", "drone1-at-60s", 1, "echo"), cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def test_the_sample_is_the_first_decisions_rebuilt_exactly(self):
        sample = recorded_decisions(self.out, 25)
        self.assertEqual(len(sample), 25)
        self.assertEqual([s["at"] for s in sample], sorted(s["at"] for s in sample))
        result = ask_again(sample, lambda req: next(s["reply"] for s in sample
                                                    if req["messages"] == __import__(
                                                        "agentic_uav.agents.llm_context", fromlist=["render"]
                                                    ).render(s["context"])))
        self.assertEqual(result["problems"], [])
        self.assertEqual((result["asked"], result["agreed"], result["agreement"]), (25, 25, 1.0))

    def test_a_different_answer_is_counted_and_kept(self):
        sample = recorded_decisions(self.out, 10)
        result = ask_again(sample, lambda req: '{"situation_assessment": {}, "tool": "hold", "parameters": '
                                               '{"seconds": 7}, "outgoing_messages": [], "confidence": 0.5, '
                                               '"reason_code": "X"}')
        self.assertLess(result["agreed"], 10)
        differing = [r for r in result["rows"] if not r["agreed"]]
        self.assertTrue(all(r["reply_again"] for r in differing))

    def test_an_error_is_recorded_not_hidden(self):
        sample = recorded_decisions(self.out, 3)

        def down(req):
            raise TimeoutError("server gone")
        result = ask_again(sample, down)
        self.assertEqual((result["errors"], result["agreement"]), (3, None))

    def test_a_tampered_context_is_refused(self):
        sample = recorded_decisions(self.out, 2)
        sample[0]["context"] = dict(sample[0]["context"], extra="x")
        result = ask_again(sample, lambda req: sample[1]["reply"])
        self.assertEqual(len(result["problems"]), 1)
        self.assertEqual(result["asked"], 1)


if __name__ == "__main__":
    unittest.main()
