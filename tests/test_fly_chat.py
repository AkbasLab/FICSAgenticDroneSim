#!/usr/bin/env python3
"""Tests for tools/fly_chat.py beyond its golden: the sandbox stays a sandbox.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Until Phase 2 step 5 the sandbox made its two departures from the study -- the
prompt addendum and the hovering runner -- and its speed by rewriting the
agent's globals at runtime. Since step 5 it passes them as arguments. The
golden proves a session behaves as before; these prove the other half of the
change: that a session leaves the study's own prompt, speed and runner exactly
as they were, and that the sandbox reaches AirSim only through the adapter.
"""

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests")]

import record_golden  # noqa: E402
from agentic_uav.control import executor  # noqa: E402
from agentic_uav.planners import prompt  # noqa: E402

FLY_CHAT = os.path.join(ROOT, "tools", "fly_chat.py")


class SandboxIsolationTests(unittest.TestCase):

    def test_a_session_leaves_the_study_untouched(self):
        with open(os.path.join(ROOT, "tests", "golden", "fly_chat.json"), encoding="utf-8") as f:
            golden = json.load(f)
        case = golden["cases"][0]           # speed changed, every command used
        before = (prompt.SYSTEM_PROMPT, executor.MOVE_SPEED, executor.DroneRunner)
        result = record_golden.run_fly_chat_case(case, golden["replies"])
        self.assertEqual(result["exit"], 0)
        self.assertEqual((prompt.SYSTEM_PROMPT, executor.MOVE_SPEED, executor.DroneRunner),
                         before)
        # ...while the model was still told the sandbox's prompt and speed.
        sent = [r["messages"][0]["content"] for r in result["requests"]]
        self.assertTrue(all("never return an empty plan" in p for p in sent))
        self.assertIn("fixed at 8.0 m/s", sent[-1])

    def test_it_imports_neither_airsim_nor_the_agent(self):
        with open(FLY_CHAT, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertNotIn("airsim", imported)
        self.assertNotIn("open_loop_agent", imported)


if __name__ == "__main__":
    unittest.main()
