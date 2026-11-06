#!/usr/bin/env python3
"""Tests for Phase 14's experiment configuration, the run directory and the event log.

    python -m unittest discover -s tests -p test_experiment.py

WHY THESE EXIST
---------------
AUV-14: "one experiment configuration" (14.1), "an experiment manifest per
run" (14.2), "structured event logs" (14.3), "preserve failed runs" (14.4).
These hold the batch file to being read strictly -- a run that cannot fly is
refused before anything flies, with its reason -- and a run to leaving one
complete directory whatever happens: a mission not met is kept, a run that
raises is kept with its traceback, a finished run is never flown twice, and
the event log of a real flight is well formed and says what the configuration
asked for.
"""

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

from agentic_uav.experiments import experiment_run as R  # noqa: E402
from agentic_uav.experiments.batch_exit import as_configured, manifest_problems, well_formed  # noqa: E402
from agentic_uav.experiments.events import EVENT_TYPES, read_events  # noqa: E402
from agentic_uav.experiments.experiment import (ExperimentConfig, load_batch, load_failure, parse_batch,  # noqa: E402
                                                parse_failure, parse_planner, run_problems)

REPLAY = "replay:phases/phase-12-llm-agent-policy/results/llm-exit-20261105-150453-exit.jsonl"


def cfg(arch="C", scenario="search_pair_001", size=2, network="nominal", failure="none", seed=1, planner="none",
        index=1):
    return ExperimentConfig(index, "t", arch, scenario, size, network, failure, seed, planner)


def block(**over):
    b = {"id": "x", "architecture": "C", "scenario": "search_pair_001", "team_size": 2, "network": "nominal",
         "failure": "none", "seed": 1, "planner": "none"}
    b.update(over)
    return b


def batch(*blocks):
    return {"batch": {"id": "b", "description": "d"}, "experiment": list(blocks)}


class ConfigTests(unittest.TestCase):

    def test_the_exit_batch_reads_and_expands_in_a_fixed_order(self):
        b = load_batch("phase14_exit")
        self.assertEqual(len(b.runs), 43)
        self.assertEqual([r.index for r in b.runs], list(range(1, 44)))
        self.assertEqual(len({r.run_id for r in b.runs}), 43)
        self.assertEqual(b.runs[0].run_id, "0001-A-search_relay_001-nominal-none-s1")
        self.assertEqual({r.planner for r in b.runs if r.architecture in ("A", "B", "C", "E", "D-fallback")}, {"none"})

    def test_lists_and_ranges_expand_to_every_combination(self):
        b = parse_batch(batch(block(architecture=["C", "D"], network=["nominal", "perfect"], seed="1-3",
                                    planner="echo")))
        self.assertEqual(len(b.runs), 2 * 2 * 3)
        self.assertEqual([(r.architecture, r.network, r.seed) for r in b.runs[:4]],
                         [("C", "nominal", 1), ("C", "nominal", 2), ("C", "nominal", 3), ("C", "perfect", 1)])
        self.assertEqual({r.planner for r in b.runs if r.architecture == "C"}, {"none"})
        self.assertEqual({r.planner for r in b.runs if r.architecture == "D"}, {"echo"})

    def test_a_batch_that_cannot_fly_is_refused_whole_with_its_reasons(self):
        bad = {
            "an unknown key": batch(block(speed=3)),
            "a missing key": batch({k: v for k, v in block().items() if k != "seed"}),
            "a seed of the wrong kind": batch(block(seed="soon")),
            "a team size the scenario lacks": batch(block(team_size=4)),
            "a partition naming drones the scenario lacks": batch(block(network="partitioned")),
            "an unknown architecture": batch(block(architecture="Z")),
            "a model arm with no planner": batch(block(architecture="D")),
            "a planner and no model arm": batch(block(planner="echo")),
            "an injection with no guardian": batch(block(architecture="C-no-guardian", scenario="search_relay_001",
                                                         team_size=4, failure="unsafe-proposal")),
            "E on a network": batch(block(architecture="E", scenario="search_relay_001", team_size=4)),
            "E with a stop": batch(block(architecture="E", scenario="search_relay_001", team_size=4,
                                         network="perfect", failure="drone1-at-60s")),
            "a replay with no such flight": batch(block(architecture="D", scenario="search_relay_001", team_size=4,
                                                        network="perfect", seed=9, planner=REPLAY)),
            "an unknown model manifest": batch(block(architecture="D", planner="llm:nosuch")),
            "two experiments of one id": batch(block(), block()),
            "an unknown section": {**batch(block()), "extra": {}},
        }
        for why, data in bad.items():
            with self.subTest(why=why):
                with self.assertRaises(ValueError):
                    parse_batch(data)

    def test_run_problems_name_the_reason(self):
        self.assertEqual(run_problems(cfg()), [])
        self.assertTrue(any("team size" in p for p in run_problems(cfg(size=4))))
        self.assertTrue(any("planner must be none" in p for p in run_problems(cfg(planner="echo"))))
        self.assertTrue(any("give a planner" in p for p in run_problems(cfg(arch="D"))))
        self.assertTrue(any("stops Drone9" in p for p in run_problems(cfg(failure=self.profile(stop={"Drone9": 5.0})))))

    def profile(self, **failure):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "f.toml")
        lines = ['[failure]', 'name = "f"', 'description = "a test"']
        if "stop" in failure:
            lines.append("stop = { " + ", ".join(f"{k} = {v}" for k, v in failure["stop"].items()) + " }")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write("\n".join(lines) + "\n")
        return path

    def test_failure_profiles_and_planners_are_read_strictly(self):
        self.assertEqual(load_failure("drone1-at-60s").stop, {"Drone1": 60.0})
        self.assertEqual(load_failure("unsafe-proposal").injection, "rule-fence-far")
        for bad in ({"failure": {"name": "x", "description": "y", "stop": {"Drone1": -1}}},
                    {"failure": {"name": "x", "description": "y", "injection": "nosuch"}},
                    {"failure": {"name": "x", "description": "y", "when": 3}},
                    {"failure": {"name": "x"}}, {"other": {}}):
            with self.assertRaises(ValueError):
                parse_failure(bad)
        self.assertEqual(parse_planner("llm:default").arg, "default")
        for bad in ("gpt", "echo:x", "llm", "replay", 3):
            with self.assertRaises(ValueError):
                parse_planner(bad)


