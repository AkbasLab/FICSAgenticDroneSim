#!/usr/bin/env python3
"""One contract, every adapter: what the skill layer may rely on from a simulator.

    python -m unittest discover tests
    AUV_LIVE_AIRSIM=1 python -m unittest tests.test_adapter_contract   # + live CarlaAir

WHY THIS EXISTS
---------------
The skills are written once against `VehicleAdapter` and must fly the same on
AirSim and on the mock (AUV-04, 3.4). That is only true if every adapter keeps
the same promises, so the promises are written down once, here, as tests, and
every adapter runs all of them:

* `AirSimOverFakeContract` -- the real `AirSimAdapter`, over the recording
  fake of AirSim's client;
* `MockContract` -- `MockVehicleAdapter`;
* `LiveAirSimContract` -- the real `AirSimAdapter` against a running CarlaAir.
  Skipped unless `AUV_LIVE_AIRSIM=1`, because it flies a real drone; it is
  part of Phase 3's live check. It needs the simulator up, with Drone1 on the
  ground, and moves only Drone1.

A new adapter -- Cosys-AirSim, a different simulator -- gets this suite by
subclassing `AdapterContract` and saying how to build one.
"""

import math
import os
import sys
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
from agentic_uav.control import navigation as nav  # noqa: E402
from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.core.clock import RealClock, SimClock  # noqa: E402
from agentic_uav.core.models import CollisionInfo, Position, PrimitiveCommand  # noqa: E402
from agentic_uav.simulator import SceneAdapter, VehicleAdapter, scenario_manager  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402

LIVE = os.environ.get("AUV_LIVE_AIRSIM") == "1"


