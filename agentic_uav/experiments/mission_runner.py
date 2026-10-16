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


def run_scripted_mission(scenario, adapter, concurrent=False, log=None,
                         leg_timeout_s=LEG_TIMEOUT):
    """Fly the scripted mission on `adapter` and return an evaluated MissionReport.

    `concurrent=True` flies every drone at the same time, one thread each. The
    mock path leaves it off: its clock is simulated per vehicle, so sequential
    flight is exact and deterministic. In the simulator, sequential flight means
    watching Drone1 finish its whole mission before Drone2 leaves the ground,
    which is minutes of one drone and not what the mission is.

    `log`, if given, is called with one line per completed skill, so a live run
    narrates itself on the terminal as it flies instead of printing nothing
    until the end.
    """
    import threading

    executor = SkillExecutor(adapter)
    assignment = assign_sectors(scenario)

    paths, finish_time, returned, skill_log = {}, {}, {}, []
    lock = threading.Lock()

    # Register each vehicle's pad. On the mock this puts it there; on AirSim it
    # records the spawn point so positions convert between the vehicle's own
    # frame and the world frame the scenario is written in. Without it the
    # mock stacked every drone on the origin and, in the simulator, drones 2-4
    # flew their sectors offset by their own spawn points.
    if hasattr(adapter, "place"):
        for v in scenario.vehicles:
            adapter.place(v.vehicle_id, v.start)

    def say(line):
        if log is not None:
            log(line)

    def run_skill(vid, label, command):
        r = executor.execute(vid, command)
        took = (r.ended_at - r.started_at) if (
            r.ended_at is not None and r.started_at is not None) else 0.0
        say(f"[{vid}] {label:<16} -> {r.status.name.lower():<8} ({took:.1f}s)")
        return r

    def fly(v):
        sectors = assignment.get(v.vehicle_id, [])
        if not sectors:
            return
        vid = v.vehicle_id
        cruise = sectors[0].altitude
        home = Position3D(v.start.x, v.start.y, cruise)
        waypoints, results = [], []

        say(f"[{vid}] assigned {', '.join(s.sector_id for s in sectors)}")
        results.append(run_skill(vid, "TAKE_OFF", sk.TakeOffCommand(
            target_altitude=cruise, timeout_s=leg_timeout_s)))

        for sector in sectors:
            cmd = sk.SearchRegionCommand(
                min_x=sector.footprint.min_x, min_y=sector.footprint.min_y,
                max_x=sector.footprint.max_x, max_y=sector.footprint.max_y,
                altitude=sector.altitude, lane_spacing_m=LANE_SPACING,
                speed_mps=SEARCH_SPEED, tolerance_m=TOLERANCE,
                timeout_s=leg_timeout_s)
            say(f"[{vid}] SEARCH_REGION    -> sweeping {sector.sector_id}")
            waypoints.extend(_lawnmower(cmd))
            results.append(run_skill(vid, f"SEARCH {sector.sector_id}", cmd))

        results.append(run_skill(vid, "RETURN_HOME", sk.ReturnHomeCommand(
            home=home, speed_mps=SEARCH_SPEED, tolerance_m=TOLERANCE,
            timeout_s=leg_timeout_s)))
        waypoints.append(home)
        results.append(run_skill(vid, "LAND", sk.LandCommand(
            timeout_s=leg_timeout_s)))

        with lock:
            paths[vid] = _timed_path(v.start, waypoints, SEARCH_SPEED, cruise)
            finish_time[vid] = _finish_time(adapter, vid)
            returned[vid] = _returned_home(adapter, vid, v.start)
            skill_log.append((vid, [r.status.name for r in results]))

    if concurrent:
        threads = [threading.Thread(target=fly, args=(v,), name=v.vehicle_id)
                   for v in scenario.vehicles]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        # keep the report in scenario order regardless of finishing order
        order = [v.vehicle_id for v in scenario.vehicles]
        skill_log.sort(key=lambda e: order.index(e[0]))
    else:
        for v in scenario.vehicles:
            fly(v)

    run = {"paths": paths, "finish_time": finish_time,
           "returned": returned, "speed_mps": SEARCH_SPEED}
    report = evaluate_mission(scenario, run)
    report.detail = _detail(assignment, skill_log)
    return report


def _timed_path(start, waypoints, speed, altitude=nav.ALTITUDE):
    """Build [(Position3D, cumulative_time_s), ...] at constant horizontal speed.

    The path begins at the drone's take-off point (its start x,y at altitude) and
    walks the horizontal plan. Vertical-only legs are ignored for the ground track
    the evaluator scores (coverage/detection are horizontal).
    """
    cursor = Position3D(start.x, start.y, altitude)
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