class RunTests(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out)

    def read(self, run, name):
        with io.open(os.path.join(self.out, run.run_id, name), encoding="utf-8") as h:
            return json.load(h)

    def test_a_run_leaves_one_complete_directory_and_is_never_flown_twice(self):
        run = cfg(failure="drone1-at-60s")
        row = R.run_one(run, self.out)
        self.assertEqual((row["status"], row["met"]), ("completed", True))
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, run.run_id))),
                         sorted([R.MANIFEST, R.REPORT, R.EVENTS, R.RECORDS]))
        m = self.read(run, R.MANIFEST)
        self.assertEqual(manifest_problems(m), [])
        self.assertEqual(m["config"], run.as_json())
        self.assertEqual(set(m["files"]), {"architecture", "scenario", "failure", "network", "allocation",
                                           "recovery", "guardian", "keep_out"})
        with mock.patch.object(R, "fly_config", side_effect=AssertionError("flown again")):
            self.assertEqual(R.run_one(run, self.out), row)               # complete: not flown again

    def test_a_crashed_run_is_kept_with_its_traceback(self):
        run = cfg()
        with mock.patch.object(R, "fly_config", side_effect=RuntimeError("the simulator fell over")):
            row = R.run_one(run, self.out)
        self.assertEqual((row["status"], row["error"]), ("crashed", "RuntimeError"))
        m = self.read(run, R.MANIFEST)
        self.assertEqual(manifest_problems(m), [])
        self.assertIn("the simulator fell over", m["error"]["traceback"])
        self.assertEqual(m["files_written"], [R.MANIFEST])

    def test_a_mission_not_met_is_a_completed_run(self):
        run = cfg(arch="B", scenario="search_relay_001", size=4, failure="drone1-at-60s")
        row = R.run_one(run, self.out)
        self.assertEqual((row["status"], row["met"]), ("completed", False))
        events = read_events(os.path.join(self.out, run.run_id, R.EVENTS))
        end = [e for e in events if e["type"] == "MISSION_COMPLETED"][0]
        self.assertEqual((end["met"], end["completion_s"]), (False, None))
        self.assertEqual(well_formed(events, self.read(run, R.REPORT)), [])

    def test_an_unfinished_directory_is_flown_again(self):
        run = cfg()
        os.makedirs(os.path.join(self.out, run.run_id))
        with io.open(os.path.join(self.out, run.run_id, R.EVENTS), "w") as h:
            h.write("half")
        self.assertEqual(R.run_one(run, self.out)["status"], "completed")


class EventTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.runs = {
            "stop": cfg("C", "search_relay_001", 4, "severe", "drone1-at-60s", 3),
            "unsafe": cfg("D", "search_relay_001", 4, "partitioned", "unsafe-proposal", 1, "echo", 2),
            "central": cfg("A", "search_pair_001", 2, "nominal", "drone1-at-60s", 1, "none", 3),
            "fallback": cfg("D-fallback", "search_pair_001", 2, "perfect", "none", 1, "none", 4),
            "scripted": cfg("E", "search_relay_001", 4, "perfect", "none", 1, "none", 5),
            "replay": cfg("D", "search_relay_001", 4, "perfect", "none", 1, REPLAY, 6),
        }
        for run in cls.runs.values():
            R.run_one(run, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def events(self, key):
        return read_events(os.path.join(self.out, self.runs[key].run_id, R.EVENTS))

    def report(self, key):
        with io.open(os.path.join(self.out, self.runs[key].run_id, R.REPORT), encoding="utf-8") as h:
            return json.load(h)

    def test_every_run_is_well_formed_and_as_configured(self):
        for key, run in self.runs.items():
            with self.subTest(run=key):
                ev, rep = self.events(key), self.report(key)
                self.assertEqual(well_formed(ev, rep), [])
                self.assertEqual(as_configured(run, ev, rep), [])

    def test_between_them_every_type_happens(self):
        seen = {e["type"] for k in self.runs for e in self.events(k)}
        self.assertEqual(seen, set(EVENT_TYPES))

    def test_the_failures_are_in_the_log(self):
        faults = [e for e in self.events("unsafe") if e["type"] == "FAULT_INJECTED"]
        self.assertEqual(sorted(e["fault"] for e in faults), ["injection", "partition"])
        self.assertTrue(any(e["outcome"] == "reject_and_replan" and "geofence" in e["checks"]
                            for e in self.events("unsafe") if e["type"] == "GUARDIAN_INTERVENED"))
        stop = [e for e in self.events("stop") if e["type"] == "FAULT_INJECTED"]
        self.assertEqual([(e["drone"], e["fault"]) for e in stop], [("Drone1", "stop")])
        self.assertTrue(any(e["why"] == "lost" for e in self.events("stop") if e["type"] == "MESSAGE_DROPPED"))

    def test_who_assigns_is_the_architectures(self):
        by = lambda key: {e.get("by") for e in self.events(key) if e["type"] == "TASK_ASSIGNED"}  # noqa: E731
        self.assertEqual(by("central"), {"base"})
        self.assertEqual(by("stop"), {"self"})
        self.assertFalse(any(e["type"] in ("TASK_BID", "TASK_ANNOUNCED") for e in self.events("central")))

    def test_a_model_only_where_one_decides(self):
        self.assertFalse(any(e["type"] == "LLM_CALLED" for e in self.events("fallback")))
        calls = [e for e in self.events("replay") if e["type"] == "LLM_CALLED"]
        self.assertTrue(calls and all(e["prompt_digest"] for e in calls))   # a replay's latency is its own, ~0

    def test_what_the_log_says_of_messages_skills_and_targets(self):
        ev = self.events("stop")
        whys = {e["why"] for e in ev if e["type"] == "MESSAGE_DROPPED"}
        self.assertIn("never_read", whys)                  # waiting for the stopped drone when the flight ended
        self.assertNotIn("pending", whys)
        self.assertTrue({"success", "aborted"} <= {e["status"] for e in ev if e["type"] == "SKILL_COMPLETED"})
        found = [e for e in ev if e["type"] == "TARGET_FOUND"]
        self.assertTrue(found and all(e["reported_s"] is None or e["reported_s"] >= e["detected_s"] for e in found))
        self.assertTrue(any(e["reported_s"] is not None for e in found))

    def test_the_checks_see_a_partition_or_an_intervention_missing(self):
        run, ev, rep = self.runs["unsafe"], self.events("unsafe"), self.report("unsafe")
        no_part = [e for e in ev if not (e["type"] == "FAULT_INJECTED" and e["fault"] == "partition")]
        self.assertTrue(any("partitions" in p for p in as_configured(run, no_part, rep)))
        no_guard = [e for e in ev if e["type"] != "GUARDIAN_INTERVENED"]
        self.assertTrue(any("no guardian intervened" in p for p in as_configured(run, no_guard, rep)))
        swapped = list(ev)
        i = next(k for k in range(1, len(ev) - 1) if ev[k]["t"] < ev[k + 1]["t"])
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        self.assertIn("events not in time order", well_formed(swapped, rep))

    def test_skills_each_end_once(self):
        for key in self.runs:
            ev = self.events(key)
            started = [(e["drone"], e["serial"]) for e in ev if e["type"] == "SKILL_STARTED"]
            ended = [(e["drone"], e["serial"]) for e in ev if e["type"] == "SKILL_COMPLETED"]
            self.assertEqual(sorted(started), sorted(ended), key)
        stop = [e for e in self.events("stop") if e["type"] == "SKILL_COMPLETED" and e["drone"] == "Drone1"]
        self.assertEqual(stop[-1]["ended"], "stopped")

    def test_the_log_is_the_same_when_flown_again(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other)
        run = self.runs["stop"]
        R.run_one(run, other)
        for f in (R.EVENTS, R.REPORT, R.RECORDS):
            with open(os.path.join(self.out, run.run_id, f), "rb") as a, open(os.path.join(other, run.run_id, f),
                                                                               "rb") as b:
                self.assertEqual(a.read(), b.read(), f)


if __name__ == "__main__":
    unittest.main()
