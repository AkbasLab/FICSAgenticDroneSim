#!/usr/bin/env python3
"""Tests for the two defects Phase 17's pilot timelines found, each re-flown on the mock (AUV-16 17.2).

    python -m unittest discover -s tests -p test_pilot_defects.py

WHY THESE EXIST
---------------
Pilot batch phase17-pilot-20261106-201311 (the live llama3.3:70b, Vega gpu02) flew D's two-drone team with
Drone1 stopped at 60 s: 4 of 10 missions completed, against C's 10 of 10. The timelines showed why, the same in all
six failures. The survivor claimed Drone1's sector and the model chose `start_search`; the tool searched FROM
WHERE THE DRONE WAS, so the search's first leg crossed the keep-out round Drone1's last position; the guardian
refused it (rightly); and a refusal sends a drone home. The rule team never meets this: it searches from where it
is only when the way to its first lane is clear, and otherwise flies a route round what it avoids first.

And in one of the six (run 0027), after the model had put the drone on "stand by" and then sent it home, the
landing's success took it back to "wait for a task": a hold on the ground that failed, a landing retried, every
half second to the deadline (559 decisions).

1. THE PILOT RUN, RE-FLOWN WITH THE MODEL'S OWN ANSWERS. Run 0029 (seed 4) is flown again on the mock, every
   request answered with the reply the 70B gave for exactly those messages that night, and with the rule's answer
   once the flight leaves its record. It must take the model's `start_search` (the replay really reaches the
   defect), be refused by nothing, and complete the mission.
2. START_SEARCH BY THE RULE'S WAY IN, at the unit: asked from the far side of a keep-out it routes round it; asked
   with the way clear, it is the search itself, as before.
3. GOING HOME IS NOT WAITING: a drone put on "stand by" then sent home lands and is done -- no hold on the ground,
   no landing retried.
"""

import dataclasses
import gzip
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents import llm_tools as T  # noqa: E402
from agentic_uav.agents.llm_policy import digest  # noqa: E402
from agentic_uav.experiments import experiment_run as ER  # noqa: E402
from agentic_uav.experiments.experiment import ExperimentConfig  # noqa: E402

BATCH = os.path.join(ROOT, "phases", "phase-17-pilot-experiments", "results", "phase17-pilot-20261106-201311")
RUN_0029 = "0029-D-search_pair_001-nominal-drone1-at-60s-s4"


class PilotReplay:
    """Answers each request with the 70B's recorded reply for exactly those messages; off the record, the rule's."""

    def __init__(self, records: dict) -> None:
        self.queue: dict[str, list[list[str]]] = {}
        for log in records["llm"].values():
            for e in log["log"]:
                if e.get("prompt_digest"):
                    self.queue.setdefault(e["prompt_digest"], []).append(e["replies"])
        self.current: dict[str, list[str]] = {}
        self.recorded = self.off = 0

    def __call__(self, request):
        msgs = request["messages"]
        key, n = digest(msgs[:2]), (len(msgs) - 2) // 2          # n: 0 the first ask, 1 its correction
        if n == 0 and self.queue.get(key):
            self.current[key] = self.queue[key].pop(0)
        replies = self.current.get(key) if n == 0 or key in self.current else None
        if replies is not None and n < len(replies):
            self.recorded += 1
            return replies[n]
        self.off += 1
        return request["meta"]["rule_reply"]


class Scripted:
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, request):
        return self.fn(request)


def fly(seed, ask, failure="drone1-at-60s"):
    """One D flight of the pilot's two-drone cell, as the batch flies it, with `ask` as the model."""
    run = ExperimentConfig(1, "pilot", "D", "search_pair_001", 2, "nominal", failure, seed, "echo")
    original = ER._ask
    ER._ask = lambda *a, **k: (ask, {"planner": "test"})
    try:
        return ER.fly_config(run)[0]
    finally:
        ER._ask = original


def entries(flight, drone):
    return flight.llm[drone]["log"]


def refusals(flight):
    return [(d, e["at"]) for d in flight.llm for e in entries(flight, d) if "guard_rejected" in e["events"]]


