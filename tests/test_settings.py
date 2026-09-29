#!/usr/bin/env python3
"""Tests for the AirSim settings the agent generates.

    python -m unittest discover tests

WHY THESE EXIST
---------------
A settings.json AirSim dislikes does not raise, warn or log. The simulator
starts, runs for about ten seconds, and exits -- no error, no crash dump,
nothing in the Windows event log. The only symptom is "it shuts down before
starting properly", which looks like a broken install rather than a bad config
file.

That happened here on 2026-09-28. An earlier version of build_settings() wrote
vehicle-level "X"/"Y"/"Z" keys; "Z": 0.0 is world origin height in NED, not
ground level, so the drone was placed inside the terrain and the process died
on every launch. Confirmed by A/B: shipped template -> ports up in 5 s, our
file -> dead in 10 s.

These tests pin the shape that works. They cannot prove the simulator will
start -- only a launch does that -- but they will catch the specific mistake
that cost an evening, and any future drift from the shipped template.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baseline"))

import open_loop_agent as agent  # noqa: E402  (path set above)


class SettingsShapeTests(unittest.TestCase):

    def test_required_top_level_keys(self):
        settings = agent.build_settings(1)
        self.assertEqual(settings["SettingsVersion"], 1.2)
        # Without SimMode the launcher shows a car-or-drone dialog and waits
        # forever for a click that -unattended will never produce.
        self.assertEqual(settings["SimMode"], "Multirotor")

    def test_every_drone_is_emitted(self):
        # The whole file is rewritten, so omitting Drone1 -- an easy off-by-one
        # when generating Drone2..N -- deletes it from the simulator entirely.
        for count in (1, 2, 4):
            with self.subTest(count=count):
                vehicles = agent.build_settings(count)["Vehicles"]
                self.assertEqual(list(vehicles), [f"Drone{i}" for i in range(1, count + 1)])

    def test_vehicles_are_simpleflight_and_autocreate(self):
        for vehicle in agent.build_settings(2)["Vehicles"].values():
            self.assertEqual(vehicle["VehicleType"], "SimpleFlight")
            self.assertTrue(vehicle["AutoCreate"])


class SpawnPositionTests(unittest.TestCase):
    """The regression that killed the simulator."""

    def test_no_vehicle_level_z(self):
        # THE BUG. Z=0 in NED is world origin height, not the ground, so the
        # vehicle spawns inside the terrain and the simulator exits silently.
        for count in (1, 2, 4):
            for name, vehicle in agent.build_settings(count)["Vehicles"].items():
                with self.subTest(count=count, drone=name):
                    self.assertNotIn("Z", vehicle)

    def test_no_vehicle_level_y(self):
        for vehicle in agent.build_settings(4)["Vehicles"].values():
            self.assertNotIn("Y", vehicle)

    def test_first_drone_has_no_offset(self):
        # Let AirSim place it at the PlayerStart, exactly as the shipped
        # template does.
        self.assertNotIn("X", agent.build_settings(1)["Vehicles"]["Drone1"])

    def test_later_drones_are_spaced_on_x(self):
        # There is no collision avoidance anywhere in this stack; spacing plus
        # staggered altitudes is the only separation multi-drone missions have.
        vehicles = agent.build_settings(4)["Vehicles"]
        self.assertNotIn("X", vehicles["Drone1"])
        self.assertEqual(vehicles["Drone2"]["X"], agent.SPACING)
        self.assertEqual(vehicles["Drone3"]["X"], 2 * agent.SPACING)
        self.assertEqual(vehicles["Drone4"]["X"], 3 * agent.SPACING)


class CameraTests(unittest.TestCase):
    """Cameras are the shipped block, verbatim."""

    def test_both_shipped_cameras_are_present(self):
        cameras = agent.build_settings(1)["Vehicles"]["Drone1"]["Cameras"]
        self.assertEqual(set(cameras), {"0", "front_center"})

    def test_capture_settings_match_the_shipped_resolution(self):
        cameras = agent.build_settings(1)["Vehicles"]["Drone1"]["Cameras"]
        for name, camera in cameras.items():
            with self.subTest(camera=name):
                capture = camera["CaptureSettings"][0]
                self.assertEqual((capture["Width"], capture["Height"]), (1280, 960))
                self.assertEqual(capture["ImageType"], 0)

    def test_cameras_carry_their_offsets(self):
        # Present in the shipped file; dropping them was part of the settings
        # that killed the simulator, so they are pinned rather than assumed
        # optional.
        for camera in agent.build_settings(1)["Vehicles"]["Drone1"]["Cameras"].values():
            for axis in ("X", "Y", "Z", "Pitch", "Roll", "Yaw"):
                self.assertIn(axis, camera)


class FleetReuseTests(unittest.TestCase):
    """A bigger roster serves a smaller mission without a rewrite.

    This is what removes the restart between mission blocks: declare four
    drones once, and one-, two- and four-drone missions all fly against the
    same booted simulator. Only too few vehicles forces a change.
    """

    def test_a_four_drone_roster_contains_the_smaller_ones(self):
        four = agent.build_settings(4)["Vehicles"]
        for count in (1, 2, 4):
            with self.subTest(count=count):
                needed = list(agent.build_settings(count)["Vehicles"])
                self.assertTrue(set(needed).issubset(four))

    def test_the_first_drones_are_identical_at_any_fleet_size(self):
        # Drone1 must be the same vehicle whether the fleet is 1 or 4, or a
        # mission would fly a differently-configured aircraft depending on what
        # else happened to be declared.
        for count in (2, 4):
            with self.subTest(count=count):
                self.assertEqual(
                    agent.build_settings(1)["Vehicles"]["Drone1"],
                    agent.build_settings(count)["Vehicles"]["Drone1"],
                )


class SerialisationTests(unittest.TestCase):

    def test_settings_are_json_serialisable(self):
        import json
        text = json.dumps(agent.build_settings(4), indent=2)
        self.assertEqual(json.loads(text), agent.build_settings(4))


if __name__ == "__main__":
    unittest.main()
