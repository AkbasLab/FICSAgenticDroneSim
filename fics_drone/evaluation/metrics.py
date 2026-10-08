"""Grades one run against one scenario. Pure function: (scenario, run log) ->
report - no simulator access, no side effects, so it can re-score an old log
and is fully testable offline. Every criterion is checked independently and
none of them can save you if another fails - a scorer that can only say PASS
proves nothing, so tests must include runs that deliberately break each rule.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List

from ..core.scenario import Scenario
from ..telemetry.recorder import Sample

COVERAGE_CELL_M = 5.0    # coverage grid resolution
COVERAGE_RADIUS_M = 8.0  # a drone "covers" every grid cell within this of its path


@dataclass
class ScoreReport:
    coverage_fraction: float
    coverage_pass: bool
    targets_found: List[str]
    targets_pass: bool
    no_fly_violations: List[str]  # "{drone} entered {zone} at t={t:.1f}s"
    no_fly_pass: bool
    separation_violations: List[str]
    separation_pass: bool
    battery_violations: List[str]
    battery_pass: bool
    deadline_s: float
    deadline_pass: bool
    all_home: bool
    all_home_pass: bool

    @property
    def overall_pass(self) -> bool:
        return all([
            self.coverage_pass, self.targets_pass, self.no_fly_pass,
            self.separation_pass, self.battery_pass, self.deadline_pass,
            self.all_home_pass,
        ])


def _sector_grid_cells(sector) -> List[tuple]:
    cells = []
    x = sector.x_min
    while x <= sector.x_max:
        y = sector.y_min
        while y <= sector.y_max:
            cells.append((x, y))
            y += COVERAGE_CELL_M
        x += COVERAGE_CELL_M
    return cells


def _score_coverage(scenario: Scenario, run_log: Dict[str, List[Sample]]):
    covered = 0
    total = 0
    for spec in scenario.drones:
        sector = scenario.sector(spec.sector)
        cells = _sector_grid_cells(sector)
        samples = run_log.get(spec.name, [])
        for cell in cells:
            total += 1
            if any(math.dist(cell, (s.position[0], s.position[1])) <= COVERAGE_RADIUS_M
                   for s in samples):
                covered += 1
    fraction = covered / total if total else 0.0
    return fraction, fraction >= scenario.required_coverage


def _score_targets(scenario: Scenario, run_log: Dict[str, List[Sample]]):
    found = []
    for target in scenario.targets:
        for name, samples in run_log.items():
            in_range = [s for s in samples
                        if math.dist((s.position[0], s.position[1]), (target.x, target.y))
                        <= target.detection_radius_m]
            if _has_continuous_dwell(in_range, target.dwell_s):
                found.append(target.id)
                break
    return found, len(found) == len(scenario.targets)


def _has_continuous_dwell(in_range_samples: List[Sample], dwell_s: float) -> bool:
    """True if some run of consecutive in-range samples spans >= dwell_s.
    Samples are timestamped, not assumed evenly spaced, so a gap (the drone
    left range and came back) has to restart the run instead of accumulating."""
    if not in_range_samples:
        return False
    run_start = in_range_samples[0].t
    prev_t = in_range_samples[0].t
    for s in in_range_samples[1:]:
        gap = s.t - prev_t
        if gap > 1.0:  # bigger than a couple of missed samples - treat as a real exit
            run_start = s.t
        elif s.t - run_start >= dwell_s:
            return True
        prev_t = s.t
    return prev_t - run_start >= dwell_s


def _score_no_fly(scenario: Scenario, run_log: Dict[str, List[Sample]]):
    violations = []
    for name, samples in run_log.items():
        for s in samples:
            for zone in scenario.no_fly_zones:
                if zone.contains(s.position[0], s.position[1], s.t):  # time-aware: a scheduled zone only counts while active
                    violations.append(f"{name} entered {zone.id} at t={s.t:.1f}s")
    return violations, len(violations) == 0


def _score_separation(scenario: Scenario, run_log: Dict[str, List[Sample]]):
    violations = []
    names = list(run_log.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = run_log[names[i]], run_log[names[j]]
            for sa, sb in zip(a, b):  # recorder samples all drones on one shared tick
                d = math.dist(sa.position, sb.position)
                if d < scenario.min_separation_m:
                    violations.append(
                        f"{names[i]}/{names[j]} at {d:.1f}m (< {scenario.min_separation_m}m) "
                        f"at t={sa.t:.1f}s")
    return violations, len(violations) == 0


def _score_battery(scenario: Scenario, run_log: Dict[str, List[Sample]]):
    violations = []
    for spec in scenario.drones:
        samples = run_log.get(spec.name, [])
        if samples and samples[-1].t > spec.battery_s:
            violations.append(f"{spec.name} flew {samples[-1].t:.1f}s (budget {spec.battery_s}s)")
    return violations, len(violations) == 0


def _score_all_home(scenario: Scenario, run_log: Dict[str, List[Sample]], tolerance_m=2.0):
    """'Home' for a drone is its own spawn point in world coordinates
    (spawn_offset), not one shared base_station point - return_home() flies
    each drone to its own local (0,0,*), which the recorder already
    converted to that drone's own world spawn point."""
    for spec in scenario.drones:
        samples = run_log.get(spec.name, [])
        if not samples:
            return False
        final_xy = (samples[-1].position[0], samples[-1].position[1])
        home_xy = (spec.spawn_offset[0], spec.spawn_offset[1])
        if math.dist(final_xy, home_xy) > tolerance_m:
            return False
    return True


def score_run(scenario: Scenario, run_log: Dict[str, List[Sample]], mission_elapsed_s: float) -> ScoreReport:
    coverage_fraction, coverage_pass = _score_coverage(scenario, run_log)
    targets_found, targets_pass = _score_targets(scenario, run_log)
    no_fly_violations, no_fly_pass = _score_no_fly(scenario, run_log)
    separation_violations, separation_pass = _score_separation(scenario, run_log)
    battery_violations, battery_pass = _score_battery(scenario, run_log)
    all_home = _score_all_home(scenario, run_log)

    return ScoreReport(
        coverage_fraction=coverage_fraction, coverage_pass=coverage_pass,
        targets_found=targets_found, targets_pass=targets_pass,
        no_fly_violations=no_fly_violations, no_fly_pass=no_fly_pass,
        separation_violations=separation_violations, separation_pass=separation_pass,
        battery_violations=battery_violations, battery_pass=battery_pass,
        deadline_s=mission_elapsed_s, deadline_pass=mission_elapsed_s <= scenario.deadline_s,
        all_home=all_home, all_home_pass=all_home,
    )
