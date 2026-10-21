#!/usr/bin/env python3
"""Tests for MockVehicleAdapter: its kinematics, its shared time, its contacts, its faults.

    python -m unittest discover tests

WHY THESE EXIST
---------------
The contract suite (`test_adapter_contract.py`) checks the mock keeps the
same promises as AirSim. These check what is the mock's own: that motion takes
the simulated time it should, that several drones share one timeline
deterministically, that contacts and separation are measured, that the faults
it can inject produce the skill results they should -- and that nothing here
takes real time.
"""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.control import skills as S  # noqa: E402
from agentic_uav.control.contacts import classify_contact, is_ground  # noqa: E402
from agentic_uav.control.navigation import Waypoint  # noqa: E402
from agentic_uav.core.models import Position, PrimitiveCommand, PrimitiveKind  # noqa: E402
from agentic_uav.simulator.mock_adapter import (  # noqa: E402
    GROUND_OBJECT,
    MOCK_GROUND_Z,
    MockVehicleAdapter,
    MockWorld,
)

G = MOCK_GROUND_Z


def airborne(world, name="Drone1", altitude=10.0):
    adapter = MockVehicleAdapter(world)
    runner = S.SkillRunner(adapter, name, world.clock)
    result = runner.run(S.TakeOffCommand(altitude_m=altitude))
    assert result.ok, result
    return adapter, runner


