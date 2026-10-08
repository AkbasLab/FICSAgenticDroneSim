"""Phase 12.5 tests: the deterministic calculators the model leans on instead of
doing arithmetic. The most important test is the validity one - the tools and
the SafetyGuardian must agree on every point, because if they ever disagree one
of them is wrong, and a "repaired" point the guardian then blocks would be worse
than no repair at all.
"""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import MissionBelief, Provenance, SelfState, TeammateRecord
from fics_drone.agents.decision_schema import decision_json
from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.llm_policy import LLMAgentPolicy, make_policy_factory
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.reasoning_tools import ReasoningTools
from fics_drone.agents.safety_guardian import Command, GuardianOutcome, SafetyGuardian, SafetyLimits
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.waypoint_probe import make_situation, run_probe
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
NFZ1 = (-10.0, 10.0, 45.0, 60.0)   # x_min, x_max, y_min, y_max (world)


def _scenario():
    return load_scenario(SCENARIO_PATH)


def _belief(pos=(0.0, 0.0, 8.0), battery_s=300.0, elapsed_s=0.0, teammates=None):
    b = Belief(self_state=SelfState(position=pos, elapsed_s=elapsed_s, battery_s=battery_s),
               mission=MissionBelief(sector_id="C", search_queue=[]))
    b.phase, b.listen_rounds = "listening", 1
    for name, p in (teammates or {}).items():
        b.team.teammates[name] = TeammateRecord(name, (p[0], p[1], 8.0), Provenance(timestamp=0.0, source="heartbeat"))
    return b


def _tools(offset=(0.0, 0.0, 0.0), speed=5.0):
    return ReasoningTools(_scenario(), spawn_offset=offset, speed_mps=speed)


def _wp(x, y):
    return decision_json("go_to_waypoint", "search_elsewhere", x=x, y=y)


class TestGeometry(unittest.TestCase):
    def test_distance_and_travel_time(self):
        t = _tools(speed=5.0)
        self.assertAlmostEqual(t.distance((0, 0), (3, 4)), 5.0)
        self.assertAlmostEqual(t.travel_time_s((0, 0), (30, 40)), 10.0)

    def test_own_world_applies_the_spawn_offset(self):
        t = _tools(offset=(20.0, 5.0, 0.0))
        self.assertEqual(t.own_world(_belief(pos=(1.0, 2.0, 8.0))), (21.0, 7.0))

    def test_separation_risk_names_the_nearest_known_teammate(self):
        t = _tools()
        b = _belief(teammates={"D1": (10, 0), "D2": (3, 4)})
        self.assertEqual(t.separation_risk(b, (0, 0)), ("D2", 5.0))
        self.assertEqual(t.separation_risk(_belief(), (0, 0)), (None, None))

    def test_unknown_teammate_positions_are_ignored_not_treated_as_the_origin(self):
        t = _tools()
        b = _belief()
        b.team.teammates["D1"] = TeammateRecord("D1", None, Provenance(timestamp=0.0, source="mission_start"))
        self.assertEqual(t.separation_risk(b, (0, 0)), (None, None))


