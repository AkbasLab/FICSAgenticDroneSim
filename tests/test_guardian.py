#!/usr/bin/env python3
"""Tests for Phase 11's runtime safety guardian: its manifest, each check, the four outcomes, the fallbacks.

    python -m unittest discover -s tests -p test_guardian.py

WHY THESE EXIST
---------------
AUV-11: "The LLM may propose actions. It must not directly control unsafe
behaviour." Phase 12 puts an LLM behind the guardian; everything it proposes
will be only as safe as these checks. Each check is tested alone, on a
hand-made belief, both ways -- what it must stop and what it must let
through -- because a guardian that refuses too much is also a failure: it
turns into the thing the mission is fighting. Each outcome is tested for what
it hands back to the agent and what it writes in the log, and each row of the
fallback table for the action it picks. Phase 5's two rules must keep Phase
5's words, so a reason a reader learnt there still means the same.
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.agents import drone_agent  # noqa: E402
from agentic_uav.agents.belief_state import BeliefState, Observation  # noqa: E402
from agentic_uav.agents.decision import Decision, DecisionKind  # noqa: E402
from agentic_uav.agents.validation import validate, zone_problems  # noqa: E402
from agentic_uav.control import navigation as nav  # noqa: E402
from agentic_uav.control.action_executor import Execution, SkillHandle  # noqa: E402
from agentic_uav.control.skills import (  # noqa: E402
    FollowWaypointsCommand,
    GoToWaypointCommand,
    HoldPositionCommand,
    InspectPointCommand,
    LandCommand,
    ReturnHomeCommand,
    SearchRegionCommand,
    SkillName,
    TakeOffCommand,
)
from agentic_uav.core.geometry import Region  # noqa: E402
from agentic_uav.core.team import TeamReport  # noqa: E402
from agentic_uav.experiments.runner import load_toml  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.safety import guardian as g  # noqa: E402

BRIEF = load_scenario("search_relay_001").brief()
LIMITS = g.parse_limits(load_toml(os.path.join(ROOT, "configs", "guardian", "default.toml")))


class Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


class Handle:
    """A stand-in executor: records what was started; `running` is what it says is flying."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.started = []
        self.running = None

    def skill_handle(self) -> SkillHandle:
        def start(command):
            self.started.append(command)
            self.running = Execution(len(self.started), command, self.clock.now())
            return self.running

        def current():
            return self.running

        return SkillHandle(self.clock, start, lambda: False, current, lambda: tuple(), lambda: self.running is not None,
                           lambda timeout_s=None: self.running)


def belief(x=60.0, y=-40.0, alt=12.0, airborne=True, battery=90.0, at=100.0, home=(0.0, 0.0)):
    b = BeliefState.start(BRIEF, "Drone1", Observation(at, home[0], home[1], 0.0, False, 100.0, (), True, None, 0, None))
    b.update(Observation(at, x, y, alt, airborne, battery, (), True, None, 0, None))
    b.self_.x, b.self_.y, b.self_.altitude_m, b.self_.airborne, b.self_.battery = x, y, alt, airborne, battery
    return b


def hear(b, drone, x, y, alt, at, ttl=3.0):
    b.receive(TeamReport(drone, at, "message", position=(x, y, alt), ttl_s=ttl), at)


def hear_all(b, at=100.0, where=None):
    where = where or {"Drone2": (60.0, 40.0, 16.0), "Drone3": (150.0, -40.0, 20.0), "Drone4": (150.0, 40.0, 24.0)}
    for d, (x, y, a) in where.items():
        hear(b, d, x, y, a, at)


def guardian(clock=None, layer=12.0):
    clock = clock or Clock()
    h = Handle(clock)
    return g.Guardian(BRIEF, "Drone1", LIMITS, h.skill_handle(), layer), h, clock


def go(x, y, alt=12.0, speed=5.0):
    return Decision.start(GoToWaypointCommand(nav.Waypoint(x, y, alt), speed_mps=speed), "go", "test")


