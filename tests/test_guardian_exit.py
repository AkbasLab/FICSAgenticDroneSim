#!/usr/bin/env python3
"""Tests for Phase 11's exit: the injections, the injector, and each exit check (step 5).

    python -m unittest discover -s tests -p test_guardian_exit.py

WHY THESE EXIST
---------------
The exit says the guardian stops every injected command. That is only worth
something if (a) the schedule really covers every check, through both
channels; (b) each injection is really made, as described; and (c) each
check really fails when what it watches goes wrong. (c) is tested here by
planting the failure in a flown record -- an injection never made, logged with
the wrong outcome, its command started after all, a trajectory over a limit,
a clean flight that differs -- and seeing the check say so.
"""

import copy
import dataclasses
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.decision import Decision, DecisionKind  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.events import Event, Trigger  # noqa: E402
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.experiments import guardian_exit as X  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.recovery import load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.safety import guardian as g  # noqa: E402
from agentic_uav.simulator.trajectory import Knot, Trajectory  # noqa: E402

SCENARIO = load_scenario("search_relay_001")
LIMITS = X.load_guardian()
BOX = g.operating_box(SCENARIO.brief(), LIMITS.fence_margin_m)
FEW = tuple(i for i in X.INJECTIONS if i.name in ("rule-zone", "rule-altitude-high", "rule-fallback", "rule-bypass",
                                                  "llm-nan", "llm-stale"))


class ScheduleTests(unittest.TestCase):
    def test_thirty_three_named_once(self):
        self.assertEqual(len(X.INJECTIONS), 33)
        self.assertEqual(len({i.name for i in X.INJECTIONS}), 33)
        self.assertTrue(all(i.name.startswith(i.channel + "-") for i in X.INJECTIONS))

    def test_every_check_is_injected_and_both_channels_meet_every_check_they_can(self):
        by = {c: {i.check for i in X.INJECTIONS if i.channel == c} for c in X.CHANNELS}
        self.assertEqual(by["rule"] | by["llm"], set(g.CHECKS))
        # A rule policy hands back objects, never text; an LLM's NaN is caught reading it, as text.
        self.assertEqual(set(g.CHECKS) - by["rule"], {"proposal"})
        self.assertEqual(set(g.CHECKS) - by["llm"], {"waypoint"})

    def test_every_outcome_but_approve_is_expected_on_both_channels(self):
        for c in X.CHANNELS:
            self.assertEqual({i.outcome for i in X.INJECTIONS if i.channel == c}, {g.MODIFY, g.REJECT, g.FALLBACK})

    def test_styles_and_drones(self):
        self.assertEqual({i.style for i in X.INJECTIONS}, {"mutate", "substitute", "repeat", "direct", "conflict"})
        self.assertEqual({i.drone for i in X.INJECTIONS}, {v.id for v in SCENARIO.vehicles})
        self.assertTrue(all(i.outcome == g.FALLBACK for i in X.INJECTIONS if i.style == "repeat"))
        mutations = {i.name for i in X.INJECTIONS if i.style == "mutate"}
        self.assertEqual(mutations - set(X.TAKE_OFF_MUTATIONS) - set(X.SEARCH_MUTATIONS), {"rule-timeout", "llm-stale"})

    def test_a_region_stretched_past_the_fence_reaches_ten_metres_out(self):
        for s in SCENARIO.brief().sectors:
            r = X._stretched(s.region, BOX)
            over = max(BOX.x_min - r.x_min, r.x_max - BOX.x_max, BOX.y_min - r.y_min, r.y_max - BOX.y_max)
            self.assertAlmostEqual(over, X.OUTSIDE_BY_M)
            self.assertEqual(g.modify(S.SearchRegionCommand(region=r), LIMITS, BOX)[2], [])


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


class Inner:
    def __init__(self, decision):
        self.decision, self.asked = decision, 0

    def decide(self, belief, events):
        self.asked += 1
        return self.decision


class Me:
    def __init__(self, airborne=True):
        self.self_ = type("S", (), {"x": 60.0, "y": -40.0, "airborne": airborne})()
        self.team = type("T", (), {"members": {}})()


