#!/usr/bin/env python3
"""Tests for drone placement in a running simulator.

    python -m unittest discover tests

WHY THESE EXIST
---------------
Placement failed silently for days. `simSetVehiclePose` returns None whether it
worked or not, and the check that was supposed to catch a stacked fleet read the
vehicle-local frame, which reported a local z of 166.70 m for a drone whose
world z was -0.85 m. The result was two drones spawned 0.08 m apart in one
flight and 0.19 m apart in another, both already colliding before takeoff.

The mechanism, measured on 2026-09-28: a drone pinned inside another cannot be
repositioned at all. Only the drone on top can move. So a naive loop that asks
each drone to go to its slot never works, because the first drone's slot IS the
spawn pile, making that request a no-op and leaving every other drone trapped.

These tests run against a fake simulator that reproduces exactly that rule. No
real simulator, no GPU. If someone simplifies the two-pass placement back into
one loop, `test_single_pass_would_leave_drones_stacked` is the test that fails.
"""

from __future__ import annotations

import math
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "baseline"))


def _install_fake_airsim() -> None:
    """Provide the small slice of the airsim API that ensure_vehicles uses.

    Injected rather than imported so these tests run anywhere, including a
    checkout with no simulator and no airsim package installed.
    """
    if "airsim" in sys.modules:
        return
    fake = types.ModuleType("airsim")

    class Vector3r:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x_val, self.y_val, self.z_val = float(x), float(y), float(z)

    class Pose:
        def __init__(self, position=None, orientation=None):
            self.position = position or Vector3r()
            self.orientation = orientation

    fake.Vector3r = Vector3r
    fake.Pose = Pose
    fake.to_quaternion = lambda pitch, roll, yaw: (pitch, roll, yaw)
    sys.modules["airsim"] = fake


_install_fake_airsim()
import airsim                                       # noqa: E402  (the fake)
import open_loop_agent as agent                     # noqa: E402


class FakeSim:
    """A simulator that pins drones inside each other, as the real one does.

    The rule is ASYMMETRIC, which is the whole point. In the real simulator
    Drone1 could be moved out of the pile while Drone2 could not, so "both are
    touching, therefore neither moves" is the wrong model -- it deadlocks, and a
    fake that deadlocks would condemn correct code.

    Modelled instead as a stack: among drones within PIN_RADIUS of each other,
    only the one nearest the top is free, and declaration order is the stacking
    order. So a drone is pinned exactly when some drone declared before it is
    sitting on it. That reproduces the measurement -- Drone1 free, Drone2
    pinned -- and it unblocks progressively as drones leave, which is why the
    two-pass scatter terminates.

    Refused requests return None and change nothing, exactly like the real API.
    """

    PIN_RADIUS = 1.0

    def __init__(self, names, ground_z=29.25):
        # Everything spawns at the player start, a few centimetres apart --
        # the measured reality, not the declared layout.
        self.order = list(names)
        self.poses = {
            name: [0.0 + 0.02 * index, 0.0 - 0.02 * index, ground_z]
            for index, name in enumerate(names)
        }
        self.refused = 0
        self.honoured = 0

    # -- the slice of the API ensure_vehicles calls -------------------------
    def listVehicles(self):
        return list(self.poses)

    def simGetVehiclePose(self, vehicle_name):
        x, y, z = self.poses[vehicle_name]
        return airsim.Pose(airsim.Vector3r(x, y, z))

    def simSetVehiclePose(self, pose, ignore_collision=False, vehicle_name=None):
        here = self.poses[vehicle_name]
        rank = self.order.index(vehicle_name)
        pinned = any(
            other != vehicle_name
            and self.order.index(other) < rank                 # declared above
            and math.dist(here, position) < self.PIN_RADIUS    # and touching
            for other, position in self.poses.items()
        )
        if pinned:
            self.refused += 1
            return None
        self.poses[vehicle_name] = [pose.position.x_val,
                                    pose.position.y_val,
                                    pose.position.z_val]
        self.honoured += 1
        return None

    def simAddVehicle(self, name, vehicle_type, pose):
        raise AssertionError("no drone should be added; all are declared")