class ManifestTests(unittest.TestCase):
    def test_the_default_manifest_holds_the_planned_limits(self):
        self.assertEqual(LIMITS, g.GuardianLimits(20.0, 20.0, 5.0, 40.0, 8.0, 2.0, 5.0, 10.0, 2.0))

    def test_read_strictly(self):
        good = load_toml(os.path.join(ROOT, "configs", "guardian", "default.toml"))
        for broken, word in (({**good, "extra": {}}, "unknown section"),
                             ({"limits": good["limits"]}, "missing section [fallback]"),
                             ({**good, "limits": {**good["limits"], "max_speed_mps": "8"}}, "not a number"),
                             ({**good, "limits": {**good["limits"], "max_speed_mps": True}}, "not a number"),
                             ({**good, "limits": {k: v for k, v in good["limits"].items() if k != "fence_clamp_m"}},
                              "missing fence_clamp_m"),
                             ({**good, "fallback": {**good["fallback"], "hold": 1}}, "unknown key hold")):
            with self.assertRaises(ValueError) as e:
                g.parse_limits(broken)
            self.assertIn(word, str(e.exception))

    def test_limits_must_make_sense(self):
        base = LIMITS.as_json()
        for change in ({"min_altitude_m": 1.0}, {"max_altitude_m": 200.0}, {"min_altitude_m": 50.0},
                       {"max_speed_mps": 25.0}, {"command_timeout_s": 0.0}, {"fence_clamp_m": -1.0},
                       {"hazard_factor": 0.5}):
            with self.assertRaises(ValueError):
                g.GuardianLimits(**{**base, **change})

    def test_the_fallback_comes_on_the_agent_loops_last_ask(self):
        self.assertEqual(g.REFUSALS_BEFORE_FALLBACK, drone_agent.MAX_REJECTIONS)


class GeometryTests(unittest.TestCase):
    def test_the_geofence_is_the_operating_box_and_its_margin(self):
        self.assertEqual(g.operating_box(BRIEF, 20.0), Region(-28.0, -100.0, 220.0, 100.0))

    def test_outside_by_and_onto(self):
        box = Region(0, 0, 10, 10)
        self.assertEqual(g.outside_by(box, 5, 5), 0)
        self.assertEqual(g.outside_by(box, 10, 10), 0)
        self.assertAlmostEqual(g.outside_by(box, 13, 14), 5.0)
        self.assertEqual(g.onto(box, 13, -2), (10, 0))

    def test_segment_distance(self):
        self.assertAlmostEqual(g.segment_distance((0, 0, 0), (10, 0, 0), (5, 3, 4)), 5.0)
        self.assertAlmostEqual(g.segment_distance((0, 0, 0), (10, 0, 0), (-3, 0, 4)), 5.0)
        self.assertAlmostEqual(g.segment_distance((1, 1, 1), (1, 1, 1), (1, 1, 3)), 2.0)

    def test_the_track_has_heights(self):
        here = (0.0, 0.0, 0.0)
        self.assertEqual(g.track3d(TakeOffCommand(altitude_m=12.0), here, (0, 0)), [here, (0.0, 0.0, 12.0)])
        self.assertEqual(g.track3d(LandCommand(), (5.0, 5.0, 12.0), (0, 0)), [(5.0, 5.0, 12.0), (5.0, 5.0, 0.0)])
        self.assertEqual(g.track3d(ReturnHomeCommand(), (5.0, 5.0, 12.0), (1, 2))[-1], (1, 2, 12.0))
        self.assertEqual(g.track3d(HoldPositionCommand(), here, (0, 0)), [here])


class ApproveTests(unittest.TestCase):
    def test_a_safe_command_is_approved_as_it_is_and_only_counted(self):
        gd, h, _ = guardian()
        v = gd.review(go(80, -40), belief())
        self.assertEqual(v, validate(go(80, -40), belief()))
        self.assertEqual((v.ok, v.outcome, v.replacement), (True, None, None))
        self.assertEqual((gd.approved, gd.log), (1, []))

    def test_continue_abort_and_finish_on_the_ground_are_approved(self):
        gd, _, _ = guardian()
        for d in (Decision.carry_on(), Decision.abort(), Decision.finish()):
            b = belief(alt=0.0, airborne=False, x=0.0, y=0.0) if d.kind is DecisionKind.FINISH else belief()
            self.assertTrue(gd.review(d, b).ok)
        self.assertEqual(gd.log, [])

    def test_phase_5s_refusals_keep_phase_5s_words(self):
        gd, _, _ = guardian()
        for d, b in ((go(25, 0), belief(x=0.0, y=0.0)),                       # through R1
                     (go(200, 80), belief(battery=25.0))):                   # not home on what is left
            self.assertEqual(gd.review(d, b).reasons, validate(d, b).reasons)
            self.assertFalse(validate(d, b).ok)