class PilotRunTests(unittest.TestCase):
    def test_run_0029_re_flown_with_the_models_own_answers_completes(self):
        with gzip.open(os.path.join(BATCH, RUN_0029, "records.json.gz"), "rt", encoding="utf-8") as h:
            ask = PilotReplay(json.load(h))
        flight = fly(4, ask)
        took = [e for e in entries(flight, "Drone2") if e.get("tool") == "start_search" and not e.get("agreed")]
        self.assertTrue(took, "the replay never reached the model's start_search")
        self.assertGreater(ask.recorded, 10)                  # the night's own answers, up to and past the defect
        self.assertEqual(refusals(flight), [])
        self.assertTrue(flight.run.met)
        self.assertNotIn("Drone2", [d for d, _ in refusals(flight)])


class StartSearchTests(unittest.TestCase):
    def test_from_beyond_a_keep_out_it_routes_round_it_then_searches(self):
        # The model answers start_search the moment it holds Drone1's sector (as 0029, 0030 and 0038 did).
        said = []

        def jump_ahead(request):
            ctx = json.loads(request["messages"][1]["content"])
            you, acts = ctx["you"], [(a["tool"], a["parameters"]) for a in ctx["actions"]]
            if you["id"] == "Drone2" and not said and you["task"] == "search S1" \
                    and ("start_search", {"task_id": "search S1"}) in acts:
                said.append(you["stage"])
                return T.reply_for("start_search", {"task_id": "search S1"}, "JUMP_AHEAD")
            return request["meta"]["rule_reply"]
        flight = fly(4, Scripted(jump_ahead))
        jumped = [e for e in entries(flight, "Drone2") if e.get("tool") == "start_search" and not e.get("agreed")]
        self.assertTrue(jumped)
        self.assertEqual(refusals(flight), [])
        reached = [e for e in entries(flight, "Drone2") if (e.get("decision") or {}).get("objective") == "reach S1"]
        self.assertTrue(reached, "it should fly a route to S1 first, round the keep-out")
        self.assertTrue(flight.run.met)

    def test_with_the_way_clear_it_is_the_search_itself(self):
        # No teammate silent, so nothing to go round: answered at once, start_search is the search, as before.
        def search_now(request):
            ctx = json.loads(request["messages"][1]["content"])
            you = ctx["you"]
            if you["task"] and ("start_search", {"task_id": you["task"]}) in \
                    [(a["tool"], a["parameters"]) for a in ctx["actions"]] and you["stage"] == "to_sector":
                return T.reply_for("start_search", {"task_id": you["task"]}, "SEARCH_NOW")
            return request["meta"]["rule_reply"]
        flight = fly(4, Scripted(search_now), failure="none")
        self.assertEqual(refusals(flight), [])
        self.assertTrue(flight.run.met)


class GoingHomeTests(unittest.TestCase):
    def test_stand_by_then_home_lands_and_is_done(self):
        # As 0027: once Drone2 holds S1, "stand by" (reserve), then home. It must land and finish.
        said = {"reserve": False, "home": False}

        def stand_by_then_home(request):
            ctx = json.loads(request["messages"][1]["content"])
            you = ctx["you"]
            acts = [(a["tool"], a["parameters"]) for a in ctx["actions"]]
            if you["id"] == "Drone2" and not said["reserve"] and you["task"] == "search S1" \
                    and ("change_role", {"new_role": "reserve"}) in acts:
                said["reserve"] = True
                return T.reply_for("change_role", {"new_role": "reserve"}, "STAND_BY")
            if you["id"] == "Drone2" and said["reserve"] and not said["home"] and ("return_home", {}) in acts:
                said["home"] = True
                return T.reply_for("return_home", {}, "HOME")
            return request["meta"]["rule_reply"]
        flight = fly(2, Scripted(stand_by_then_home))
        self.assertTrue(said["reserve"] and said["home"])
        log = entries(flight, "Drone2")
        looped = [e for e in log if "not under API control" in json.dumps(e.get("decision"))]
        self.assertEqual(looped, [])
        on_ground = [e for e in log if e["at"] > 200 and (e.get("decision") or {}).get("objective") == "wait for a task"]
        self.assertEqual(on_ground, [])
        self.assertLess(len(log), 120)                       # 0027's loop made it 600


if __name__ == "__main__":
    unittest.main()
