#!/usr/bin/env python3
"""Tests for the ground reference: how high the ground is believed to be.

    python -m unittest discover tests

WHY THESE EXIST
---------------
`arm()` establishes where the ground is by watching the aircraft until it stops
moving. That works when the aircraft is falling to the ground, and fails
silently when it is being held motionless above it -- SimpleFlight holds an
armed aircraft wherever it was, and a frozen one does not move either. Both
look identical to a stillness test, and `ground_settled` only records that the
number stopped changing, not that it is right.

Observed 2026-10-06: the agent printed "armed, ground z = -0.18" against a true
29.25 and flew the whole run against it. Before that, 2026-09-29, three M01 runs
read 12.07, 12.17 and 12.12 and landed 17 m in the air; Block A's 24 flights
recorded 10.87-11.02 and did the same.

The ground under a given drone is a constant for the session, because
reset_world() returns every vehicle to the same pose. So a run that measures
something different has measured wrong, and is refused rather than recorded.
These tests need no simulator and no model.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "baseline"))

import open_loop_agent as agent  # noqa: E402


class GroundReferenceTests(unittest.TestCase):

    def setUp(self):
        agent.forget_ground_reference()

    def tearDown(self):
        agent.forget_ground_reference()

    def test_first_measurement_is_accepted_and_returned(self):
        self.assertEqual(agent.check_ground_reference("Drone1", 29.25), 29.25)

    def test_second_measurement_agreeing_returns_the_reference(self):
        agent.check_ground_reference("Drone1", 29.25)
        self.assertEqual(agent.check_ground_reference("Drone1", 29.31), 29.25)

    def test_the_observed_failure_is_refused(self):
        """The real case: a true ground of 29.25 followed by a held hover."""
        agent.check_ground_reference("Drone1", 29.25)
        with self.assertRaises(agent.GroundReferenceError):
            agent.check_ground_reference("Drone1", -0.18)

    def test_the_2026_09_29_failure_is_refused(self):
        agent.check_ground_reference("Drone1", 29.25)
        for bad in (12.07, 12.17, 12.12, 10.87, 11.02):
            with self.assertRaises(agent.GroundReferenceError):
                agent.check_ground_reference("Drone1", bad)

    def test_tolerance_boundary_is_inclusive(self):
        agent.check_ground_reference("Drone1", 29.25)
        agent.check_ground_reference(
            "Drone1", 29.25 + agent.GROUND_REFERENCE_TOLERANCE)
        with self.assertRaises(agent.GroundReferenceError):
            agent.check_ground_reference(
                "Drone1", 29.25 + agent.GROUND_REFERENCE_TOLERANCE + 0.01)

    def test_each_vehicle_has_its_own_reference(self):
        """Spawn spacing puts drones over different terrain."""
        agent.check_ground_reference("Drone1", 29.25)
        agent.check_ground_reference("Drone4", 27.29)
        self.assertEqual(agent.check_ground_reference("Drone1", 29.25), 29.25)
        self.assertEqual(agent.check_ground_reference("Drone4", 27.29), 27.29)

    def test_message_names_both_values_so_the_log_is_diagnostic(self):
        agent.check_ground_reference("Drone1", 29.25)
        with self.assertRaises(agent.GroundReferenceError) as caught:
            agent.check_ground_reference("Drone1", -0.18)
        message = str(caught.exception)
        for fragment in ("Drone1", "-0.18", "29.25"):
            self.assertIn(fragment, message)

    def test_forgetting_one_vehicle_leaves_the_others(self):
        agent.check_ground_reference("Drone1", 29.25)
        agent.check_ground_reference("Drone2", 29.28)
        agent.forget_ground_reference("Drone1")
        # Re-registering is allowed, but still has to agree with Drone2, which
        # is why 5.0 is refused here where a lone drone would have been believed.
        self.assertEqual(agent.check_ground_reference("Drone1", 29.30), 29.30)
        with self.assertRaises(agent.GroundReferenceError):
            agent.check_ground_reference("Drone2", 5.0)

    def test_a_first_reading_is_checked_against_the_other_drones(self):
        """The hole the per-drone check left, and the case that exposed it.

        Measured 2026-10-06: two drones armed seconds apart in the same world
        reported 29.25 and -0.28. The second was that drone's first reading, so
        nothing questioned it, and it flew its 18 m leg at about 50 m.
        """
        agent.check_ground_reference("Drone1", 29.25)
        with self.assertRaises(agent.GroundReferenceError) as caught:
            agent.check_ground_reference("Drone3", -0.28)
        message = str(caught.exception)
        self.assertIn("Drone1", message)
        self.assertIn("-0.28", message)

    def test_real_terrain_relief_between_spawn_points_is_allowed(self):
        """The four M10 spawn points measured 29.25, 29.28, 29.28 and 27.29."""
        for name, value in (("Drone1", 29.25), ("Drone2", 29.28),
                            ("Drone3", 29.28), ("Drone4", 27.29)):
            self.assertEqual(agent.check_ground_reference(name, value), value)

    def test_the_spread_tolerance_is_wider_than_the_per_drone_one(self):
        """Terrain varies between spawn points; one drone's ground does not."""
        self.assertGreater(agent.GROUND_SPREAD_TOLERANCE,
                           agent.GROUND_REFERENCE_TOLERANCE)

    def test_error_is_a_runtime_error_so_fly_records_it_as_a_failure(self):
        self.assertTrue(issubclass(agent.GroundReferenceError, RuntimeError))