class ModifyTests(unittest.TestCase):
    def check(self, decision, b, check, field, value):
        gd, _, _ = guardian()
        v = gd.review(decision, b)
        self.assertTrue(v.ok)
        self.assertEqual(v.outcome, g.MODIFY)
        self.assertEqual(getattr(v.replacement.command, field) if field else v.replacement.command, value)
        self.assertEqual([e["outcome"] for e in gd.log], [g.MODIFY])
        self.assertEqual(gd.log[0]["checks"], [check])
        self.assertEqual(gd.log[0]["executed"]["command"], v.replacement.as_json()["command"])
        self.assertIs(gd._cleared, v.replacement.command)
        return v

    def test_too_high_is_brought_down_to_the_band(self):
        self.check(Decision.start(TakeOffCommand(altitude_m=60.0), "t"), belief(alt=0, airborne=False), "altitude",
                   "altitude_m", 40.0)
        self.check(go(80, -40, alt=90.0), belief(), "altitude", "waypoint", nav.Waypoint(80, -40, 40.0))

    def test_the_band_and_the_speed_limit_are_exact(self):
        self.check(go(80, -40, alt=40.5), belief(), "altitude", "waypoint", nav.Waypoint(80, -40, 40.0))
        self.check(go(80, -40, speed=8.5), belief(), "speed", "speed_mps", 8.0)
        gd, _, _ = guardian()
        for d in (go(80, -40, alt=40.0, speed=8.0), go(80, -40, alt=5.0)):
            self.assertEqual(gd.review(d, belief()).outcome, None)
        self.assertEqual(gd.log, [])

    def test_too_low_is_brought_up_to_the_band(self):
        self.check(Decision.start(TakeOffCommand(altitude_m=3.0), "t"), belief(alt=0, airborne=False), "altitude",
                   "altitude_m", 5.0)

    def test_too_fast_is_slowed_to_the_limit(self):
        self.check(go(80, -40, speed=15.0), belief(), "speed", "speed_mps", 8.0)
        self.check(Decision.start(TakeOffCommand(altitude_m=12.0, speed_mps=12.0), "t"),
                   belief(alt=0, airborne=False), "speed", "speed_mps", 8.0)

    def test_just_outside_the_fence_is_moved_onto_it(self):
        self.check(go(230, -40), belief(x=190.0), "geofence", "waypoint", nav.Waypoint(220.0, -40.0, 12.0))
        cmd = FollowWaypointsCommand((nav.Waypoint(100, -40, 12), nav.Waypoint(100, -115, 12)))
        v = self.check(Decision.start(cmd, "f"), belief(), "geofence", "waypoints",
                       (nav.Waypoint(100, -40, 12), nav.Waypoint(100.0, -100.0, 12)))
        self.assertIs(v.replacement.command.waypoints[0], cmd.waypoints[0])

    def test_a_region_over_the_fence_is_cut_to_it(self):
        cmd = SearchRegionCommand(region=Region(160, 40, 230, 80), altitude_m=12.0)
        self.check(Decision.start(cmd, "s"), belief(x=150.0, y=60.0), "geofence", "region", Region(160, 40, 220, 80))

    def test_several_changes_at_once_are_all_logged(self):
        gd, _, _ = guardian()
        v = gd.review(go(230, -40, alt=60.0, speed=12.0), belief(x=190.0))
        self.assertEqual(v.replacement.command, GoToWaypointCommand(nav.Waypoint(220, -40, 40), speed_mps=8.0))
        self.assertEqual(gd.log[0]["checks"], ["altitude", "geofence", "speed"])

    def test_the_modified_command_must_pass_every_other_check(self):
        gd, _, _ = guardian()
        v = gd.review(go(200, 80, speed=15.0), belief(battery=25.0))
        self.assertEqual((v.ok, v.outcome), (False, None))
        self.assertEqual(gd.log[0]["outcome"], g.REJECT)
        self.assertEqual(gd.log[0]["checks"], ["battery"])


