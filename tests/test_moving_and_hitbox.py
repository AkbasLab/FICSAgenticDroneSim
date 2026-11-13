"""Two things the guardian did not do: count the drone's body (not just its centre point) against a no-fly zone, and keep clear
of vehicles and pedestrians that move. Mock-only, no simulator."""

import math
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.guardian import Guardian
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.agents.safety_guardian import SafetyGuardian, SafetyLimits
from fics_drone.agents.safety_guardian import Command
from fics_drone.core import moving
from fics_drone.core.moving import MovingObject, ScriptedMovers
from fics_drone.core.scenario import DRONE_RADIUS_M, NoFlyZone, load_scenario
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")


def fly(x, y, z=4.0):
    return Command(kind="fly", target=(x, y, z), speed_mps=3.0, timeout_s=30.0, purpose="search")


class HitboxTests(unittest.TestCase):
    def test_the_body_edge_counts_not_just_the_centre(self):
        zone = NoFlyZone("Z", 0.0, 10.0, 0.0, 10.0)
        self.assertFalse(zone.contains(10.3, 5.0))                    # the centre point is outside
        self.assertTrue(zone.contains(10.3, 5.0, None, 0.5))          # but the body, half a metre wide, has crossed the edge
        self.assertFalse(zone.contains(10.6, 5.0, None, 0.5))

    def test_the_hitbox_grows_a_scheduled_zone_too(self):
        zone = NoFlyZone("Z", 0.0, 10.0, 0.0, 10.0, active_from_s=5.0, active_until_s=20.0, vx=1.0)
        self.assertFalse(zone.contains(9.9, 5.0, 4.0, 0.5))           # not on yet
        self.assertTrue(zone.contains(-0.3, 5.0, 5.0, 0.5))           # on, and the body touches the near edge
        self.assertTrue(zone.contains(15.3, 5.0, 10.0, 0.5))          # it has drifted 5 m: the far edge is now at 15
        self.assertFalse(zone.contains(15.6, 5.0, 10.0, 0.5))

    def test_the_guardian_keeps_the_body_out_of_a_zone(self):
        zone = NoFlyZone("Z", 0.0, 10.0, 0.0, 10.0)
        g = SafetyGuardian(limits=SafetyLimits(restricted_zones=[zone], geofence_half_extent_m=200.0))
        self.assertEqual(g.limits.drone_radius_m, DRONE_RADIUS_M)
        self.assertFalse(g._check_restricted_zones(fly(10.3, 5.0)).passed)    # a centre 0.3 m clear of the edge: the body is in
        self.assertTrue(g._check_restricted_zones(fly(10.7, 5.0)).passed)

    def test_the_older_guardian_agrees(self):
        zone = NoFlyZone("Z", 0.0, 10.0, 0.0, 10.0)
        self.assertFalse(Guardian([zone]).check((10.3, 5.0, 8.0))[0])
        self.assertTrue(Guardian([zone], drone_radius_m=0.0).check((10.3, 5.0, 8.0))[0])

    def test_a_drone_whose_body_is_in_a_dynamic_zone_is_seen_to_be_in_it(self):
        zone = NoFlyZone("Z", 0.0, 10.0, 0.0, 10.0, active_from_s=0.0, active_until_s=50.0, vx=0.1)
        g = SafetyGuardian(limits=SafetyLimits(restricted_zones=[zone], geofence_half_extent_m=200.0))
        self.assertTrue(g.in_active_dynamic_zone((10.3, 5.0), 1.0))
        self.assertFalse(g.in_active_dynamic_zone((11.0, 5.0), 1.0))


class ColumnTests(unittest.TestCase):
    def test_a_standing_person_is_one_padded_column(self):
        cols = moving.columns([MovingObject("p1", "pedestrian", 5.0, 5.0, radius=0.4)], pad_m=1.5, lookahead_s=3.0)
        self.assertEqual(len(cols), 1)
        self.assertAlmostEqual(cols[0].trunk_r, 1.9)
        self.assertTrue(cols[0].blocks_point(5.0, 6.8, 3.0))
        self.assertFalse(cols[0].blocks_point(5.0, 7.0, 3.0))

    def test_a_moving_car_is_swept_along_where_it_will_be(self):
        car = MovingObject("c1", "vehicle", 0.0, 0.0, vx=10.0, vy=0.0, radius=2.5)
        cols = moving.columns([car], pad_m=1.5, lookahead_s=3.0)
        xs = [c.x for c in cols]
        self.assertAlmostEqual(min(xs), 0.0)
        self.assertAlmostEqual(max(xs), 30.0)                         # where it will be in 3 s
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        self.assertLess(max(gaps), 4.0)                               # no gap wider than the column: nothing slips through the sweep
        self.assertTrue(any(c.blocks_point(30.0, 3.0, 3.0) for c in cols))

    def test_a_person_only_matters_to_an_aircraft_that_is_low(self):
        cols = moving.columns([MovingObject("p", "pedestrian", 5.0, 5.0, radius=0.4, height=1.8)], pad_m=1.5, lookahead_s=3.0)
        self.assertTrue(cols[0].blocks_point(5.0, 5.0, 5.0))          # 5 m up: under the person's top plus the 4 m pad (5.8)
        self.assertFalse(cols[0].blocks_point(5.0, 5.0, 8.0))         # cruising at 8 m or higher passes over
        self.assertFalse(cols[0].blocks_point(5.0, 5.0, -2.0 - 1000.0))

    def test_scripted_movers_walk_in_a_straight_line(self):
        now = [100.0]
        m = ScriptedMovers([MovingObject("p", "pedestrian", 0.0, 0.0, vx=1.5, vy=0.5)], clock=lambda: now[0])
        now[0] = 104.0
        o = m.snapshot()[0]
        self.assertAlmostEqual(o.x, 6.0)
        self.assertAlmostEqual(o.y, 2.0)