class TestFeasibility(unittest.TestCase):
    def test_battery_counts_the_return_leg(self):
        """210 m out fits one-way (52 s) but not there-and-back (105 s) in a 100 s budget."""
        t = _tools(speed=5.0)
        b = _belief(battery_s=100.0)
        one_way = t.travel_time_s((0, 0), (210, 0)) * 1.25
        self.assertLess(one_way, 100.0)
        ok, needed = t.battery_sufficient(b, (210, 0))
        self.assertFalse(ok)
        self.assertGreater(needed, 100.0)
        self.assertTrue(t.battery_sufficient(b, (150, 0))[0])

    def test_comms_reachable_via_base_or_a_teammate(self):
        t = _tools()
        rng = t.scenario.comms_range_m
        self.assertTrue(t.comms_reachable(_belief(), (rng - 1, 0)))
        self.assertFalse(t.comms_reachable(_belief(), (rng + 40, 0)))
        far = (rng + 40, 0)
        self.assertTrue(t.comms_reachable(_belief(teammates={"D1": (rng + 30, 0)}), far))

    def test_task_cost_is_the_same_deterministic_bid_the_allocator_uses(self):
        from fics_drone.coordination.bidding import compute_bid
        t, s = _tools(), _scenario()
        b = _belief(pos=(5.0, 5.0, 8.0), elapsed_s=30.0)
        expected = compute_bid((5.0, 5.0, 0.0), b.battery_frac_remaining, 0, s.sector("A"))
        self.assertAlmostEqual(t.task_cost(b, "A"), expected)

    def test_route_feasible_names_the_failed_checks_in_the_guardians_words(self):
        t = _tools()
        nfz = t.route_feasible(_belief(), (0, 52))
        self.assertFalse(nfz.legal)
        self.assertIn("restricted_zones", nfz.failed_checks)
        self.assertTrue(any(r.startswith("restricted_zones:") for r in nfz.reasons))
        near = t.route_feasible(_belief(teammates={"Drone2": (30, -30)}), (31, -30))
        self.assertIn("separation", near.failed_checks)
        self.assertTrue(t.route_feasible(_belief(), (30, -30)).legal)

    def test_tools_and_guardian_agree_on_random_points(self):
        """The validity test. If these ever disagree, one of them is wrong."""
        s, rng = _scenario(), random.Random(7)
        limits = SafetyLimits.from_scenario(s)
        t = ReasoningTools(s, spawn_offset=(20.0, 0.0, 0.0))
        mismatches = []
        for _ in range(400):
            b = _belief(pos=(rng.uniform(-30, 30), rng.uniform(-30, 30), 8.0),
                        elapsed_s=rng.uniform(0, 290),
                        teammates={f"D{i}": (rng.uniform(-60, 60), rng.uniform(-60, 60)) for i in range(3)})
            pt = (rng.uniform(-150, 150), rng.uniform(-150, 150))
            fresh = SafetyGuardian(limits=limits)
            outcome = fresh.evaluate(Command(kind="fly", target=(pt[0], pt[1], 8.0), purpose="mission",
                                             speed_mps=5.0, timeout_s=30.0), b).outcome
            if (outcome == GuardianOutcome.APPROVE) != t.route_feasible(b, pt).legal:
                mismatches.append((pt, outcome))
        self.assertEqual(mismatches, [])

    def test_preview_touches_no_guardian_state(self):
        g = SafetyGuardian(limits=SafetyLimits.from_scenario(_scenario()))
        t = ReasoningTools(_scenario(), guardian=g)
        for _ in range(30):
            t.route_feasible(_belief(), (0, 52))
            t.nearest_legal_point(_belief(), (0, 52))
        self.assertEqual((g.consecutive_rejections, g.consecutive_interventions, g._command_in_flight, g.escalated),
                         (0, 0, False, False))


class TestNearestLegalPoint(unittest.TestCase):
    def test_a_legal_point_is_returned_unchanged(self):
        self.assertEqual(_tools().nearest_legal_point(_belief(), (30, -30)), (30, -30))

    def test_a_point_inside_the_no_fly_zone_moves_just_outside_it(self):
        t, b = _tools(), _belief()
        fixed = t.nearest_legal_point(b, (0, 52))
        self.assertIsNotNone(fixed)
        self.assertTrue(t.route_feasible(b, fixed).legal)
        self.assertFalse(NFZ1[0] <= fixed[0] <= NFZ1[1] and NFZ1[2] <= fixed[1] <= NFZ1[3])
        self.assertLess(t.distance((0, 52), fixed), 10.0, "the nearest exit is ~7 m away")

    def test_a_point_on_top_of_a_teammate_moves_to_a_safe_separation(self):
        t = _tools()
        b = _belief(teammates={"Drone2": (30, -30)})
        fixed = t.nearest_legal_point(b, (30, -30))
        self.assertGreaterEqual(t.distance(fixed, (30, -30)), t.scenario.min_separation_m)
        self.assertLess(t.distance((30, -30), fixed), t.scenario.min_separation_m + 2)

    def test_it_is_deterministic(self):
        t, b = _tools(), _belief(teammates={"Drone2": (30, -30)})
        self.assertEqual(t.nearest_legal_point(b, (0, 52)), t.nearest_legal_point(b, (0, 52)))
        self.assertEqual(t.nearest_legal_point(b, (31, -30)), t.nearest_legal_point(b, (31, -30)))

    def test_it_gives_up_honestly_instead_of_inventing_a_point(self):
        t, b = _tools(), _belief()
        self.assertIsNone(t.nearest_legal_point(b, (0, 52), max_radius_m=2.0))
        self.assertIsNone(t.nearest_legal_point(b, (float("nan"), 0)))
        self.assertIsNone(t.nearest_legal_point(b, (float("inf"), 0)))


