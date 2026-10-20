#!/usr/bin/env python3
"""Tests for the MissionPlanner protocol and its two planners.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 2 step 4 put planning behind a `MissionPlanner` protocol (AUV-03, 2.1).
The golden tests prove the Ollama path still sends the same request and makes
the same record. These prove the rest:

* both planners satisfy the protocol;
* `OllamaPlanner.plan` is exactly `plan_for` with fixed settings;
* `ReplayPlanner` turns a recorded reply into the SAME plan, notes and error
  as the Ollama planner did, for every reply in the planning goldens -- so a
  replayed plan is the plan the model produced, not an approximation of it.

No model, no network: the Ollama client is the scripted one from the harness.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "baseline"), os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
import open_loop_agent as agent  # noqa: E402
from agentic_uav.planners import MissionPlanner  # noqa: E402
from agentic_uav.planners.ollama_planner import OllamaPlanner  # noqa: E402
from agentic_uav.planners.replay_planner import REPLAY_ENDPOINT, ReplayPlanner  # noqa: E402

with open(os.path.join(ROOT, "tests", "golden", "planning.json"), encoding="utf-8") as _f:
    PLANNING = json.load(_f)["cases"]


class ProtocolTests(unittest.TestCase):

    def test_both_planners_satisfy_the_protocol(self):
        self.assertIsInstance(OllamaPlanner(), MissionPlanner)
        self.assertIsInstance(ReplayPlanner({}), MissionPlanner)


class OllamaPlannerTests(unittest.TestCase):

    def test_plan_is_plan_for_with_fixed_settings(self):
        # Same request and same record as the golden recorded through plan_for.
        case = next(c for c in PLANNING if not c["id"].startswith("synthetic"))
        planner = OllamaPlanner(case["model"], case["endpoint"], case["options"])
        fake = airsim_fake.ScriptedOllama(case["reply"])
        saved = sys.modules.get("ollama")
        sys.modules["ollama"] = fake.module
        try:
            record = planner.plan(case["instruction"], case["drone"])
        finally:
            sys.modules["ollama"] = saved
        got = json.loads(json.dumps(airsim_fake._norm(fake.requests)))
        self.assertEqual(got, case["result"]["request"])
        self.assertEqual(record.plan, case["result"]["record"]["plan"])

    def test_a_given_system_prompt_is_the_one_sent(self):
        fake = airsim_fake.ScriptedOllama('{"plan": [{"action": "land"}]}')
        saved = sys.modules.get("ollama")
        sys.modules["ollama"] = fake.module
        try:
            OllamaPlanner(system_prompt="SANDBOX PROMPT").plan("land", "Drone1")
        finally:
            sys.modules["ollama"] = saved
        self.assertEqual(fake.requests[0]["chat"]["messages"][0]["content"], "SANDBOX PROMPT")

    def test_the_agent_wrapper_sends_the_agents_current_prompt(self):
        # A caller that rewrites agent.SYSTEM_PROMPT must still reach the model with
        # it (tools/fly_chat.py did, until Phase 2 step 5).
        fake = airsim_fake.ScriptedOllama('{"plan": [{"action": "land"}]}')
        saved_module, saved_prompt = sys.modules.get("ollama"), agent.SYSTEM_PROMPT
        sys.modules["ollama"] = fake.module
        agent.SYSTEM_PROMPT = "REWRITTEN BY THE SANDBOX"
        try:
            agent.plan_for("land", "Drone1")
        finally:
            sys.modules["ollama"], agent.SYSTEM_PROMPT = saved_module, saved_prompt
        self.assertEqual(fake.requests[0]["chat"]["messages"][0]["content"],
                         "REWRITTEN BY THE SANDBOX")


class ReplayPlannerTests(unittest.TestCase):

    def test_every_golden_reply_replays_to_the_same_record(self):
        replayable = [c for c in PLANNING if c.get("reply") is not None]
        self.assertGreaterEqual(len(replayable), 43)
        for case in replayable:
            with self.subTest(case=case["id"]):
                planner = ReplayPlanner({(case["drone"], case["instruction"]): case["reply"]})
                record = json.loads(json.dumps(airsim_fake._norm(
                    planner.plan(case["instruction"], case["drone"]).as_json())))
                want = case["result"]["record"]
                for field in ("plan", "valid", "error", "normalised", "raw_output", "transport_error"):
                    self.assertEqual(record[field], want[field], field)
                self.assertEqual(record["endpoint"], REPLAY_ENDPOINT)

    def test_built_from_a_results_file_it_replays_v6(self):
        path = os.path.join(ROOT, "phases", "phase-01-baseline-freeze", "results",
                            "baseline_v1-llama3.3_70b-20261019-183805-v6-polled.jsonl")
        planner = ReplayPlanner.from_jsonl(path)
        with open(path, encoding="utf-8") as handle:
            row = json.loads(handle.readline())
        for drone in row["per_drone"]:
            record = planner.plan(drone["instruction"], drone["drone"])
            self.assertTrue(record.valid)
            self.assertEqual(record.plan, drone["plan_steps"])
        self.assertEqual(planner.model, "llama3.3:70b")

    def test_conflicting_replies_are_refused(self):
        rows = [{"per_drone": [{"drone": "Drone1", "instruction": "x", "raw_output": "a"}]},
                {"per_drone": [{"drone": "Drone1", "instruction": "x", "raw_output": "b"}]}]
        with self.assertRaises(ValueError):
            ReplayPlanner.from_rows(rows)

    def test_an_unrecorded_request_is_an_error_not_an_invented_plan(self):
        with self.assertRaises(KeyError):
            ReplayPlanner({}).plan("fly forward", "Drone1")


if __name__ == "__main__":
    unittest.main()
