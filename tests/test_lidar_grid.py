"""A real lidar scan turned into NavRL's input grid, and the AirSim adapter's velocity and lidar calls.

No simulator and no torch: the grid function is plain numpy, and the adapter is built without __init__ with a fake client.
"""

import math
import os
import sys
import unittest
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.simulator.airsim_adapter import VELOCITY_HOLD_S, AirSimVehicleAdapter


def points(*xyz_rows):
    return [v for row in xyz_rows for v in row]


def polar(distance, azimuth_deg, elevation_deg):
    """A sensor-frame (x forward, y right, z down) point at a horizontal distance, azimuth and elevation."""
    a, e = math.radians(azimuth_deg), math.radians(elevation_deg)
    return (distance * math.cos(a), distance * math.sin(a), -distance * math.tan(e))


class TestLidarGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import numpy  # noqa: F401  the grid code is numpy; the plain test environment has none
        except ImportError:
            raise unittest.SkipTest("numpy is not installed")
        from fics_drone.planners import navrl_planner
        cls.lidar_range_grid = staticmethod(navrl_planner.lidar_range_grid)
        global MAX_RAY_M
        MAX_RAY_M = navrl_planner.MAX_RAY_M

    def test_no_returns_is_all_max_range(self):
        grid = self.lidar_range_grid([], 0.0, 0.0)
        self.assertEqual(grid.shape, (36, 4))
        self.assertTrue((grid == MAX_RAY_M).all())

    def test_an_object_dead_ahead_appears_in_direction_zero_when_the_goal_is_ahead(self):
        grid = self.lidar_range_grid(points(polar(2.0, 0.0, 0.0)), 0.0, start_angle_deg=0.0)
        self.assertAlmostEqual(grid[0, 1], 2.0, places=3)           # the 0 degree row
        self.assertEqual(grid[0, 2], MAX_RAY_M)                      # nothing in the 10 degree row
        self.assertEqual(grid[1:, 1].min(), MAX_RAY_M)               # and nothing in any other direction

    def test_directions_are_counted_from_the_goal_direction(self):
        # an object due east (azimuth 0) while the goal lies 90 degrees to the left: it is 90 degrees clockwise of the goal
        grid = self.lidar_range_grid(points(polar(2.0, 0.0, 0.0)), 0.0, start_angle_deg=90.0)
        self.assertAlmostEqual(grid[27, 1], 2.0, places=3)           # (0 - 90) mod 360 = 270 -> 270 / 10 = 27

    def test_the_aircrafts_yaw_turns_the_scan_into_the_local_frame(self):
        # aircraft facing local +y (yaw 90 degrees): an object straight ahead of the sensor is at local azimuth 90
        grid = self.lidar_range_grid(points(polar(2.0, 0.0, 0.0)), math.radians(90.0), start_angle_deg=0.0)
        self.assertAlmostEqual(grid[9, 1], 2.0, places=3)

    def test_the_height_of_a_return_picks_its_row(self):
        grid = self.lidar_range_grid(points(polar(3.0, 40.0, 10.0), polar(3.0, 80.0, 20.0)), 0.0, 0.0)
        self.assertAlmostEqual(grid[4, 2], 3.0, places=2)           # 10 degrees up -> row 2
        self.assertAlmostEqual(grid[8, 3], 3.0, places=2)           # 20 degrees up -> row 3

    def test_the_downward_row_is_ignored_so_the_ground_is_not_an_obstacle(self):
        grid = self.lidar_range_grid(points(polar(2.9, 0.0, -10.0)), 0.0, 0.0)
        self.assertTrue((grid == MAX_RAY_M).all())

    def test_the_nearest_return_in_a_direction_wins_and_far_ones_are_capped(self):
        grid = self.lidar_range_grid(points(polar(3.0, 0.0, 0.0), polar(1.5, 2.0, 0.0), polar(9.0, 90.0, 0.0)), 0.0, 0.0)
        self.assertAlmostEqual(grid[0, 1], 1.5, places=2)
        self.assertEqual(grid[9, 1], MAX_RAY_M)

    def test_returns_on_the_aircrafts_own_frame_are_ignored(self):
        grid = self.lidar_range_grid(points(polar(0.2, 0.0, 0.0)), 0.0, 0.0)
        self.assertTrue((grid == MAX_RAY_M).all())


class TestAirSimAdapterCalls(unittest.TestCase):
    def _adapter(self):
        calls = []

        class Client:
            def moveByVelocityAsync(self, vx, vy, vz, duration, vehicle_name=None):
                calls.append(("velocity", vx, vy, vz, duration, vehicle_name))

            def getLidarData(self, lidar_name=None, vehicle_name=None):
                calls.append(("lidar", lidar_name, vehicle_name))
                return SimpleNamespace(point_cloud=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

            def getMultirotorState(self, vehicle_name=None):
                half = math.radians(90.0) / 2.0     # yaw 90 degrees about the down axis
                return SimpleNamespace(kinematics_estimated=SimpleNamespace(orientation=SimpleNamespace(
                    w_val=math.cos(half), x_val=0.0, y_val=0.0, z_val=math.sin(half))))

        import threading
        a = AirSimVehicleAdapter.__new__(AirSimVehicleAdapter)
        a.vehicle_name = "Drone1"
        a.client = Client()
        a._lock = threading.Lock()
        return a, calls

    def test_velocity_is_sent_with_height_up_turned_into_ned_down(self):
        a, calls = self._adapter()
        a.start_velocity(1.5, -0.5, 0.8)
        self.assertEqual(calls, [("velocity", 1.5, -0.5, -0.8, VELOCITY_HOLD_S, "Drone1")])

    def test_the_lidar_scan_comes_with_the_yaw(self):
        a, calls = self._adapter()
        pts, yaw = a.get_lidar_scan()
        self.assertEqual(pts, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertAlmostEqual(yaw, math.radians(90.0), places=6)
        self.assertEqual(calls[0], ("lidar", "NavLidar", "Drone1"))


if __name__ == "__main__":
    unittest.main()
