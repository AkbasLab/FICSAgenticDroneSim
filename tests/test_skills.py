#!/usr/bin/env python3
"""Tests for agentic_uav.control.skills: eleven skills, their contracts, their results.

    python -m unittest discover tests

WHY THESE EXIST
---------------
AUV-04 asks that every skill have a formal contract and return a structured
result "rather than merely printing output" (3.3, and Phase 3's exit
criterion). These check, for every skill, the success path and the state it
leaves the drone in, and for the contracts' failure clauses that each one
actually happens: a precondition refused, a target missed, a timeout, an
abort, a simulator error, a landing that did not land. Each must come back as
a result with the right status and error code -- never as an exception.

The vehicle is the real `AirSimAdapter` over the recording fake, so every
height a skill sends can be checked as the AirSim call it became. Time is a
`SimClock`: holds and settles take no real time. Failures are injected by
thin wrappers around the adapter, below.
"""

import json
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.navigation import Region, Waypoint  # noqa: E402
from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.core.models import Position, PrimitiveKind  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402

GROUND = airsim_fake.GROUND_Z


class Wrapped:
    """An adapter that delegates, with a hook before each primitive."""

    def __init__(self, inner, before=None):
        self.inner, self.before = inner, before

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute_primitive(self, vehicle_id, command):
        if self.before is not None:
            replaced = self.before(vehicle_id, command)
            if replaced is not None:
                return replaced
        return self.inner.execute_primitive(vehicle_id, command)


class Rig:
    def __init__(self, before=None, declared=None, stuck_land=None):
        self.world = airsim_fake.FakeWorld(declared=declared, stuck_land=stuck_land)
        self.adapter = AirSimAdapter(airsim_fake.FakeClient(self.world, "main"))
        self.vehicle = Wrapped(self.adapter, before)
        self.clock = SimClock()
        self.runner = S.SkillRunner(self.vehicle, "Drone1", self.clock)

    @property
    def calls(self):
        return json.loads(json.dumps(self.world.calls.get("main", [])))

    def airborne(self, altitude=10.0):
        result = self.runner.run(S.TakeOffCommand(altitude_m=altitude))
        assert result.ok, result
        self.world.calls.clear()
        return result


class ContractTests(unittest.TestCase):

    def test_all_eleven_skills_have_a_complete_contract(self):
        self.assertEqual(set(S.CONTRACTS), set(S.SkillName))
        self.assertEqual(len(S.CONTRACTS), 11)
        for name, contract in S.CONTRACTS.items():
            with self.subTest(skill=name):
                for clause in ("parameters", "preconditions", "success", "failure",
                               "timeout", "abort", "state_change"):
                    self.assertTrue(getattr(contract, clause).strip(), clause)
                self.assertIs(contract.command.skill, name)

    def test_every_skill_has_a_handler(self):
        runner = Rig().runner
        self.assertEqual(set(runner._handlers), set(S.SkillName))

    def test_four_statuses(self):
        self.assertEqual({s.value for s in S.SkillStatus}, {"success", "failed", "aborted", "timeout"})


class CommandValidationTests(unittest.TestCase):

    def test_impossible_commands_are_refused_before_anything_flies(self):
        bad = [
            lambda: S.TakeOffCommand(altitude_m=1.0),
            lambda: S.TakeOffCommand(altitude_m=500),
            lambda: S.TakeOffCommand(speed_mps=0),
            lambda: S.TakeOffCommand(speed_mps=25),
            lambda: S.GoToWaypointCommand(),
            lambda: S.GoToWaypointCommand(Waypoint(0, 0, 1.5)),
            lambda: S.GoToWaypointCommand(Waypoint(0, 0, 10), tolerance_m=0),
            lambda: S.GoToWaypointCommand(Waypoint(0, 0, 10), timeout_s=-1),
            lambda: S.FollowWaypointsCommand(()),
            lambda: S.SearchRegionCommand(region=None),
            lambda: S.SearchRegionCommand(Region(0, 0, 10, 10), spacing_m=0),
            lambda: S.InspectPointCommand(target=None),
            lambda: S.InspectPointCommand(Waypoint(0, 0, 0), standoff_m=-1),
            lambda: S.HoldPositionCommand(-1),
            lambda: S.RendezvousCommand(Waypoint(0, 0, 10), arrive_by=10, hold_until=5),
            lambda: S.ActAsRelayCommand(Waypoint(0, 0, 10), duration_s=-1),
            lambda: S.ReturnHomeCommand(altitude_m=0.5),
            lambda: S.LandCommand(timeout_s=0),
        ]
        for i, make in enumerate(bad):
            with self.subTest(i=i):
                with self.assertRaises(ValueError):
                    make()

    def test_a_non_command_is_a_type_error(self):
        with self.assertRaises(TypeError):
            Rig().runner.run("GO_TO_WAYPOINT")