class KinematicsTests(unittest.TestCase):

    def test_motion_takes_distance_over_speed_in_simulated_time(self):
        world = MockWorld()
        adapter, runner = airborne(world)
        t0 = world.clock.now()
        adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_position(50, 0, G - 10, 5.0))
        self.assertAlmostEqual(world.clock.now() - t0, 10.0)
        self.assertEqual(adapter.get_pose("Drone1"), Position(50, 0, G - 10))

    def test_take_off_climb_and_turn_times(self):
        world = MockWorld()
        adapter = MockVehicleAdapter(world)
        adapter.take_control("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.take_off())
        self.assertAlmostEqual(world.clock.now(), 2.0)              # 3 m at 1.5 m/s
        adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(90))
        self.assertAlmostEqual(world.clock.now(), 3.0)              # 90 degrees at 90 deg/s
        self.assertAlmostEqual(adapter.get_state("Drone1").yaw_deg, 90.0)

    def test_a_timeout_stops_the_drone_part_way(self):
        world = MockWorld()
        adapter, _ = airborne(world)
        start = adapter.get_pose("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_position(
            start.x + 50, start.y, start.z, 5.0, timeout=4.0))
        self.assertAlmostEqual(adapter.get_pose("Drone1").x, start.x + 20.0)

    def test_velocity_is_body_frame(self):
        world = MockWorld()
        adapter, _ = airborne(world)
        adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(90))
        before = adapter.get_pose("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.velocity(5.0, 0.0, 2.0))
        after = adapter.get_pose("Drone1")
        self.assertAlmostEqual(after.y - before.y, 10.0)            # "forward" faces +y now
        self.assertAlmostEqual(after.x - before.x, 0.0)

    def test_primitives_need_control(self):
        adapter = MockVehicleAdapter(MockWorld())
        with self.assertRaises(RuntimeError):
            adapter.execute_primitive("Drone1", PrimitiveCommand.take_off())

    def test_unknown_vehicle(self):
        with self.assertRaises(KeyError):
            MockVehicleAdapter(MockWorld()).get_pose("Drone9")

    def test_no_real_time_passes(self):
        world = MockWorld()
        started = time.monotonic()
        adapter, runner = airborne(world)
        runner.run(S.SearchRegionCommand(region=__import__(
            "agentic_uav.control.navigation", fromlist=["Region"]).Region(0, 0, 200, 100),
            spacing_m=10))
        self.assertGreater(world.clock.now(), 400.0)                 # minutes of simulated flight
        self.assertLess(time.monotonic() - started, 5.0)


class GroundTests(unittest.TestCase):

    def test_the_ground_is_at_town10hd_height_by_default(self):
        world = MockWorld()
        self.assertEqual(MockVehicleAdapter(world).get_pose("Drone1").z, 29.25)

    def test_a_move_below_ground_stops_there_and_touches_it(self):
        world = MockWorld()
        adapter, _ = airborne(world)
        here = adapter.get_pose("Drone1")
        adapter.execute_primitive("Drone1", PrimitiveCommand.move_to_z(here.z + 50, 5.0))  # sign error
        self.assertEqual(adapter.get_pose("Drone1").z, G)
        self.assertTrue(is_ground(adapter.get_collision("Drone1").object_name))

    def test_releasing_in_the_air_drops_it(self):
        world = MockWorld()
        adapter, _ = airborne(world)
        adapter.release("Drone1")
        self.assertEqual(adapter.get_pose("Drone1").z, G)
        self.assertEqual(adapter.get_collision("Drone1").object_name, GROUND_OBJECT)

    def test_landing_records_ground_contact(self):
        world = MockWorld()
        adapter, runner = airborne(world)
        self.assertTrue(runner.run(S.LandCommand()).ok)
        self.assertTrue(is_ground(adapter.get_collision("Drone1").object_name))
        self.assertEqual(adapter.get_state("Drone1").landed_state, 0)


class FaultTests(unittest.TestCase):

    def test_stuck_landing_is_a_failed_landing_with_control_kept(self):
        world = MockWorld()
        world.faults.stuck_land.add("Drone1")
        adapter, runner = airborne(world)
        result = runner.run(S.LandCommand())
        self.assertEqual(result.error_code, S.ErrorCode.LANDING_FAILED)
        self.assertTrue(adapter.has_control("Drone1"))

    def test_a_stalled_drone_times_out(self):
        world = MockWorld()
        adapter, runner = airborne(world)
        world.faults.stalled.add("Drone1")
        result = runner.run(S.GoToWaypointCommand(Waypoint(40, 0, 10), timeout_s=15))
        self.assertEqual(result.status, S.SkillStatus.TIMEOUT)
        self.assertAlmostEqual(result.duration_s, 15.0, places=3)

    def test_a_raising_primitive_is_a_simulator_error(self):
        world = MockWorld()
        adapter, runner = airborne(world)
        world.faults.raise_on[("Drone1", PrimitiveKind.MOVE_TO_POSITION)] = "BufferError: Existing exports"
        result = runner.run(S.GoToWaypointCommand(Waypoint(40, 0, 10)))
        self.assertEqual(result.error_code, S.ErrorCode.SIMULATOR_ERROR)
        self.assertIn("BufferError", result.message)

    def test_a_slow_drone_takes_longer(self):
        world = MockWorld()
        adapter, runner = airborne(world)
        world.faults.speed_factor["Drone1"] = 0.5
        result = runner.run(S.GoToWaypointCommand(Waypoint(50, 0, 10), speed_mps=5))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.duration_s, 20.0, places=3)


