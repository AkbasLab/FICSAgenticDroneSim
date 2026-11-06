#!/usr/bin/env python3
"""Tests for Phase 14's batch command and its exit checks.

    python -m unittest discover -s tests -p test_batch.py

WHY THESE EXIST
---------------
AUV-14's exit: "a batch command executes a list of scenario configurations
without manual prompts and produces one complete result directory per run".
These hold the batch to it on a small real batch -- in order, side by side the
same as one at a time, resumed without flying a finished run again, a crashed
run recorded and the batch going on, a model it cannot reach refused before
anything flies -- and show each of the exit's checks able to fail, on a real
batch directory altered to break it.
"""

import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from agentic_uav.experiments import experiment_run as R  # noqa: E402
from agentic_uav.experiments.batch import read_index, run_batch  # noqa: E402
from agentic_uav.experiments.batch_exit import compare_batches, run_checks  # noqa: E402
from agentic_uav.experiments.experiment import load_batch  # noqa: E402

BATCH = """[batch]
id = "small"
description = "four runs of the pair"

[[experiment]]
id = "pair"
architecture = ["C", "D"]
scenario = "search_pair_001"
team_size = 2
network = "nominal"
failure = ["none", "drone1-at-60s"]
seed = 1
planner = "echo"
"""


# A slow run first (four drones, severe network, a stop) and a quick one second (Phase 4's plan): side by side,
# the second finishes first.
ORDER_BATCH = """[batch]
id = "order"
description = "a slow run, then a quick one"

[[experiment]]
id = "slow"
architecture = "C"
scenario = "search_relay_001"
team_size = 4
network = "severe"
failure = "drone1-at-60s"
seed = 1
planner = "none"

[[experiment]]
id = "quick"
architecture = "E"
scenario = "search_relay_001"
team_size = 4
network = "perfect"
failure = "none"
seed = 1
planner = "none"
"""


def quiet(_line):
    pass


class BatchTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, "small.toml")
        with io.open(cls.path, "w", encoding="utf-8") as h:
            h.write(BATCH)
        cls.batch = load_batch(cls.path)
        cls.first = run_batch(cls.batch, os.path.join(cls.tmp, "a"), jobs=1, progress=quiet)
        cls.second = run_batch(cls.batch, os.path.join(cls.tmp, "b"), jobs=2, progress=quiet)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self, which):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        dest = os.path.join(d, "batch")
        shutil.copytree(which, dest)
        return dest

    def test_one_directory_per_run_in_the_batchs_order(self):
        rows = read_index(self.first)
        self.assertEqual([r["run_id"] for r in rows], [r.run_id for r in self.batch.runs])
        self.assertEqual({r["status"] for r in rows}, {"completed"})
        failing = {k: v for k, v in run_checks(self.batch, self.first).items() if v}
        self.assertEqual(set(failing), {"every_event_type"})    # four runs of the pair cannot make all 19 happen:
        self.assertIn("GUARDIAN_INTERVENED", failing["every_event_type"][0])   # that is the exit batch's to show
        self.assertTrue(os.path.isfile(os.path.join(self.first, "summary.md")))

    def test_side_by_side_is_the_same_as_one_at_a_time(self):
        self.assertEqual(compare_batches(self.first, self.second, [r.run_id for r in self.batch.runs]), [])

    def test_resuming_flies_only_what_is_unfinished(self):
        d = self.copy(self.second)
        gone = self.batch.runs[1].run_id
        shutil.rmtree(os.path.join(d, gone))
        flown = []
        real = R.fly_config

        def counting(run, endpoint=None):
            flown.append(run.run_id)
            return real(run, endpoint)
        with mock.patch.object(R, "fly_config", counting):
            run_batch(self.batch, resume=d, progress=quiet)
        self.assertEqual(flown, [gone])
        self.assertEqual(compare_batches(self.first, d, [r.run_id for r in self.batch.runs]), [])

    def test_the_index_keeps_the_batchs_order_when_runs_finish_out_of_it(self):
        text = ORDER_BATCH
        path = os.path.join(self.tmp, "order.toml")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(text)
        b = load_batch(path)
        finished = []
        out = run_batch(b, os.path.join(self.tmp, "order"), jobs=2, progress=finished.append)
        self.assertTrue(finished[0].startswith("[1/2] 0002-E"))          # the quick one finished first
        self.assertEqual([r["run_id"] for r in read_index(out)], [r.run_id for r in b.runs])

    def test_resuming_another_batch_is_refused(self):
        d = self.copy(self.first)
        other = load_batch("phase14_exit")
        with self.assertRaises(RuntimeError):
            run_batch(other, resume=d, progress=quiet)

    def test_a_crash_is_recorded_and_the_batch_goes_on(self):
        real = R.fly_config
        crash = self.batch.runs[2].run_id

        def flaky(run, endpoint=None):
            if run.run_id == crash:
                raise RuntimeError("a run that falls over")
            return real(run, endpoint)
        with mock.patch.object(R, "fly_config", flaky):
            out = run_batch(self.batch, os.path.join(self.tmp, "c"), progress=quiet)
        rows = {r["run_id"]: r for r in read_index(out)}
        self.assertEqual(rows[crash]["status"], "crashed")
        self.assertEqual(sum(r["status"] == "completed" for r in rows.values()), 3)
        checks = run_checks(self.batch, out)
        self.assertEqual(checks["manifests_complete"], [])                  # a crash is a complete record of itself

    def test_a_model_it_cannot_reach_is_refused_before_anything_flies(self):
        text = BATCH.replace('planner = "echo"', 'planner = "llm:default"')
        path = os.path.join(self.tmp, "llm.toml")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(text)
        b = load_batch(path)
        root = os.path.join(self.tmp, "never")
        with self.assertRaises(RuntimeError):
            run_batch(b, root, progress=quiet)                              # no endpoint
        with self.assertRaises(RuntimeError):
            run_batch(b, root, endpoint="http://127.0.0.1:9", progress=quiet)   # nothing there
        self.assertFalse(os.path.exists(root))


