"""The simulator's side of sensing: a drone's readings, built from ground truth it never sees.

    sensors = mock_sensors(world, scenario, "Drone1")    # hand only this to the agent

Ground truth stays here: the scenario, the targets placed from its seed, every
drone's exact path. What leaves is `core.sensing.Sensors` -- functions of the
present instant that answer only what one drone could know (see that module
for what each reading means). The agent never receives the world, the
scenario or the targets, so it cannot read them by accident or by design.

EACH READING IS PHASE 4'S OWN RULE, applied up to now, on the mock's exact
trace (`mock_trajectories(..., until_now=True)`):

* own state: the drone's position at this instant, and its landed flag;
* battery: `mission_world.battery` over the drone's path since `start`;
* sightings: `mission_world.detections` over the drone's OWN path since
  `start` -- a target held 2 s by another drone is not this drone's sighting;
* base link: the radio graph at this instant (every scenario drone and the
  base, links no longer than the range in 3D), and whether it joins this
  drone to the base.

So a reading taken in flight agrees exactly with what the evaluator will
later say about the same instant; a test holds them to it.
"""

from __future__ import annotations

import math
from collections import deque

from ..core.scenario import Scenario
from ..core.sensing import OwnState, Sensors, Sighting
from .mission_world import battery, detections, place_targets
from .mock_adapter import MockWorld
from .observer import mock_trajectories


def mock_sensors(world: MockWorld, scenario: Scenario, drone: str,
                 start: float | None = None) -> Sensors:
    """`drone`'s readings in `world`, counted from `start` (default: now)."""
    names = [v.id for v in scenario.vehicles]
    if drone not in names:
        raise ValueError(f"{drone} is not one of {scenario.scenario_id}'s drones")
    missing = [n for n in names if n not in world.vehicles]
    if missing:
        raise ValueError(f"the world has no {missing}")
    t0 = world.clock.now() if start is None else start
    targets = place_targets(scenario)
    base = (scenario.base.x, scenario.base.y, 0.0)
    range_m = scenario.network.communication_range_m

    def now() -> float:
        # A function, not the clock's bound method: a bound method's
        # __self__ would lead back to an object of the world.
        return world.clock.now()

    def own_path():
        return mock_trajectories(world, [drone], until_now=True)[drone]

    def own_state() -> OwnState:
        now = world.clock.now()
        k = own_path().knots[-1]
        return OwnState(now, k.x, k.y, k.altitude_m, k.airborne)

    def battery_now() -> float:
        return battery(own_path(), scenario.battery, t0, world.clock.now()).remaining

    def sightings_now() -> tuple[Sighting, ...]:
        found = detections([own_path()], targets, scenario.detection, t0, world.clock.now())
        where = {t.id: t for t in targets}
        return tuple(Sighting(d.target, where[d.target].x, where[d.target].y, d.detected_at) for d in found)

    def base_link_now() -> bool:
        paths = mock_trajectories(world, names, until_now=True)
        now = world.clock.now()
        points = {n: paths[n].position_at(now) for n in names}
        return drone in _reach_base(points, base, range_m)

    return Sensors(drone, now, own_state, battery_now, sightings_now, base_link_now)


def _reach_base(points: dict[str, tuple[float, float, float]], base: tuple[float, float, float],
                range_m: float) -> set[str]:
    """The drones a chain of links no longer than `range_m` joins to the base."""
    reached: set[str] = set()
    frontier = deque([base])
    while frontier:
        here = frontier.popleft()
        for name, p in points.items():
            if name not in reached and math.dist(here, p) <= range_m:
                reached.add(name)
                frontier.append(p)
    return reached