class RejectTests(unittest.TestCase):
    def refused(self, decision, b, check):
        gd, h, _ = guardian()
        v = gd.review(decision, b)
        self.assertFalse(v.ok)
        self.assertIsNone(v.replacement)
        self.assertEqual([e["outcome"] for e in gd.log], [g.REJECT])
        self.assertIn(check, gd.log[0]["checks"])
        self.assertIsNone(gd._cleared)
        self.assertEqual(h.started, [])
        return gd.log[0]

    def test_far_outside_the_fence(self):
        self.refused(go(500, -40), belief(), "geofence")
        self.refused(Decision.start(SearchRegionCommand(region=Region(300, 0, 400, 50)), "s"), belief(), "geofence")
        # Reaching far past the fence is refused, not cut back, even where it overlaps the inside.
        self.refused(Decision.start(SearchRegionCommand(region=Region(160, 40, 400, 80), altitude_m=12.0), "s"),
                     belief(x=150.0, y=60.0), "geofence")

    def test_through_a_restricted_zone(self):
        e = self.refused(go(25, 0), belief(x=0.0, y=0.0), "restricted_zone")
        self.assertEqual(e["checks"], ["restricted_zone"])

    def test_a_point_that_is_no_number(self):
        for bad in (math.nan, math.inf):
            self.refused(go(bad, -40), belief(), "waypoint")
        self.refused(Decision.start(InspectPointCommand(target=nav.Waypoint(80, math.nan, 0)), "i"), belief(),
                     "waypoint")

    def test_not_home_on_what_is_left(self):
        legs = tuple(nav.Waypoint(x, y, 12) for _ in range(10) for x, y in ((40, -80), (200, 80)))
        self.refused(Decision.start(FollowWaypointsCommand(legs), "loop"), belief(), "battery")

    def test_a_stale_decision(self):
        stale = Decision(DecisionKind.START, "go", GoToWaypointCommand(nav.Waypoint(80, -40, 12)), "", issued_at=95.0)
        self.refused(stale, belief(), "timeout")
        gd, _, _ = guardian()
        fresh = Decision(DecisionKind.START, "go", GoToWaypointCommand(nav.Waypoint(80, -40, 12)), "", issued_at=98.5)
        self.assertTrue(gd.review(fresh, belief()).ok)

    def test_into_a_teammates_last_known_position(self):
        b = belief()
        hear_all(b)
        self.refused(go(60, 40, alt=16.0), b, "separation")

    def test_separation_is_three_dimensional_and_needs_current_news(self):
        gd, _, _ = guardian()
        b = belief()
        hear_all(b)
        self.assertTrue(gd.review(go(60, 40, alt=12.0), b).ok)        # 4 m below it
        b = belief(at=100.0)
        hear_all(b, at=90.0)                                           # past its 3 s lifetime
        self.assertTrue(gd.review(go(60, 40, alt=16.0), b).ok)

    def test_landing_only_at_home_or_the_base(self):
        self.refused(Decision.start(LandCommand(), "land"), belief(), "landing_site")
        gd, _, _ = guardian()
        self.assertTrue(gd.review(Decision.start(LandCommand(), "land"), belief(x=0.5, y=0.5)).ok)
        self.assertTrue(gd.review(Decision.start(LandCommand(), "land"), belief(x=-6.0, y=1.0)).ok)

    def test_finishing_in_the_air(self):
        self.refused(Decision.finish(reason="done"), belief(), "finish_airborne")

    def test_an_unreadable_answer(self):
        e = self.refused(Decision.invalid("{", ["[proposal] not JSON", "[conflict] two commands"]), belief(),
                         "proposal")
        self.assertEqual(e["checks"], ["conflict", "proposal"])
        self.assertEqual(e["reasons"], ["not JSON", "two commands"])
        self.assertEqual(e["proposed"]["raw"], "{")

    def test_an_unreadable_answer_with_no_reason_given_is_still_refused(self):
        bare = Decision(DecisionKind.INVALID, None, None, "", None, "?")
        e = self.refused(bare, belief(), "proposal")
        self.assertEqual(e["reasons"], ["an answer that could not be read as a decision"])


