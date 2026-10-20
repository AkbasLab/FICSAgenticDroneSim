#!/usr/bin/env python3
"""Tests for agentic_uav.experiments: the runner, the agent log, provenance.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 2 step 5 moved the mission runner, the agent log and provenance out of
`scripts/run_missions.py` and `baseline/open_loop_agent.py` (AUV-03). The
runner golden proves the runner still prints, writes and flies the same. It
cannot pin what changes with every edit by design -- the digests and the
commit in each record -- so these pin what those values must still MEAN:

* a record still names the baseline agent file and its digest, and one digest
  over the whole package, exactly as before the move;
* the agent log is still the one file at the repository root;
* the agent's re-exports are the moved objects, not copies;
* the runner plans through any MissionPlanner, and nothing in the package
  calls AirSim, Ollama or the baseline directly.
"""

import ast
import glob
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "baseline"), os.path.join(ROOT, "scripts")]

import open_loop_agent as agent  # noqa: E402
import run_missions  # noqa: E402
from agentic_uav.experiments import agent_log, provenance, runner  # noqa: E402
from agentic_uav.planners import MissionPlanner  # noqa: E402
from agentic_uav.planners.endpoint import OLLAMA_ENDPOINT  # noqa: E402
from agentic_uav.planners.replay_planner import REPLAY_ENDPOINT, ReplayPlanner  # noqa: E402
from agentic_uav.simulator import airsim_settings  # noqa: E402

V6_M01_M08 = os.path.join(ROOT, "phases", "phase-01-baseline-freeze", "results",
                          "baseline_v1-llama3.3_70b-20261019-182324-v6-polled.jsonl")


class ProvenanceTests(unittest.TestCase):
    """A record states the same agent it did before the move."""

    def setUp(self):
        self.record = provenance.provenance()

    def test_the_fields_are_unchanged(self):
        self.assertEqual(set(self.record), {"commit", "dirty", "agent", "agent_sha256",
                                            "agentic_uav_sha256", "python", "ollama_endpoint"})

    def test_it_names_the_baseline_agent_and_its_digest(self):
        path = os.path.join(ROOT, "baseline", "open_loop_agent.py")
        self.assertEqual(self.record["agent"], "open_loop_agent.py")
        self.assertEqual(self.record["agent_sha256"], provenance.file_digest(path))
        self.assertEqual(provenance.AGENT_PATH, path)

    def test_the_package_digest_covers_every_module(self):
        self.assertEqual(self.record["agentic_uav_sha256"], provenance.package_digest())
        digest = hashlib.sha256()
        for path in sorted(glob.glob(os.path.join(ROOT, "agentic_uav", "**", "*.py"),
                                     recursive=True)):
            digest.update(os.path.relpath(path, ROOT).replace(os.sep, "/").encode() + b"\0")
            with open(path, "rb") as handle:
                digest.update(handle.read() + b"\0")
        self.assertEqual(self.record["agentic_uav_sha256"], digest.hexdigest()[:16])

    def test_the_rest_is_as_before(self):
        self.assertEqual(self.record["python"], sys.version.split()[0])
        self.assertEqual(self.record["ollama_endpoint"], OLLAMA_ENDPOINT)

    def test_file_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "x.txt")
            with open(path, "wb") as handle:
                handle.write(b"open loop")
            self.assertEqual(provenance.file_digest(path),
                             hashlib.sha256(b"open loop").hexdigest()[:16])
            self.assertIsNone(provenance.file_digest(os.path.join(folder, "missing")))


class AgentLogTests(unittest.TestCase):

    def test_it_is_still_the_one_file_at_the_repository_root(self):
        self.assertEqual(agent_log.LOG_PATH, os.path.join(ROOT, "runs", "agent-log.jsonl"))

    def test_a_record_is_appended_where_LOG_PATH_says(self):
        planner = ReplayPlanner({("Drone1", "land"): '{"plan": [{"action": "land"}]}'})
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "log.jsonl")
            with mock.patch.object(agent_log, "LOG_PATH", path):
                agent_log.log_record(planner.plan("land", "Drone1"))
                agent_log.log_execution([{"completed": True}], None)
            with open(path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        self.assertEqual([r.get("kind") for r in rows], [None, "execution"])
        self.assertEqual(rows[0]["plan"], [{"action": "land"}])
        self.assertEqual(set(rows[1]["code"]), set(provenance.provenance()))


class ReExportTests(unittest.TestCase):
    """The agent and the CLI hand out the moved objects, not copies."""

    def test_the_agent_re_exports_the_moved_objects(self):
        for name, module in [("log_record", agent_log), ("log_execution", agent_log),
                             ("provenance", provenance), ("file_digest", provenance),
                             ("package_digest", provenance),
                             ("documents_dir", airsim_settings),
                             ("build_settings", airsim_settings),
                             ("write_settings", airsim_settings),
                             ("vehicle_names", airsim_settings)]:
            with self.subTest(name=name):
                self.assertIs(getattr(agent, name), getattr(module, name))

    def test_the_command_line_re_exports_the_runner(self):
        for name in ("main", "score", "series_conflicts", "summarise", "run_one",
                     "fly_one", "describe", "snapshot_code", "current_roster", "load_toml"):
            with self.subTest(name=name):
                self.assertIs(getattr(run_missions, name), getattr(runner, name))


class RunnerSeamTests(unittest.TestCase):

    def test_run_one_plans_through_any_mission_planner(self):
        # The ReplayPlanner re-plans v6's M01 from its recorded reply: the same
        # plan and the same score the live model got, with no model running.
        planner = ReplayPlanner.from_jsonl(V6_M01_M08)
        self.assertIsInstance(planner, MissionPlanner)
        config = runner.load_toml(runner.DEFAULT_CONFIG)
        m01 = next(m for m in config["mission"] if m["id"] == "M01")
        with open(V6_M01_M08, encoding="utf-8") as handle:
            recorded = json.loads(handle.readline())
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(agent_log, "LOG_PATH", os.path.join(folder, "log.jsonl")):
            row = runner.run_one(planner, m01, "llama3.3:70b", 1, None)
        self.assertEqual(row["per_drone"][0]["plan_steps"], recorded["per_drone"][0]["plan_steps"])
        self.assertEqual(row["all_correct"], recorded["all_correct"])
        self.assertEqual(row["per_drone"][0]["endpoint"], REPLAY_ENDPOINT)

    def test_nothing_in_the_package_reaches_past_its_adapters(self):
        # AirSim is imported only by the AirSim adapter, Ollama only by the
        # Ollama planner and the endpoint check, and the baseline by nobody.
        allowed = {
            "airsim": {"simulator/airsim_adapter.py"},
            "ollama": {"planners/ollama_planner.py", "planners/endpoint.py"},
            "open_loop_agent": set(),
        }
        package = os.path.join(ROOT, "agentic_uav")
        for path in glob.glob(os.path.join(package, "**", "*.py"), recursive=True):
            name = os.path.relpath(path, package).replace(os.sep, "/")
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [(node.module or "").split(".")[0]]
                else:
                    continue
                for module in modules:
                    if module in allowed:
                        with self.subTest(file=name, imports=module):
                            self.assertIn(name, allowed[module])


if __name__ == "__main__":
    unittest.main()