class TakeOffTests(unittest.TestCase):

    def test_measures_the_ground_before_taking_control(self):
        rig = Rig()
        result = rig.runner.run(S.TakeOffCommand(altitude_m=8.0))
        self.assertTrue(result.ok, result)
        self.assertEqual(rig.runner.ground_z, GROUND)
        self.assertEqual(rig.runner.home, Position(0.0, 0.0, GROUND))
        methods = [c[0] for c in rig.calls]
        # The ground is read (getMultirotorState) before control is taken.
        self.assertLess(methods.index("getMultirotorState"), methods.index("enableApiControl"))
        self.assertAlmostEqual(result.final_altitude_m, 8.0)
        self.assertTrue(result.details["ground_measured"])

    def test_the_climb_is_sent_as_ned_from_the_measured_ground(self):
        rig = Rig()
        rig.runner.run(S.TakeOffCommand(altitude_m=30.0))
        climb = [c for c in rig.calls if c[0] == "moveToZAsync"][0]
        self.assertAlmostEqual(climb[1][0], GROUND - 30.0)      # -0.75, not -30

    def test_refuses_to_measure_a_drone_already_under_control(self):
        rig = Rig()
        rig.adapter.take_control("Drone1")
        result = rig.runner.run(S.TakeOffCommand())
        self.assertEqual(result.status, S.SkillStatus.FAILED)
        self.assertEqual(result.error_code, S.ErrorCode.PRECONDITION_FAILED)
        self.assertNotIn("takeoffAsync", [c[0] for c in rig.calls])

    def test_refuses_when_already_airborne(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.TakeOffCommand())
        self.assertEqual(result.error_code, S.ErrorCode.PRECONDITION_FAILED)

    def test_a_climb_that_falls_short_fails(self):
        def short_climb(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_Z:
                v = rig.world.vehicles[vid]
                v.z = GROUND - 4.0                    # only 4 m of the 8
                return True
        rig = Rig(before=short_climb)
        result = rig.runner.run(S.TakeOffCommand(altitude_m=8.0))
        self.assertEqual(result.status, S.SkillStatus.FAILED)
        self.assertEqual(result.error_code, S.ErrorCode.NOT_REACHED)


class WaypointTests(unittest.TestCase):

    def test_go_to_waypoint(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(25, -10, 18), speed_mps=6))
        self.assertTrue(result.ok)
        self.assertEqual(result.final_position, Position(25, -10, GROUND - 18))
        self.assertAlmostEqual(result.final_altitude_m, 18.0)
        move = [c for c in rig.calls if c[0] == "moveToPositionAsync"][0]
        self.assertEqual(move[1][:4], [25, -10, GROUND - 18, 6])

    def test_heading_on_arrival(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(5, 5, 10), heading_deg=-135))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.final_yaw_deg, -135.0)

    def test_heading_not_reached(self):
        def stuck_yaw(vid, cmd):
            if cmd.kind is PrimitiveKind.ROTATE_TO_YAW:
                return True                              # does not turn
        rig = Rig(before=stuck_yaw)
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(5, 5, 10), heading_deg=90))
        self.assertEqual(result.error_code, S.ErrorCode.HEADING_NOT_REACHED)

    def test_not_airborne_is_a_precondition_failure(self):
        rig = Rig()
        rig.runner.ground_z = GROUND
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(5, 5, 10)))
        self.assertEqual(result.error_code, S.ErrorCode.PRECONDITION_FAILED)
        self.assertNotIn("moveToPositionAsync", [c[0] for c in rig.calls])

    def test_without_a_ground_nothing_flies(self):
        result = Rig().runner.run(S.GoToWaypointCommand(Waypoint(5, 5, 10)))
        self.assertEqual(result.error_code, S.ErrorCode.PRECONDITION_FAILED)
        self.assertIn("ground", result.message)

    def test_stopping_short_is_not_reached(self):
        def half_way(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                v = rig.world.vehicles[vid]
                p = cmd.params
                v.x, v.y, v.z = (v.x + p["x"]) / 2, (v.y + p["y"]) / 2, p["z"]
                return True
        rig = Rig(before=half_way)
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(40, 0, 10)))
        self.assertEqual(result.status, S.SkillStatus.FAILED)
        self.assertEqual(result.error_code, S.ErrorCode.NOT_REACHED)
        self.assertIn("20.00 m", result.message)

    def test_running_out_of_time_is_a_timeout(self):
        def slow(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                rig.clock.sleep(cmd.params["timeout"])   # AirSim gives up at its timeout
                return True                              # having moved nowhere
        rig = Rig(before=slow)
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(40, 0, 10), timeout_s=12))
        self.assertEqual(result.status, S.SkillStatus.TIMEOUT)
        self.assertEqual(result.error_code, S.ErrorCode.TIMEOUT)
        self.assertAlmostEqual(result.duration_s, 12.0, places=2)

    def test_the_default_timeout_is_from_the_travel_time(self):
        seen = {}
        def record(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                seen["timeout"] = cmd.params["timeout"]
        rig = Rig(before=record)
        rig.airborne()
        here = rig.adapter.get_pose("Drone1")
        rig.runner.run(S.GoToWaypointCommand(Waypoint(here.x + 50, here.y, 10), speed_mps=5))
        self.assertAlmostEqual(seen["timeout"], S.TIMEOUT_FACTOR * 10.0 + S.TIMEOUT_MARGIN_S)

    def test_a_simulator_error_is_reported_word_for_word(self):
        def boom(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                raise RuntimeError("IOLoop is already running")
        rig = Rig(before=boom)
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(5, 0, 10)))
        self.assertEqual(result.error_code, S.ErrorCode.SIMULATOR_ERROR)
        self.assertEqual(result.message, "RuntimeError: IOLoop is already running")

    def test_follow_waypoints_reports_each_leg(self):
        rig = Rig()
        rig.airborne()
        wps = (Waypoint(10, 0, 10), Waypoint(10, 10, 12), Waypoint(0, 10, 14))
        result = rig.runner.run(S.FollowWaypointsCommand(wps))
        self.assertTrue(result.ok)
        self.assertEqual([leg["status"] for leg in result.details["legs"]], ["success"] * 3)
        self.assertEqual(result.final_position, Position(0, 10, GROUND - 14))

    def test_follow_waypoints_stops_at_the_first_failing_leg(self):
        count = {"n": 0}
        def second_leg_fails(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                count["n"] += 1
                if count["n"] == 2:
                    return True                          # leg 2 goes nowhere
        rig = Rig(before=second_leg_fails)
        rig.airborne()
        wps = (Waypoint(10, 0, 10), Waypoint(20, 0, 10), Waypoint(30, 0, 10))
        result = rig.runner.run(S.FollowWaypointsCommand(wps))
        self.assertEqual(result.error_code, S.ErrorCode.NOT_REACHED)
        self.assertEqual([leg["status"] for leg in result.details["legs"]], ["success", "failed"])
        self.assertEqual(count["n"], 2)                  # leg 3 never sent


class SearchAndInspectTests(unittest.TestCase):

    def test_search_region_flies_the_whole_lawnmower(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.SearchRegionCommand(Region(0, 0, 40, 30), altitude_m=15, spacing_m=10))
        self.assertTrue(result.ok)
        self.assertEqual(result.details["lanes"], 3)
        self.assertEqual(result.details["lanes_completed"], 3)
        self.assertEqual(result.details["coverage"], 1.0)
        moves = [c[1][:3] for c in rig.calls if c[0] == "moveToPositionAsync"]
        self.assertEqual(moves[:2], [[0, 5, GROUND - 15], [40, 5, GROUND - 15]])

    def test_search_region_partial_coverage(self):
        count = {"n": 0}
        def fourth_leg_fails(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                count["n"] += 1
                if count["n"] == 4:
                    return True
        rig = Rig(before=fourth_leg_fails)
        rig.airborne()
        result = rig.runner.run(S.SearchRegionCommand(Region(0, 0, 40, 30), altitude_m=15, spacing_m=10))
        self.assertEqual(result.status, S.SkillStatus.FAILED)
        self.assertEqual(result.details["lanes_completed"], 1)
        self.assertAlmostEqual(result.details["coverage"], 0.333)

    def test_inspect_point_stands_off_and_faces_the_target(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.InspectPointCommand(Waypoint(30, 0, 0), altitude_m=12,
                                                      standoff_m=6, dwell_s=4))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.final_position.x, 24.0)
        self.assertAlmostEqual(result.final_altitude_m, 12.0)
        self.assertAlmostEqual(result.final_yaw_deg, 0.0, places=6)   # facing +x, at the target
        self.assertGreaterEqual(result.duration_s, 4.0)


class HoldTests(unittest.TestCase):

    def test_hold_position_takes_its_duration_in_simulated_time(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.HoldPositionCommand(30.0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.duration_s, 30.0)
        self.assertEqual(result.details["drift_m"], 0.0)
        self.assertIn("hoverAsync", [c[0] for c in rig.calls])

    def test_rendezvous_on_time_then_holds(self):
        rig = Rig()
        rig.airborne()
        t = rig.clock.now()
        result = rig.runner.run(S.RendezvousCommand(Waypoint(10, 10, 10), arrive_by=t + 60,
                                                    hold_until=t + 90))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.ended_at, t + 90)

    def test_rendezvous_late(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.RendezvousCommand(Waypoint(10, 10, 10),
                                                    arrive_by=rig.clock.now() - 1))
        self.assertEqual(result.error_code, S.ErrorCode.LATE)

    def test_act_as_relay(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.ActAsRelayCommand(Waypoint(-20, 15, 25), duration_s=45))
        self.assertTrue(result.ok)
        self.assertEqual(result.final_position, Position(-20, 15, GROUND - 25))
        self.assertGreaterEqual(result.duration_s, 45.0)


class HomeAndLandTests(unittest.TestCase):

    def test_return_home_keeps_the_current_height(self):
        rig = Rig()
        rig.airborne(altitude=10)
        rig.runner.run(S.GoToWaypointCommand(Waypoint(30, 20, 14)))
        result = rig.runner.run(S.ReturnHomeCommand())
        self.assertTrue(result.ok)
        self.assertEqual((result.final_position.x, result.final_position.y), (0, 0))
        self.assertAlmostEqual(result.final_altitude_m, 14.0)

    def test_return_home_without_a_home(self):
        rig = Rig()
        rig.airborne()
        rig.runner.home = None
        result = rig.runner.run(S.ReturnHomeCommand())
        self.assertEqual(result.error_code, S.ErrorCode.PRECONDITION_FAILED)

    def test_land_descends_lands_verifies_and_releases(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.LandCommand())
        self.assertTrue(result.ok)
        self.assertFalse(rig.adapter.has_control("Drone1"))
        methods = [c[0] for c in rig.calls]
        self.assertEqual([m for m in methods if m in ("moveToZAsync", "landAsync", "armDisarm",
                                                      "enableApiControl")],
                         ["moveToZAsync", "landAsync", "armDisarm", "enableApiControl"])
        descent = [c for c in rig.calls if c[0] == "moveToZAsync"][0]
        self.assertAlmostEqual(descent[1][0], GROUND - 1.0)     # the baseline's descent target

    def test_a_landing_that_does_not_land_keeps_control(self):
        rig = Rig(stuck_land={"Drone1"})
        rig.airborne(altitude=10)
        result = rig.runner.run(S.LandCommand())
        self.assertEqual(result.status, S.SkillStatus.FAILED)
        self.assertEqual(result.error_code, S.ErrorCode.LANDING_FAILED)
        self.assertTrue(rig.adapter.has_control("Drone1"))      # never released in the air
        self.assertNotIn("armDisarm", [c[0] for c in rig.calls])

    def test_landing_a_landed_drone_is_nothing_to_do(self):
        rig = Rig()
        rig.runner.ground_z = GROUND
        result = rig.runner.run(S.LandCommand())
        self.assertTrue(result.ok)
        self.assertTrue(result.details["already_on_ground"])
        self.assertTrue({c[0] for c in rig.calls} <= {"simGetVehiclePose", "getMultirotorState",
                                                       "isApiControlEnabled"})  # only reads


class AbortTests(unittest.TestCase):

    def test_abort_mid_move_holds_and_reports_aborted(self):
        def abort_on_move(vid, cmd):
            if cmd.kind is PrimitiveKind.MOVE_TO_POSITION:
                rig.runner.request_abort()               # as another thread would
                return True                              # cancelled: moved nowhere
        rig = Rig(before=abort_on_move)
        rig.airborne()
        result = rig.runner.run(S.GoToWaypointCommand(Waypoint(50, 0, 10)))
        self.assertEqual(result.status, S.SkillStatus.ABORTED)
        self.assertEqual(result.error_code, S.ErrorCode.ABORTED)
        methods = [c[0] for c in rig.calls]
        self.assertLess(methods.index("cancelLastTask"), len(methods))
        self.assertEqual(methods[methods.index("cancelLastTask"):].count("hoverAsync"), 1)

    def test_abort_during_a_hold_from_another_thread(self):
        rig = Rig()
        rig.airborne()
        clock = rig.clock

        class AbortingClock:
            """Lets the hold run 3 s, then aborts from a second thread."""
            def now(self):
                return clock.now()

            def sleep(self, seconds):
                clock.sleep(seconds)
                if clock.now() >= 3.0 + start and not fired:
                    fired.append(True)
                    t = threading.Thread(target=rig.runner.request_abort)
                    t.start(); t.join()

        fired, start = [], clock.now()
        rig.runner.clock = AbortingClock()
        result = rig.runner.run(S.HoldPositionCommand(60.0))
        self.assertEqual(result.status, S.SkillStatus.ABORTED)
        self.assertLess(result.duration_s, 4.0)

    def test_the_next_skill_is_not_aborted_by_an_old_request(self):
        rig = Rig()
        rig.airborne()
        rig.runner.request_abort()
        self.assertTrue(rig.runner.run(S.HoldPositionCommand(1.0)).ok)

    def test_emergency_hold_cancels_then_brakes(self):
        rig = Rig()
        rig.airborne()
        result = rig.runner.run(S.EmergencyHoldCommand())
        self.assertTrue(result.ok)
        self.assertEqual([c[0] for c in rig.calls][:2], ["cancelLastTask", "hoverAsync"])


class ResultTests(unittest.TestCase):

    def test_every_result_is_json(self):
        rig = Rig()
        results = [rig.runner.run(S.TakeOffCommand()),
                   rig.runner.run(S.SearchRegionCommand(Region(0, 0, 20, 20), spacing_m=10)),
                   rig.runner.run(S.InspectPointCommand(Waypoint(30, 0, 0))),
                   rig.runner.run(S.LandCommand())]
        for r in results:
            data = json.loads(json.dumps(r.as_json()))
            self.assertIn(data["status"], {"success", "failed", "aborted", "timeout"})
            self.assertEqual(data["skill"], r.skill.value)
            self.assertEqual(set(data["final_position"]), {"x", "y", "z"})

    def test_a_result_carries_its_times(self):
        rig = Rig()
        result = rig.runner.run(S.TakeOffCommand())
        self.assertEqual(result.started_at, 0.0)
        self.assertGreater(result.ended_at, result.started_at)
        self.assertEqual(result.duration_s, result.ended_at - result.started_at)


if __name__ == "__main__":
    unittest.main()
