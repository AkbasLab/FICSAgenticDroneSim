#!/usr/bin/env python3
"""Tests for Phase 3's exit script and the team flight behind it.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 3's exit criterion: "a deterministic script makes four drones take off,
navigate to distinct waypoints, hold, return and land -- and each skill
returns a structured result". On the mock that is checkable on every test
run, so it is: the script's own `main`, end to end, its outputs, its
determinism, and what it does when a skill fails. The AirSim path is run too,
against the recording fake, so its wiring -- a connection per drone thread,
the separation monitor -- is exercised before the live flight.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts"), os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
import four_drone_skills as script  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.core.clock import SimClock  # noqa: E402
from agentic_uav.experiments import team_flight as T  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.scenario_manager import ensure_vehicles  # noqa: E402


def run_main(argv):
    out = tempfile.mkdtemp(prefix="exit-script-")
    try:
        with mock.patch("builtins.print"):
            code = script.main(argv + ["--out", out])
        rows = []
        for path in glob.glob(os.path.join(out, "*.jsonl")):
            with open(path, encoding="utf-8") as h:
                rows += [json.loads(line) for line in h]
        summary = ""
        for path in glob.glob(os.path.join(out, "*.md")):
            with open(path, encoding="utf-8") as h:
                summary += h.read()
        return code, rows, summary
    finally:
        shutil.rmtree(out, ignore_errors=True)


class PlanTests(unittest.TestCase):

    def test_four_drones_five_skills_each(self):
        plan = T.exit_plan()
        self.assertEqual([m.drone for m in plan], ["Drone1", "Drone2", "Drone3", "Drone4"])
        for m in plan:
            self.assertEqual([c.skill for c in m.commands],
                             [S.SkillName.TAKE_OFF, S.SkillName.GO_TO_WAYPOINT, S.SkillName.HOLD_POSITION,
                              S.SkillName.RETURN_HOME, S.SkillName.LAND])

    def test_distinct_waypoints_on_tracks_that_never_cross(self):
        plan = T.exit_plan()
        waypoints = [m.commands[1].waypoint for m in plan]
        self.assertEqual(len({(w.x, w.y) for w in waypoints}), 4)               # distinct
        self.assertEqual([w.altitude_m for w in waypoints], [12.0, 16.0, 20.0, 24.0])
        self.assertEqual([w.x for w in waypoints], [0.0, 4.0, 8.0, 12.0])       # straight out sideways
        self.assertEqual([w.y > 0 for w in waypoints], [False, True, False, True])  # alternating sides

    def test_the_plan_is_fixed(self):
        self.assertEqual(T.exit_plan(), T.exit_plan())


class MockRunTests(unittest.TestCase):

    def test_the_exit_criterion_is_met_on_the_mock(self):
        code, rows, summary = run_main(["--sim", "mock"])
        self.assertEqual(code, 0)
        header, records = rows[0], rows[1:]
        self.assertTrue(header["exit_criterion_met"], header["verdict"])
        self.assertEqual(len(records), 20)
        for r in records:
            with self.subTest(drone=r["drone"], skill=r["skill"]):
                self.assertEqual(r["result"]["status"], "success")
                self.assertEqual(set(r["result"]) >= {"skill", "status", "started_at", "ended_at",
                                                       "final_position", "error_code"}, True)
        self.assertIn("**Exit criterion: MET**", summary)

    def test_separation_on_the_mock(self):
        _, rows, _ = run_main(["--sim", "mock"])
        sep = rows[0]["separation"]
        self.assertEqual(sep["drone_contacts"], [])
        self.assertGreaterEqual(min(sep["per_pair_min_m"].values()), 4.0)
        self.assertEqual(len(sep["per_pair_min_m"]), 6)

    def test_every_drone_ends_on_the_ground_at_home(self):
        _, rows, _ = run_main(["--sim", "mock"])
        for r in rows[1:]:
            if r["skill"] == "LAND":
                self.assertEqual(r["result"]["final_altitude_m"], 0.0)

    def test_deterministic(self):
        def strip(rows):
            out = []
            for r in rows[1:]:
                res = r["result"]
                out.append((r["drone"], r["index"], res["status"], res["started_at"], res["ended_at"],
                            res["final_position"], res["final_yaw_deg"]))
            return out, rows[0]["separation"]
        first = strip(run_main(["--sim", "mock"])[1])
        for _ in range(3):
            self.assertEqual(strip(run_main(["--sim", "mock"])[1]), first)


class FailureTests(unittest.TestCase):

    def fly(self, fault):
        world = MockWorld(declared=("Drone1",))
        scene = MockVehicleAdapter(world)
        with mock.patch("builtins.print"):
            ensure_vehicles(scene, list(T.EXIT_DRONES), settle=world.clock.sleep)
        fault(world)
        return world, T.fly_team(T.exit_plan(), lambda: MockVehicleAdapter(world), world.clock)

    def test_a_failed_skill_ends_in_hold_and_land_not_in_the_air(self):
        def stall_drone2_after_take_off(world):
            original = MockVehicleAdapter.execute_primitive

            def stall(self, vid, cmd):
                if vid == "Drone2" and cmd.kind.value == "move_to_position" and \
                        "Drone2" not in world.faults.stalled and world.position("Drone2").z < world.ground_z - 10:
                    world.faults.stalled.add("Drone2")
                    try:
                        return original(self, vid, cmd)
                    finally:
                        world.faults.stalled.discard("Drone2")
                return original(self, vid, cmd)
            patcher = mock.patch.object(MockVehicleAdapter, "execute_primitive", stall)
            patcher.start()
            self.addCleanup(patcher.stop)

        world, records = self.fly(stall_drone2_after_take_off)
        d2 = records["Drone2"]
        self.assertEqual(d2[1].result.status, S.SkillStatus.TIMEOUT)          # GO_TO timed out
        self.assertEqual([r.result is None for r in d2[2:5]], [True, True, True])  # skipped
        safety = [r for r in d2 if r.safety]
        self.assertEqual([r.command.skill for r in safety], [S.SkillName.EMERGENCY_HOLD, S.SkillName.LAND])
        self.assertTrue(all(r.result.ok for r in safety))
        self.assertEqual(world.position("Drone2").z, world.ground_z)          # on the ground
        ok, why = T.verdict(records)
        self.assertFalse(ok)
        self.assertIn("Drone2: GO_TO_WAYPOINT timeout", why)
        for other in ("Drone1", "Drone3", "Drone4"):
            self.assertTrue(all(r.result.ok for r in records[other]), other)

    def test_a_stuck_landing_fails_the_verdict(self):
        world, records = self.fly(lambda w: w.faults.stuck_land.add("Drone4"))
        ok, why = T.verdict(records)
        self.assertFalse(ok)
        self.assertIn("Drone4: LAND failed (LANDING_FAILED)", why)


class AirSimWiringTests(unittest.TestCase):
    """`--sim airsim`, against the recording fake: the wiring, not the physics."""

    def test_the_airsim_path_runs(self):
        world = airsim_fake.FakeWorld(declared=["Drone1"])
        connections = []

        def connect(cls, host="127.0.0.1", port=41451):
            connections.append(host)
            return cls(airsim_fake.FakeClient(world, "main"))

        with mock.patch.object(AirSimAdapter, "connect", classmethod(connect)), \
                mock.patch.object(script, "RealClock", SimClock):
            code, rows, summary = run_main(["--sim", "airsim"])
        self.assertEqual(code, 0, rows[0]["verdict"] if rows else "no output")
        # the scene, the monitor, and one per drone thread
        self.assertEqual(len(connections), 1 + 1 + 4)
        self.assertEqual(rows[0]["separation"]["source"], "SeparationMonitor, 10 Hz")
        self.assertEqual(sorted(world.vehicles), ["Drone1", "Drone2", "Drone3", "Drone4"])
        moves = [c for c in world.calls["main"] if c[0] == "moveToPositionAsync"]
        self.assertIn([0.0, -20.0, airsim_fake.GROUND_Z - 12.0], [m[1][:3] for m in moves])


if __name__ == "__main__":
    unittest.main()
