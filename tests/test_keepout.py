#!/usr/bin/env python3
"""Tests for keeping clear of a teammate silent in the air: the rule, the search round it, and its readers.

    python -m unittest discover -s tests -p test_keepout.py

WHY THESE EXIST
---------------
Phase 9's live flight ended in a collision: the drone given a stopped
teammate's sector searched it at its own layer, passed beneath the hovering
drone, and was thrown into it. The fix keeps every route and every search out
of a square round a silent teammate's last known position. These test the
rule (who is silent in the air, for how long, how far), the search that goes
round such a square -- and that with nothing to avoid it is the plain
lawnmower, point for point, so no earlier flight changes -- and that the skill,
Phase 5's zone rule, the guardian and the LLM channel all trace a search the
same way.
"""

import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import airsim_fake  # noqa: E402
from agentic_uav.agents.decision import Decision  # noqa: E402
from agentic_uav.agents.proposal import parse_proposal, render_proposal  # noqa: E402
from agentic_uav.agents.validation import ground_track  # noqa: E402
from agentic_uav.control import navigation as nav  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.routing import AVOID_CLEARANCE_M, NoRouteError, grown, search_path  # noqa: E402
from agentic_uav.coordination import keepout as K  # noqa: E402
from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.safety.guardian import segment_distance, track3d, waypoint_problems  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402

CFG = K.KeepOutConfig(5.0, 10.0, 3.0)
SECTOR = Region(40.0, -80.0, 120.0, 0.0)
SQUARE = K.square(80.0, -40.0, 5.0)


class RuleTests(unittest.TestCase):
    def test_the_manifest(self):
        cfg = K.parse_keepout(load_toml(os.path.join(ROOT, "configs", "keepout", "default.toml")))
        self.assertEqual(cfg, CFG)
        for bad, word in (({}, "missing section"), ({"keep_out": {"half_width_m": 5, "after_s": 10}}, "missing"),
                          ({"keep_out": {**cfg.as_json(), "extra": 1}}, "unknown key"),
                          ({"keep_out": {**cfg.as_json(), "after_s": "10"}}, "not a number"),
                          ({"keep_out": cfg.as_json(), "x": {}}, "unknown section")):
            with self.assertRaises(ValueError) as e:
                K.parse_keepout(bad)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(ValueError):
            K.KeepOutConfig(0.0, 10.0, 3.0)

    def test_silent_long_enough_and_in_the_air(self):
        heard = [("Drone2", 80.0, -40.0, 16.0, 50.0),       # 10 s ago, up: silent in the air
                 ("Drone3", 150.0, -40.0, 20.0, 55.0),      # 5 s ago: only suspected
                 ("Drone4", 12.0, 0.0, 0.2, 10.0)]          # long silent, on its pad
        self.assertEqual(K.silent_in_the_air(heard, 60.0, CFG), [("Drone2", 80.0, -40.0)])
        self.assertEqual(K.silent_in_the_air(heard, 59.9, CFG), [])

    def test_the_square_and_who_is_inside(self):
        self.assertEqual(SQUARE.vertices, ((75.0, -45.0), (85.0, -45.0), (85.0, -35.0), (75.0, -35.0)))
        self.assertTrue(K.inside((84.0, -36.0), (80.0, -40.0), 5.0))
        self.assertFalse(K.inside((86.0, -40.0), (80.0, -40.0), 5.0))

    def test_a_drone_already_within_a_keep_out_may_fly_out_of_it(self):
        heard = [("Drone2", 80.0, -40.0, 16.0, 50.0)]
        self.assertEqual([d for d, _ in K.keep_outs(heard, 60.0, CFG, (100.0, -40.0), 2.0)], ["Drone2"])
        self.assertEqual(K.keep_outs(heard, 60.0, CFG, (82.0, -41.0), 2.0), [])
        self.assertEqual(K.keep_outs(heard, 60.0, CFG, (86.5, -40.0), 2.0), [])     # within the clearance too
        # On a route's corner node, just outside the grown square, it still plans round it (the first draft
        # let a drone there off: its search then flew straight through the stopped drone's column).
        corner = (80.0 - 7.0 * 1.05 + 0.1, -40.0 + 7.0 * 1.05 - 0.1)
        self.assertEqual([d for d, _ in K.keep_outs(heard, 60.0, CFG, corner, 2.0)], ["Drone2"])

    def test_over_its_own_pad_the_keep_out_is_its_pads_column(self):
        # Phase 17 pilot run 0035 (2026-11-07): Drone3, last heard descending onto its pad at (8, 0), went
        # silent for good; the full square round it covered Drone4's home 4 m away, so Drone4 could never get
        # home. Over its own pad a silent teammate keeps its pad's column -- PAD_RADIUS_M either side -- and
        # the neighbouring pads stay open.
        pads = {"Drone3": (8.0, 0.0), "Drone4": (12.0, 0.0)}
        landing = [("Drone3", 8.0, 0.4, 4.0, 198.4)]
        got = K.keep_outs(landing, 351.0, CFG, (205.0, 72.0), 2.0, pads)
        self.assertEqual([d for d, _ in got], ["Drone3"])
        self.assertEqual(got[0][1].vertices, K.square(8.0, 0.4, K.PAD_RADIUS_M).vertices)
        self.assertFalse(grown(got[0][1], 2.0 * 1.05).contains(12.0, 0.0))        # Drone4's home is reachable
        self.assertEqual(K.PAD_RADIUS_M, 1.0)
        # Anywhere else -- off its pad by more than PAD_RADIUS_M, or with no pads given -- the full square.
        off = [("Drone3", 8.0, 1.5, 4.0, 198.4)]
        self.assertEqual(K.keep_outs(off, 351.0, CFG, (205.0, 72.0), 2.0, pads)[0][1].vertices,
                         K.square(8.0, 1.5, 5.0).vertices)
        self.assertEqual(K.keep_outs(landing, 351.0, CFG, (205.0, 72.0), 2.0)[0][1].vertices,
                         K.square(8.0, 0.4, 5.0).vertices)
        # Over ANOTHER drone's pad it is no landing of its own: the full square.
        self.assertEqual(K.keep_outs([("Drone3", 12.0, 0.0, 4.0, 198.4)], 351.0, CFG, (205.0, 72.0), 2.0,
                                     pads)[0][1].vertices, K.square(12.0, 0.0, 5.0).vertices)