class AdapterContract:
    """The promises. Subclasses provide `make(declared)` and the tolerances."""

    position_tolerance_m = 0.01
    yaw_tolerance_deg = 0.5
    ground_tolerance_m = 0.01

    def make(self, declared=("Drone1",)):
        """Return (adapter, clock, ground_z) for a fresh scene with `declared`."""
        raise NotImplementedError

    # -------------------------------------------------------------- helpers

    def setUp(self):
        self.adapter, self.clock, self.ground = self.make()

    def assertNear(self, a: Position, b: Position, tol=None):
        tol = self.position_tolerance_m if tol is None else tol
        self.assertLessEqual(nav.distance(a, b), tol, f"{a} vs {b}")

    def fly(self, altitude=6.0):
        self.adapter.take_control("Drone1")
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.take_off())
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_z(
            nav.altitude_to_z(altitude, self.ground), 3.0, 30.0))

    # ------------------------------------------------------------ the scene

    def test_is_both_protocols(self):
        self.assertIsInstance(self.adapter, VehicleAdapter)
        self.assertIsInstance(self.adapter, SceneAdapter)

    def test_declared_vehicles_are_listed(self):
        self.assertIn("Drone1", self.adapter.list_vehicles())

    def test_a_vehicle_starts_on_the_ground_uncontrolled(self):
        state = self.adapter.get_state("Drone1")
        self.assertLessEqual(abs(state.position.z - self.ground), self.ground_tolerance_m + 0.3)
        self.assertEqual(state.landed_state, 0)
        self.assertFalse(self.adapter.has_control("Drone1"))
        self.assertIsInstance(self.adapter.get_collision("Drone1"), CollisionInfo)

    def test_confirm_connection(self):
        self.adapter.confirm_connection()

    # ------------------------------------------------------------- control

    def test_take_control_and_release(self):
        self.adapter.take_control("Drone1")
        self.assertTrue(self.adapter.has_control("Drone1"))
        self.adapter.release("Drone1")
        self.assertFalse(self.adapter.has_control("Drone1"))

    def test_cancel_with_nothing_moving_is_harmless(self):
        self.adapter.cancel("Drone1")

    # ---------------------------------------------------------- primitives

    def test_take_off_leaves_the_ground(self):
        self.adapter.take_control("Drone1")
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.take_off())
        state = self.adapter.get_state("Drone1")
        self.assertLess(state.position.z, self.ground - 1.0)    # NED: up is negative
        self.assertEqual(state.landed_state, 1)

    def test_move_to_z_and_to_position(self):
        self.fly()
        target = Position(self.adapter.get_pose("Drone1").x + 8.0, 3.0,
                          nav.altitude_to_z(9.0, self.ground))
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_position(
            target.x, target.y, target.z, 3.0, 30.0))
        self.assertNear(self.adapter.get_pose("Drone1"), target)
        self.assertNear(self.adapter.get_state("Drone1").position, target)

    def test_rotate_to_yaw(self):
        self.fly()
        for heading in (90.0, -135.0, 0.0):
            self.adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(heading, 15.0))
            yaw = self.adapter.get_state("Drone1").yaw_deg
            self.assertLessEqual(abs(nav.heading_error(yaw, heading)), self.yaw_tolerance_deg)

    def test_hover_holds(self):
        self.fly()
        before = self.adapter.get_pose("Drone1")
        self.adapter.stop("Drone1")
        self.assertNear(self.adapter.get_pose("Drone1"), before, max(self.position_tolerance_m, 0.5))

    def test_land_returns_to_the_ground(self):
        self.fly()
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_z(self.ground - 1.0, 2.0, 30.0))
        self.adapter.execute_primitive("Drone1", PrimitiveCommand.land(20.0))
        state = self.adapter.get_state("Drone1")
        self.assertLessEqual(abs(state.position.z - self.ground), 1.5)
        self.adapter.release("Drone1")

    # ---------------------------------------------------------------- scene

    def test_reset_returns_to_spawn(self):
        spawn = self.adapter.get_pose("Drone1")
        self.fly()
        self.adapter.reset()
        self.wait_for_rest()
        self.assertNear(self.adapter.get_pose("Drone1"), spawn, max(self.position_tolerance_m, 1.0))

    def test_add_ignores_the_pose_and_place_sets_it(self):
        name = "ContractDrone"
        if name in self.adapter.list_vehicles():
            self.skipTest("left over from an earlier live run")
        self.assertTrue(self.adapter.add_vehicle(name, "SimpleFlight", Position(12.0, 0.0, 0.0)))
        self.assertIn(name, self.adapter.list_vehicles())
        # As simAddVehicle: it appears at the player start, not at x = 12.
        self.assertLessEqual(abs(self.adapter.get_state(name).position.x), max(self.position_tolerance_m, 0.5))
        self.adapter.place_vehicle(name, Position(12.0, -6.0, 0.0))
        self.wait_for_rest()
        rest = self.adapter.get_state(name).position
        self.assertLessEqual(abs(rest.x - 12.0), max(self.position_tolerance_m, 0.5))
        self.assertLessEqual(abs(rest.y + 6.0), max(self.position_tolerance_m, 0.5))

    def wait_for_rest(self):
        pass

    # --------------------------------------------- the skills fly on it

    def test_the_skills_fly_end_to_end(self):
        runner = S.SkillRunner(self.adapter, "Drone1", self.clock)
        here = self.adapter.get_pose("Drone1")
        results = [
            runner.run(S.TakeOffCommand(altitude_m=6.0)),
            runner.run(S.GoToWaypointCommand(nav.Waypoint(here.x + 10, here.y + 5, 8.0), heading_deg=45)),
            runner.run(S.HoldPositionCommand(1.0)),
            runner.run(S.ReturnHomeCommand()),
            runner.run(S.LandCommand()),
        ]
        for r in results:
            with self.subTest(skill=r.skill.value):
                self.assertEqual(r.status, S.SkillStatus.SUCCESS, r.message)
        self.assertFalse(self.adapter.has_control("Drone1"))