class FallbackOutcomeTests(unittest.TestCase):
    def test_the_last_ask_falls_back(self):
        gd, _, _ = guardian()
        b = belief()
        hear_all(b)
        outcomes = []
        for _ in range(drone_agent.MAX_REJECTIONS + 1):
            v = gd.review(go(25, 0), b)
            outcomes.append(v.outcome or ("ok" if v.ok else "refused"))
        self.assertEqual(outcomes, ["refused"] * 3 + [g.FALLBACK])
        self.assertEqual(v.fallback, g.HOLD_POSITION)            # nothing approved is flying
        self.assertEqual(v.replacement.command, HoldPositionCommand(duration_s=10.0))
        self.assertIs(gd._cleared, v.replacement.command)
        self.assertEqual([e["outcome"] for e in gd.log], [g.REJECT] * 3 + [g.FALLBACK])
        self.assertEqual(gd.log[-1]["why"], "refused 4 times")

    def test_refusals_are_counted_per_instant_and_reset_by_an_approval(self):
        gd, _, clock = guardian()
        b = belief()
        for _ in range(3):
            gd.review(go(25, 0), b)
        clock.t += 0.5
        self.assertIsNone(gd.review(go(25, 0), b).outcome)
        gd.review(go(80, -40), b)
        for _ in range(3):
            self.assertIsNone(gd.review(go(25, 0), b).outcome)

    def test_unsafe_now_falls_back_unless_the_decision_is_an_approved_command(self):
        gd, _, _ = guardian()
        b = belief(x=230.0, y=0.0)
        hear_all(b)
        v = gd.review(Decision.carry_on(), b)
        self.assertEqual((v.outcome, v.fallback), (g.FALLBACK, g.RETURN_HOME))
        self.assertEqual(gd.log[-1]["why"], "unsafe now")
        self.assertTrue(gd.review(go(200, 0), b).ok)               # back inside: approved as it is
        self.assertIsNone(gd.review(go(200, 0), b).outcome)

    def test_low_battery_heading_home_is_not_unsafe(self):
        gd, h, _ = guardian()
        b = belief(battery=20.5)
        h.running = Execution(1, ReturnHomeCommand(), 90.0)
        self.assertEqual(gd.review(Decision.carry_on(), b).outcome, None)
        route = FollowWaypointsCommand((nav.Waypoint(13.0, -17.0, 12.0), nav.Waypoint(0.0, 0.0, 12.0)))
        h.running = Execution(1, route, 90.0)                       # a route that ends over home
        self.assertEqual(gd.review(Decision.carry_on(), b).outcome, None)
        h.running = Execution(1, GoToWaypointCommand(nav.Waypoint(80, -40, 12)), 90.0)
        self.assertEqual(gd.review(Decision.carry_on(), b).fallback, g.RETURN_HOME)


    def test_on_the_ground_nothing_is_unsafe_now(self):
        gd, _, _ = guardian()
        landed = belief(x=0.0, y=0.0, alt=0.0, airborne=False, battery=15.0)       # below the reserve, down
        self.assertEqual(gd.review(Decision.finish(), landed).outcome, None)
        self.assertEqual(gd.log, [])

    def test_above_the_band_now_it_falls_back_to_its_layer(self):
        gd, _, _ = guardian()
        b = belief(alt=45.0)
        hear_all(b)
        v = gd.review(Decision.carry_on(), b)
        self.assertEqual((v.outcome, v.fallback), (g.FALLBACK, g.CLIMB_OR_DESCEND))
        self.assertEqual(gd.log[-1]["checks"], ["altitude"])

    def test_a_teammate_inside_the_separation_now_falls_back(self):
        gd, _, _ = guardian()
        b = belief()
        hear_all(b, where={"Drone2": (60.5, -40.0, 12.5), "Drone3": (150.0, -40.0, 20.0), "Drone4": (150.0, 40.0, 24.0)})
        v = gd.review(Decision.carry_on(), b)
        self.assertEqual((v.outcome, v.fallback), (g.FALLBACK, g.HOLD_POSITION))
        self.assertEqual(gd.log[-1]["checks"], ["separation"])
        b = belief()
        hear_all(b, at=90.0, where={"Drone2": (60.5, -40.0, 12.5)})               # no longer current
        self.assertIsNone(gd.review(Decision.carry_on(), b).outcome)


