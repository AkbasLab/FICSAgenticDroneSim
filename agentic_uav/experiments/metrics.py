"""Mission evaluation against the Phase 4.3 success criteria.

Given a scenario and the flown paths, decide whether the mission succeeded:
  - required sectors searched to the coverage threshold,
  - all targets detected and reported to base,
  - no restricted-region entry,
  - no separation/collision violation,
  - battery and deadline respected,
  - all drones returned safely.

Everything is geometric/deterministic so the same run always scores the same.
"""

from ..core.geometry import point_in_polygon
from ..core.mission_models import MissionReport
from ..simulator.target_model import detect_targets

# grid resolution for coverage (metres between sample cells)
COVERAGE_CELL_M = 5.0
# a cell counts as covered if a flown path passes within this of it
COVERAGE_RADIUS_M = 8.0


def evaluate_mission(scenario, run) -> MissionReport:
    """
    run: dict with
      paths:        {vid: [(Position3D, t_s), ...]}  flown path (timed)
      finish_time:  {vid: t_s}
      returned:     {vid: bool}  landed back near base
      speed_mps:    float
    """
    paths = run["paths"]
    speed = run.get("speed_mps", 4.0)

    report = MissionReport()

    # coverage of the required sectors
    report.coverage = _coverage(scenario.sectors, paths)
    report.sectors_searched = [s.sector_id for s in scenario.sectors
                               if _sector_coverage(s, paths) >= scenario.mission.required_coverage]
    coverage_ok = report.coverage >= scenario.mission.required_coverage

    # detections + reporting (reported if the detector returns within comm range)
    detections = detect_targets(scenario.targets, paths, speed)
    for det in detections:
        det.reported = _reported(scenario, paths.get(det.by_vehicle, []))
    report.detections = detections
    found = len(detections)
    reported = sum(1 for d in detections if d.reported)
    detect_ok = found >= scenario.mission.targets_to_find
    report_ok = reported >= scenario.mission.targets_to_find

    # restricted-region entry
    report.restricted_entry = _any_restricted_entry(scenario, paths)

    # separation / collision
    report.separation_violation = _separation_violation(
        paths, scenario.mission.min_separation_m, speed)

    # battery + deadline
    report.battery_exceeded = any(
        run["finish_time"].get(v.vehicle_id, 0.0) > v.battery_s
        for v in scenario.vehicles if v.vehicle_id in paths)
    latest = max(run["finish_time"].values()) if run["finish_time"] else 0.0
    report.deadline_exceeded = latest > scenario.mission.deadline_s

    # safe return
    report.all_returned = all(run["returned"].get(v.vehicle_id, False)
                              for v in scenario.vehicles if v.vehicle_id in paths)

    report.criteria = {
        "coverage": coverage_ok,
        "targets_detected": detect_ok,
        "detections_reported": report_ok,
        "no_restricted_entry": not report.restricted_entry,
        "no_separation_violation": not report.separation_violation,
        "battery_ok": not report.battery_exceeded,
        "deadline_ok": not report.deadline_exceeded,
        "all_returned": report.all_returned,
    }
    report.success = all(report.criteria.values())
    return report


# --- coverage ---

def _coverage(sectors, paths):
    covered = total = 0
    for s in sectors:
        c, t = _sector_cells(s, paths)
        covered += c
        total += t
    return (covered / total) if total else 0.0


def _sector_coverage(sector, paths):
    c, t = _sector_cells(sector, paths)
    return (c / t) if t else 0.0


def _sector_cells(sector, paths):
    r = sector.footprint
    covered = total = 0
    y = r.min_y
    while y <= r.max_y + 1e-9:
        x = r.min_x
        while x <= r.max_x + 1e-9:
            total += 1
            if _near_any_path(x, y, paths, COVERAGE_RADIUS_M):
                covered += 1
            x += COVERAGE_CELL_M
        y += COVERAGE_CELL_M
    return covered, total


def _near_any_path(x, y, paths, radius):
    from ..core.geometry import dist_point_to_segment
    for path in paths.values():
        for i in range(len(path) - 1):
            a, b = path[i][0], path[i + 1][0]
            if dist_point_to_segment(x, y, a.x, a.y, b.x, b.y) <= radius:
                return True
    return False


# --- reporting / restricted / separation ---

def _reported(scenario, path):
    """A detection is reported if the detector ends within comm range of base."""
    if not path:
        return False
    end = path[-1][0]
    base = scenario.base.position
    return end.horizontal_distance_to(base) <= scenario.base.comm_range_m


def _any_restricted_entry(scenario, paths):
    from ..core.geometry import dist_point_to_segment
    for zone in scenario.restricted_zones:
        for path in paths.values():
            for (p, _t) in path:
                if point_in_polygon(p.x, p.y, zone.polygon):
                    return True
    return False


def _separation_violation(paths, min_sep, speed):
    """Sample each drone's position over time and check pairwise separation."""
    series = {vid: _sampled(path, speed) for vid, path in paths.items()}
    times = sorted({t for s in series.values() for (t, _p) in s})
    vids = list(series)
    for t in times:
        positions = {vid: _pos_at(series[vid], t) for vid in vids}
        for i in range(len(vids)):
            for j in range(i + 1, len(vids)):
                pi, pj = positions[vids[i]], positions[vids[j]]
                if pi is None or pj is None:
                    continue
                if pi.horizontal_distance_to(pj) < min_sep:
                    return True
    return False


def _sampled(path, speed, dt=2.0):
    """Reconstruct (time, Position3D) samples along a timed path."""
    return [(t, p) for (p, t) in path]


def _pos_at(series, t):
    """Nearest sampled position at time t (series is [(t, pos), ...])."""
    best = None
    for (ts, p) in series:
        if best is None or abs(ts - t) < abs(best[0] - t):
            best = (ts, p)
    return best[1] if best else None


def summarize(results):
    """Legacy helper kept for the Phase 2 runner."""
    finished = sum(1 for r in results.values() if not isinstance(r, Exception))
    return {"drones": len(results), "finished": finished}
