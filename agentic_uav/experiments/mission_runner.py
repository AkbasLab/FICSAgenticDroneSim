"""Scripted, non-agentic mission controller (Phase 4 exit criterion).

This is the deliberately dumb baseline: a fixed script, no beliefs, no peer
messaging, no dynamic re-allocation. It statically assigns one search sector to
each drone, then flies every drone through the same fixed sequence of Phase 3
skills:

    TAKE_OFF -> SEARCH_REGION(its sector) -> RETURN_HOME -> LAND

It runs on any VehicleAdapter (the deterministic mock for CI, AirSim for a real
run) and records each drone's timed path. Those paths are handed to the
evaluator, which scores the run against the Phase 4.3 success criteria. If this
scripted controller can complete the canonical mission, the environment,
detection model, skills and metrics are all wired up correctly - which is the
baseline the coordinated architecture has to beat later.
"""

from ..control import navigation as nav
from ..control import skills as sk
from ..control.skill_executor import SkillExecutor, _lawnmower
from ..core.models import Position3D
from .metrics import evaluate_mission

SEARCH_SPEED = 4.0
LANE_SPACING = 8.0
TOLERANCE = 1.5
LEG_TIMEOUT = 600.0


def assign_sectors(scenario):
    """Static round-robin: hand out sectors to drones in order."""
    vehicles = scenario.vehicles
    sectors = scenario.sectors
    assignment = {}
    for i, sector in enumerate(sectors):
        if not vehicles:
            break
        v = vehicles[i % len(vehicles)]
        assignment.setdefault(v.vehicle_id, []).append(sector)
    return assignment


def run_scripted_mission(scenario, adapter):
    """Fly the scripted mission on `adapter` and return an evaluated MissionReport."""
    executor = SkillExecutor(adapter)
    assignment = assign_sectors(scenario)

    paths = {}
    finish_time = {}
    returned = {}
    skill_log = []

    for v in scenario.vehicles:
        sectors = assignment.get(v.vehicle_id, [])
        if not sectors:
            continue
        home = Position3D(v.start.x, v.start.y, nav.ALTITUDE)
        waypoints = []  # horizontal plan for the timed path
        results = []

        # take off
        results.append(executor.execute(
            v.vehicle_id, sk.TakeOffCommand(target_altitude=nav.ALTITUDE,
                                            timeout_s=LEG_TIMEOUT)))

        # search each assigned sector
        for sector in sectors:
            cmd = sk.SearchRegionCommand(
                min_x=sector.footprint.min_x, min_y=sector.footprint.min_y,
                max_x=sector.footprint.max_x, max_y=sector.footprint.max_y,
                altitude=sector.altitude, lane_spacing_m=LANE_SPACING,
                speed_mps=SEARCH_SPEED, tolerance_m=TOLERANCE, timeout_s=LEG_TIMEOUT)
            waypoints.extend(_lawnmower(cmd))
            results.append(executor.execute(v.vehicle_id, cmd))

        # return home and land
        results.append(executor.execute(
            v.vehicle_id, sk.ReturnHomeCommand(
                home=home, speed_mps=SEARCH_SPEED,
                tolerance_m=TOLERANCE, timeout_s=LEG_TIMEOUT)))
        waypoints.append(home)
        results.append(executor.execute(
            v.vehicle_id, sk.LandCommand(timeout_s=LEG_TIMEOUT)))

        paths[v.vehicle_id] = _timed_path(v.start, waypoints, SEARCH_SPEED)
        finish_time[v.vehicle_id] = _finish_time(adapter, v.vehicle_id)
        returned[v.vehicle_id] = _returned_home(adapter, v.vehicle_id, v.start)
        skill_log.append((v.vehicle_id, [r.status.name for r in results]))

    run = {"paths": paths, "finish_time": finish_time,
           "returned": returned, "speed_mps": SEARCH_SPEED}
    report = evaluate_mission(scenario, run)
    report.detail = _detail(assignment, skill_log)
    return report


def _timed_path(start, waypoints, speed):
    """Build [(Position3D, cumulative_time_s), ...] at constant horizontal speed.

    The path begins at the drone's take-off point (its start x,y at altitude) and
    walks the horizontal plan. Vertical-only legs are ignored for the ground track
    the evaluator scores (coverage/detection are horizontal).
    """
    cursor = Position3D(start.x, start.y, nav.ALTITUDE)
    t = 0.0
    path = [(cursor, t)]
    for wp in waypoints:
        leg = cursor.horizontal_distance_to(wp)
        t += leg / max(speed, 0.001)
        cursor = Position3D(wp.x, wp.y, wp.z)
        path.append((cursor, t))
    return path


def _finish_time(adapter, vid):
    return adapter.now(vid) if hasattr(adapter, "now") else 0.0


def _returned_home(adapter, vid, start, tol=2.0):
    if not hasattr(adapter, "get_position"):
        return True
    p = adapter.get_position(vid)
    return p.horizontal_distance_to(start) <= tol


def _detail(assignment, skill_log):
    parts = []
    for vid, statuses in skill_log:
        secs = ",".join(s.sector_id for s in assignment.get(vid, []))
        parts.append(f"{vid}[{secs}]: {'>'.join(statuses)}")
    return " | ".join(parts)