class FallbackTableTests(unittest.TestCase):
    def choose(self, b, hazards=(), running=None):
        gd, h, _ = guardian()
        h.running = running
        return gd.choose_fallback(g.GuardianView.of(b, 100.0), list(hazards))

    def test_on_the_ground_it_stays_there(self):
        name, d = self.choose(belief(x=0.0, y=0.0, alt=0.0, airborne=False))
        self.assertEqual((name, d.kind), (g.HOLD_POSITION, DecisionKind.ABORT))

    def test_short_of_battery_it_goes_home_round_the_zone_or_lands_there(self):
        name, d = self.choose(belief(x=60.0, y=0.0, battery=21.0))
        self.assertEqual(name, g.RETURN_HOME)
        self.assertEqual((d.command.waypoints[-1].x, d.command.waypoints[-1].y), (0.0, 0.0))
        self.assertEqual(zone_problems(d.command, (60.0, 0.0), (0.0, 0.0), BRIEF.restricted_zones), [])
        self.assertTrue(all(w.altitude_m == 12.0 for w in d.command.waypoints))
        name, d = self.choose(belief(x=1.0, y=1.0, battery=19.0))
        self.assertEqual((name, d.command), (g.LAND_AT_SAFE_LOCATION, LandCommand()))

    def test_out_of_the_fence_it_goes_home(self):
        name, _ = self.choose(belief(x=230.0, y=0.0), [("geofence", "out")])
        self.assertEqual(name, g.RETURN_HOME)

    def test_above_the_band_it_goes_to_its_layer(self):
        name, d = self.choose(belief(alt=45.0), [("altitude", "high")])
        self.assertEqual((name, d.command.waypoint), (g.CLIMB_OR_DESCEND, nav.Waypoint(60.0, -40.0, 12.0)))

    def test_a_teammate_near(self):
        b = belief(alt=15.0)
        hear_all(b, where={"Drone2": (60.0, -40.0, 18.0), "Drone3": (150.0, -40.0, 20.0), "Drone4": (150.0, 40.0, 24.0)})
        self.assertEqual(self.choose(b)[0], g.CLIMB_OR_DESCEND)
        b = belief(alt=12.0)
        hear_all(b, where={"Drone2": (60.0, -40.0, 15.0), "Drone3": (150.0, -40.0, 20.0), "Drone4": (150.0, 40.0, 24.0)})
        self.assertEqual(self.choose(b)[0], g.HOLD_POSITION)

    def test_not_knowing_where_teammates_are_it_holds(self):
        b = belief()
        flying = Execution(1, GoToWaypointCommand(nav.Waypoint(80, -40, 12)), 90.0)
        self.assertEqual(self.choose(b, running=flying)[0], g.HOLD_POSITION)          # never heard
        hear_all(b, at=90.0)
        self.assertEqual(self.choose(b, running=flying)[0], g.HOLD_POSITION)          # no longer current

    def test_all_well_the_approved_skill_flies_on(self):
        b = belief()
        hear_all(b)
        flying = Execution(1, GoToWaypointCommand(nav.Waypoint(80, -40, 12)), 90.0)
        name, d = self.choose(b, running=flying)
        self.assertEqual((name, d.kind), (g.CONTINUE_LAST_VALID_PLAN, DecisionKind.CONTINUE))
        self.assertEqual(self.choose(b)[0], g.HOLD_POSITION)

    def test_an_unsafe_fallback_becomes_a_hold(self):
        gd, _, _ = guardian()
        view = g.GuardianView.of(belief(), 100.0)
        name, d = gd._checked(g.RETURN_HOME, GoToWaypointCommand(nav.Waypoint(25, 0, 12)), view, "test")
        self.assertEqual(name, g.HOLD_POSITION)


