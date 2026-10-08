"""The Phase 4 exit criterion: a fully scripted, non-agentic controller that
completes the canonical mission - 100% coverage, both targets found, every
other criterion PASS. No LLM, no planning - this is the bar the later,
actually-agentic architecture (Phase 5 onward) has to beat.

Strategy: lawnmower (boustrophedon) sweep. Each drone flies straight lanes
back and forth across its own sector, spaced close enough that consecutive
lanes' coverage circles overlap - then returns home.
"""

from typing import List, Tuple

from ..control.skills import follow_waypoints, hold_position, return_home, take_off
from ..core.scenario import Scenario, Sector, Target
from ..core.skill_result import SkillStatus
from ..evaluation.metrics import COVERAGE_RADIUS_M

LANE_SPACING_M = COVERAGE_RADIUS_M * 1.2  # < 2*radius with real margin - 2*radius is only an
# exact geometric guarantee for a continuous path; a corner cell can sit right at that boundary
# with zero slack, which discrete telemetry sampling + waypoint-arrival tolerance can then miss
DWELL_MARGIN_S = 0.5  # hold a bit longer than dwell_s so timing jitter can't fail a real find
ALTITUDE_STEP_M = 6.0  # > min_separation_m (5.0) so even two drones with ADJACENT altitude
# bands stay separated purely by altitude, with zero help needed from horizontal distance,
# at the moment their transit routes happen to cross in x/y


def lawnmower_waypoints(sector: Sector, height: float) -> List[Tuple[float, float, float]]:
    """Boustrophedon sweep: fly the full x-span at y=y_min, step up by
    LANE_SPACING_M, fly the x-span back, repeat until y_max is covered."""
    waypoints = []
    y = sector.y_min
    left_to_right = True
    while y <= sector.y_max:
        x_start, x_end = (sector.x_min, sector.x_max) if left_to_right else (sector.x_max, sector.x_min)
        waypoints.append((x_start, y, height))
        waypoints.append((x_end, y, height))
        y += LANE_SPACING_M
        left_to_right = not left_to_right
    return waypoints


def _targets_in_sector(sector: Sector, targets: List[Target]) -> List[Target]:
    return [t for t in targets
            if sector.x_min <= t.x <= sector.x_max and sector.y_min <= t.y <= sector.y_max]


def _to_local(point: Tuple[float, float, float], spawn_offset: Tuple[float, float, float]):
    """Sectors/targets are defined in world coordinates, but start_move_to
    operates in the drone's own local frame (its own (0,0,*) is its own
    spawn point) - subtract the offset the recorder later adds back, so a
    drone with a nonzero spawn_offset still flies to the right physical
    place, not to that offset applied a second time."""
    return (point[0] - spawn_offset[0], point[1] - spawn_offset[1], point[2] - spawn_offset[2])


def run_scripted_mission(scenario: Scenario, adapters: dict, height: float = 8.0) -> None:
    """Every drone's sweep runs on its own thread (mirrors FleetController's
    'plan up front, fly concurrently' shape) - the scenario is declarative and
    known in advance, so this scripted controller is allowed to use that: it
    doesn't just sweep and hope a target happens to fall under the flight
    path long enough, it detours to sit on each known target in its sector
    and holds there for dwell_s, which is what a *scripted, world-aware*
    baseline is supposed to do. A search-blind agent (later phases) won't
    have this shortcut."""
    import threading

    drone_index = {spec.name: i for i, spec in enumerate(scenario.drones)}

    def fly_one(name, adapter):
        result = take_off(adapter)
        if result.status != SkillStatus.SUCCESS:
            # No ground reference was ever recorded - every flight command past this
            # point needs one, so there is nothing safe left to do with this drone.
            print(f"{name}: takeoff failed ({result.error}) - aborting this drone, not flying it")
            return
        spec = next(d for d in scenario.drones if d.name == name)
        sector = scenario.sector(spec.sector)
        # Each drone gets its own cruise altitude, distinct by ALTITUDE_STEP_M per
        # drone. Sectors are far apart, but the transit routes from spawn into a
        # sector can still cross another drone's transit route in x/y before either
        # arrives - giving each drone its own altitude band means a path crossing
        # in x/y is still vertically separated, without needing real-time
        # coordination between drones (this baseline is scripted, not agentic).
        cruise = height + drone_index[name] * ALTITUDE_STEP_M
        # Climb straight up to cruise height before any horizontal move - a diagonal
        # climb-and-translate can briefly narrow the gap between drones whose spawn
        # points are otherwise safely separated, since two diagonal paths can cross.
        follow_waypoints(adapter, [(0.0, 0.0, cruise)])
        waypoints = [_to_local(wp, spec.spawn_offset) for wp in lawnmower_waypoints(sector, cruise)]
        follow_waypoints(adapter, waypoints)
        for target in _targets_in_sector(sector, scenario.targets):
            local_target = _to_local((target.x, target.y, cruise), spec.spawn_offset)
            follow_waypoints(adapter, [local_target])
            hold_position(adapter, target.dwell_s + DWELL_MARGIN_S)
        return_home(adapter)

    threads = [threading.Thread(target=fly_one, args=(name, adapter))
               for name, adapter in adapters.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
