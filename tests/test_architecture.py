#!/usr/bin/env python3
"""Tests for Phase 13: the architectures, chosen by configuration, flown by one harness.

    python -m unittest discover -s tests -p test_architecture.py

WHY THESE EXIST
---------------
AUV-13: four architectures differing "in exactly one dimension: how
coordination decisions are made". These hold each arm to what it claims, on a
real flight: C is Phase 9's team; D with an echo is C, and replayed from
Phase 12's record is Phase 12's flight; D with its model replaced by the
fallback is C; B starts from C's own first division and never sends a task
message, so a stopped drone's task is orphaned; A's every task comes from the
base controller, which reassigns a silent drone's; and each ablation's
mechanism is really off. And the configuration files themselves are read
strictly: a wrong key or an impossible combination is refused.
"""

import dataclasses
import json
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents.follower_policy import DISCONNECT_S, FollowerPolicy  # noqa: E402
from agentic_uav.agents.independent_policy import initial_division  # noqa: E402
from agentic_uav.control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M  # noqa: E402
from agentic_uav.coordination.keepout import KeepOutConfig  # noqa: E402
from agentic_uav.core.messages import MessageType  # noqa: E402
from agentic_uav.experiments import architecture as X  # noqa: E402
from agentic_uav.experiments.allocation import load_allocation  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian, same_flight  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.planners.llm_ask import EchoAsk, ReplayAsk  # noqa: E402

SC = load_scenario("search_relay_001")
ALLOC, HEALTH, LIMITS, KO = load_allocation(), load_recovery(), load_guardian(), KeepOutConfig(5.0, 10.0, 3.0)
STOP = {"Drone1": 60.0}
TASK_TYPES = {MessageType.TASK_ANNOUNCEMENT, MessageType.TASK_BID, MessageType.TASK_AWARD, MessageType.TASK_ACCEPT,
              MessageType.TASK_RELEASE, MessageType.TASK_COMPLETE}


def fly(name, stop=None, seed=17, ask=None):
    return X.fly_architecture(X.load_architecture(name), SC, seed, ALLOC, HEALTH, LIMITS, KO, stop,
                              ask=ask or EchoAsk())


def sent(run):
    seen, out = set(), []
    for d in run.team.deliveries:
        if d.message.message_id not in seen:
            seen.add(d.message.message_id)
            out.append(d.message)
    return out


class ConfigTests(unittest.TestCase):
    def test_every_file_loads_and_names_itself(self):
        names = X.all_architectures()
        self.assertTrue({"A", "B", "C", "D", "E"} <= set(names))
        self.assertEqual(len(names), 13)
        for n in names:
            self.assertEqual(X.load_architecture(n).name, n)

    def test_read_strictly_and_impossible_combinations_refused(self):
        base = {"architecture": {"name": "x", "description": "x", "team": "decentralized", "decider": "rules"}}
        self.assertEqual(X.parse_architecture(base).team, "decentralized")
        for bad in ({**base, "x": {}},
                    {"architecture": {**base["architecture"], "team": "swarm"}},
                    {"architecture": {**base["architecture"], "decider": "oracle"}},
                    {**base, "mechanisms": {"speed": True}},
                    {**base, "mechanisms": {"leases": "no"}},
                    {"architecture": {**base["architecture"], "team": "central", "decider": "llm"}},
                    {**base, "mechanisms": {"memory": False}},
                    {"architecture": {**base["architecture"], "team": "independent"}, "mechanisms": {"roles": False}},
                    {"architecture": {**base["architecture"], "team": "scripted"}, "mechanisms": {"link_inputs": True}}):
            with self.assertRaises(ValueError):
                X.parse_architecture(bad)

    def test_a_model_decider_needs_a_model(self):
        with self.assertRaises(ValueError):
            X.fly_architecture(X.load_architecture("D"), SC, 17, ALLOC, HEALTH, LIMITS, KO, None, ask=None)
        with self.assertRaises(ValueError):
            fly("E", STOP)


class ArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.c_stop = fly("C"), fly("C", STOP)

    def test_c_is_phase_9s_team(self):
        phase9 = fly_recovery_on_mock(dataclasses.replace(SC, random_seed=17), ALLOC, HEALTH, "no stop")
        self.assertEqual(same_flight(self.c.run, phase9), [])
        self.assertEqual(self.c.run.team_kind, "decentralized")

    def test_d_with_an_echo_and_d_without_its_model_are_c(self):
        for name, stop, c in (("D", None, self.c), ("D", STOP, self.c_stop), ("D-fallback", None, self.c),
                              ("D-fallback", STOP, self.c_stop)):
            with self.subTest(name=name, stop=bool(stop)):
                f = fly(name, stop)
                self.assertEqual(same_flight(f.run, c.run), [])
                kinds = {k for log in f.llm.values() for k in log["decisions"]}
                self.assertEqual(kinds, {"procedural", "fallback" if name == "D-fallback" else "llm"})

    def test_d_replayed_from_phase_12_is_phase_12s_flight(self):
        path = os.path.join(ROOT, "phases", "phase-12-llm-agent-policy", "results", "llm-exit-20261105-150453-exit.jsonl")
        with open(path, encoding="utf-8") as h:
            rec = {(r["seed"], r["flight"]): r for r in map(json.loads, h) if r["kind"] == "flight"}
        r12 = rec[(1, "no stop")]
        f = fly("D", None, seed=1, ask=ReplayAsk(r12["records"]))
        self.assertEqual(json.loads(json.dumps(f.run.executed, default=str)), r12["executed"])
        self.assertEqual([[e.get("prompt_digest") for e in log["log"]] for log in f.llm.values()],
                         [[e.get("prompt_digest") for e in log["log"]] for log in r12["llm"].values()])

    def test_b_starts_from_cs_division_and_never_sends_a_task_message(self):
        heights = {v.id: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, v in enumerate(SC.vehicles)}
        division = initial_division(SC.brief(), ALLOC, heights)
        self.assertEqual({d: s[0] for d, s in self.c.run.searched.items()}, division)
        b, b_stop = fly("B"), fly("B", STOP)
        self.assertEqual(b.run.team_kind, "independent")
        for f in (b, b_stop):
            self.assertFalse(any(m.message_type in TASK_TYPES for m in sent(f.run)))
        self.assertTrue(b.run.met)
        self.assertFalse(b_stop.run.met)                     # the stopped drone's sector is never searched
        self.assertNotIn("search S3", [t for ts in b_stop.run.searched.values() for t in ts])
        for d, task in division.items():                     # each drone reports its own task as its own
            self.assertTrue(any(m.message_type is MessageType.STATUS_UPDATE and m.sender_id == d
                                and m.payload["task"] == task for m in sent(b.run)), d)

    def test_bs_division_takes_the_best_bid_first(self):
        # From a lopsided start (Drone1 far east), so a symmetric layout cannot hide the order.
        from agentic_uav.coordination.bids import Bidder, bid_for
        from agentic_uav.coordination.tasks import tasks_from_brief
        brief = SC.brief()
        brief = dataclasses.replace(brief, vehicles=tuple(
            dataclasses.replace(v, start_x=v.start_x + 150.0) if v.id == "Drone1" else v for v in brief.vehicles))
        heights = {v.id: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, v in enumerate(SC.vehicles)}
        bids = []
        for v in brief.vehicles:
            bidder = Bidder(v.id, v.start_x, v.start_y, brief.battery.capacity, (v.start_x, v.start_y),
                            brief.mission.deadline_s, heights[v.id], 5.0)
            for t in tasks_from_brief(brief):
                bid = bid_for(t, bidder, brief, ALLOC.weights)
                if bid.eligible:
                    bids.append((bid.value, v.id, t.task_id))
        division = initial_division(brief, ALLOC, heights)
        best = min(bids)                                     # a bid's value is a cost: lowest first (bids.py)
        self.assertEqual(division[best[1]], best[2])
        # Best-first's guarantee: every pair left out lost to its drone's or its task's own award, at a cost no
        # higher than its own (worst-first breaks this).
        cost = {(d, t): round(v, 6) for v, d, t in bids}
        by_drone = {d: cost[(d, t)] for d, t in division.items()}
        by_task = {t: cost[(d, t)] for d, t in division.items()}
        for (d, t), c in cost.items():
            if division.get(d) != t:
                self.assertLessEqual(min(by_drone.get(d, float("inf")), by_task.get(t, float("inf"))), c, (d, t))

    def test_a_takes_every_task_from_the_base_which_reassigns_a_silent_drones(self):
        a, a_stop = fly("A"), fly("A", STOP)
        self.assertEqual(a.run.team_kind, "central")
        for f in (a, a_stop):
            drone_task = [m for m in sent(f.run) if m.message_type in TASK_TYPES - {MessageType.TASK_COMPLETE}
                          and m.sender_id != "base"]
            self.assertEqual(drone_task, [])
            awards = {(m.recipient_ids[0], m.payload["task_id"]) for m in sent(f.run)
                      if m.message_type is MessageType.TASK_AWARD and m.sender_id == "base"}
            flown = {(d, t) for d, ts in f.run.searched.items() for t in ts}
            self.assertTrue(flown <= awards, flown - awards)
        self.assertTrue(a.run.met and a_stop.run.met)
        log = a_stop.run.controller["log"]
        self.assertTrue(any(e["what"] == "reassigned" and e["from"] == "Drone1" for e in log))

    def test_e_is_phase_4s_preflight_plan(self):
        e = fly("E")
        self.assertTrue(e.run.met)
        self.assertEqual(e.llm, {})


