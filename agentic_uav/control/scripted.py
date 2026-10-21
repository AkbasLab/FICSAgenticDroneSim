"""Phase 4's scripted, non-agentic controller: a fixed plan from the mission brief (AUV-05).

    plan = plan_mission(scenario.brief())
    plan["Drone1"].commands        # the skills Drone1 flies, in order

AUV-05's exit criterion: "a fully scripted, NON-AGENTIC controller can
complete the canonical mission" -- proof the mission is feasible before any
agent is asked to fly it. So nothing here decides anything in flight: the
whole plan is computed before take-off from the brief alone (no targets, no
seed), every drone flies its list of skills, and the same brief always gives
the same plan.

THE PLAN, and why each part:

* ONE DRONE PER SECTOR: drones and sectors each in id order, drone i taking
  sectors i, i + n, ... With four of each that is AUV-05's "obvious naive
  allocation", the baseline any coordination must beat.
* ITS OWN HEIGHT: 12, 16, 20, 24 m, 4 m apart -- the heights Phase 3 flew
  live in CarlaAir. Every route may then cross every other and no two drones
  are ever at one height, so separation holds whatever the timing.
* LANES the detection rule can see between: at speed v a point must stay
  within the radius r for the minimum observation time T, so a lane detects
  to sqrt(r^2 - (vT/2)^2) either side -- 8.66 m for the canonical 10 m, 2 s,
  5 m/s. Lanes are at most LANE_MARGIN of twice that apart, rounded up to
  whole lanes across the sector: 16 m in an 80 m sector. The margin is for
  live flight, which does not hold a lane exactly.
* ROUTES round restricted zones by `routing.route`, keeping ZONE_CLEARANCE_M,
  out to each sector's first lane, between sectors, and home to the pad.
  The search itself is the SEARCH_REGION skill's lawnmower; a lane that would
  pass within the clearance of a zone is refused, not flown.
* HOME is the drone's own pad, and it lands there.
* CHECKED BEFORE FLIGHT: the plan's length, time and battery are estimated
  with the brief's linear battery model, and a plan that would land under
  the reserve or finish after the deadline is refused before take-off.

Reporting needs nothing more here: a drone that detects a target in a far
sector is connected to the base again on its way home, which is AUV-05's
"eventually synchronized". Relaying earlier is coordination, for the agents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.scenario import DetectionSpec, MissionBrief
from . import navigation as nav
from .routing import Point2, clear, grown, length, route
from .skills import (
    DEFAULT_SPEED_MPS,
    FollowWaypointsCommand,
    LandCommand,
    SearchRegionCommand,
    SkillCommand,
    TakeOffCommand,
)

BASE_ALTITUDE_M = 12.0          # the first drone's height; Phase 3's lowest live height
ALTITUDE_STEP_M = 4.0           # between drones; Phase 3's live spacing
LANE_MARGIN = 0.95              # lanes at most this fraction of the widest the detection rule allows
ZONE_CLEARANCE_M = 2.0          # routes keep this far from every restricted zone
CLIMB_SPEED_MPS = 2.0           # for estimates only: take-off and landing are slower than cruise
ESTIMATE_SETTLE_S = 15.0        # per drone, for estimates: take-off settle, turns, landing settle


class PlanError(ValueError):
    """The brief cannot be flown by this controller within its limits."""


@dataclass(frozen=True)
class DronePlan:
    drone: str
    sectors: tuple[str, ...]
    altitude_m: float
    lane_spacing_m: float
    path: tuple[Point2, ...]          # the whole ground track, pad to pad
    length_m: float
    estimated_s: float
    estimated_battery_used: float
    commands: tuple[SkillCommand, ...]


def detection_half_width(detection: DetectionSpec, speed_mps: float) -> float:
    """How far either side of a straight lane a point is held long enough to detect."""
    half_chord = speed_mps * detection.min_observation_s / 2.0
    if half_chord >= detection.radius_m:
        raise PlanError(f"at {speed_mps} m/s nothing stays within {detection.radius_m} m "
                        f"for {detection.min_observation_s} s: fly slower")
    return math.sqrt(detection.radius_m ** 2 - half_chord ** 2)


def lane_spacing(width_m: float, detection: DetectionSpec, speed_mps: float) -> float:
    """Whole lanes across `width_m`, each no further apart than the detection rule allows."""
    widest = 2.0 * detection_half_width(detection, speed_mps) * LANE_MARGIN
    lanes = max(1, math.ceil(width_m / widest - 1e-9))
    return width_m / lanes


def plan_mission(brief: MissionBrief, speed_mps: float = DEFAULT_SPEED_MPS) -> dict[str, DronePlan]:
    """Every drone's plan, from the brief alone. Raises PlanError if it cannot be flown."""
    if not isinstance(brief, MissionBrief):
        # A Scenario has every field a brief has, and the targets too: refuse it.
        raise TypeError(f"plan_mission takes a MissionBrief (scenario.brief()), not {type(brief).__name__}")
    zones =[z.polygon for z in brief.restricted_zones]
    obstacles = [grown(z, ZONE_CLEARANCE_M) for z in zones]
    drones = sorted(brief.vehicles, key=lambda v: v.id)
    sectors = sorted(brief.sectors, key=lambda s: s.id)
    plans = {}
    for i, vehicle in enumerate(drones):
        mine = sectors[i::len(drones)]
        altitude = BASE_ALTITUDE_M + i * ALTITUDE_STEP_M
        pad = (vehicle.start_x, vehicle.start_y)
        commands: list[SkillCommand] = [TakeOffCommand(altitude_m=altitude, speed_mps=speed_mps)]
        track: list[Point2] = [pad]
        spacings = []
        for sector in mine:
            region = sector.region
            spacing = lane_spacing(region.y_max - region.y_min, brief.detection, speed_mps)
            spacings.append(spacing)
            lanes = [(w.x, w.y) for w in nav.lawnmower(region, spacing, altitude)]
            for a, b in zip(lanes, lanes[1:]):
                if not clear(a, b, obstacles):
                    raise PlanError(f"{sector.id}'s lawnmower passes within {ZONE_CLEARANCE_M} m "
                                    f"of a restricted zone ({a} -> {b})")
            leg = route(track[-1], lanes[0], zones, ZONE_CLEARANCE_M)
            if len(leg) > 2:            # the search flies straight to its first lane itself
                commands.append(FollowWaypointsCommand(
                    tuple(nav.Waypoint(x, y, altitude) for x, y in leg[1:-1]), speed_mps=speed_mps))
            commands.append(SearchRegionCommand(region=region, altitude_m=altitude,
                                                spacing_m=spacing, speed_mps=speed_mps))
            track += leg[1:] + lanes[1:]
        home = route(track[-1], pad, zones, ZONE_CLEARANCE_M)
        commands.append(FollowWaypointsCommand(
            tuple(nav.Waypoint(x, y, altitude) for x, y in home[1:]), speed_mps=speed_mps))
        commands.append(LandCommand())
        track += home[1:]

        flown = length(track)
        seconds = flown / speed_mps + 2.0 * altitude / CLIMB_SPEED_MPS + ESTIMATE_SETTLE_S
        used = brief.battery.hover_drain_per_s * seconds + brief.battery.move_drain_per_m * (flown + 2 * altitude)
        if brief.battery.capacity - used < brief.battery.reserve:
            raise PlanError(f"{vehicle.id}: an estimated {used:.1f} % of the battery leaves less than "
                            f"the {brief.battery.reserve:g} % reserve")
        if seconds > brief.mission.deadline_s:
            raise PlanError(f"{vehicle.id}: an estimated {seconds:.0f} s, over the "
                            f"{brief.mission.deadline_s:g} s deadline")
        plans[vehicle.id] = DronePlan(vehicle.id, tuple(s.id for s in mine), altitude,
                                      min(spacings) if spacings else 0.0, tuple(track),
                                      flown, seconds, used, tuple(commands))
    return plans
