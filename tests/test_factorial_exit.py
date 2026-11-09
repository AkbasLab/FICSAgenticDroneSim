#!/usr/bin/env python3
"""Tests for Phase 18's exit check (AUV-16 18; docs/EXCLUSIONS.md).

    python -m unittest discover -s tests -p test_factorial_exit.py

WHY THESE EXIST
---------------
Phase 18's exit is "every final cell has sufficient valid replications, and exclusions rest on predeclared technical
criteria rather than unfavourable outcomes". The check that says so must be able to say NO. A small real batch is
flown on the mock -- A, B, C and D (by the echo), one cell, development seeds 1-3 -- given the server log and
variability report a live D batch would carry, and passes; then copies of it are broken one way each: every
exclusion X1-X5 caught and the seed set aside for all four and a reserve called for; an unfavourable outcome NOT
excluded; a development seed, a run flown twice, a reserve flown without need; different targets, roster or fault
between architectures, and a message whose fate is not the seeded draw; a decision saved without its input; a
missing variability report; requests not matching the server log. And the real design: the four Phase 18 batch
files fly exactly its 48 cells on the 20 held-out test seeds.
"""

import datetime
import glob
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
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import factorial_checks as F  # noqa: E402
from agentic_uav.experiments.batch import run_batch  # noqa: E402
from agentic_uav.experiments.experiment import load_batch  # noqa: E402
from agentic_uav.experiments.heldout import load_heldout  # noqa: E402

CELL = (2, "moderate", "drone1-at-60s")
BATCH = """[batch]
id = "mini"
description = "the exit check's test batch"

[[experiment]]
id = "abc"
architecture = ["A", "B", "C"]
scenario = "search_pair_001"
team_size = 2
network = "moderate"
failure = "drone1-at-60s"
seed = SEEDS
planner = "none"

[[experiment]]
id = "d"
architecture = "D"
scenario = "search_pair_001"
team_size = 2
network = "moderate"
failure = "drone1-at-60s"
seed = SEEDS
planner = "echo"
"""


def quiet(_line):
    pass


def jload(path):
    if path.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as h:
            return [json.loads(x) for x in h]
    opener = gzip.open if path.endswith(".gz") else io.open
    with opener(path, "rt", encoding="utf-8") as h:
        return json.load(h)


def jsave(path, data):
    if path.endswith(".jsonl.gz"):
        with gzip.open(path, "wt", encoding="utf-8") as h:
            h.writelines(json.dumps(x) + "\n" for x in data)
        return
    opener = gzip.open if path.endswith(".gz") else io.open
    with opener(path, "wt", encoding="utf-8") as h:
        json.dump(data, h)


def fly(tmp, name, seeds):
    path = os.path.join(tmp, name + ".toml")
    with io.open(path, "w", encoding="utf-8") as h:
        h.write(BATCH.replace("SEEDS", json.dumps(seeds)).replace('id = "mini"', f'id = "{name}"'))
    b = run_batch(load_batch(path), os.path.join(tmp, name), jobs=4, progress=quiet)
    for m in glob.glob(os.path.join(b, "*", "manifest.json")):     # as from a clean commit
        j = jload(m)
        j["code"]["dirty"] = False
        jsave(m, j)
    serve_log(b)
    jsave(os.path.join(b, "model-variability-x.json"), {"agreement": 1.0, "errors": 0, "asked": 100})
    return b


def serve_log(b, cuda=True, drop=0, status="200"):
    """The server log a live batch carries: CUDA found before the runs, one POST /api/chat per request."""
    runs = F.load_runs([b])
    ds = [r for r in runs if r.arch == "D" and r.manifest]
    asked = sum(len(e.get("latency_s") or []) for r in ds for lg in r.load("records.json.gz")["llm"].values()
                for e in lg["log"] if e.get("prompt_digest"))
    lo, hi = min(r.manifest["started"] for r in ds), max(r.manifest["finished"] for r in ds)
    gin = lo.replace("-", "/", 2).replace("T", " - ")
    lines = ['time=2000-01-01T00:00:00.000-05:00 level=INFO msg="Listening on 127.0.0.1:11434 (version 0.40.6)"',
             f'time=2000-01-01T00:00:01.000-05:00 level=INFO source=types.go:32 msg="inference compute" id=0 '
             f'library={"CUDA" if cuda else "cpu"} name=CUDA0']
    lines += [f'[GIN] {gin} | {status} |  1.0s |  127.0.0.1 | POST     "/api/chat"'] * (asked - drop)
    lines.append(f"time={hi[:4]}-12-31T23:59:59.000-05:00 level=INFO msg=end")
    for old in glob.glob(os.path.join(b, "serve*.log*")):
        os.remove(old)
    with io.open(os.path.join(b, "serve-test.log"), "w", encoding="utf-8") as h:
        h.write("\n".join(lines) + "\n")


class ExitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.main = fly(cls.tmp, "main", [1, 2])
        cls.reserve = fly(cls.tmp, "reserve", [3])
        runs = F.load_runs([cls.main])
        cls.design = F.mini_design([CELL], [1, 2], [3], 2, runs[0].manifest["code"]["agentic_uav_sha256"],
                                   next(r for r in runs if r.arch == "D").manifest.get("model", {}).get("llm") or {})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def copy(self, which=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        dest = os.path.join(d, os.path.basename(which or self.main))
        shutil.copytree(which or self.main, dest)
        return dest

    def check(self, *dirs):
        return F.run_checks(F.load_runs(dirs), self.design)

    def run_of(self, b, arch, seed):
        return next(p for p in glob.glob(os.path.join(b, f"*-{arch}-*-s{seed}")))

    # ------------------------------------------------------------------ clean

    def test_a_clean_batch_meets_the_exit(self):
        res = self.check(self.main)
        self.assertTrue(res["met"], res["problems"])
        self.assertEqual(res["excluded"], {})
        self.assertEqual(res["cells"]["2-moderate-drone1-at-60s"]["valid"], 2)

    # ------------------------------------------------------------- exclusions

    def assert_excluded(self, b, code, extra=()):
        res = self.check(b, *extra)
        self.assertEqual([v[:2] for v in res["excluded"].values()], [code], res["excluded"])
        return res

    def test_x1_a_crash_sets_the_seed_aside_for_all_four_and_calls_a_reserve(self):
        b = self.copy()
        m = os.path.join(self.run_of(b, "D", 1), "manifest.json")
        j = jload(m)
        j["status"], j["error"] = "crashed", {"type": "RuntimeError", "message": "x", "traceback": ""}
        jsave(m, j)
        res = self.assert_excluded(b, "X1")
        cell = res["cells"]["2-moderate-drone1-at-60s"]
        self.assertEqual((cell["valid"], cell["needed"]), (1, [[3, ["A", "B", "C", "D"]]]))
        self.assertFalse(res["met"])
        written = F.write_replacements(res, self.design, self.copy(), "reserve_t")
        self.assertEqual(sorted(os.path.basename(p) for p in written), ["reserve_t_abc.toml", "reserve_t_d.toml"])
        runs = [r for p in written for r in load_batch(p).runs]
        self.assertEqual(sorted((r.architecture, r.seed, r.planner) for r in runs),
                         [("A", 3, "none"), ("B", 3, "none"), ("C", 3, "none"), ("D", 3, "llm:default")])
        res = self.check(b, self.reserve)                        # the reserve flown by all four: complete again
        self.assertTrue(res["met"], res["problems"])
        self.assertEqual(res["cells"]["2-moderate-drone1-at-60s"]["valid"], 2)

    def test_x2_the_model_not_answering(self):
        b = self.copy()
        rec = os.path.join(self.run_of(b, "D", 2), "records.json.gz")
        j = jload(rec)
        e = next(e for lg in j["llm"].values() for e in lg["log"] if e.get("prompt_digest"))
        e["kind"], e["problems"] = "fallback", ["no reply: ReadTimeout('timed out')"]
        jsave(rec, j)
        self.assert_excluded(b, "X2")

    def test_x2_is_not_an_answer_that_could_not_be_used(self):
        b = self.copy()
        rec = os.path.join(self.run_of(b, "D", 2), "records.json.gz")
        j = jload(rec)
        e = next(e for lg in j["llm"].values() for e in lg["log"] if e.get("prompt_digest"))
        e["kind"], e["problems"] = "fallback", ["claim_task: 'search S2' is not open (open: none)"]
        jsave(rec, j)
        self.assertEqual(self.check(b)["excluded"], {})

    def test_x3_off_the_gpu_or_no_log(self):
        b = self.copy()
        serve_log(b, cuda=False)
        res = self.check(b)
        self.assertEqual(sorted(v[:2] for v in res["excluded"].values()), ["X3", "X3"])
        serve_log(b)                                              # CUDA first, then the CPU while a run flew
        r = self.run_of(b, "D", 2)
        m = os.path.join(r, "manifest.json")
        j = jload(m)
        start = datetime.datetime.fromisoformat(j["started"])
        j["started"] = (start + datetime.timedelta(seconds=100)).isoformat(timespec="seconds")   # alone in the air
        j["finished"] = (start + datetime.timedelta(seconds=130)).isoformat(timespec="seconds")
        jsave(m, j)
        when = (start + datetime.timedelta(seconds=115)).isoformat(timespec="seconds")
        serve_log(b)
        log = os.path.join(b, "serve-test.log")
        with io.open(log, encoding="utf-8") as h:
            lines = h.read().splitlines()
        lines.insert(-1, f'time={when}.500-05:00 level=INFO source=types.go:32 msg="inference compute" id=cpu library=cpu')
        with io.open(log, "w", encoding="utf-8") as h:              # inside the log's span, before its end
            h.write("\n".join(lines) + "\n")
        got = self.check(b)["excluded"]
        self.assertEqual([(os.path.basename(k), v[:2]) for k, v in got.items()], [(os.path.basename(r), "X3")])
        for f in glob.glob(os.path.join(b, "serve*")):
            os.remove(f)
        self.assertTrue(all("no server log" in v for v in self.check(b)["excluded"].values()))

    def test_x4_not_the_frozen_code(self):
        b = self.copy()
        m = os.path.join(self.run_of(b, "B", 1), "manifest.json")
        j = jload(m)
        j["code"]["dirty"] = True
        jsave(m, j)
        self.assert_excluded(b, "X4")

    def test_x5_not_the_pinned_model(self):
        b = self.copy()
        m = os.path.join(self.run_of(b, "D", 1), "manifest.json")
        j = jload(m)
        j.setdefault("model", {}).setdefault("llm", {})["digest"] = "0" * 64
        jsave(m, j)
        self.assert_excluded(b, "X5")

    def test_an_unfavourable_outcome_is_never_excluded(self):
        b = self.copy()
        for arch in "ABCD":
            p = os.path.join(self.run_of(b, arch, 1), "report.json")
            j = jload(p)
            j["met"] = False
            j["report"]["success"] = False
            jsave(p, j)
        res = self.check(b)
        self.assertEqual(res["excluded"], {})
        self.assertTrue(res["met"], res["problems"])

    # ------------------------------------------------------------------ design

    def test_a_development_seed_a_duplicate_or_an_unneeded_reserve_fails(self):
        res = self.check(self.main, self.reserve)                 # seed 3 flown with nothing set aside
        self.assertTrue(any("reserve seeds flown" in p for p in res["problems"]["design"]), res["problems"])
        b = self.copy()
        m = os.path.join(self.run_of(b, "A", 1), "manifest.json")
        j = jload(m)
        j["config"]["seed"] = 99
        jsave(m, j)
        self.assertTrue(any("not a held-out seed" in p for p in self.check(b)["problems"]["design"]))
        twin = self.copy()
        self.assertTrue(any("flown twice" in p for p in self.check(self.main, twin)["problems"]["design"]))

    # ------------------------------------------------- common random numbers

    def test_different_targets_or_planned_failure_between_architectures_fails(self):
        b = self.copy()
        p = os.path.join(self.run_of(b, "C", 1), "report.json")
        j = jload(p)
        j["report"]["facts"]["targets"][0]["x"] += 1.0
        jsave(p, j)
        self.assertTrue(any("targets differs" in x for x in self.check(b)["problems"]["common_random_numbers"]))
        b = self.copy()                                           # the failure as planned: its file
        m = os.path.join(self.run_of(b, "A", 2), "manifest.json")
        j = jload(m)
        j["files"]["failure"]["sha256"] = "0" * 16
        jsave(m, j)
        self.assertTrue(any("files differs" in x for x in self.check(b)["problems"]["common_random_numbers"]))

    def test_a_planned_stop_that_found_nothing_to_stop_is_no_difference(self):
        # Phase 18's A, severe links: Drone1 landed at 19 s, so the stop planned at 60 s took hold of nothing.
        b = self.copy()
        p = os.path.join(self.run_of(b, "A", 1), "events.jsonl.gz")
        jsave(p, [e for e in jload(p) if e["type"] != "FAULT_INJECTED"])
        self.assertEqual(self.check(b)["problems"]["common_random_numbers"], [])
        # Taking hold a step after its plan is the architecture's clock (A at 60.1 s), not a different fault ...
        b = self.copy()
        p = os.path.join(self.run_of(b, "A", 2), "events.jsonl.gz")
        ev = jload(p)
        fault = next(e for e in ev if e["type"] == "FAULT_INJECTED")
        fault["t"] = fault["planned_s"] + 0.1
        jsave(p, ev)
        self.assertEqual(self.check(b)["problems"]["common_random_numbers"], [])
        # ... but taking hold seconds late is.
        fault["t"] = fault["planned_s"] + 5.0
        jsave(p, ev)
        self.assertTrue(any("took hold at" in x for x in self.check(b)["problems"]["common_random_numbers"]))

    def test_a_partition_fault_is_compared_whole(self):
        # A partition is injected with no drone, its groups and its end (the dry run of 2026-11-09 met it first).
        part = {"drone": None, "fault": "partition", "groups": [["Drone1", "base"], ["Drone2"]], "t": 60.0,
                "type": "FAULT_INJECTED", "until_s": 120.0}
        b = self.copy()
        for arch in "ABCD":
            p = os.path.join(self.run_of(b, arch, 1), "events.jsonl.gz")
            jsave(p, jload(p) + [dict(part)])
        self.assertEqual(self.check(b)["problems"]["common_random_numbers"], [])

    def test_a_message_fate_that_is_not_the_seeded_draw_fails(self):
        b = self.copy()
        p = os.path.join(self.run_of(b, "C", 2), "events.jsonl.gz")
        ev = jload(p)
        e = next(e for e in ev if e["type"] == "MESSAGE_RECEIVED")
        e.update(type="MESSAGE_DROPPED", why="lost")
        jsave(p, ev)
        self.assertTrue(any("the draw says otherwise" in x
                            for x in self.check(b)["problems"]["common_random_numbers"]))

    # --------------------------------------------------------- decisions saved

    def test_a_decision_without_its_input_fails(self):
        b = self.copy()
        rec = os.path.join(self.run_of(b, "D", 1), "records.json.gz")
        j = jload(rec)
        del next(e for lg in j["llm"].values() for e in lg["log"] if e.get("prompt_digest"))["context"]
        jsave(rec, j)
        self.assertTrue(any("without context" in x for x in self.check(b)["problems"]["decisions_saved"]))

    # -------------------------------------------------- variability, requests

    def test_variability_missing_fails_and_low_agreement_is_flagged(self):
        b = self.copy()
        jsave(os.path.join(b, "model-variability-x.json"), {"agreement": 0.9, "errors": 0})
        res = self.check(b)
        self.assertEqual(res["problems"]["variability"], [])
        self.assertTrue(any("under 95%" in f for f in res["flags"]))
        os.remove(os.path.join(b, "model-variability-x.json"))
        self.assertTrue(self.check(b)["problems"]["variability"])

    def test_requests_not_matching_the_server_log_fail(self):
        b = self.copy()
        serve_log(b, drop=1)
        self.assertTrue(any("in the records" in x for x in self.check(b)["problems"]["requests_accounted"]))
        serve_log(b, status="500")
        self.assertTrue(any("not answered" in x for x in self.check(b)["problems"]["requests_accounted"]))


class TheRealDesignTests(unittest.TestCase):
    def test_the_four_batch_files_fly_the_design_on_the_held_out_test_seeds(self):
        d = F.design(ROOT)
        test, reserve = load_heldout(ROOT)
        self.assertEqual((d.test, d.reserve, d.required, len(d.cells)), (tuple(test), tuple(reserve), 20, 12))
        flown = []
        for name in ("phase18_abc", "phase18_d_pair", "phase18_d_four_a", "phase18_d_four_b"):
            for r in load_batch(os.path.join(ROOT, "configs", "experiments", name + ".toml")).runs:
                self.assertEqual(r.scenario, F.SCENARIOS[r.team_size])
                self.assertEqual(r.planner, "llm:default" if r.architecture == "D" else "none")
                flown.append((r.architecture, (r.team_size, r.network, r.failure), r.seed))
        want = [(a, c, s) for a in F.ARCHS for c in d.cells for s in test]
        self.assertEqual(sorted(flown, key=str), sorted(want, key=str))
        self.assertEqual(len(flown), 960)
        self.assertEqual(d.llm["model"], "llama3.3:70b")


if __name__ == "__main__":
    unittest.main()