if __name__ == "__main__":
    unittest.main()


class ContactClassificationTests(unittest.TestCase):
    """Every name here was observed in a real flight on 2026-10-06."""

    DRONES = ["Drone1", "Drone2", "Drone3", "Drone4"]

    def kind(self, name):
        return agent.classify_contact(name, self.DRONES)

    def test_terrain_is_ground(self):
        self.assertEqual(self.kind("Town10HD_Terrain_GroundNode_1088"), "ground")
        self.assertEqual(self.kind("Town10HD_Terrain_Ground_64"), "ground")

    def test_the_player_start_surface_is_ground(self):
        """SM_seaM is what the aircraft rests on, measured at 0.00 m AGL."""
        self.assertEqual(self.kind("SM_seaM"), "ground")

    def test_another_drone_is_its_own_category(self):
        """What M09 and M10 exist to measure, and not an obstacle."""
        self.assertEqual(self.kind("Drone1"), "drone")
        self.assertEqual(self.kind("Drone3"), "drone")

    def test_the_spectator_camera_is_not_an_obstacle(self):
        self.assertEqual(self.kind("SpectatorPawn_2147444257"), "camera")

    def test_a_real_obstacle_is_an_obstacle(self):
        for name in ("BP_Building_42", "BP_Vehicle_Tesla_3", "SM_Tree_07",
                     "BP_StreetLight_12"):
            self.assertEqual(self.kind(name), "obstacle", name)

    def test_an_unknown_or_empty_name_counts_against_the_flight(self):
        """Unknown is treated as an obstacle: the safe direction to be wrong."""
        self.assertEqual(self.kind(""), "obstacle")
        self.assertEqual(self.kind("Something_Unrecognised"), "obstacle")

    def test_a_drone_name_wins_over_a_ground_marker(self):
        """A vehicle called Drone3_Ground is a drone, not the floor."""
        self.assertEqual(self.kind("Drone3_GroundTest"), "drone")

    def test_classification_without_a_drone_roster_still_works(self):
        self.assertEqual(agent.classify_contact("SM_seaM"), "ground")
        self.assertEqual(agent.classify_contact("SpectatorPawn_1"), "camera")
        self.assertEqual(agent.classify_contact("Drone1"), "obstacle")

    def test_the_m10_contact_set_splits_as_measured(self):
        """The 16 polled events of one M10 run: 1 ground, 11 floor/camera, 4 drone."""
        observed = [
            "Town10HD_Terrain_GroundNode_1088", "SM_seaM", "SM_seaM", "SM_seaM",
            "Drone3", "Drone1", "Drone3", "Drone1", "Drone3", "Drone1",
            "SpectatorPawn_2147444257", "SpectatorPawn_2147444257",
            "SpectatorPawn_2147444257", "SM_seaM", "SM_seaM", "SM_seaM",
        ]
        kinds = [self.kind(n) for n in observed]
        self.assertEqual(kinds.count("obstacle"), 0)
        self.assertEqual(kinds.count("drone"), 6)
        self.assertEqual(kinds.count("camera"), 3)
        self.assertEqual(kinds.count("ground"), 7)


