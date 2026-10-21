#!/usr/bin/env python3
"""Tests for the AirSim adapter: it must make the baseline's calls, exactly.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Phase 2 step 3 moves the agent's flying onto `AirSimAdapter`, and the golden
tests then check nothing changed. That only works if each adapter method sends
precisely what the baseline sent for the same purpose. So the expectations
here are not written by hand. Each is TAKEN FROM `tests/golden/execution.json`,
the calls recorded from `v0.1-open-loop-baseline`, and the adapter is checked
against them call for call.

No simulator: the adapter wraps the recording fake from `tests/airsim_fake.py`.

PHASE 3 ADDITIONS have no baseline to take expectations from: the baseline
never turned to a heading or cancelled a movement. Their expected calls follow
AirSim's own API (`rotateToYawAsync(yaw, timeout_sec, margin, vehicle_name)`,
`cancelLastTask(vehicle_name)`), and their behaviour in CarlaAir is checked by
a live flight before Phase 3 closes. The heading conversion is checked against
AirSim's own `to_eularian_angles`.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
from agentic_uav.core import Position, PrimitiveCommand, PrimitiveKind, PrimitiveResult  # noqa: E402
from agentic_uav.simulator import SceneAdapter, VehicleAdapter  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402

with open(os.path.join(ROOT, "tests", "golden", "execution.json"), encoding="utf-8") as _f:
    GOLDEN = {c["id"]: c for c in json.load(_f)["cases"]}


def baseline_calls(case_id: str, stream: str = "Drone1") -> list:
    return GOLDEN[case_id]["result"]["calls"][stream]


def first(calls: list, method: str, after: int = 0) -> tuple[int, list]:
    for i in range(after, len(calls)):
        if calls[i][0] == method:
            return i, calls[i]
    raise AssertionError(f"{method} not in baseline calls")


class _Rig:
    """An AirSimAdapter on a fresh recording fake, flown as `main` stream."""

    def __init__(self, declared=None):
        self.world = airsim_fake.FakeWorld(declared=declared)
        self.adapter = AirSimAdapter(airsim_fake.FakeClient(self.world, "main"))

    @property
    def calls(self) -> list:
        return json.loads(json.dumps(self.world.calls.get("main", [])))


class ProtocolTests(unittest.TestCase):

    def test_airsim_adapter_is_both_protocols(self):
        adapter = _Rig().adapter
        self.assertIsInstance(adapter, VehicleAdapter)
        self.assertIsInstance(adapter, SceneAdapter)

    def test_primitive_commands_reject_unknown_kinds(self):
        with self.assertRaises(ValueError):
            PrimitiveCommand("teleport")

    def test_primitive_result_reports_what_ran(self):
        result = _Rig().adapter.execute_primitive("Drone1", PrimitiveCommand.hover())
        self.assertEqual(result, PrimitiveResult("Drone1", PrimitiveKind.HOVER, True))


class PrimitiveCallTests(unittest.TestCase):
    """Each primitive sends exactly what the baseline sent. Expectations from the goldens."""

    def check(self, command: PrimitiveCommand, expected: list, prepare=None) -> None:
        rig = _Rig()
        if prepare:
            prepare(rig.adapter)
            rig.world.calls.clear()
        rig.adapter.execute_primitive("Drone1", command)
        self.assertEqual(rig.calls, [expected])

    def test_take_off(self):
        _, call = first(baseline_calls("M01#1"), "takeoffAsync")
        self.check(PrimitiveCommand.take_off(), call)

    def test_climb_to_cruise_uses_the_default_timeout(self):
        calls = baseline_calls("M01#1")
        i, _ = first(calls, "takeoffAsync")
        _, climb = first(calls, "moveToZAsync", i)
        z, speed = climb[1]
        self.check(PrimitiveCommand.move_to_z(z, speed), climb)

    def test_landing_descent_carries_its_timeout(self):
        calls = baseline_calls("M03#1")
        _, land = first(calls, "landAsync")
        descent = calls[calls.index(land) - 1]
        self.assertEqual(descent[0], "moveToZAsync")
        z, speed = descent[1]
        self.check(PrimitiveCommand.move_to_z(z, speed, descent[2]["timeout_sec"]), descent)

    def test_velocity_leg(self):
        _, call = first(baseline_calls("M01#1"), "moveByVelocityBodyFrameAsync")
        vx, vy, _vz, duration = call[1]
        self.check(PrimitiveCommand.velocity(vx, vy, duration), call)

    def test_velocity_duration_passes_through_unconverted(self):
        # The plan's integer 5 reached AirSim as 5, not 5.0. Keep it so.
        _, call = first(baseline_calls("M01#1"), "moveByVelocityBodyFrameAsync")
        self.assertIsInstance(call[1][3], int)

    def test_hover(self):
        _, call = first(baseline_calls("M02#1"), "hoverAsync")
        self.check(PrimitiveCommand.hover(), call)

    def test_fly_to(self):
        _, call = first(baseline_calls("M04#1"), "moveToPositionAsync")
        x, y, z, speed = call[1]
        self.check(PrimitiveCommand.move_to_position(x, y, z, speed, call[2]["timeout_sec"]), call)

    def test_land(self):
        _, call = first(baseline_calls("M03#1"), "landAsync")
        self.check(PrimitiveCommand.land(call[2]["timeout_sec"]), call)

    def test_stop_is_a_hover(self):
        rig = _Rig()
        rig.adapter.stop("Drone1")
        _, call = first(baseline_calls("M02#1"), "hoverAsync")
        self.assertEqual(rig.calls, [call])


class ControlAndReadTests(unittest.TestCase):

    def test_take_control_enables_then_arms(self):
        calls = baseline_calls("M01#1")
        i, enable = first(calls, "enableApiControl")
        rig = _Rig()
        rig.adapter.take_control("Drone1")
        self.assertEqual(rig.calls, [enable, calls[i + 1]])
        self.assertEqual(calls[i + 1][0], "armDisarm")

    def test_release_disarms_then_hands_back(self):
        calls = baseline_calls("M01#1")
        disarm = [c for c in calls if c[0] == "armDisarm" and c[1] == [False]][0]
        i = calls.index(disarm)
        rig = _Rig()
        rig.adapter.release("Drone1")
        self.assertEqual(rig.calls, [disarm, calls[i + 1]])

    def test_reads_make_the_baseline_calls(self):
        calls = baseline_calls("M01#1")
        rig = _Rig()
        rig.adapter.get_state("Drone1")
        rig.adapter.get_pose("Drone1")
        rig.adapter.get_collision("Drone1")
        expected = [first(calls, m)[1] for m in
                    ("getMultirotorState", "simGetVehiclePose", "simGetCollisionInfo")]
        self.assertEqual(rig.calls, expected)

    def test_state_and_pose_are_ned_positions(self):
        adapter = _Rig().adapter
        state = adapter.get_state("Drone1")
        self.assertEqual(state.position, Position(0.0, 0.0, airsim_fake.GROUND_Z))
        self.assertEqual(state.landed_state, 0)
        self.assertEqual(adapter.get_pose("Drone1"), Position(0.0, 0.0, airsim_fake.GROUND_Z))

    def test_collision_info_is_converted(self):
        info = _Rig().adapter.get_collision("Drone1")
        self.assertFalse(info.has_collided)
        self.assertEqual(info.object_name, "")
        self.assertEqual(info.impact_point, Position(0.0, 0.0, 0.0))

    def test_simulator_errors_propagate_unchanged(self):
        # The flight record quotes the exception; the adapter must not wrap it.
        rig = _Rig()
        with self.assertRaises(KeyError):
            rig.adapter.get_state("NoSuchDrone")


class SandboxCallTests(unittest.TestCase):
    """What tools/fly_chat.py did to AirSim directly, the adapter now does.

    Expectations from `tests/golden/fly_chat.json`: the sandbox's calls,
    recorded in step 5 before it was moved onto the adapter.
    """

    @staticmethod
    def sandbox_calls() -> list:
        with open(os.path.join(ROOT, "tests", "golden", "fly_chat.json"), encoding="utf-8") as f:
            case = json.load(f)["cases"][0]
        assert case["id"] == "sandbox:one-drone-every-command"
        return case["result"]["calls"]["main"]

    def test_has_control_reads_the_api_control_flag(self):
        _, call = first(self.sandbox_calls(), "isApiControlEnabled")
        rig = _Rig()
        self.assertIs(rig.adapter.has_control("Drone1"), False)
        self.assertEqual(rig.calls, [call])

    def test_bringing_one_down_is_take_control_land_release(self):
        # :land on a hovering drone: control, land, then hand back.
        calls = self.sandbox_calls()
        i, _ = first(calls, "landAsync")
        expected = calls[i - 2:i + 3]
        self.assertEqual([c[0] for c in expected], ["enableApiControl", "armDisarm", "landAsync",
                                                    "armDisarm", "enableApiControl"])
        rig = _Rig()
        rig.adapter.take_control("Drone1")
        rig.adapter.execute_primitive("Drone1", PrimitiveCommand.land(expected[2][2]["timeout_sec"]))
        rig.adapter.release("Drone1")
        self.assertEqual(rig.calls, expected)


class SceneTests(unittest.TestCase):

    def test_reset_and_confirm(self):
        main = GOLDEN["M01#1"]["result"]["calls"]["main"]
        rig = _Rig()
        rig.adapter.reset()
        rig.adapter.confirm_connection()
        self.assertEqual(rig.calls, main[:2])

    def test_spawn_and_place_match_the_baseline(self):
        # M10 spawned three drones and placed all four. Same calls, in order.
        main = GOLDEN["M10#1"]["result"]["calls"]["main"]
        adds = [c for c in main if c[0] == "simAddVehicle"]
        places = [c for c in main if c[0] == "simSetVehiclePose"]
        rig = _Rig()
        for name, kind, pose in (c[1] for c in adds):
            rig.adapter.add_vehicle(name, kind, Position(*pose["pose"]))
        for c in places:
            rig.adapter.place_vehicle(c[2]["vehicle_name"], Position(*c[1][0]["pose"]),
                                      ignore_collision=c[1][1])
        self.assertEqual(rig.calls, adds + places)

    def test_list_vehicles(self):
        rig = _Rig(declared=["Drone1", "Drone2"])
        self.assertEqual(rig.adapter.list_vehicles(), ["Drone1", "Drone2"])


class HeadingAndCancelTests(unittest.TestCase):
    """Phase 3, 3.2: turn to a heading, read the heading, cancel a movement."""

    def test_rotate_to_yaw_leaves_airsim_defaults_out(self):
        rig = _Rig()
        rig.adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(90.0))
        # The fake records AirSim's defaults when an argument is omitted.
        self.assertEqual(rig.calls, [["rotateToYawAsync", [90.0],
                                      {"margin": 5, "timeout_sec": 3e38, "vehicle_name": "Drone1"}]])

    def test_rotate_to_yaw_passes_timeout_and_margin(self):
        rig = _Rig()
        rig.adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(-45.0, 10.0, 2.0))
        self.assertEqual(rig.calls, [["rotateToYawAsync", [-45.0],
                                      {"margin": 2.0, "timeout_sec": 10.0, "vehicle_name": "Drone1"}]])

    def test_heading_is_read_from_the_same_state_call(self):
        rig = _Rig()
        rig.adapter.execute_primitive("Drone1", PrimitiveCommand.rotate_to_yaw(135.0))
        rig.world.calls.clear()
        state = rig.adapter.get_state("Drone1")
        self.assertAlmostEqual(state.yaw_deg, 135.0, places=6)
        self.assertEqual([c[0] for c in rig.calls], ["getMultirotorState"])   # no new call

    def test_cancel(self):
        rig = _Rig()
        rig.adapter.cancel("Drone1")
        self.assertEqual(rig.calls, [["cancelLastTask", [], {"vehicle_name": "Drone1"}]])

    def test_yaw_degrees_matches_airsim(self):
        # Against AirSim's own conversion, across the circle and with pitch and
        # roll present -- including -45.59, the spawn heading Phase 1 measured.
        import airsim
        from agentic_uav.simulator.airsim_adapter import yaw_degrees
        for pitch, roll, yaw in [(0, 0, 0), (0, 0, 90), (0, 0, -90), (0, 0, 179.9),
                                 (0, 0, -45.59), (0.2, -0.1, 30), (-0.3, 0.25, -120)]:
            q = airsim.to_quaternion(pitch, roll, __import__("math").radians(yaw))
            expected = __import__("math").degrees(airsim.to_eularian_angles(q)[2])
            with self.subTest(yaw=yaw):
                self.assertAlmostEqual(yaw_degrees(q.w_val, q.x_val, q.y_val, q.z_val), expected, 9)

    def test_no_orientation_means_no_heading(self):
        import types
        client = types.SimpleNamespace(getMultirotorState=lambda vehicle_name="": types.SimpleNamespace(
            kinematics_estimated=types.SimpleNamespace(
                position=types.SimpleNamespace(x_val=0.0, y_val=0.0, z_val=29.25)),
            landed_state=0))
        self.assertIsNone(AirSimAdapter(client).get_state("Drone1").yaw_deg)

    def test_the_baseline_never_turns_or_cancels(self):
        # Additions, not changes: no recorded baseline flight makes either call.
        for case in GOLDEN.values():
            for stream in case["result"]["calls"].values():
                methods = {c[0] for c in stream}
                self.assertFalse(methods & {"rotateToYawAsync", "cancelLastTask"}, case["id"])


if __name__ == "__main__":
    unittest.main()