class SearchPathTests(unittest.TestCase):
    def test_with_nothing_to_avoid_it_is_the_lawnmower(self):
        self.assertEqual(search_path(SECTOR, 10.0, 12.0), nav.lawnmower(SECTOR, 10.0, 12.0))
        self.assertEqual(search_path(SECTOR, 10.0, 12.0, ()), nav.lawnmower(SECTOR, 10.0, 12.0))

    def test_round_a_square_keeping_the_clearance(self):
        path = search_path(SECTOR, 10.0, 12.0, (SQUARE,))
        out = grown(SQUARE, AVOID_CLEARANCE_M)
        for a, b in zip(path, path[1:]):
            self.assertFalse(out.crosses((a.x, a.y), (b.x, b.y)), (a, b))
            self.assertFalse(out.contains(a.x, a.y))
        self.assertTrue(all(w.altitude_m == 12.0 for w in path))
        self.assertGreater(len(path), len(nav.lawnmower(SECTOR, 10.0, 12.0)))
        # Close enough to see a target right beneath it: the detection footprint holds to 8.66 m.
        near = min(segment_distance((a.x, a.y), (b.x, b.y), (80.0, -40.0)) for a, b in zip(path, path[1:]))
        self.assertLess(near, 8.66)
        self.assertGreater(near, 5.0)

    def test_points_inside_are_dropped_and_no_way_round_raises(self):
        region = Region(78, -60, 120, -20)
        lanes = nav.lawnmower(region, 10.0, 12.0)
        inside = [w for w in lanes if grown(SQUARE, 2.0).contains(w.x, w.y)]
        self.assertEqual([(w.x, w.y) for w in inside], [(78, -45), (78, -35)])
        path = search_path(region, 10.0, 12.0, (SQUARE,))
        self.assertFalse(any(grown(SQUARE, 2.0).contains(w.x, w.y) for w in path))
        self.assertEqual(path[-1], lanes[-1])
        with self.assertRaises(NoRouteError):
            search_path(Region(78, -42, 82, -38), 10.0, 12.0, (SQUARE,))