class TeamTests(unittest.TestCase):
    """Several drones, one simulated timeline."""

    def fly_team(self, plans, contact_distance_m=0.8):
        """plans: {drone: [commands]} flown concurrently; returns (world, results)."""
        names = sorted(plans)
        world = MockWorld(declared=names, contact_distance_m=contact_distance_m)
        results = {n: [] for n in names}
        start = threading.Barrier(len(names))

        def fly(name):
            adapter = MockVehicleAdapter(world)           # one per thread
            runner = S.SkillRunner(adapter, name, world.clock)
            with world.clock.participate():
                start.wait()
                for command in plans[name]:
                    results[name].append(runner.run(command))

        threads = [threading.Thread(target=fly, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
            self.assertFalse(t.is_alive(), "deadlock")
        return world, results

    def four_drone_plans(self):
        return {f"Drone{i}": [S.TakeOffCommand(altitude_m=6.0 + 2 * i),
                              S.GoToWaypointCommand(Waypoint(4.0 * (i - 1), 10.0 * i, 6.0 + 2 * i)),
                              S.HoldPositionCommand(5.0),
                              S.ReturnHomeCommand(),
                              S.LandCommand()]
                for i in range(1, 5)}

    def test_four_drones_fly_concurrently_on_one_timeline(self):
        world, results = self.fly_team(self.four_drone_plans())
        for name, rs in results.items():
            self.assertEqual([r.status for r in rs], [S.SkillStatus.SUCCESS] * 5, name)
        # Drone4 has the longest legs, so it finishes last; all share one clock.
        ends = {n: rs[-1].ended_at for n, rs in results.items()}
        self.assertEqual(max(ends, key=ends.get), "Drone4")
        self.assertAlmostEqual(world.clock.now(), max(ends.values()))
        self.assertEqual(len(world.separation()), 6)                 # every pair measured

    def test_the_team_flight_is_deterministic(self):
        def snapshot():
            world, results = self.fly_team(self.four_drone_plans())
            return ({n: [(r.status.value, round(r.started_at, 6), round(r.ended_at, 6),
                          r.final_position) for r in rs] for n, rs in results.items()},
                    world.separation(), world.contacts())
        first = snapshot()
        for _ in range(5):
            self.assertEqual(snapshot(), first)

    def test_crossing_paths_touch(self):
        # Two drones at the same height swap places: they meet in the middle.
        plans = {"Drone1": [S.TakeOffCommand(altitude_m=8), S.GoToWaypointCommand(Waypoint(8, 0, 8))],
                 "Drone2": [S.TakeOffCommand(altitude_m=8), S.GoToWaypointCommand(Waypoint(0, 0, 8))]}
        # Drone2 spawns at x = 4: it flies to x = 0 while Drone1 flies to x = 8.
        world, results = self.fly_team(plans)
        contacts = world.contacts()
        drones = {c["drone"] for c in contacts if not is_ground(c["object"])}
        self.assertEqual(drones, {"Drone1", "Drone2"})
        self.assertEqual(classify_contact(contacts[-1]["object"], ["Drone1", "Drone2"]), "drone")
        self.assertLess(world.separation()["Drone1-Drone2"]["min_m"], 0.8)

    def test_parallel_flight_does_not_touch(self):
        plans = {"Drone1": [S.TakeOffCommand(altitude_m=8), S.GoToWaypointCommand(Waypoint(0, 30, 8))],
                 "Drone2": [S.TakeOffCommand(altitude_m=8), S.GoToWaypointCommand(Waypoint(4, 30, 8))]}
        world, _ = self.fly_team(plans)
        self.assertFalse([c for c in world.contacts() if not is_ground(c["object"])])
        self.assertAlmostEqual(world.separation()["Drone1-Drone2"]["min_m"], 4.0, places=3)

    def test_abort_from_another_thread_stops_the_drone_mid_leg(self):
        world = MockWorld()
        flyer, flyer_runner = airborne(world)
        start = flyer.get_pose("Drone1")
        outcome = {}
        ready = threading.Barrier(2)

        def fly():
            with world.clock.participate():
                ready.wait()
                outcome["result"] = flyer_runner.run(S.GoToWaypointCommand(
                    Waypoint(start.x + 50, start.y, 10), speed_mps=5))

        def control():
            other = MockVehicleAdapter(world)              # the controller's own adapter
            with world.clock.participate():
                ready.wait()
                world.clock.sleep(3.0)
                flyer_runner.request_abort(via=other)

        threads = [threading.Thread(target=fly), threading.Thread(target=control)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        result = outcome["result"]
        self.assertEqual(result.status, S.SkillStatus.ABORTED)
        self.assertAlmostEqual(result.final_position.x - start.x, 15.0, delta=0.6)   # 3 s at 5 m/s


if __name__ == "__main__":
    unittest.main()