class GuardianMovingTests(unittest.TestCase):
    def _guardian(self, objects):
        feed = ScriptedMovers(objects, clock=lambda: 0.0)
        return SafetyGuardian(limits=SafetyLimits(geofence_half_extent_m=200.0, moving_fn=feed.snapshot))

    def test_no_moving_objects_changes_nothing(self):
        g = SafetyGuardian(limits=SafetyLimits(geofence_half_extent_m=200.0))
        self.assertTrue(g._check_obstacles(fly(10, 0), (0, 0, 4)).passed)

    def test_a_leg_that_ends_beside_a_pedestrian_is_refused(self):
        g = self._guardian([MovingObject("p", "pedestrian", 10.0, 0.0, radius=0.4)])
        self.assertFalse(g._check_obstacles(fly(10.0, 1.5), (0, 20, 4)).passed)
        self.assertTrue(g._check_obstacles(fly(10.0, 3.0), (0, 20, 4)).passed)

    def test_a_leg_through_a_standing_car_is_refused(self):
        g = self._guardian([MovingObject("c", "vehicle", 15.0, 0.0, radius=2.5)])
        self.assertFalse(g._check_obstacles(fly(30, 0), (0, 0, 4)).passed)
        self.assertTrue(g._check_obstacles(fly(30, 12), (0, 12, 4)).passed)

    def test_a_leg_across_a_road_is_refused_while_a_car_is_about_to_cross_it(self):
        # the car is 30 m up the road and moving 10 m/s toward the line the drone will fly: it is there in 3 s
        g = self._guardian([MovingObject("c", "vehicle", 15.0, -30.0, vx=0.0, vy=10.0, radius=2.5)])
        self.assertFalse(g._check_obstacles(fly(30, 0), (0, 0, 4)).passed)
        # the same car moving away from the line does not stop it
        g = self._guardian([MovingObject("c", "vehicle", 15.0, -30.0, vx=0.0, vy=-10.0, radius=2.5)])
        self.assertTrue(g._check_obstacles(fly(30, 0), (0, 0, 4)).passed)

    def test_a_far_body_does_not_hold_a_leg_back_when_a_reactive_planner_flies_it(self):
        g = self._guardian([MovingObject("p", "pedestrian", 25.0, 0.0, radius=0.4)])
        self.assertFalse(g._check_obstacles(fly(40, 0), (0, 0, 4)).passed)          # no reactive planner: the whole leg is checked
        g.limits.moving_check_range_m = 15.0
        self.assertTrue(g._check_obstacles(fly(40, 0), (0, 0, 4)).passed)           # 25 m off: left to the planner in flight
        g = self._guardian([MovingObject("p", "pedestrian", 8.0, 0.0, radius=0.4)])
        g.limits.moving_check_range_m = 15.0
        self.assertFalse(g._check_obstacles(fly(40, 0), (0, 0, 4)).passed)          # 8 m off: still refused
        self.assertFalse(g._check_obstacles(fly(25.0, 0.2), (0, 0, 4)).passed)      # and a target in the column is always refused

    def test_a_cruising_aircraft_flies_over_a_person_without_a_detour(self):
        g = self._guardian([MovingObject("p", "pedestrian", 15.0, 0.0, radius=0.4, height=1.8)])
        self.assertTrue(g._check_obstacles(fly(30, 0, 12.0), (0, 0, 12.0)).passed)
        self.assertFalse(g._check_obstacles(fly(30, 0, 4.0), (0, 0, 4.0)).passed)

    def test_an_aircraft_already_close_to_a_person_can_still_leave(self):
        g = self._guardian([MovingObject("p", "pedestrian", 0.5, 0.0, radius=0.4)])
        self.assertTrue(g._check_obstacles(fly(10, 0), (0, 0, 4)).passed)     # a leg that moves away is not blocked by it

    def test_a_failing_feed_does_not_stop_the_guardian(self):
        def broken():
            raise RuntimeError("sim not answering")
        g = SafetyGuardian(limits=SafetyLimits(geofence_half_extent_m=200.0, moving_fn=broken))
        self.assertTrue(g._check_obstacles(fly(10, 0), (0, 0, 4)).passed)