class ReadersTests(unittest.TestCase):
    CMD = S.SearchRegionCommand(region=SECTOR, altitude_m=12.0, spacing_m=10.0, avoid=(SQUARE,))

    def test_the_command_holds_polygons_only(self):
        self.assertEqual(S.SearchRegionCommand(region=SECTOR, avoid=[SQUARE]).avoid, (SQUARE,))
        with self.assertRaises(ValueError):
            S.SearchRegionCommand(region=SECTOR, avoid=((1, 2),))

    def test_phase_5s_rule_and_the_guardian_trace_the_path_flown(self):
        path = search_path(SECTOR, 10.0, 12.0, (SQUARE,))
        self.assertEqual(ground_track(self.CMD, (40.0, 0.0))[1:], [(w.x, w.y) for w in path])
        self.assertEqual(track3d(self.CMD, (40.0, 0.0, 12.0), (0, 0))[1:], [(w.x, w.y, w.altitude_m) for w in path])
        self.assertEqual(waypoint_problems(self.CMD), [])
        boxed = S.SearchRegionCommand(region=Region(78, -42, 82, -38), avoid=(SQUARE,))
        self.assertEqual([c for c, _ in waypoint_problems(boxed)], ["waypoint"])
        self.assertEqual(ground_track(boxed, (0.0, 0.0))[1:], [(w.x, w.y) for w in nav.lawnmower(boxed.region, 10.0, 15.0)])

    def test_the_llm_channel_carries_areas_both_ways(self):
        d = Decision.start(self.CMD, "search S1")
        text = render_proposal(d)
        self.assertEqual(json.loads(text)["parameters"]["avoid"],
                         [{"vertices": [[75.0, -45.0], [85.0, -45.0], [85.0, -35.0], [75.0, -35.0]]}])
        self.assertEqual(parse_proposal(text).command, self.CMD)
        for bad in ('"avoid": 3', '"avoid": [{"vertices": [[1, 2], [3]]}]', '"avoid": [{"corners": []}]',
                    '"avoid": [{"vertices": [[0, 0], [1, 1]]}]'):
            got = parse_proposal('{"decision": "start", "skill": "SEARCH_REGION", "parameters": {"region": '
                                 '{"x_min": 40, "y_min": -80, "x_max": 120, "y_max": 0}, ' + bad + '}}')
            self.assertEqual(got.kind.value, "invalid", bad)

    def test_the_skill_flies_round_it(self):
        world = airsim_fake.FakeWorld()
        runner = S.SkillRunner(AirSimAdapter(airsim_fake.FakeClient(world, "main")), "Drone1", SimClock())
        self.assertTrue(runner.run(S.TakeOffCommand(altitude_m=12.0)).ok)
        world.calls.clear()
        cmd = S.SearchRegionCommand(region=Region(0, 0, 40, 30), altitude_m=12, spacing_m=10,
                                    avoid=(K.square(20.0, 15.0, 3.0),))
        result = runner.run(cmd)
        self.assertTrue(result.ok, result)
        moves = [tuple(c[1][:2]) for c in world.calls["main"] if c[0] == "moveToPositionAsync"]
        self.assertEqual(moves, [(w.x, w.y) for w in search_path(cmd.region, 10, 12, cmd.avoid)])
        self.assertEqual((result.details["lanes"], result.details["lanes_completed"], result.details["coverage"]),
                         (3, 3, 1.0))


