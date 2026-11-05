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
            # Agreeing, it runs the rule's own path -- the rule's reasons, every one, not a tool's "LLM ...".
            self.assertEqual([(d, e.at, e.decision.reason) for d, t in run.team.traces.items() for e in t],
                             [(d, e.at, e.decision.reason) for d, t in rule.team.traces.items() for e in t])
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
                self.assertIn("flying_now", c["you"])
                self.assertLessEqual(len(c["memory"]), 5)
                for m in c["teammates"]:              # what a teammate SAID, never its private state
                    self.assertLessEqual(set(m), {"id", "health", "role", "heard_s_ago", "last_position_m", "task"})
        sizes = [len(json.dumps(c)) for ctxs in contexts.values() for c in ctxs]
        self.assertLess(max(sizes), 6000)                 # summarized, not the raw log (12.4)

    def test_the_menu_never_offers_a_restart_or_an_idle(self):
        # bench1 (2026-11-05): offered while searching, start_search was read as "keep searching" by the 70B
        # (105 of 200) -- executed it restarts the search; and continue_task was taken with nothing flying.
        seen = []

        def keep(request):
            seen.append(context_of(request))
            return request["meta"]["rule_reply"]
        self.fly(Scripted(keep))
        offered = lambda c, tool: any(a["tool"] == tool for a in c["actions"])
        searching = [c for c in seen if c["you"]["stage"] == "searching" and c["you"]["flying_now"] == "SEARCH_REGION"]
        idle = [c for c in seen if c["you"]["flying_now"] is None]
        self.assertTrue(searching and idle)
        self.assertFalse(any(offered(c, "start_search") or offered(c, "accept_task") for c in searching))
        self.assertTrue(all(offered(c, "continue_task") for c in searching))
        self.assertFalse(any(offered(c, "continue_task") for c in idle))

    def test_the_context_is_rendered_the_same_for_the_same_state(self):
        ctx = {"you": {"id": "Drone1"}, "memory": [{"at": 5.0, "tool": "hold", "s_ago": 1.0}], "actions": []}
        self.assertEqual(render(ctx), render(dict(reversed(list(ctx.items())))))
        self.assertNotIn('"at"', render(ctx)[1]["content"])


    def test_a_reply_that_parses_but_is_not_possible_now_is_corrected_then_falls_back(self):
        def impossible(request):
            return T.reply_for("act_as_relay", {"teammate": "Drone9"})
        run, logs = self.fly(Scripted(impossible))
        self.assertEqual(same_flight(run, self.rule), [])
        model = [e for log in logs.values() for e in log["log"] if e["kind"] != "procedural"]
        self.assertTrue(model and all(e["kind"] == "fallback" and "is not unreachable" in e["problems"][0] for e in model))

    def test_each_drones_memory_is_its_own_last_decisions(self):
        seen = {}

        def keep(request):
            seen.setdefault(request["meta"]["drone"], []).append(context_of(request))
            return request["meta"]["rule_reply"]
        run, logs = self.fly(Scripted(keep))
        for drone, ctxs in seen.items():
            own = [e for e in logs[drone]["log"] if e["kind"] in ("llm", "corrected")]
            for i, c in enumerate(ctxs):
                self.assertEqual([m["tool"] for m in c["memory"]], [e["tool"] for e in own[:i]][-5:])


class UnitTests(unittest.TestCase):
    def belief(self, airborne=True):
        from agentic_uav.agents.belief_state import BeliefState, Observation
        brief = SC.brief()
        b = BeliefState.start(brief, "Drone1", Observation(10.0, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None))
        b.update(Observation(10.0, 60.0, -40.0, 12.0 if airborne else 0.0, airborne, 90.0, (), True, None, 0, None))
        return b

    def policy(self):
        from agentic_uav.agents.recovery_policy import RecoveryPolicy
        from agentic_uav.coordination.contract_net import ContractNet
        from agentic_uav.coordination.tasks import tasks_from_brief
        return RecoveryPolicy(ContractNet("Drone1", tasks_from_brief(SC.brief()), CFG), HEALTH, altitude_m=12.0)

    def test_task_actions_need_a_task_held(self):
        p, b = self.policy(), self.belief()
        for tool in ("accept_task", "start_search", "release_task"):
            self.assertIn("holds no task", T.check(tool, {"task_id": "search S1"}, p, b)[0])

    def test_a_hold_is_from_1_to_30_seconds(self):
        p, b = self.policy(), self.belief()
        self.assertEqual(T.check("hold", {"duration_s": 10}, p, b), [])
        for bad in (0, 31, True, "10"):
            self.assertTrue(T.check("hold", {"duration_s": bad}, p, b), bad)

    def test_on_the_ground_every_decision_is_procedure(self):
        from agentic_uav.agents.llm_policy import LLMPolicy
        from agentic_uav.core.events import Event, Trigger
        pol = LLMPolicy(self.policy(), EchoAsk())
        pol.inner.stage = __import__("agentic_uav.agents.rule_policy", fromlist=["Stage"]).Stage.SEARCHING
        events = (Event(Trigger.PERIODIC, 10.0),)
        self.assertTrue(pol._procedural(self.belief(airborne=False), events, 10.0))
        self.assertFalse(pol._procedural(self.belief(airborne=True), events, 10.0))

    def test_the_rules_relay_is_said_as_a_relay(self):
        import types
        from agentic_uav.agents.decision import Decision
        from agentic_uav.control.skills import HoldPositionCommand
        p = self.policy()
        p.detector = types.SimpleNamespace(in_state=lambda *h: ("Drone3",))
        d = Decision.start(HoldPositionCommand(duration_s=5.0), "relay toward Drone3", "r")
        self.assertEqual(T.rule_tool(d, p), ("act_as_relay", {"teammate": "Drone3"}))

    def test_a_replay_gives_the_replies_in_their_recorded_order(self):
        req = {"messages": [{"role": "user", "content": "x"}], "meta": {}}
        ask = ReplayAsk({request_key(req): ["a", "b"]})
        self.assertEqual((ask(req), ask(req)), ("a", "b"))
        with self.assertRaises(LookupError):
            ask(req)


if __name__ == "__main__":
    unittest.main()