class TestChosenPointsContext(unittest.TestCase):
    def test_one_line_per_sector_with_a_verdict_and_the_facts(self):
        lines = _tools().checked_points(_belief(teammates={"Drone2": (30, 30)}))
        self.assertEqual(len(lines), len(_scenario().sectors))
        a = next(l for l in lines if "sector A" in l)
        self.assertIn("nearest teammate Drone2", a)
        self.assertIn("LEGAL", a)
        self.assertTrue(all("round trip needs" in l and "radio range" in l for l in lines))


class TestPolicyAssistModes(unittest.TestCase):
    def _policy(self, answer, assist, offset=(0.0, 0.0, 0.0)):
        s = _scenario()
        tools = ReasoningTools(s, spawn_offset=offset) if assist != "off" else None
        return LLMAgentPolicy(ScriptedBackend([answer] * 3, respond=None), sectors=s.sectors,
                              spawn_offset=offset, assist=assist, tools=tools), s

    def test_repair_flies_the_nearest_legal_point_and_keeps_the_raw_one_on_record(self):
        policy, s = self._policy(_wp(0, 52), "repair")
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        flown = policy.take_waypoint()
        rec = policy.records[0]
        self.assertTrue(ReasoningTools(s).route_feasible(_belief(), flown).legal)
        self.assertEqual((rec.raw_waypoint, rec.repaired), ((0.0, 52.0), True))
        self.assertGreater(rec.repair_distance_m, 0)
        self.assertEqual(rec.waypoint, flown)

    def test_a_point_that_was_already_legal_is_not_touched(self):
        policy, _ = self._policy(_wp(30, -30), "repair")
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.take_waypoint(), (30.0, -30.0))
        self.assertFalse(policy.records[0].repaired)

    def test_an_unrepairable_point_goes_through_raw_so_the_guardian_still_blocks_it(self):
        policy, _ = self._policy(_wp(float("nan"), 0), "repair")
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        flown = policy.take_waypoint()
        self.assertTrue(math.isnan(flown[0]))
        self.assertFalse(policy.records[0].repaired)

    def test_assist_off_never_repairs(self):
        policy, _ = self._policy(_wp(0, 52), "off")
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.take_waypoint(), (0.0, 52.0))

    def test_context_mode_puts_the_checked_points_in_the_prompt_and_off_does_not(self):
        s = _scenario()
        for assist, shown in (("context", True), ("off", False), ("repair", False)):
            backend = ScriptedBackend([decision_json("return_home")], respond=None)
            tools = ReasoningTools(s) if assist != "off" else None
            LLMAgentPolicy(backend, sectors=s.sectors, assist=assist, tools=tools).decide(
                _belief(), ReplanEvent.SKILL_SUCCEEDED)
            self.assertEqual("CHECKED POINTS" in backend.prompts[0], shown, assist)

    def test_bad_assist_configuration_is_refused_loudly(self):
        b = ScriptedBackend()
        with self.assertRaises(ValueError):
            LLMAgentPolicy(b, assist="context")           # needs tools
        with self.assertRaises(ValueError):
            LLMAgentPolicy(b, assist="telepathy")

    def test_factory_gives_each_drone_its_own_tools_and_guardian(self):
        s = _scenario()
        factory, policies = make_policy_factory(ScriptedBackend(), s, assist="repair")
        for d in s.drones:
            factory(d.name)
        tools = [p.tools for p in policies.values()]
        self.assertEqual(len({id(t) for t in tools}), 4)
        self.assertEqual(len({id(t.guardian) for t in tools}), 4)
        self.assertEqual([t.spawn_offset for t in tools], [d.spawn_offset for d in s.drones])