def belief_at(x=100.0, y=-40.0, alt=12.0, at=60.0, heard=(("Drone2", 80.0, -40.0, 16.0, 50.0),)):
    from agentic_uav.agents.belief_state import BeliefState, Observation
    from agentic_uav.core.team import TeamReport
    b = BeliefState.start(BRIEF, "Drone1", Observation(at, 0.0, 0.0, 0.0, False, 100.0, (), True, None, 0, None))
    b.update(Observation(at, x, y, alt, True, 90.0, (), True, None, 0, None))
    for d, hx, hy, ha, hat in heard:
        b.receive(TeamReport(d, hat, "message", position=(hx, hy, ha), ttl_s=3.0, message_id=f"{d}#1"), hat)
    return b


BRIEF = __import__("agentic_uav.experiments.scenarios", fromlist=["x"]).load_scenario("search_relay_001").brief()


class PolicyTests(unittest.TestCase):
    def policy(self, keep_out=CFG):
        from agentic_uav.agents.rule_policy import RulePolicy
        p = RulePolicy(altitude_m=12.0)
        p.keep_out = keep_out
        return p

    def test_the_search_goes_round_a_silent_teammate(self):
        p, b = self.policy(), belief_at(x=40.0, y=-80.0)
        p._prepare(b, BRIEF.sectors[0])                       # S1: 40..120, -80..0
        d = p._search(b, "test")
        self.assertEqual(d.command.avoid, (SQUARE,))
        out = grown(SQUARE, AVOID_CLEARANCE_M)
        path = search_path(d.command.region, d.command.spacing_m, 12.0, d.command.avoid)
        self.assertFalse(any(out.crosses((a.x, a.y), (c.x, c.y)) for a, c in zip(path, path[1:])))
        self.assertEqual(p.search_path[1:], [(w.x, w.y) for w in path])

    def test_off_it_is_the_old_search_and_reads_no_teammate(self):
        p, b = self.policy(None), belief_at(x=40.0, y=-80.0)
        p._prepare(b, BRIEF.sectors[0])
        b.start_reading()
        d = p._search(b, "test")
        self.assertEqual((d.command.avoid, b.read()), ((), ()))

    def test_on_its_reads_are_known_to_the_knowledge_log(self):
        p, b = self.policy(), belief_at(x=40.0, y=-80.0)
        p._prepare(b, BRIEF.sectors[0])
        b.start_reading()
        p._search(b, "test")
        self.assertIn("Drone2#1", b.read())

    def test_the_way_home_goes_round_it(self):
        p, b = self.policy(), belief_at(x=100.0, y=-40.0)
        p._prepare(b, BRIEF.sectors[0])
        d = p._home(b, "test")
        pts = [(100.0, -40.0)] + [(w.x, w.y) for w in d.command.waypoints]
        out = grown(SQUARE, AVOID_CLEARANCE_M)
        self.assertFalse(any(out.crosses(a, c) for a, c in zip(pts, pts[1:])))
        self.assertEqual(pts[-1], (0.0, 0.0))

    def test_a_teammate_heard_lately_or_landed_is_no_keep_out(self):
        p = self.policy()
        for heard in ((("Drone2", 80.0, -40.0, 16.0, 55.0),), (("Drone2", 80.0, -40.0, 0.5, 20.0),)):
            b = belief_at(x=40.0, y=-80.0, heard=heard)
            p._prepare(b, BRIEF.sectors[0])
            self.assertEqual(p._keep_outs(b), [])