class HandleTests(unittest.TestCase):
    def test_a_reviewed_command_starts(self):
        gd, h, _ = guardian()
        b = belief()
        gd.attach(b)
        d = go(80, -40)
        gd.review(d, b)
        gd.handle().start(d.command)
        self.assertEqual(h.started, [d.command])

    def test_an_unreviewed_unsafe_command_is_refused_and_logged(self):
        gd, h, _ = guardian()
        gd.attach(belief(x=0.0, y=0.0))
        with self.assertRaises(g.CommandRefused):
            gd.handle().start(GoToWaypointCommand(nav.Waypoint(25, 0, 12)))
        self.assertEqual(h.started, [])
        self.assertEqual((gd.log[0]["source"], gd.log[0]["outcome"], gd.log[0]["checks"]),
                         ("direct", g.REJECT, ["restricted_zone"]))

    def test_an_unreviewed_command_is_never_modified(self):
        gd, h, _ = guardian()
        gd.attach(belief())
        with self.assertRaises(g.CommandRefused):
            gd.handle().start(GoToWaypointCommand(nav.Waypoint(80, -40, 12), speed_mps=15.0))
        self.assertEqual(h.started, [])
        self.assertEqual(gd.log[0]["checks"], ["speed"])

    def test_an_unreviewed_safe_command_is_checked_and_starts(self):
        gd, h, _ = guardian()
        gd.attach(belief())
        cmd = GoToWaypointCommand(nav.Waypoint(80, -40, 12))
        gd.handle().start(cmd)
        self.assertEqual((h.started, gd.log), ([cmd], []))

    def test_without_a_belief_an_unreviewed_command_is_refused(self):
        gd, h, _ = guardian()
        with self.assertRaises(g.CommandRefused):
            gd.handle().start(GoToWaypointCommand(nav.Waypoint(80, -40, 12)))
        self.assertEqual(h.started, [])

    def test_a_second_command_at_the_same_instant_conflicts(self):
        gd, h, clock = guardian()
        b = belief()
        gd.attach(b)
        d = go(80, -40)
        gd.review(d, b)
        gd.handle().start(d.command)
        with self.assertRaises(g.CommandRefused):
            gd.handle().start(HoldPositionCommand())
        self.assertEqual(h.started, [d.command])
        self.assertEqual(gd.log[-1]["checks"], ["conflict"])
        clock.t += 0.5
        gd.handle().start(HoldPositionCommand())
        self.assertEqual(len(h.started), 2)

    def test_the_clearance_is_for_that_command_object_once(self):
        gd, h, _ = guardian()
        b = belief()
        gd.attach(b)
        d = go(80, -40)
        gd.review(d, b)
        self.assertIs(gd._cleared, d.command)
        with self.assertRaises(g.CommandRefused):            # another command, unsafe, in its place
            gd.handle().start(GoToWaypointCommand(nav.Waypoint(25, 0, 12)))
        self.assertIsNone(gd._cleared)

    def test_the_rest_of_the_handle_passes_straight_through(self):
        gd, h, clock = guardian()
        handle = gd.handle()
        self.assertIs(handle.clock, clock)
        self.assertIsNone(handle.current())
        self.assertFalse(handle.busy)
        self.assertFalse(handle.abort())


class RecordTests(unittest.TestCase):
    def test_as_json_holds_limits_fence_counts_and_log(self):
        gd, _, _ = guardian()
        gd.review(go(25, 0), belief(x=0.0, y=0.0))
        j = gd.as_json()
        self.assertEqual(j["geofence"], {"x_min": -28.0, "y_min": -100.0, "x_max": 220.0, "y_max": 100.0})
        self.assertEqual((j["approved"], len(j["log"]), j["layer_m"]), (0, 1, 12.0))
        self.assertEqual(set(j["log"][0]), {"at", "drone", "source", "proposed", "outcome", "checks", "reasons",
                                            "executed", "fallback"})

    def test_every_check_and_outcome_named(self):
        self.assertEqual(len(g.CHECKS), len(set(g.CHECKS)))
        self.assertEqual(g.problem_check("[speed] x"), "speed")
        self.assertEqual(g.problem_check("no tag"), "proposal")
        self.assertEqual(set(g.FALLBACKS), {"HOLD_POSITION", "CLIMB_OR_DESCEND_TO_SAFE_LAYER", "RETURN_HOME",
                                            "LAND_AT_SAFE_LOCATION", "CONTINUE_LAST_VALID_PLAN"})
        self.assertEqual(SkillName.LAND.value, "LAND")


if __name__ == "__main__":
    unittest.main()
