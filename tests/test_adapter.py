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
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import airsim_fake  # noqa: E402
from agentic_uav.core import Position, SkillCommand, SkillKind, SkillResult  # noqa: E402
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

    def test_skill_commands_reject_unknown_kinds(self):
        with self.assertRaises(ValueError):
            SkillCommand("teleport")

    def test_skill_result_reports_what_ran(self):
        result = _Rig().adapter.execute_skill("Drone1", SkillCommand.hover())
        self.assertEqual(result, SkillResult("Drone1", SkillKind.HOVER, True))


class SkillCallTests(unittest.TestCase):
    """Each skill sends exactly what the baseline sent. Expectations from the goldens."""

    def check(self, command: SkillCommand, expected: list, prepare=None) -> None:
        rig = _Rig()
        if prepare:
            prepare(rig.adapter)
            rig.world.calls.clear()
        rig.adapter.execute_skill("Drone1", command)
        self.assertEqual(rig.calls, [expected])

    def test_take_off(self):
        _, call = first(baseline_calls("M01#1"), "takeoffAsync")
        self.check(SkillCommand.take_off(), call)

    def test_climb_to_cruise_uses_the_default_timeout(self):
        calls = baseline_calls("M01#1")
        i, _ = first(calls, "takeoffAsync")
        _, climb = first(calls, "moveToZAsync", i)
        z, speed = climb[1]
        self.check(SkillCommand.move_to_z(z, speed), climb)

    def test_landing_descent_carries_its_timeout(self):
        calls = baseline_calls("M03#1")
        _, land = first(calls, "landAsync")
        descent = calls[calls.index(land) - 1]
        self.assertEqual(descent[0], "moveToZAsync")
        z, speed = descent[1]
        self.check(SkillCommand.move_to_z(z, speed, descent[2]["timeout_sec"]), descent)

    def test_velocity_leg(self):
        _, call = first(baseline_calls("M01#1"), "moveByVelocityBodyFrameAsync")
        vx, vy, _vz, duration = call[1]
        self.check(SkillCommand.velocity(vx, vy, duration), call)

    def test_velocity_duration_passes_through_unconverted(self):
        # The plan's integer 5 reached AirSim as 5, not 5.0. Keep it so.
        _, call = first(baseline_calls("M01#1"), "moveByVelocityBodyFrameAsync")
        self.assertIsInstance(call[1][3], int)

    def test_hover(self):
        _, call = first(baseline_calls("M02#1"), "hoverAsync")
        self.check(SkillCommand.hover(), call)

    def test_fly_to(self):
        _, call = first(baseline_calls("M04#1"), "moveToPositionAsync")
        x, y, z, speed = call[1]
        self.check(SkillCommand.move_to_position(x, y, z, speed, call[2]["timeout_sec"]), call)

    def test_land(self):
        _, call = first(baseline_calls("M03#1"), "landAsync")
        self.check(SkillCommand.land(call[2]["timeout_sec"]), call)

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
        rig.adapter.execute_skill("Drone1", SkillCommand.land(expected[2][2]["timeout_sec"]))
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


if __name__ == "__main__":
    unittest.main()