class ExitCheckTests(unittest.TestCase):
    """Each check, shown able to fail on a real batch directory altered to break it."""

    @classmethod
    def setUpClass(cls):
        BatchTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    copy = BatchTests.copy

    def failing(self, d):
        return {k for k, v in run_checks(self.batch, d).items() if v}

    def run_dir(self, d, i=0):
        return os.path.join(d, self.batch.runs[i].run_id)

    def edit_events(self, d, change):
        path = os.path.join(self.run_dir(d), R.EVENTS)
        with gzip.open(path, "rt", encoding="utf-8") as h:
            events = [json.loads(x) for x in h]
        events = change(events)
        with gzip.open(path, "wt", encoding="utf-8") as h:
            h.writelines(json.dumps(e) + "\n" for e in events)

    def edit_manifest(self, d, change):
        path = os.path.join(self.run_dir(d), R.MANIFEST)
        with io.open(path, encoding="utf-8") as h:
            m = json.load(h)
        change(m)
        with io.open(path, "w", encoding="utf-8") as h:
            json.dump(m, h)

    def test_a_missing_directory_or_file(self):
        d = self.copy(self.first)
        os.remove(os.path.join(self.run_dir(d), R.EVENTS))
        self.assertIn("one_directory_per_run", self.failing(d))

    def test_an_incomplete_manifest(self):
        d = self.copy(self.first)
        self.edit_manifest(d, lambda m: m["files"]["scenario"].update(sha256=None))
        self.assertIn("manifests_complete", self.failing(d))

    def test_a_run_not_as_configured(self):
        d = self.copy(self.first)
        self.edit_manifest(d, lambda m: m["config"].update(seed=99))
        self.assertIn("as_configured", self.failing(d))
        d = self.copy(self.first)
        self.edit_events(d, lambda ev: [dict(e, network="severe") if e["type"] == "MISSION_STARTED" else e
                                        for e in ev])
        self.assertIn("as_configured", self.failing(d))

    def test_events_out_of_order_or_unpaired(self):
        d = self.copy(self.first)
        self.edit_events(d, lambda ev: list(reversed(ev)))
        self.assertIn("events_well_formed", self.failing(d))
        d = self.copy(self.first)
        self.edit_events(d, lambda ev: [e for e in ev if e["type"] != "SKILL_COMPLETED"])
        self.assertIn("events_well_formed", self.failing(d))

    def test_a_type_that_never_happens(self):
        d = self.copy(self.first)
        for i in range(len(self.batch.runs)):
            path = os.path.join(self.run_dir(d, i), R.EVENTS)
            with gzip.open(path, "rt", encoding="utf-8") as h:
                ev = [json.loads(x) for x in h if '"TASK_BID"' not in x]
            with gzip.open(path, "wt", encoding="utf-8") as h:
                h.writelines(json.dumps(e) + "\n" for e in ev)
        self.assertIn("every_event_type", self.failing(d))

    def test_a_failed_mission_not_kept(self):
        d = self.copy(self.first)
        rows = read_index(d)
        rows[0]["met"] = False
        os.remove(os.path.join(self.run_dir(d), R.RECORDS))
        with io.open(os.path.join(d, "index.jsonl"), "w", encoding="utf-8") as h:
            h.writelines(json.dumps(r) + "\n" for r in rows)
        self.assertIn("failures_kept", self.failing(d))

    def test_a_run_that_differs_when_flown_again(self):
        d = self.copy(self.first)
        with io.open(os.path.join(self.run_dir(d), R.REPORT), "a", encoding="utf-8") as h:
            h.write(" ")
        self.assertTrue(compare_batches(self.first, d, [r.run_id for r in self.batch.runs]))


class ScriptTests(unittest.TestCase):

    def test_a_refused_batch_exits_2_and_flies_nothing(self):
        import run_batch as script
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "bad.toml")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(BATCH.replace("team_size = 2", "team_size = 4"))
        self.assertEqual(script.main([path, "--out", tmp]), 2)
        self.assertEqual(os.listdir(tmp), ["bad.toml"])

    def test_a_crash_makes_the_exit_code_1(self):
        import run_batch as script
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "small.toml")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(BATCH.replace('failure = ["none", "drone1-at-60s"]', 'failure = "none"'))
        with mock.patch.object(R, "fly_config", side_effect=RuntimeError("down")):
            self.assertEqual(script.main([path, "--out", tmp]), 1)


if __name__ == "__main__":
    unittest.main()