def injector(name, decision, channel=False):
    inj = next(i for i in X.INJECTIONS if i.name == name)
    clock = Clock()
    return X.Injector(inj, Inner(decision), clock, 0.0, BOX, 12.0, channel), clock


class InjectorTests(unittest.TestCase):
    TAKE = Decision.start(S.TakeOffCommand(altitude_m=12.0), "take off", "r")
    PERIODIC = (Event(Trigger.PERIODIC, 0.0),)

    def test_a_mutation_waits_for_a_fitting_decision_then_fires_once(self):
        inj, clock = injector("rule-altitude-high", Decision.carry_on())
        self.assertEqual(inj.decide(Me(False), ()).kind, DecisionKind.CONTINUE)
        self.assertIsNone(inj.record)
        inj.inner.decision = self.TAKE
        self.assertEqual(inj.decide(Me(False), ()).command.altitude_m, 60.0)
        self.assertEqual(inj.record["command"]["command"]["altitude_m"], 60.0)
        clock.t = 1.0
        self.assertEqual(inj.decide(Me(False), ()).command.altitude_m, 12.0)     # once only

    def test_a_substitution_waits_for_its_time_and_the_air(self):
        inj, clock = injector("rule-zone", self.TAKE)
        clock.t = 39.5
        self.assertIs(inj.decide(Me(), ()), self.TAKE)
        clock.t = 40.0
        self.assertIs(inj.decide(Me(False), ()), self.TAKE)                      # on the ground: not yet
        got = inj.decide(Me(), ())
        self.assertEqual(got.command.waypoint, Waypoint(25.0, 0.0, 12.0))
        self.assertEqual(inj.inner.asked, 2)                                      # not asked when substituted

    def test_a_repeat_is_the_same_at_every_ask_of_one_quiet_decision(self):
        inj, clock = injector("rule-fallback", self.TAKE)
        clock.t = 80.0
        self.assertIs(inj.decide(Me(), (Event(Trigger.SKILL_SUCCEEDED, 80.0),)), self.TAKE)   # not quiet
        first = inj.decide(Me(), self.PERIODIC)
        again = [inj.decide(Me(), self.PERIODIC + (Event(Trigger.GUARD_REJECTED, 80.0),)) for _ in range(3)]
        self.assertTrue(all(a == first for a in again))
        clock.t = 80.5
        self.assertIs(inj.decide(Me(), self.PERIODIC), self.TAKE)

    def test_on_the_llm_channel_every_decision_is_text_read_back(self):
        inj, clock = injector("llm-nan", self.TAKE, channel=True)
        back = inj.decide(Me(), ())
        self.assertEqual((back.command, back.issued_at), (self.TAKE.command, 0.0))
        self.assertIsNotNone(back.raw)
        clock.t = 40.0
        bad = inj.decide(Me(), ())
        self.assertEqual(bad.kind, DecisionKind.INVALID)
        self.assertIn("NaN", bad.raw)
        self.assertIsNone(inj.record["command"])

    def test_a_late_answer_carries_when_it_was_asked(self):
        inj, clock = injector("llm-stale", self.TAKE, channel=True)
        clock.t = 41.0
        got = inj.decide(Me(), ())
        self.assertEqual((got.command, got.issued_at), (self.TAKE.command, 41.0 - X.STALE_BY_S))


class FlownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flights = X.guardian_flights(SCENARIO, 17, load_allocation(), load_recovery(), LIMITS, FEW)
        cls.checks = X.exit_checks(cls.flights, LIMITS, SCENARIO)

    def test_the_exit_holds_on_these(self):
        self.assertTrue(self.checks["all"], {k: v["problems"] for k, v in self.checks.items() if k != "all"})
        self.assertEqual((self.checks["injections_stopped"]["made"], self.checks["limits_kept"]["flights"]), (6, 8))

    def test_findings_name_what_the_guardian_did(self):
        f = X.injection_findings(self.flights)
        self.assertEqual(f["rule-zone"]["outcome"], g.REJECT)
        self.assertEqual(f["rule-altitude-high"]["outcome"], g.MODIFY)
        self.assertEqual(f["rule-fallback"]["fallback"], g.CONTINUE_LAST_VALID_PLAN)
        self.assertTrue(all(x["met"] for x in f.values()))

    def test_what_followed_an_injection_is_a_knock_on_even_at_its_instant(self):
        inj, run, record = self.flown("rule-zone")
        own = X.own_entries(run, record, inj)
        self.assertEqual([e["outcome"] for e in own], [g.REJECT])
        fallback = next(i for i in FEW if i.name == "rule-fallback")
        frun, frec = self.flights["injected"]["rule-fallback"]
        self.assertEqual([e["outcome"] for e in X.own_entries(frun, frec, fallback)], [g.REJECT] * 3 + [g.FALLBACK])
        guardians = copy.deepcopy(run.guardians)
        later = dict(own[0], outcome=g.REJECT, checks=["landing_site"], reasons=["the policy's own answer"])
        guardians[inj.drone]["log"].append(later)
        flights = dict(self.flights, injected=dict(self.flights["injected"],
                                                    **{"rule-zone": (dataclasses.replace(run, guardians=guardians), record)}))
        f = X.injection_findings(flights)["rule-zone"]
        self.assertEqual([k["checks"] for k in f["knock_on"]], [["landing_site"]])
        self.assertEqual((f["outcome"], f["checks"]), (g.REJECT, ["restricted_zone"]))

    def flown(self, name):
        inj = next(i for i in FEW if i.name == name)
        run, record = self.flights["injected"][name]
        return inj, run, copy.deepcopy(record)

    def test_never_made_is_caught(self):
        inj, run, _ = self.flown("rule-zone")
        self.assertIn("never made", X.stopped(run, None, inj)[0])

    def test_the_wrong_outcome_or_check_is_caught(self):
        inj, run, record = self.flown("rule-zone")
        log = copy.deepcopy(run.guardians)
        entry = next(e for e in log[inj.drone]["log"] if abs(e["at"] - round(record["at"], 3)) <= 1e-6)
        entry["outcome"], entry["checks"] = g.MODIFY, ["speed"]
        problems = X.stopped(dataclasses.replace(run, guardians=log), record, inj)
        self.assertTrue(any("expected reject_and_replan" in p for p in problems))
        self.assertTrue(any("expected restricted_zone" in p for p in problems))

    def test_an_injected_command_that_started_is_caught(self):
        for name in ("rule-zone", "rule-bypass", "llm-stale"):
            inj, run, record = self.flown(name)
            if record["command"] is None:
                continue
            executed = copy.deepcopy(run.executed)
            executed[inj.drone].append({"serial": 99, "started_at": record["at"], **record["command"]})
            problems = X.stopped(dataclasses.replace(run, executed=executed), record, inj)
            if inj.check == "timeout":
                self.assertEqual(problems, [])                  # its own command again, on fresh news
            else:
                self.assertTrue(any("started" in p for p in problems), name)

    def test_a_nan_that_started_would_still_be_recognised(self):
        self.assertTrue(X._eq({"x": math.nan, "y": [1.0]}, {"x": math.nan, "y": [1.0]}))
        self.assertFalse(X._eq({"x": math.nan}, {"x": 1.0}))

    def test_a_modification_that_never_flew_is_caught(self):
        inj, run, record = self.flown("rule-altitude-high")
        executed = copy.deepcopy(run.executed)
        executed[inj.drone] = [x for x in executed[inj.drone] if x["command"].get("altitude_m") != 40.0]
        problems = X.stopped(dataclasses.replace(run, executed=executed), record, inj)
        self.assertTrue(any("ran instead never started" in p for p in problems))

    def test_the_agent_acting_on_a_refused_decision_is_caught(self):
        inj, run, record = self.flown("rule-zone")
        traces = dict(run.team.traces)
        traces[inj.drone] = tuple(dataclasses.replace(e, action="started GO_TO_WAYPOINT #9")
                                  if abs(e.at - record["at"]) <= 1e-6 else e for e in traces[inj.drone])
        team = dataclasses.replace(run.team, traces=traces)
        problems = X.stopped(dataclasses.replace(run, team=team), record, inj)
        self.assertTrue(any("the agent did" in p for p in problems))

    def test_a_traced_decision_other_than_the_injected_one_is_caught(self):
        inj, run, record = self.flown("rule-zone")
        traces = dict(run.team.traces)
        traces[inj.drone] = tuple(dataclasses.replace(e, decision=Decision.carry_on(reason="something else"))
                                  if abs(e.at - record["at"]) <= 1e-6 else e for e in traces[inj.drone])
        team = dataclasses.replace(run.team, traces=traces)
        problems = X.stopped(dataclasses.replace(run, team=team), record, inj)
        self.assertTrue(any("not the one injected" in p for p in problems))

    def test_a_bypass_the_handle_let_through_is_caught(self):
        inj, run, record = self.flown("rule-bypass")
        record["refused"] = False
        self.assertTrue(any("let it start" in p for p in X.stopped(run, record, inj)))

    def test_limits_broken_in_flight_are_caught(self):
        run = self.flights["clean"]
        t = run.team.trajectories["Drone1"]
        k = list(t.knots)
        for knots, word in ((k + [Knot(k[-1].t + 10, 60.0, -40.0, 45.0, True)], "above"),
                            (k + [Knot(k[-1].t + 100, 60.0, -150.0, 12.0, True)], "outside the fence"),
                            (k + [Knot(k[-1].t + 1, k[-1].x + 20.0, k[-1].y, k[-1].altitude_m, k[-1].airborne)], "over"),
                            (k[:-1] + [Knot(k[-1].t + 40, 100.0, -40.0, 0.0, False)], "landed at")):
            trajs = dict(run.team.trajectories)
            trajs["Drone1"] = Trajectory("Drone1", knots)
            bad = dataclasses.replace(run, team=dataclasses.replace(run.team, trajectories=trajs))
            with self.subTest(word=word):
                self.assertTrue(any(word in p for p in X.limits_kept(bad, LIMITS, SCENARIO)))

    def test_a_clean_flight_unlike_phase_9_is_caught(self):
        clean = self.flights["clean"]
        policies = copy.deepcopy(clean.policies)
        policies["Drone1"]["changed"] = True
        self.assertIn("the drones' records differ",
                      X.same_flight(dataclasses.replace(clean, policies=policies), self.flights["phase9"]))
        self.assertEqual(X.same_flight(self.flights["channel"], clean), [])

    def test_an_intervention_in_a_clean_flight_is_caught(self):
        guardians = copy.deepcopy(self.flights["clean"].guardians)
        guardians["Drone2"]["log"].append({"drone": "Drone2", "outcome": g.REJECT, "at": 1.0, "reasons": ["x"]})
        flights = dict(self.flights, clean=dataclasses.replace(self.flights["clean"], guardians=guardians))
        checks = X.exit_checks(flights, LIMITS, SCENARIO)
        self.assertFalse(checks["no_interventions"]["ok"])
        self.assertFalse(checks["all"])