class AgentMovingTests(unittest.TestCase):
    def _agent(self, objects):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name=spec.name)
        agent.belief.position = (0.0, 0.0, 4.0)
        feed = ScriptedMovers(objects)
        agent.guardian.limits.moving_fn = feed.snapshot
        return agent, adapter

    def test_the_route_planner_is_shown_the_moving_objects(self):
        agent, _ = self._agent([MovingObject("p", "pedestrian", 15.0, 0.0, radius=0.4)])
        near = [o for o in agent._route_obstacles() if hasattr(o, "x") and abs(o.x - 15.0) < 0.1 and abs(o.y) < 0.1]
        self.assertTrue(near)

    def test_a_reactive_planner_is_left_to_steer_round_standing_people_itself(self):
        person = MovingObject("p", "pedestrian", 15.0, 0.0, radius=0.4)
        agent, _ = self._agent([person])
        near = lambda: [o for o in agent._route_obstacles() if hasattr(o, "x") and abs(o.x - 15.0) < 0.1 and abs(o.y) < 0.1]
        self.assertTrue(near())                                       # no leg planner: the route is planned round the standing person
        agent.leg_planner = type("Reactive", (), {"movers_fn": staticmethod(lambda: [person])})()
        self.assertFalse(near())                                      # a planner that sees movers does the steering

    def test_a_standing_pedestrian_on_the_line_is_flown_round_and_never_touched(self):
        person = MovingObject("p", "pedestrian", 15.0, 0.0, radius=0.4)
        agent, adapter = self._agent([person])
        closest, stop = [1e9], threading.Event()

        def watch():
            while not stop.is_set():
                x, y, _ = adapter.get_position()
                closest[0] = min(closest[0], math.hypot(x - person.x, y - person.y))
                time.sleep(0.005)

        threading.Thread(target=watch, daemon=True).start()
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 4.0), trace)
        stop.set()
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertGreater(closest[0], person.radius + DRONE_RADIUS_M, (closest[0], trace))


class AgentWaitsForMoversTests(unittest.TestCase):
    def _agent(self, feed):
        scenario = load_scenario(SCENARIO_PATH)
        spec = next(d for d in scenario.drones if d.name == "Drone1")
        adapter = KinematicMockVehicleAdapter(spec.name, speed_mps=15.0)
        agent = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset, spec.battery_s, drone_name=spec.name)
        agent.belief.position = (0.0, 0.0, 4.0)
        agent.guardian.limits.moving_fn = feed
        return agent, adapter

    def test_a_leg_refused_for_a_moving_body_is_held_and_planned_again(self):
        # the route planner is shown an empty street, then the guardian finds a pedestrian on the line: the leg is not given up
        calls = {"n": 0}
        person = MovingObject("p", "pedestrian", 15.0, 0.0, radius=0.4, height=1.8)

        def feed():
            calls["n"] += 1
            return [] if calls["n"] == 1 else ([person] if calls["n"] <= 4 else [])
        agent, adapter = self._agent(feed)
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 4.0), trace)
        self.assertEqual(event.value, "skill_succeeded", trace)
        self.assertIn("waited_for_mover", trace)

    def test_a_pedestrian_who_never_leaves_does_not_hold_the_leg_forever(self):
        person = MovingObject("p", "pedestrian", 30.0, 0.0, radius=0.4, height=1.8)       # standing on the target itself
        agent, adapter = self._agent(lambda: [person])
        trace = []
        event = agent._guarded_fly((30.0, 0.0, 4.0), trace)
        self.assertEqual(event.value, "guardian_blocked")
        self.assertLessEqual(trace.count("waited_for_mover"), 6)


if __name__ == "__main__":
    unittest.main()



class CarlaMoversCacheTests(unittest.TestCase):
    """The size of a body is read from the simulator once, not on every refresh (each read is a round trip, about 18 ms)."""

    def test_the_bounding_box_is_read_once_per_actor(self):
        reads = {"n": 0}

        class Box:
            @property
            def extent(self_inner):
                reads["n"] += 1
                return type("E", (), {"x": 2.0, "y": 0.9, "z": 0.75})

        class Vec:
            def __init__(self, x=0.0, y=0.0, z=0.0):
                self.x, self.y, self.z = x, y, z

        class Rot:
            yaw = 0.0

        class Tf:
            rotation = Rot()

        class Actor:
            id = 7
            type_id = "vehicle.audi.a2"
            bounding_box = Box()

            def get_location(self):
                return Vec(10.0, 5.0)

            def get_velocity(self):
                return Vec(3.0, 0.0)

            def get_transform(self):
                return Tf()

        class World:
            def get_actors(self):
                return [Actor()]

        from fics_drone.core.moving import CarlaMovers
        feed = CarlaMovers(World(), origin=(0.0, 0.0), refresh_s=0.0)
        for _ in range(5):
            out = feed.snapshot()
        self.assertEqual(len(out), 1)
        self.assertEqual(reads["n"], 1)
        self.assertAlmostEqual(out[0].radius, (2.0 ** 2 + 0.9 ** 2) ** 0.5)
