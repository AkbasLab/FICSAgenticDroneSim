"""An aircraft must not go on flying on a command nobody renewed (the real adapter lets a velocity command lapse), and a detour
must never stop at a way-point inside a keep-out's margin."""
import time
import unittest

from fics_drone.control.leg_planner_skill import fly_leg_with_planner
from fics_drone.core.obstacles import TreeObstacle
from fics_drone.planners.street_path import plan_around
from fics_drone.simulator.kinematic_mock_adapter import VELOCITY_HOLD_S, KinematicMockVehicleAdapter


def pole(x, y, r=2.5):
    return TreeObstacle(x=x, y=y, z_bottom=0.0, z_top=25.0, trunk_r=r, crown_r=r, crown_from_frac=0.0)


class MockVelocityTests(unittest.TestCase):
    def test_a_velocity_command_lapses(self):
        adapter = KinematicMockVehicleAdapter()
        adapter.start_velocity(4.0, 0.0)
        time.sleep(VELOCITY_HOLD_S + 0.4)
        x, _, _ = adapter.get_position()
        self.assertLessEqual(x, 4.0 * VELOCITY_HOLD_S + 0.05)      # it flew for the hold time only
        self.assertEqual(adapter.get_speed(), 0.0)
        time.sleep(0.3)
        self.assertEqual(adapter.get_position()[0], x)              # and stays where it got to

    def test_a_renewed_velocity_command_goes_on(self):
        adapter = KinematicMockVehicleAdapter()
        for _ in range(4):
            adapter.start_velocity(4.0, 0.0)
            time.sleep(0.4)
        self.assertGreater(adapter.get_position()[0], 4.0 * 1.2)

    def test_landing_stops_the_aircraft(self):
        adapter = KinematicMockVehicleAdapter()
        adapter.start_velocity(4.0, 0.0)
        time.sleep(0.2)
        adapter.land()
        x = adapter.get_position()[0]
        time.sleep(0.3)
        self.assertEqual(adapter.get_position()[0], x)
        self.assertEqual(adapter.get_speed(), 0.0)


class _BrokenPlanner:
    wants_adapter = False

    def begin_leg(self, start, goal):
        raise RuntimeError("planner failed")


class FailedLegTests(unittest.TestCase):
    def test_a_leg_that_raises_leaves_the_aircraft_hovering_and_says_where_it_is(self):
        adapter = KinematicMockVehicleAdapter(start_position=(5.0, 5.0, 12.0))
        adapter.start_velocity(4.0, 0.0)            # still flying on the last leg's command
        result = fly_leg_with_planner(adapter, 50.0, 5.0, 12.0, _BrokenPlanner(), lambda: [])
        self.assertEqual(result.status.value, "failed")
        self.assertIsNotNone(result.final_position)
        self.assertEqual(adapter.get_speed(), 0.0)
        self.assertIn("planner failed", result.error)


class WayPointTests(unittest.TestCase):
    def test_no_way_point_inside_a_margin_when_the_start_is_inside_one(self):
        trees = [pole(0.0, 0.0), pole(0.0, 9.0), pole(6.0, 4.5)]
        start, goal = (-2.0, 0.5, 12.0), (14.0, 4.5, 12.0)          # inside the first pole's margin
        path = plan_around(start, goal, trees, margin=2.0)
        if path is not None:
            for x, y, z in path[:-1]:
                self.assertFalse(any(t.blocks_point(x, y, z, margin=2.0) for t in trees), (x, y))


if __name__ == "__main__":
    unittest.main()
