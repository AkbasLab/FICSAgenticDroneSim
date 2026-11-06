#!/usr/bin/env python3
"""AUV-15, 16.4: with the same architecture, model output and seed, everything repeats exactly.

    python -m unittest discover -s tests -p test_determinism.py

WHY THESE EXIST
---------------
16.4: "network events repeat; target placement repeats; injected faults
repeat; deterministic policies repeat exactly." Each is flown twice here and
compared -- and, so that "the same" means something, a different seed is
shown to change it. "Model output" is held fixed by replaying a recorded
model (Phase 12's llama3.3:70b): its flight repeats exactly too. What a LIVE
model does when asked again is residual variability, to be measured, not
assumed away -- the protocol is in docs/TESTING.md.
"""

import filecmp
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments.events import read_events  # noqa: E402
from agentic_uav.experiments.experiment import ExperimentConfig  # noqa: E402
from agentic_uav.experiments.experiment_run import EVENTS, RECORDS, REPORT, TRAJECTORIES, run_one  # noqa: E402

REPLAY = "replay:phases/phase-12-llm-agent-policy/results/llm-exit-20261105-150453-exit.jsonl"
RUNS = {
    "severe network, a stop": ("C", "severe", "drone1-at-60s", 3, "none"),
    "partitioned network": ("D", "partitioned", "none", 1, "echo"),
    "an unsafe proposal": ("C", "nominal", "unsafe-proposal", 1, "none"),
    "the 70B replayed": ("D", "perfect", "drone1-at-60s", 2, REPLAY),
    "central controller": ("A", "severe", "drone1-at-60s", 1, "none"),
}


def cfg(i, arch, net, fail, seed, planner):
    return ExperimentConfig(i, "det", arch, "search_relay_001", 4, net, fail, seed, planner)


class DeterminismTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.a, cls.b, cls.c = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        cls.runs = {k: cfg(i, *v) for i, (k, v) in enumerate(RUNS.items(), 1)}
        for run in cls.runs.values():
            run_one(run, cls.a)
            run_one(run, cls.b)
        other = cls.runs["severe network, a stop"]
        cls.reseeded = cfg(99, other.architecture, other.network, other.failure, 4, other.planner)
        run_one(cls.reseeded, cls.c)

    @classmethod
    def tearDownClass(cls):
        for d in (cls.a, cls.b, cls.c):
            shutil.rmtree(d)

    def events(self, root, run):
        return read_events(os.path.join(root, run.run_id, EVENTS))

    def of(self, events, *kinds):
        return [e for e in events if e["type"] in kinds]

    def test_every_run_directory_repeats_byte_for_byte(self):
        for key, run in self.runs.items():
            for f in (EVENTS, REPORT, RECORDS, TRAJECTORIES):
                with self.subTest(run=key, file=f):
                    self.assertTrue(filecmp.cmp(os.path.join(self.a, run.run_id, f),
                                                os.path.join(self.b, run.run_id, f), shallow=False))

    def test_network_events_repeat(self):
        for key in ("severe network, a stop", "partitioned network"):
            run = self.runs[key]
            fates = lambda root: self.of(self.events(root, run), "MESSAGE_SENT", "MESSAGE_RECEIVED",  # noqa: E731
                                         "MESSAGE_DROPPED")
            a, b = fates(self.a), fates(self.b)
            self.assertEqual(a, b, key)
            self.assertTrue(any(e["type"] == "MESSAGE_DROPPED" and e["why"] in ("lost", "partitioned") for e in a))
        other = self.of(self.events(self.c, self.reseeded), "MESSAGE_DROPPED")
        self.assertNotEqual(other, self.of(self.events(self.a, self.runs["severe network, a stop"]),
                                           "MESSAGE_DROPPED"))          # another seed, other fates

    def test_target_placement_repeats(self):
        import json
        def targets(root, run):
            with open(os.path.join(root, run.run_id, REPORT), encoding="utf-8") as h:
                return json.load(h)["report"]["facts"]["targets"]
        for key, run in self.runs.items():
            self.assertEqual(targets(self.a, run), targets(self.b, run), key)
        self.assertNotEqual(targets(self.a, self.runs["severe network, a stop"]), targets(self.c, self.reseeded))

    def test_injected_faults_repeat(self):
        for key in ("severe network, a stop", "partitioned network", "an unsafe proposal", "central controller"):
            run = self.runs[key]
            a = self.of(self.events(self.a, run), "FAULT_INJECTED", "GUARDIAN_INTERVENED")
            self.assertTrue(a, key)
            self.assertEqual(a, self.of(self.events(self.b, run), "FAULT_INJECTED", "GUARDIAN_INTERVENED"), key)

    def test_deterministic_policies_repeat_exactly(self):
        for key in ("severe network, a stop", "an unsafe proposal", "central controller"):
            run = self.runs[key]
            kinds = ("DECISION_PROPOSED", "TASK_ASSIGNED", "TASK_RELEASED", "ROLE_CHANGED", "SKILL_STARTED")
            self.assertEqual(self.of(self.events(self.a, run), *kinds), self.of(self.events(self.b, run), *kinds),
                             key)

    def test_the_same_model_output_repeats_exactly(self):
        for key in ("partitioned network", "the 70B replayed"):
            run = self.runs[key]
            calls = lambda root: [{k: v for k, v in e.items() if k != "latency_s"}  # noqa: E731
                                  for e in self.of(self.events(root, run), "LLM_CALLED")]
            self.assertTrue(calls(self.a))
            self.assertEqual(calls(self.a), calls(self.b), key)


if __name__ == "__main__":
    unittest.main()
