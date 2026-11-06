#!/usr/bin/env python3
"""Tests for Phase 15's metrics: each one, on a run built by hand, against the answer worked out by hand.

    python -m unittest discover -s tests -p test_metrics.py

WHY THESE EXIST
---------------
AUV-14's exit for Phase 15: "every primary metric has a written definition and
a tested implementation". The definitions are docs/METRICS.md, committed before
any of this code; these hold the implementation to them, metric by metric:
P1.success, P1.coverage, P1.target_detection, P1.safe_return, P1.mission_score,
P2.completion_s, P2.censored, P3.continuity_retention, P4.recovery_s,
P4.censored, P5.collisions, P5.separation_violations, P5.zone_entries,
P5.emergency_fallbacks, P5.unsafe_proposals, P5.guardian_interventions,
P6.messages, P6.bytes, P6.messages_per_completed_task, P6.duplicates,
P6.expired, CE.coordination_efficiency, CE.total_cells, CE.unique_cells and
D1-D15 -- including the edges each definition names (a failed mission
censored, nothing lost, no twin, a zero denominator, an old log), and that
the registry and the document agree, so neither can drift from the other.
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

from agentic_uav.experiments import metrics as M  # noqa: E402

W = 300.0                      # the window of every hand-built run


def ev(t, etype, drone=None, /, **f):
    return {"t": t, "type": etype, "drone": drone, **f}


def sent(t, drone, mtype="task_bid", digest="d1", ttl=10.0, nbytes=100, to=("*",)):
    return ev(t, "MESSAGE_SENT", drone, message_id=f"{drone}#{t}", message_type=mtype, recipients=list(to),
              bytes=nbytes, ttl_s=ttl, payload_digest=digest)


def report(success=True, completion=200.0, coverage=0.9, detection=1.0, safe=0.5, collisions=0, sep=0, zones=0,
           by_sector=None, batteries=None, searched=None):
    out = {"met": success, "report": {
        "success": success, "completion_s": completion if success else None, "window_s": W,
        "components": {"coverage": coverage, "target_detection": detection, "safe_return": safe,
                       "collisions": collisions, "separation_violations": sep, "zone_entries": zones},
        "coverage": {"by_sector": by_sector or {"S1": 1.0, "S2": 1.0}},
        "facts": {"batteries": batteries or [{"drone": "Drone1", "used": 10.0, "flown_m": 400.0},
                                             {"drone": "Drone2", "used": 12.5, "flown_m": 500.0}]}}}
    if searched is not False:
        out["searched"] = searched if searched is not None else {"Drone1": ["search S1"], "Drone2": ["search S2"]}
    return out


def config(arch="C", network="nominal", failure="none", seed=1, planner="none"):
    return {"index": 1, "experiment_id": "t", "architecture": arch, "scenario": "search_pair_001", "team_size": 2,
            "network": network, "failure": failure, "seed": seed, "planner": planner}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def make(self, rid="r", cfg=None, rep=None, events=(), records=None, trajectories=None, status="completed"):
        d = os.path.join(self.root, rid)
        os.makedirs(d)
        with io.open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as h:
            json.dump({"run_id": rid, "config": cfg or config(), "status": status}, h)
        if status == "completed":
            with io.open(os.path.join(d, "report.json"), "w", encoding="utf-8") as h:
                json.dump(rep or report(), h)
            with gzip.open(os.path.join(d, "events.jsonl.gz"), "wt", encoding="utf-8") as h:
                h.writelines(json.dumps(e) + "\n" for e in sorted(events, key=lambda e: e["t"]))
            with gzip.open(os.path.join(d, "records.json.gz"), "wt", encoding="utf-8") as h:
                json.dump(records if records is not None else {"policies": {}}, h)
            if trajectories is not None:
                with gzip.open(os.path.join(d, "trajectories.json.gz"), "wt", encoding="utf-8") as h:
                    json.dump(trajectories, h)
        return d

    def score(self, **kw):
        return M.run_metrics(M.load_run(self.make(**kw)))


class RegistryTests(Base):

    def test_the_registry_is_the_documents_and_the_document_is_version_1(self):
        self.assertEqual(M.check_registry(), [])
        self.assertEqual(M.doc_ids(M.doc_text()), list(M.REGISTRY))
        self.assertEqual(M.doc_version(M.doc_text()), M.VERSION)

    def test_a_drifted_document_is_caught(self):
        text = M.doc_text()
        path = os.path.join(self.root, "METRICS.md")
        for altered in (text.replace("| `D15.conflicting_claims` |", "| `D15.claims` |"),
                        text.replace("definitions, version 1", "definitions, version 2")):
            with io.open(path, "w", encoding="utf-8") as h:
                h.write(altered)
            self.assertTrue(M.check_registry(path))

    def test_every_metric_has_a_value_or_a_reason(self):
        rows = M.batch_metrics(os.path.dirname(self.make()))
        r = rows[0]
        self.assertEqual(set(r["values"]) | set(r["absent"]), set(M.REGISTRY))
        self.assertFalse(set(r["values"]) & set(r["absent"]))
        self.assertEqual(r["definitions_sha256"], M.doc_sha256())

    def test_a_crashed_run_has_every_metric_absent(self):
        v, a = self.score(status="crashed")
        self.assertEqual(v, {})
        self.assertEqual({k for k, (kind, _) in a.items() if kind == M.NOT_AVAILABLE}, set(M.REGISTRY))


class PrimaryTests(Base):

    def test_P1_success_components_and_mission_score(self):
        v, _ = self.score(rep=report(coverage=0.9, detection=1.0, safe=0.5))
        self.assertIs(v["P1.success"], True)
        self.assertEqual((v["P1.coverage"], v["P1.target_detection"], v["P1.safe_return"]), (0.9, 1.0, 0.5))
        self.assertAlmostEqual(v["P1.mission_score"], 0.8)

    def test_P2_completion_time_and_censoring_at_the_deadline(self):
        v, _ = self.score(rep=report(success=True, completion=187.5))
        self.assertEqual((v["P2.completion_s"], v["P2.censored"]), (187.5, False))
        v, _ = self.score(rid="fail", rep=report(success=False))
        self.assertEqual((v["P1.success"], v["P2.completion_s"], v["P2.censored"]), (False, 900.0, True))

    def test_P3_continuity_retention_against_the_nominal_twin(self):
        self.make("nominal", cfg=config(), rep=report(coverage=0.9, detection=1.0, safe=0.5))           # 0.8
        self.make("severe", cfg=config(network="severe"), rep=report(coverage=0.6, detection=1.0, safe=0.2))  # 0.6
        self.make("orphan", cfg=config(network="severe", seed=2))
        self.make("zero-twin", cfg=config(seed=3), rep=report(coverage=0.0, detection=0.0, safe=0.0))
        self.make("stop-of-zero", cfg=config(seed=3, failure="drone1-at-60s"))
        rows = {r["run_id"]: r for r in M.batch_metrics(self.root)}
        self.assertAlmostEqual(rows["severe"]["values"]["P3.continuity_retention"], 0.75)
        self.assertEqual(rows["severe"]["twin"], "nominal")
        kind = lambda rid: rows[rid]["absent"]["P3.continuity_retention"]["kind"]  # noqa: E731
        self.assertEqual(kind("nominal"), M.NOT_APPLICABLE)
        self.assertEqual(kind("orphan"), M.NOT_AVAILABLE)
        self.assertEqual(kind("stop-of-zero"), M.UNDEFINED)

    def stop_run(self, rid, events, completed=()):
        return self.score(rid=rid, events=[ev(60.0, "FAULT_INJECTED", "Drone1", fault="stop")] + events,
                          records={"policies": {"Drone1": {"completed": list(completed)}}})

    def test_P4_recovery_time_from_the_stop_to_another_drone_taking_the_lost_task(self):
        v, _ = self.stop_run("taken", [ev(5.0, "TASK_ASSIGNED", "Drone1", task="search S1"),
                                       ev(75.0, "TASK_ASSIGNED", "Drone1", task="search S1"),   # itself: not it
                                       ev(80.0, "TASK_ASSIGNED", "Drone2", task="search S2"),   # not the lost task
                                       ev(90.5, "TASK_ASSIGNED", "Drone2", task="search S1")])
        self.assertEqual((v["P4.recovery_s"], v["P4.censored"]), (30.5, False))
        v, _ = self.stop_run("never", [ev(5.0, "TASK_ASSIGNED", "Drone1", task="search S1")])
        self.assertEqual((v["P4.recovery_s"], v["P4.censored"]), (W - 60.0, True))

    def test_P4_with_two_stops_is_the_longer_recovery(self):
        v, _ = self.score(rid="two", events=[
            ev(5.0, "TASK_ASSIGNED", "Drone1", task="search S1"), ev(6.0, "TASK_ASSIGNED", "Drone2", task="search S2"),
            ev(60.0, "FAULT_INJECTED", "Drone1", fault="stop"), ev(60.0, "FAULT_INJECTED", "Drone2", fault="stop"),
            ev(75.0, "TASK_ASSIGNED", "Drone3", task="search S1"), ev(90.0, "TASK_ASSIGNED", "Drone3", task="search S2")],
            records={"policies": {}})
        self.assertEqual((v["P4.recovery_s"], v["P4.censored"]), (30.0, False))

    def test_P4_not_applicable_when_nothing_was_lost(self):
        for rid, events, done in (("none", [], ()),
                                  ("released", [ev(5.0, "TASK_ASSIGNED", "Drone1", task="search S1"),
                                                ev(40.0, "TASK_RELEASED", "Drone1", task="search S1", why="x")], ()),
                                  ("finished", [ev(5.0, "TASK_ASSIGNED", "Drone1", task="search S1")],
                                   ("search S1",))):
            v, a = self.stop_run(rid, events, done)
            self.assertEqual(a["P4.recovery_s"][0], M.NOT_APPLICABLE, rid)
        v, a = self.score(rid="nostop")
        self.assertEqual(a["P4.censored"][0], M.NOT_APPLICABLE)

    def test_P5_the_judges_counts_and_the_guardians(self):
        g = lambda t, o: ev(t, "GUARDIAN_INTERVENED", "Drone1", outcome=o)  # noqa: E731
        v, _ = self.score(rep=report(collisions=1, sep=2, zones=3),
                          events=[g(1, "reject_and_replan"), g(2, "approve_with_modification"),
                                  g(3, "execute_safe_fallback"), g(4, "reject_and_replan")])
        self.assertEqual((v["P5.collisions"], v["P5.separation_violations"], v["P5.zone_entries"]), (1, 2, 3))
        self.assertEqual((v["P5.unsafe_proposals"], v["P5.emergency_fallbacks"], v["P5.guardian_interventions"]),
                         (3, 1, 4))

    def test_P6_messages_bytes_per_task_and_expired(self):
        v, _ = self.score(events=[sent(1, "Drone1", nbytes=100), sent(2, "Drone2", nbytes=250, digest="x"),
                                  sent(3, "Drone2", mtype="heartbeat", nbytes=50),
                                  ev(4, "MESSAGE_DROPPED", "Drone1", why="expired"),
                                  ev(5, "MESSAGE_DROPPED", "Drone1", why="lost")],
                          rep=report(searched={"Drone1": ["search S1", "search S1"], "Drone2": ["search S2"]}))
        self.assertEqual((v["P6.messages"], v["P6.bytes"], v["P6.expired"]), (3, 400, 1))
        self.assertAlmostEqual(v["P6.messages_per_completed_task"], 1.5)            # 3 messages, 2 sectors

    def test_P6_duplicates_are_the_same_thing_said_again_while_still_current(self):
        v, _ = self.score(events=[
            sent(0, "Drone1", digest="a", ttl=10),                   # first
            sent(5, "Drone1", digest="a", ttl=10),                   # 5 s after, still current: duplicate 1
            sent(16, "Drone1", digest="a", ttl=10),                  # 11 s after t=5: stale, not a duplicate
            sent(20, "Drone1", digest="a", ttl=10),                  # 4 s after t=16: duplicate 2
            sent(17, "Drone1", digest="b", ttl=10),                  # something else
            sent(18, "Drone2", digest="a", ttl=10),                  # someone else
            sent(19, "Drone1", digest="a", ttl=10, to=("Drone2",)),  # to someone else
            sent(21, "Drone1", mtype="heartbeat", digest="h"), sent(22, "Drone1", mtype="heartbeat", digest="h")])
        self.assertEqual(v["P6.duplicates"], 2)                     # heartbeats never count
        v, _ = self.score(rid="edge", events=[sent(0, "Drone1", digest="a", ttl=10),
                                              sent(10, "Drone1", digest="a", ttl=10)])     # exactly its lifetime later
        self.assertEqual(v["P6.duplicates"], 0)

    def test_P6_absent_for_an_old_log(self):
        old = sent(1, "Drone1")
        del old["payload_digest"]
        v, a = self.score(events=[old, dict(sent(2, "Drone2"), bytes="<bound method>")])
        self.assertEqual(a["P6.duplicates"][0], M.NOT_AVAILABLE)
        self.assertEqual(a["P6.bytes"][0], M.NOT_AVAILABLE)
        v, a = self.score(rid="nosearch", rep=report(searched=False))
        self.assertEqual(a["P6.messages_per_completed_task"][0], M.NOT_AVAILABLE)
        v, a = self.score(rid="nothingdone", rep=report(searched={"Drone1": [], "Drone2": []}))
        self.assertEqual(a["P6.messages_per_completed_task"][0], M.UNDEFINED)


class EfficiencyTests(Base):

    def hover(self, x, y, s=20.0):
        return [[0.0, x, y, 12.0, True], [s, x, y, 12.0, True]]

    def test_CE_two_drones_searching_the_same_ground_is_one_half(self):
        v, _ = self.score(trajectories={"Drone1": self.hover(80, -40), "Drone2": self.hover(80, -40)})
        self.assertGreater(v["CE.unique_cells"], 0)
        self.assertEqual(v["CE.total_cells"], 2 * v["CE.unique_cells"])
        self.assertEqual(v["CE.coordination_efficiency"], 0.5)

    def test_CE_two_drones_apart_is_one(self):
        v, _ = self.score(trajectories={"Drone1": self.hover(80, -40), "Drone2": self.hover(80, 40)})
        self.assertEqual(v["CE.total_cells"], v["CE.unique_cells"])
        self.assertEqual(v["CE.coordination_efficiency"], 1.0)

    def test_CE_needs_a_dwell_and_trajectories(self):
        brief = [[0.0, 80, -40, 12.0, True], [1.0, 80, -40, 12.0, True], [1.0, 80, -40, 0.0, False]]
        v, a = self.score(trajectories={"Drone1": brief})        # 1 s over it, then on the ground: under 2 s
        self.assertEqual((v["CE.total_cells"], a["CE.coordination_efficiency"][0]), (0, M.UNDEFINED))
        v, a = self.score(rid="none")
        self.assertEqual(a["CE.unique_cells"][0], M.NOT_AVAILABLE)


class DiagnosticTests(Base):

    def test_D1_to_D4(self):
        v, _ = self.score(
            rep=report(coverage=0.875, by_sector={"S1": 0.99, "S2": 0.5},
                       searched={"Drone1": ["search S1", "search S2"], "Drone2": ["search S1", "search S1"]}),
            events=[ev(1, "TASK_ASSIGNED", "Drone1", task="search S1"), ev(2, "TASK_ASSIGNED", "Drone2",
                                                                         task="search S1"),
                    ev(3, "TASK_ASSIGNED", "Drone1", task="search S1"), ev(4, "TASK_ASSIGNED", "Drone1",
                                                                         task="search S2")])
        self.assertEqual(v["D1.area_searched_pct"], 87.5)
        self.assertEqual(v["D2.redundant_searches"], 2)              # S1 three times
        self.assertEqual(v["D3.task_reassignments"], 2)              # S1 assigned three times
        self.assertEqual(v["D4.orphaned_tasks"], 1)                  # S2 at 0.5 < 0.95

    def test_D5_D6_role_changes_and_oscillations(self):
        r = lambda t, d, role, prev: ev(t, "ROLE_CHANGED", d, role=role, previous=prev, why="")  # noqa: E731
        v, _ = self.score(events=[r(10, "Drone1", "relay", "scout"), r(30, "Drone1", "scout", "relay"),   # back: 1
                                  r(70, "Drone1", "relay", "scout"),                                       # 40 s: no
                                  r(10, "Drone2", "reserve", "scout"), r(15, "Drone2", "relay", "reserve")])  # on
        self.assertEqual((v["D5.role_changes"], v["D6.role_oscillations"]), (5, 1))

    def test_D7_stale_message_decisions(self):
        v, _ = self.score(events=[
            ev(10, "MESSAGE_RECEIVED", "Drone1", delay_s=2.5), ev(10, "DECISION_PROPOSED", "Drone1",
                                                                  triggers=["message"]),              # stale: 1
            ev(20, "MESSAGE_RECEIVED", "Drone1", delay_s=2.0), ev(20, "DECISION_PROPOSED", "Drone1",
                                                                  triggers=["message"]),              # 2.0: not
            ev(30, "MESSAGE_RECEIVED", "Drone2", delay_s=3.0), ev(30, "DECISION_PROPOSED", "Drone1",
                                                                  triggers=["message"]),              # other drone
            ev(40, "MESSAGE_RECEIVED", "Drone1", delay_s=3.0), ev(40, "DECISION_PROPOSED", "Drone1",
                                                                  triggers=["periodic"])])            # not a message
        self.assertEqual(v["D7.stale_message_decisions"], 1)

    def test_D8_to_D12_where_a_model_decides(self):
        call = lambda t, kind="llm", lat=(1.0,), problems=(): ev(t, "LLM_CALLED", "Drone1", kind=kind,  # noqa: E731
                                                                  latency_s=list(lat), calls=len(lat),
                                                                  problems=list(problems))
        events = [call(1, lat=(3.0,)), call(2, lat=(1.0, 2.0), problems=("bad json",)), call(3, kind="fallback",
                                                                                          lat=(4.0, 5.0)),
                  call(4, lat=(6.0,))]
        v, a = self.score(cfg=config(arch="D", planner="echo"), events=events,
                          records={"policies": {}, "llm": {"Drone1": {"log": [{"tokens": 120}, {"tokens": 80},
                                                                             {"kind": "procedural"}]}}})
        self.assertEqual((v["D8.invalid_llm_outputs"], v["D10.llm_calls"], v["D11.fallback_use"]), (1, 6, 1))
        self.assertEqual((v["D9.llm_latency_p50_s"], v["D9.llm_latency_p95_s"]), (3.0, 6.0))   # of 1,2,3,4,5,6
        self.assertEqual(v["D12.tokens"], 200)
        v, a = self.score(rid="untold", cfg=config(arch="D", planner="echo"), events=events)
        self.assertEqual(a["D12.tokens"][0], M.NOT_RECORDED)
        v, a = self.score(rid="noplanner", cfg=config(arch="D", planner="none"), events=events)
        self.assertEqual(a["D10.llm_calls"][0], M.NOT_APPLICABLE)        # a model arm given no model
        v, a = self.score(rid="rules", events=events)
        self.assertEqual({a[k][0] for k in ("D8.invalid_llm_outputs", "D9.llm_latency_p50_s", "D10.llm_calls",
                                            "D11.fallback_use", "D12.tokens")}, {M.NOT_APPLICABLE})

    def test_D13_to_D15(self):
        v, _ = self.score(events=[ev(5, "TASK_RELEASED", "Drone1", task="search S1",
                                     why="lost: lost to Drone2's claim by the value rule"),
                                  ev(6, "TASK_RELEASED", "Drone1", task="search S1", why="lost: Drone2 completed it"),
                                  ev(7, "TASK_RELEASED", "Drone1", task="search S2", why="abandoned: battery")])
        self.assertEqual((v["D13.battery_used_pct"], v["D14.distance_m"], v["D15.conflicting_claims"]),
                         (22.5, 900.0, 1))

    def test_nearest_rank(self):
        self.assertEqual([M.nearest_rank([5, 1, 3, 2, 4], p) for p in (1, 20, 50, 95, 100)], [1, 1, 3, 5, 5])


class ExitCheckTests(unittest.TestCase):
    """The exit's checks, each shown able to fail: on real runs scored, then altered."""

    @classmethod
    def setUpClass(cls):
        from agentic_uav.experiments.experiment import ExperimentConfig
        from agentic_uav.experiments.experiment_run import run_one
        cls.dir = tempfile.mkdtemp()
        for i, (arch, net, fail, planner) in enumerate((("C", "nominal", "none", "none"),
                                                         ("D", "nominal", "drone1-at-60s", "echo")), 1):
            run_one(ExperimentConfig(i, "x", arch, "search_pair_001", 2, net, fail, 1, planner), cls.dir)
        cls.rows = M.batch_metrics(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def scored(self, change=None):
        from agentic_uav.experiments.metrics_exit import scored_checks
        rows = json.loads(json.dumps(self.rows))
        if change:
            change(rows)
        return {k for k, v in scored_checks(rows, self.dir).items() if v}

    def test_real_runs_pass_and_the_static_checks_hold(self):
        from agentic_uav.experiments.metrics_exit import static_checks
        self.assertEqual(self.scored(), set())
        p = static_checks()
        self.assertEqual((p["defined"], p["tested"]), ([], []))

    def test_each_scored_check_can_fail(self):
        def drop(rows):
            del rows[0]["values"]["P1.coverage"]
        def wrong_reason(rows):
            r = rows[1]
            r["absent"]["P4.recovery_s"] = {"kind": M.NOT_AVAILABLE, "why": "x"}
            r["values"].pop("P4.recovery_s", None)
        self.assertIn("computed_everywhere", self.scored(drop))
        self.assertIn("computed_everywhere", self.scored(wrong_reason))
        self.assertIn("in_range", self.scored(lambda rows: rows[0]["values"].update({"P1.coverage": 1.2})))
        self.assertIn("in_range", self.scored(lambda rows: rows[0]["values"].update({"P6.messages": -1})))
        self.assertIn("agrees_with_judge", self.scored(lambda rows: rows[0]["values"].update({"CE.unique_cells": 3})))
        self.assertIn("agrees_with_judge", self.scored(lambda rows: rows[0]["values"].update({"P1.success": False})))
        self.assertIn("computed_everywhere",
                      self.scored(lambda rows: rows[0].update({"definitions_sha256": "0" * 64})))

    def test_a_primary_metric_never_asserted_is_caught(self):
        from unittest import mock
        from agentic_uav.experiments import metrics_exit as X
        with io.open(X.TESTS, encoding="utf-8") as h:
            text = h.read()
        path = os.path.join(self.dir, "test_metrics_without.py")
        with io.open(path, "w", encoding="utf-8") as h:
            h.write(text.replace('"P5.zone_entries"', '"P5.zone"'))
        with mock.patch.object(X, "TESTS", path):
            self.assertTrue(any("P5.zone_entries" in x for x in X.static_checks()["tested"]))

    def test_determinism_and_old_logs_can_fail(self):
        from agentic_uav.experiments.metrics_exit import compare_scores, old_log_checks
        other = json.loads(json.dumps(self.rows))
        self.assertEqual(compare_scores(self.rows, other), [])
        other[0]["values"]["P6.messages"] += 1
        self.assertTrue(compare_scores(self.rows, other))
        self.assertTrue(old_log_checks(self.rows))           # these have sizes and digests: not version-1 logs


if __name__ == "__main__":
    unittest.main()