class GroundCredibilityTests(unittest.TestCase):
    """Which of two disagreeing readings is believed.

    In NED a larger z is lower, and an aircraft can only be at or above the
    ground, so the larger reading is nearer the truth. Refusing whichever
    arrived second got this backwards in flight on 2026-10-06: Drone3 armed
    first with -0.23, became the reference, and Drone1's correct 29.25 was
    refused.
    """

    def setUp(self):
        agent.forget_ground_reference()

    tearDown = setUp

    def test_a_mid_air_reading_is_refused_however_late_it_arrives(self):
        agent.check_ground_reference("Drone1", 29.25)
        with self.assertRaises(agent.GroundReferenceError):
            agent.check_ground_reference("Drone3", -0.23)

    def test_a_credible_reading_is_adopted_even_if_it_arrives_second(self):
        """The flight case, in the order it actually happened."""
        agent.check_ground_reference("Drone3", -0.23)        # bad, arrives first
        self.assertEqual(agent.check_ground_reference("Drone1", 29.25), 29.25)

    def test_adopting_it_discards_the_readings_it_contradicts(self):
        agent.check_ground_reference("Drone3", -0.23)
        agent.check_ground_reference("Drone1", 29.25)
        # Drone3's -0.23 is gone, so re-arming it must now agree with 29.25.
        with self.assertRaises(agent.GroundReferenceError):
            agent.check_ground_reference("Drone3", -0.23)
        self.assertEqual(agent.check_ground_reference("Drone3", 29.28), 29.28)


class GroundBarrierTests(unittest.TestCase):
    """Judging a reading needs the complete set, which needs a barrier.

    Without one the first drone to arm sets the reference unchallenged. Measured
    2026-10-06: Drone3 armed at -0.18 before Drone1 found 29.25, and flew its
    whole mission against it.
    """

    def setUp(self):
        agent.forget_ground_reference()

    tearDown = setUp

    def test_one_reading_alone_is_not_judged(self):
        """A single-drone run has nothing to compare against."""
        agent.register_ground("Drone1", -0.18)
        agent.validate_grounds("Drone1")          # must not raise

    def test_the_mid_air_reading_is_refused_whichever_registered_first(self):
        for order in ([("Drone3", -0.18), ("Drone1", 29.25)],
                      [("Drone1", 29.25), ("Drone3", -0.18)]):
            agent.forget_ground_reference()
            for name, z in order:
                agent.register_ground(name, z)
            agent.validate_grounds("Drone1")      # the credible one is fine
            with self.assertRaises(agent.GroundReferenceError):
                agent.validate_grounds("Drone3")

    def test_real_terrain_relief_passes(self):
        for name, z in (("Drone1", 29.25), ("Drone2", 29.28),
                        ("Drone3", 29.28), ("Drone4", 27.29)):
            agent.register_ground(name, z)
        for name in ("Drone1", "Drone2", "Drone3", "Drone4"):
            agent.validate_grounds(name)

    def test_the_message_lists_every_reading_for_diagnosis(self):
        agent.register_ground("Drone1", 29.25)
        agent.register_ground("Drone3", -0.18)
        with self.assertRaises(agent.GroundReferenceError) as caught:
            agent.validate_grounds("Drone3")
        message = str(caught.exception)
        for fragment in ("Drone1=29.25", "Drone3=-0.18"):
            self.assertIn(fragment, message)

    def test_it_refuses_rather_than_substituting_another_drones_ground(self):
        """The deepest reading is another drone's terrain, not a replacement."""
        agent.register_ground("Drone1", 29.25)
        agent.register_ground("Drone3", -0.18)
        with self.assertRaises(agent.GroundReferenceError):
            agent.validate_grounds("Drone3")
        self.assertNotIn("Drone3", agent._GROUND_REFERENCE)
