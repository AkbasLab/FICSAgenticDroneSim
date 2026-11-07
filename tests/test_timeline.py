#!/usr/bin/env python3
"""Tests for Phase 17's run timeline (AUV-16, 17.2): every lane says what the run's own log says.

    python -m unittest discover -s tests -p test_timeline.py

WHY THESE EXIST
---------------
A timeline is read to find coordination defects the averages hide -- so a lane
that drew the wrong span, lost a skill or a stop, or a progress curve that did
not end at the judge's coverage, would mislead the very inspection it is for.
These fly real runs and hold the timeline to their logs and reports.
"""

import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.experiments import timeline as T  # noqa: E402
from agentic_uav.experiments.experiment import ExperimentConfig  # noqa: E402
from agentic_uav.experiments.experiment_run import run_one  # noqa: E402
from agentic_uav.experiments.metrics import load_run, run_metrics  # noqa: E402


class TimelineTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.runs = {
            "stop": ExperimentConfig(1, "t", "C", "search_relay_001", 4, "severe", "drone1-at-60s", 3, "none"),
            "partition": ExperimentConfig(2, "t", "D", "search_relay_001", 4, "partitioned", "unsafe-proposal", 1,
                                          "echo"),
        }
        cls.models = {}
        for k, r in cls.runs.items():
            run_one(r, cls.out)
            cls.models[k] = T.timeline(os.path.join(cls.out, r.run_id))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def events(self, key):
        path = os.path.join(self.out, self.runs[key].run_id, "events.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as h:
            return [json.loads(line) for line in h]

    def test_every_skill_of_every_drone_is_drawn_once(self):
        for key, m in self.models.items():
            ev = self.events(key)
            for d in m["roster"]:
                self.assertEqual(len(m["lanes"][d]["skill"]),
                                 sum(1 for e in ev if e["type"] == "SKILL_STARTED" and e["drone"] == d), (key, d))
                for t0, t1, _, _ in m["lanes"][d]["skill"]:
                    self.assertLessEqual(t0, t1)

    def test_a_stopped_drones_lanes_end_at_its_stop(self):
        m = self.models["stop"]
        stop = next(e["t"] for e in self.events("stop") if e["type"] == "FAULT_INJECTED" and e["fault"] == "stop")
        lane = m["lanes"]["Drone1"]
        self.assertIn((stop, "stopped"), lane["marks"])
        self.assertTrue(lane["task"] and lane["role"])
        self.assertLessEqual(max(t1 for _, t1, _ in lane["task"]), stop)
        self.assertLessEqual(max(t1 for _, t1, _ in lane["role"]), stop)

    def test_progress_ends_at_the_judges_coverage(self):
        for key, m in self.models.items():
            self.assertAlmostEqual(m["team"]["progress"][-1][1], m["outcome"]["coverage"], places=6)
            fractions = [f for _, f in m["team"]["progress"]]
            self.assertEqual(fractions, sorted(fractions))                 # never goes back

    def test_reallocations_are_the_metrics_and_partitions_the_logs(self):
        for key, r in self.runs.items():
            values, _ = run_metrics(load_run(os.path.join(self.out, r.run_id)))
            self.assertEqual(len(self.models[key]["team"]["reallocations"]), values["D3.task_reassignments"])
        self.assertEqual([(p[0], p[1]) for p in self.models["partition"]["team"]["partitions"]], [(60.0, 120.0)])
        self.assertEqual(self.models["stop"]["team"]["partitions"], [])

    def test_model_decisions_and_the_guardian_are_marked(self):
        m = self.models["partition"]
        ev = self.events("partition")
        self.assertEqual(sum(len(m["lanes"][d]["llm"]) for d in m["roster"]),
                         sum(1 for e in ev if e["type"] == "LLM_CALLED"))
        self.assertEqual(sum(len(m["lanes"][d]["guardian"]) for d in m["roster"]), 1)

    def test_messages_over_time_add_up(self):
        for key, m in self.models.items():
            ev = self.events(key)
            for col, kind in ((1, "MESSAGE_SENT"), (2, "MESSAGE_RECEIVED"), (3, "MESSAGE_DROPPED")):
                self.assertEqual(sum(b[col] for b in m["team"]["messages"]), sum(1 for e in ev if e["type"] == kind))

    def test_silences(self):
        self.assertEqual(T.silences([1.0, 2.0, 6.5, 7.0], 12.0), [(2.0, 6.5), (7.0, 12.0)])
        self.assertEqual(T.silences([1.0, 2.0, 4.9], 5.0), [])
        self.assertEqual(T.silences([], 2.0), [])
        self.assertEqual(T.silences([0.5], 3.5), [(0.5, 3.5)])             # exactly the rung counts

    def test_the_page_is_self_contained_and_written_where_asked(self):
        r = self.runs["stop"]
        path = T.write_timeline(os.path.join(self.out, r.run_id))
        with io.open(path, encoding="utf-8") as h:
            page = h.read()
        self.assertIn(r.run_id, page)
        self.assertIn("<svg", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http://", page.replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertEqual(page.count("<rect") >= sum(len(self.models["stop"]["lanes"][d]["skill"])
                                                   for d in self.models["stop"]["roster"]), True)


if __name__ == "__main__":
    unittest.main()