class RecordingMock(KinematicMockVehicleAdapter):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.commanded = []

    def start_move_to(self, x, y, z):
        self.commanded.append((x, y, z))
        return super().start_move_to(x, y, z)


class TestRepairEndToEnd(unittest.TestCase):
    def test_a_repaired_no_fly_proposal_is_flown_without_the_guardian_ever_blocking(self):
        s = _scenario()
        offset = (20.0, 0.0, 0.0)
        adapter = RecordingMock("Drone3", speed_mps=25.0)
        policy = LLMAgentPolicy(ScriptedBackend([_wp(0, 52)] + [decision_json("return_home")] * 3,
                                                respond=None),
                                sectors=s.sectors, spawn_offset=offset, assist="repair",
                                tools=ReasoningTools(s, spawn_offset=offset))
        agent = PersistentAgent(adapter, s, "C", offset, 300.0, policy=policy, drone_name="Drone3")
        report = agent.run()
        self.assertFalse(any("guardian_blocked" in t for t in report.trace), report.trace)
        for cx, cy, _ in adapter.commanded:
            wx, wy = cx + offset[0], cy + offset[1]
            self.assertFalse(NFZ1[0] <= wx <= NFZ1[1] and NFZ1[2] <= wy <= NFZ1[3])
        self.assertTrue(policy.records[0].repaired)
        self.assertTrue(report.trace[-1].endswith("->done"))

    def test_without_repair_the_same_proposal_is_blocked(self):
        s = _scenario()
        offset = (20.0, 0.0, 0.0)
        policy = LLMAgentPolicy(ScriptedBackend([_wp(0, 52)] + [decision_json("return_home")] * 3,
                                                respond=None), sectors=s.sectors, spawn_offset=offset)
        agent = PersistentAgent(RecordingMock("Drone3", speed_mps=25.0), s, "C", offset, 300.0,
                                policy=policy, drone_name="Drone3")
        self.assertTrue(any("guardian_blocked" in t for t in agent.run().trace))


class TestProbe(unittest.TestCase):
    def test_situations_are_seeded_and_reproducible(self):
        s = _scenario()
        a = make_situation(s, random.Random(5))
        b = make_situation(s, random.Random(5))
        self.assertEqual((a[0].name, a[1].position), (b[0].name, b[1].position))

    def test_probe_is_deterministic_for_a_deterministic_model(self):
        backend = lambda: ScriptedBackend(respond=lambda p: _wp(0, 50) if "- go_to_waypoint:" in p else
                                          decision_json("return_home"))
        r1 = run_probe(backend(), _scenario(), n=8, seed=3)
        r2 = run_probe(backend(), _scenario(), n=8, seed=3)
        self.assertEqual(r1["summary"], r2["summary"])

    def test_probe_separates_the_conditions_as_designed(self):
        """A model that always names a point inside the no-fly zone: illegal alone, illegal with
        feedback (it repeats it), and only 'repair' ever produces a legal flown point."""
        backend = ScriptedBackend(respond=lambda p: _wp(0, 50) if "- go_to_waypoint:" in p else
                                  decision_json("return_home"))
        s = run_probe(backend, _scenario(), n=12, seed=11)["summary"]
        self.assertEqual(s["none"]["waypoint_rate"], 1.0)
        self.assertEqual(s["none"]["raw_legal_rate"], 0.0)
        self.assertEqual(s["context"]["raw_legal_rate"], 0.0)       # scripted: it ignores the table
        self.assertEqual(s["repair"]["raw_legal_rate"], 0.0)
        self.assertEqual(s["repair"]["flown_legal_rate"], 1.0)
        self.assertEqual(s["feedback"]["illegal_first_proposals"], 12)
        self.assertEqual(s["feedback"]["retry_legal_rate"], 0.0)
        self.assertEqual(s["feedback"]["retry_same_point_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