class AirSimOverFakeContract(AdapterContract, unittest.TestCase):
    """The real AirSimAdapter, over the recording fake of AirSim's client."""

    def make(self, declared=("Drone1",)):
        world = airsim_fake.FakeWorld(declared=list(declared))
        return AirSimAdapter(airsim_fake.FakeClient(world, "main")), SimClock(), airsim_fake.GROUND_Z


class MockContract(AdapterContract, unittest.TestCase):
    """MockVehicleAdapter."""

    def make(self, declared=("Drone1",)):
        world = MockWorld(declared=declared)
        return MockVehicleAdapter(world), world.clock, world.ground_z

    def test_ensure_vehicles_works_on_the_mock(self):
        # The scenario manager relies on AirSim's spawn-then-place behaviour,
        # which the mock copies. Its real-time settles are skipped here.
        with mock.patch.object(scenario_manager, "time", types.SimpleNamespace(sleep=lambda s: None)), \
                mock.patch("builtins.print"):
            report = scenario_manager.ensure_vehicles(self.adapter, ["Drone1", "Drone2", "Drone3"])
        self.assertEqual(report["added"], ["Drone2", "Drone3"])
        self.assertEqual({n: xy[0] for n, xy in report["layout"].items()},
                         {"Drone1": 0.0, "Drone2": 4.0, "Drone3": 8.0})


@unittest.skipUnless(LIVE, "flies a real drone: set AUV_LIVE_AIRSIM=1 with CarlaAir running")
class LiveAirSimContract(AdapterContract, unittest.TestCase):
    """The real AirSimAdapter against a running CarlaAir. Phase 3's live check."""

    position_tolerance_m = 1.0
    yaw_tolerance_deg = 5.0
    ground_tolerance_m = 0.5

    def make(self, declared=("Drone1",)):
        adapter = AirSimAdapter.connect()
        adapter.reset()
        self.wait_for_rest(adapter)
        return adapter, RealClock(), adapter.get_state("Drone1").position.z

    def wait_for_rest(self, adapter=None):
        time.sleep(4.0)          # a reset drone falls from the player start; let it land

    def tearDown(self):
        try:
            if self.adapter.has_control("Drone1"):
                self.adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_z(
                    self.ground - 1.0, 2.0, 30.0))
                self.adapter.execute_primitive("Drone1", PrimitiveCommand.land(20.0))
                self.adapter.release("Drone1")
        except Exception:
            pass

    def test_add_ignores_the_pose_and_place_sets_it(self):
        self.skipTest("live: a spawned drone stays until restart and would block later flights")

    def test_cancel_from_a_second_connection_stops_a_move(self):
        # Phase 3's open question: SkillRunner.request_abort cancels on the
        # CALLER's own connection (one per thread). Does CarlaAir honour a
        # cancelLastTask that arrives on a different connection from the move?
        import threading
        self.fly(altitude=8.0)
        start = self.adapter.get_pose("Drone1")
        target = Position(start.x + 60.0, start.y, start.z)     # 20 s at 3 m/s
        mover = AirSimAdapter.connect()
        done = {}

        def move():
            t0 = time.monotonic()
            mover.execute_primitive("Drone1", PrimitiveCommand.move_to_position(
                target.x, target.y, target.z, 3.0, 40.0))
            done["seconds"] = time.monotonic() - t0

        thread = threading.Thread(target=move)
        thread.start()
        time.sleep(4.0)
        AirSimAdapter.connect().cancel("Drone1")                 # a third connection
        thread.join(30.0)
        self.adapter.stop("Drone1")
        travelled = self.adapter.get_pose("Drone1").x - start.x
        self.assertFalse(thread.is_alive(), "the move never returned")
        self.assertLess(done["seconds"], 12.0, f"cancel did not cut the move short ({done})")
        self.assertLess(travelled, 40.0, f"travelled {travelled:.1f} m of 60")


if __name__ == "__main__":
    unittest.main()