class AblationTests(unittest.TestCase):
    def test_no_leases_leaves_a_silent_drones_task_with_it(self):
        f = fly("D-no-leases", STOP)
        self.assertFalse(f.run.met)
        books = [p for p in f.run.policies.values()]
        self.assertFalse(any("lease ran out" in json.dumps(p) for p in books))

    def test_no_roles_sends_no_role_change_and_keeps_no_reserve(self):
        f, d = fly("D-no-roles", STOP), fly("D", STOP)
        self.assertFalse(any(m.message_type is MessageType.ROLE_CHANGE for m in sent(f.run)))
        self.assertTrue(any(m.message_type is MessageType.ROLE_CHANGE for m in sent(d.run)))

        def reserves(run):
            return [e.at for t in run.team.traces.values() for e in t if e.decision.objective == "stand by as a reserve"]
        self.assertEqual(reserves(f.run), [])
        self.assertTrue(reserves(fly("D").run) or reserves(d.run))   # with roles, a drone does stand by

    def test_the_entry_point_passes_every_switch_to_the_harness(self):
        from unittest import mock
        seen = {}

        def spy(*args, **kwargs):
            seen.clear()
            seen.update(kwargs)
            return types.SimpleNamespace()
        net = object()
        with mock.patch.object(X, "fly_recovery_on_mock", spy):
            X.fly_architecture(X.load_architecture("C"), SC, 17, ALLOC, HEALTH, LIMITS, KO, None, network=net)
            self.assertEqual((seen["guardian"], seen["keep_out"], seen["network"], seen["leases"], seen["roles"],
                              seen["link_inputs"], seen["team"]), (LIMITS, KO, net, True, True, False, "decentralized"))
            off = X.Architecture("all-off", "every switch flipped", "decentralized", "rules", leases=False, roles=False,
                                 guardian=False, keep_out=False, link_inputs=True, perfect_comms=True)
            X.fly_architecture(off, SC, 17, ALLOC, HEALTH, LIMITS, KO, None, network=net)
            self.assertEqual((seen["guardian"], seen["keep_out"], seen["network"], seen["leases"], seen["roles"],
                              seen["link_inputs"]), (None, None, None, False, False, True))
            X.fly_architecture(X.load_architecture("A"), SC, 17, ALLOC, HEALTH, LIMITS, KO, None)
            self.assertEqual(seen["team"], "central")

    def test_no_memory_tells_the_model_no_past(self):
        contexts = []

        def keep(request):
            contexts.append(json.loads(request["messages"][1]["content"]))
            return request["meta"]["rule_reply"]
        fly("D-no-memory", None, ask=keep)
        self.assertTrue(contexts and all(c["memory"] == [] for c in contexts))

    def test_no_guardian_has_none(self):
        self.assertEqual(fly("C-no-guardian").run.guardians, {})
        self.assertEqual(set(fly("C").run.guardians), {"Drone1", "Drone2", "Drone3", "Drone4"})

    def test_link_inputs_keep_estimates_and_change_nothing(self):
        f = fly("C-link-inputs")
        self.assertEqual(same_flight(f.run, fly("C").run), [])
        links = [e.belief["communication"].get("links") for t in f.run.team.traces.values() for e in t]
        self.assertTrue(any(links))

    def test_perfect_comms_ignores_a_degraded_network(self):
        from agentic_uav.experiments.conditions import load_network
        severe = load_network("severe").seeded(17)
        perfect = X.fly_architecture(X.load_architecture("D-perfect-comms"), SC, 17, ALLOC, HEALTH, LIMITS, KO, None,
                                     network=severe, ask=EchoAsk())
        self.assertEqual(same_flight(perfect.run, fly("D").run), [])
        degraded = X.fly_architecture(X.load_architecture("D"), SC, 17, ALLOC, HEALTH, LIMITS, KO, None,
                                      network=load_network("severe").seeded(17), ask=EchoAsk())
        self.assertNotEqual(same_flight(degraded.run, fly("D").run), [])     # the network does change D's flight

    def test_a_follower_without_the_base_goes_home_after_its_task(self):
        from agentic_uav.agents.belief_state import BeliefState, Observation
        p = FollowerPolicy(altitude_m=12.0)
        b = BeliefState.start(SC.brief(), "Drone1", Observation(0.0, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None))
        b.update(Observation(20.0, 60.0, -40.0, 12.0, True, 90.0, (), True, None, 0, None))
        p._joined_at = 0.0
        b.links["base"] = {"last_heard": 20.0 - DISCONNECT_S - 1}
        d = p._next(b, "held")
        self.assertTrue(p.disconnected)
        self.assertEqual(d.objective, "return home and report")
        b.links["base"] = {"last_heard": 19.0}
        p2 = FollowerPolicy(altitude_m=12.0)
        p2._joined_at = 0.0
        self.assertEqual(p2._next(b, "held").objective, "wait for a task")


if __name__ == "__main__":
    unittest.main()