class ScriptTests(unittest.TestCase):
    def test_writes_its_record_and_says_met(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import guardian_exit as script
        out = tempfile.mkdtemp()
        try:
            code = script.main(["--seeds", "17", "--only", "rule-zone,llm-two-commands", "--out", out, "--block", "t"])
            self.assertEqual(code, 0)
            names = sorted(os.listdir(out))
            self.assertEqual([n.rsplit(".", 1)[1] for n in names], ["jsonl", "md"])
            with open(os.path.join(out, names[0]), encoding="utf-8") as h:
                rows = [json.loads(line) for line in h]
            header = rows[0]
            self.assertTrue(header["exit_criterion_met"])
            self.assertEqual([i["name"] for i in header["injections"]], ["rule-zone", "llm-two-commands"])
            self.assertEqual(header["findings"]["llm-two-commands"]["as_expected"], 1)
            self.assertEqual(header["limits"], LIMITS.as_json())
            self.assertEqual([r["flight"] for r in rows if r["kind"] == "records"],
                             ["clean", "clean, LLM", "rule-zone", "llm-two-commands"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_an_unknown_injection_is_refused(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import guardian_exit as script
        with self.assertRaises(SystemExit):
            script.main(["--only", "rule-nothing", "--out", tempfile.gettempdir()])


if __name__ == "__main__":
    unittest.main()
