#!/usr/bin/env python3
"""Tests for Phase 12's LLM policy: the reply schema, the tools, the context, and every path a decision takes.

    python -m unittest discover -s tests -p test_llm_policy.py

WHY THESE EXIST
---------------
From Phase 12 a model chooses what each drone does. Before any real model is
asked anything, these hold the machinery to account with stand-in models: an
ECHO that answers what the rule policy would (the flight must then be the
rule team's, knot for knot -- so the context, the reply, the tools and the
guardian change nothing by themselves); a model that answers garbage (one
correction, then the rule policy, every time, recorded); one that never
answers (the same, as a timeout); one that DISAGREES whenever it can (the tools
then really run, every command still through the guardian, nothing breaks);
and a REPLAY of a recorded flight (the same flight, offline, exactly).
"""

import dataclasses
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents import llm_tools as T  # noqa: E402
from agentic_uav.agents.llm_context import SYSTEM, render  # noqa: E402
from agentic_uav.coordination.keepout import KeepOutConfig  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import interventions, limits_kept, load_guardian, same_flight  # noqa: E402
from agentic_uav.experiments.llm import fly_llm_on_mock, load_llm, parse_llm  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.planners.llm_ask import EchoAsk, Recorder, ReplayAsk, request_key  # noqa: E402

SC = dataclasses.replace(load_scenario("search_relay_001"), random_seed=17)
FLY = {"guardian": load_guardian(), "keep_out": KeepOutConfig(5.0, 10.0, 3.0)}
CFG, HEALTH = load_allocation(), load_recovery()


def good(tool="continue_task", params=None, **extra):
    data = json.loads(T.reply_for(tool, params or {}))
    data.update(extra)
    return json.dumps(data)


class ReplyTests(unittest.TestCase):
    def test_a_good_reply(self):
        self.assertEqual(T.parse_reply(good("hold", {"duration_s": 10})), ("hold", {"duration_s": 10}, []))

    def test_every_way_a_reply_can_be_wrong_is_named_and_none_raises(self):
        cases = {
            "not json": "not JSON", "[]": "not one JSON object",
            good(extra=1): "unknown key 'extra'",
            good("send_bid"): "run for you by the protocol",
            good("report_target"): "not available in this mission",
            good("fly_to_moon"): "not one of the tools",
            good("hold", {}): "hold needs 'duration_s'",
            good("hold", {"duration_s": 5, "x": 1}): "hold has no parameter 'x'",
            good(confidence=2): "confidence must be a number from 0 to 1",
            good(reason_code="x" * 61): "short code",
            json.dumps({k: v for k, v in json.loads(good()).items() if k != "confidence"}): "missing 'confidence'",
            good(situation_assessment={"mission_progress": "ok"}): "situation_assessment must hold exactly",
        }
        for text, word in cases.items():
            with self.subTest(text=text[:40]):
                tool, params, problems = T.parse_reply(text)
                self.assertTrue(problems)
                self.assertIn(word, "; ".join(problems))

    def test_the_schema_offered_the_server_names_every_tool(self):
        s = T.reply_schema()
        self.assertEqual(set(s["required"]), set(T.TOP))
        self.assertEqual(s["properties"]["selected_tool"]["enum"], list(T.TOOLS))
        self.assertEqual(len(T.ACTIONS) + len(T.PROTOCOL) + len(T.NOT_YET), 16)
        self.assertEqual(set(T.PARAMS), set(T.ACTIONS))

    def test_the_system_prompt_lists_the_actions_and_asks_for_no_reasoning(self):
        for t in T.ACTIONS:
            self.assertIn(t, SYSTEM)
        self.assertIn("reason_code", SYSTEM)
        self.assertNotIn("chain of thought", SYSTEM.lower())


class ManifestTests(unittest.TestCase):
    def test_the_default_manifest(self):
        c = load_llm()
        self.assertEqual((c.model, c.options["temperature"], c.timeout_s), ("llama3.3:70b", 0, 60.0))

    def test_read_strictly(self):
        base = {"model": {"name": "m", "digest": ""}, "options": {"temperature": 0, "seed": 0, "num_ctx": 1,
                                                                    "num_predict": 1}, "call": {"timeout_s": 1}}
        self.assertEqual(parse_llm(base).model, "m")
        for bad in ({**base, "x": {}}, {**base, "options": {**base["options"], "temperature": 0.7}},
                    {**base, "model": {"name": "m"}}, {**base, "call": {"timeout_s": 0}},
                    {**base, "options": {**base["options"], "top_k": 1}}):
            with self.assertRaises(ValueError):
                parse_llm(bad)


class Scripted:
    """A stand-in model: a function of the request."""

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, request):
        self.calls += 1
        return self.fn(request)


def context_of(request):
    return json.loads(request["messages"][1]["content"])


class FlightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule = fly_recovery_on_mock(SC, CFG, HEALTH, "x", None, **FLY)
        cls.rule_stop = fly_recovery_on_mock(SC, CFG, HEALTH, "x", {"Drone1": 60.0}, **FLY)

    def fly(self, ask, stop=None):
        return fly_llm_on_mock(SC, CFG, HEALTH, ask, "x", stop, **FLY)

    def test_the_echo_flies_the_rule_teams_flight(self):
        for stop, rule in ((None, self.rule), ({"Drone1": 60.0}, self.rule_stop)):
            run, logs = self.fly(EchoAsk(), stop)
            self.assertEqual(same_flight(run, rule), [])
            for d, log in logs.items():
                self.assertGreater(log["decisions"]["llm"], 5)
                self.assertEqual(log["agreed"], log["decisions"]["llm"])

    def test_garbage_is_corrected_once_then_the_rule_decides(self):
        ask = Scripted(lambda r: "I think the drone should go north.")
        run, logs = self.fly(ask)
        self.assertEqual(same_flight(run, self.rule), [])
        model = [e for log in logs.values() for e in log["log"] if e["kind"] != "procedural"]
        self.assertTrue(model and all(e["kind"] == "fallback" and len(e["replies"]) == 2 for e in model))
        self.assertEqual(ask.calls, 2 * len(model))
        self.assertIn("not JSON", model[0]["problems"][0])

    def test_no_reply_is_a_fallback_recorded_as_such(self):
        def silent(request):
            raise TimeoutError("timed out")
        run, logs = self.fly(Scripted(silent))
        self.assertEqual(same_flight(run, self.rule), [])
        model = [e for log in logs.values() for e in log["log"] if e["kind"] != "procedural"]
        self.assertTrue(all(e["kind"] == "fallback" and e["problems"][0].startswith("no reply: TimeoutError")
                            for e in model))

    def test_a_correction_that_works_is_counted_as_one(self):
        seen = set()

        def once_wrong(request):
            key = request_key({"messages": request["messages"][:2]})
            if key not in seen:
                seen.add(key)
                return "{"
            return request["meta"]["rule_reply"]
        run, logs = self.fly(Scripted(once_wrong))
        self.assertEqual(same_flight(run, self.rule), [])
        kinds = {e["kind"] for log in logs.values() for e in log["log"]}
        self.assertEqual(kinds, {"procedural", "corrected"})

    def test_a_recorded_flight_replays_exactly_and_off_its_record_falls_back(self):
        rec = Recorder(EchoAsk())
        first, logs1 = self.fly(rec)
        again, logs2 = self.fly(ReplayAsk(rec.records))
        self.assertEqual(same_flight(again, first), [])
        self.assertEqual([e.get("prompt_digest") for log in logs1.values() for e in log["log"]],
                         [e.get("prompt_digest") for log in logs2.values() for e in log["log"]])
        run, logs = self.fly(ReplayAsk({}))
        model = [e for log in logs.values() for e in log["log"] if e["kind"] != "procedural"]
        self.assertTrue(all(e["kind"] == "fallback" and "LookupError" in e["problems"][0] for e in model))

    def test_a_model_that_disagrees_flies_through_the_tools_and_the_guardian(self):
        def contrary(request):
            rule = json.loads(request["meta"]["rule_reply"])
            options = [a for a in context_of(request)["actions"]
                       if (a["tool"], a["parameters"]) != (rule["selected_tool"], rule["parameters"])]
            pick = next((a for a in options if a["tool"] == "hold"), options[0] if options else None)
            if pick is None:
                return request["meta"]["rule_reply"]
            return T.reply_for(pick["tool"], pick["parameters"], "CONTRARY")
        run, logs = self.fly(Scripted(contrary))
        model = [e for log in logs.values() for e in log["log"] if e["kind"] in ("llm", "corrected")]
        self.assertGreater(sum(not e["agreed"] for e in model), 10)
        self.assertEqual(limits_kept(run, FLY["guardian"], SC), [])
        unreviewed = [e for e in interventions(run) if e["source"] == "direct"]
        self.assertEqual(unreviewed, [])
        reasons = [e.decision.reason for t in run.team.traces.values() for e in t if e.decision.reason.startswith("LLM")]
        self.assertTrue(reasons and all(r == "LLM CONTRARY" for r in reasons))

    def test_each_drone_is_told_only_its_own_state(self):
        contexts = {}

        def keep(request):
            contexts.setdefault(request["meta"]["drone"], []).append(context_of(request))
            return request["meta"]["rule_reply"]
        self.fly(Scripted(keep))
        self.assertEqual(sorted(contexts), ["Drone1", "Drone2", "Drone3", "Drone4"])
        for drone, ctxs in contexts.items():
            for c in ctxs:
                self.assertEqual(c["you"]["id"], drone)
                self.assertNotIn(drone, [m["id"] for m in c["teammates"]])
                self.assertEqual(set(c), {"you", "mission", "tasks", "teammates", "links", "now", "memory", "actions"})
                self.assertLessEqual(len(c["memory"]), 5)
                for m in c["teammates"]:              # what a teammate SAID, never its private state
                    self.assertLessEqual(set(m), {"id", "health", "role", "heard_s_ago", "last_position_m", "task"})
        sizes = [len(json.dumps(c)) for ctxs in contexts.values() for c in ctxs]
        self.assertLess(max(sizes), 6000)                 # summarized, not the raw log (12.4)

    def test_the_context_is_rendered_the_same_for_the_same_state(self):
        ctx = {"you": {"id": "Drone1"}, "memory": [{"at": 5.0, "tool": "hold", "s_ago": 1.0}], "actions": []}
        self.assertEqual(render(ctx), render(dict(reversed(list(ctx.items())))))
        self.assertNotIn('"at"', render(ctx)[1]["content"])


if __name__ == "__main__":
    unittest.main()