class GuardianKeepOutTests(unittest.TestCase):
    def guardian(self, keep_out=CFG):
        from agentic_uav.control.action_executor import SkillHandle
        from agentic_uav.safety.guardian import Guardian, parse_limits

        class Clock:
            def now(self):
                return 60.0

        handle = SkillHandle(Clock(), lambda c: None, lambda: False, lambda: None, lambda: (), lambda: False,
                             lambda timeout_s=None: None)
        limits = parse_limits(load_toml(os.path.join(ROOT, "configs", "guardian", "default.toml")))
        return Guardian(BRIEF, "Drone1", limits, handle, 12.0, keep_out)

    def go(self, x, y, alt=12.0):
        return Decision.start(S.GoToWaypointCommand(nav.Waypoint(x, y, alt)), "go")

    def test_through_the_column_is_refused_at_any_height(self):
        g = self.guardian()
        for alt in (12.0, 30.0):
            v = g.review(self.go(60.0, -40.0, alt), belief_at())
            self.assertFalse(v.ok)
        self.assertEqual([e["checks"] for e in g.log], [["keep_out"], ["keep_out"]])
        self.assertIn("silent there 10.0 s", g.log[0]["reasons"][0])

    def test_round_it_from_inside_it_or_with_the_check_off_is_approved(self):
        g = self.guardian()
        self.assertTrue(g.review(self.go(100.0, -60.0), belief_at()).ok)                 # round, not through
        self.assertTrue(g.review(self.go(60.0, -40.0), belief_at(x=84.0, y=-40.0)).ok)   # within: fly out
        self.assertTrue(self.guardian(None).review(self.go(60.0, -40.0), belief_at()).ok)
        self.assertEqual(g.log, [])

    def test_its_way_home_goes_round_it(self):
        from agentic_uav.safety import guardian as G
        g = self.guardian()
        view = G.GuardianView.of(belief_at(x=100.0, y=-40.0), 60.0)
        cmd = g._way_home(view)
        pts = [(100.0, -40.0)] + [(w.x, w.y) for w in cmd.waypoints]
        self.assertFalse(any(SQUARE.crosses(a, c) for a, c in zip(pts, pts[1:])))
        self.assertEqual(g._checked(G.RETURN_HOME, S.GoToWaypointCommand(nav.Waypoint(60.0, -40.0, 12.0)),
                                    view, "test")[0], G.HOLD_POSITION)


class GapTests(unittest.TestCase):
    """Three behaviours the first mutation pass found untested."""

    def test_to_a_sector_whose_first_point_is_kept_out_it_aims_at_the_search_round_it(self):
        from agentic_uav.agents.rule_policy import RulePolicy
        p = RulePolicy(altitude_m=12.0)
        p.keep_out = CFG
        b0 = belief_at(x=0.0, y=0.0)
        p._prepare(b0, BRIEF.sectors[0])
        fx, fy = p.lanes[0]
        b = belief_at(x=0.0, y=0.0, heard=(("Drone2", fx, fy, 16.0, 50.0),))
        d = p._to_sector(b, "test")
        self.assertEqual(d.objective, "reach S1")                    # not given up for want of a route
        first = search_path(p.region, p.spacing, 12.0, (K.square(fx, fy, 5.0),))[0]
        self.assertNotEqual((first.x, first.y), (fx, fy))

    def test_the_relay_goes_round_the_teammate_it_relays_for(self):
        import types
        from agentic_uav.agents.recovery_policy import RecoveryPolicy
        from agentic_uav.coordination.contract_net import ContractNet
        from agentic_uav.coordination.tasks import tasks_from_brief
        from agentic_uav.experiments.allocation import load_allocation
        from agentic_uav.experiments.recovery import load_recovery
        policy = RecoveryPolicy(ContractNet("Drone1", tasks_from_brief(BRIEF), load_allocation()), load_recovery(),
                                altitude_m=12.0, keep_out=CFG)
        policy.detector = types.SimpleNamespace(in_state=lambda health: ["Drone2"])
        b = belief_at(x=150.0, y=-60.0, heard=(("Drone2", 100.0, -40.0, 16.0, 40.0),))
        d = policy._relay(b, "test")
        pts = [(150.0, -60.0)] + [(w.x, w.y) for w in d.command.waypoints]
        zone = K.square(100.0, -40.0, 5.0)
        self.assertFalse(any(zone.crosses(a, c) for a, c in zip(pts, pts[1:])), pts)
        self.assertGreater(len(pts), 2)                              # it had to go round

    def test_a_search_that_avoids_nothing_is_written_as_before(self):
        plain = S.command_json(S.SearchRegionCommand(region=SECTOR))
        self.assertNotIn("avoid", plain)
        self.assertEqual(S.command_json(S.SearchRegionCommand(region=SECTOR, avoid=(SQUARE,)))["avoid"],
                         ({"vertices": SQUARE.vertices},))
        self.assertEqual(S.command_json(S.HoldPositionCommand()), {"duration_s": 5.0})


if __name__ == "__main__":
    unittest.main()