class PlacementTests(unittest.TestCase):
    """The settle delay is there for a real simulator's tick; the fake needs no
    wall-clock wait, and 0.6 s per request made the suite take 47 seconds."""

    def setUp(self):
        self._settle = agent.PLACEMENT_SETTLE
        agent.PLACEMENT_SETTLE = 0.0

    def tearDown(self):
        agent.PLACEMENT_SETTLE = self._settle

    def test_two_drones_end_up_separated(self):
        sim = FakeSim(["Drone1", "Drone2"])
        agent.ensure_vehicles(sim, ["Drone1", "Drone2"])
        self.assertAlmostEqual(sim.poses["Drone1"][0], 0.0, places=2)
        self.assertAlmostEqual(sim.poses["Drone2"][0], agent.SPACING, places=2)

    def test_four_drones_end_up_separated(self):
        names = [f"Drone{i}" for i in range(1, 5)]
        sim = FakeSim(names)
        agent.ensure_vehicles(sim, names)
        for index, name in enumerate(names):
            self.assertAlmostEqual(sim.poses[name][0], index * agent.SPACING, places=2)

    def test_closest_pair_clears_the_floor(self):
        names = ["Drone1", "Drone2", "Drone3"]
        sim = FakeSim(names)
        agent.ensure_vehicles(sim, names)
        closest = agent.min_pairwise_separation(sim, names)
        self.assertGreaterEqual(closest, agent.MIN_SPAWN_SEPARATION)

    def test_altitude_is_preserved_not_reset(self):
        """Placement must slide drones along the ground, not lift and drop them.

        The ground here is 29 m below the world origin, so a hard-coded z sent
        every drone on a 29 m fall before each flight.
        """
        sim = FakeSim(["Drone1", "Drone2"], ground_z=29.25)
        agent.ensure_vehicles(sim, ["Drone1", "Drone2"])
        for name in ("Drone1", "Drone2"):
            self.assertAlmostEqual(sim.poses[name][2], 29.25, places=2)

    def test_single_pass_would_leave_drones_stacked(self):
        """The bug itself, pinned down so it cannot come back.

        Asking each drone for its final slot in one pass leaves Drone2 trapped,
        because Drone1's slot is the pile it is already sitting in.
        """
        sim = FakeSim(["Drone1", "Drone2"])
        for index, name in enumerate(["Drone1", "Drone2"]):
            sim.simSetVehiclePose(
                airsim.Pose(airsim.Vector3r(index * agent.SPACING, 0.0, 29.25)),
                ignore_collision=True, vehicle_name=name)
        self.assertLess(agent.min_pairwise_separation(sim, ["Drone1", "Drone2"]),
                        agent.MIN_SPAWN_SEPARATION,
                        "single-pass placement should fail; if this passes, the "
                        "fake no longer models the simulator's pinning rule")

    def test_refuses_rather_than_flying_a_stacked_fleet(self):
        """If nothing can be moved, raise. Never fly drones that may be stacked."""
        sim = FakeSim(["Drone1", "Drone2"])
        sim.simSetVehiclePose = lambda *a, **k: None      # every request ignored
        with self.assertRaises(RuntimeError):
            agent.ensure_vehicles(sim, ["Drone1", "Drone2"])


class SeparationHelperTests(unittest.TestCase):
    def test_single_drone_has_no_pairwise_separation(self):
        sim = FakeSim(["Drone1"])
        self.assertIsNone(agent.min_pairwise_separation(sim, ["Drone1"]))

    def test_measures_the_closest_pair_not_the_first(self):
        sim = FakeSim(["A", "B", "C"])
        sim.poses = {"A": [0.0, 0.0, 0.0], "B": [10.0, 0.0, 0.0], "C": [10.5, 0.0, 0.0]}
        self.assertAlmostEqual(agent.min_pairwise_separation(sim, ["A", "B", "C"]),
                               0.5, places=3)


if __name__ == "__main__":
    unittest.main()
