"""Phase 4 scorer + baseline controller tests. Three tests below deliberately
feed the scorer bad runs and assert it catches each one - a scorer that can
only say PASS proves nothing."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.core.scenario import load_scenario
from fics_drone.evaluation.metrics import score_run
from fics_drone.experiments.mission_runner import ALTITUDE_STEP_M, lawnmower_waypoints, run_scripted_mission
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter
from fics_drone.telemetry.recorder import Sample, TelemetryRecorder

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                              "search_relay_001.json")


def _synthetic_path(points, speed=5.0, dt=0.2, t0=0.0):
    """Turns a list of (x, y, z) waypoints into densely time-sampled Samples,
    as if a drone flew straight legs between them at `speed`, so tests don't
    depend on real wall-clock time like a live kinematic-mock run would."""
    samples = []
    t = t0
    for a, b in zip(points, points[1:]):
        dist = math.dist(a, b)
        leg_time = dist / speed if dist > 0 else 0.0
        steps = max(1, int(leg_time / dt))
        for i in range(steps + 1):
            frac = i / steps
            pos = tuple(a[k] + (b[k] - a[k]) * frac for k in range(3))
            samples.append(Sample(t, pos))
            t += dt
    return samples, t


class TestScorer(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario(SCENARIO_PATH)

    def _full_good_run(self):
        """One synthetic run that should pass every criterion: each drone
        sweeps its sector, explicitly detours to sit on any target inside it
        for dwell_s (a scripted, world-aware controller knows target
        positions up front - see mission_runner's own docstring), then
        returns to base."""
        run_log = {}
        max_t = 0.0
        for i, spec in enumerate(self.scenario.drones):
            cruise = 8.0 + i * ALTITUDE_STEP_M  # matches mission_runner's per-drone altitude band
            sector = self.scenario.sector(spec.sector)
            waypoints = lawnmower_waypoints(sector, height=cruise)
            climb = (spec.spawn_offset[0], spec.spawn_offset[1], cruise)
            path = [spec.spawn_offset, climb] + waypoints  # straight climb-out before any horizontal move
            samples, t = _synthetic_path(path)
            for target in self.scenario.targets:
                if sector.x_min <= target.x <= sector.x_max and sector.y_min <= target.y <= sector.y_max:
                    leg, t = _synthetic_path([samples[-1].position, (target.x, target.y, cruise)], t0=t)
                    samples += leg
                    hold_until = t + target.dwell_s + 0.5
                    while t < hold_until:
                        samples.append(Sample(t, (target.x, target.y, cruise)))
                        t += 0.2
            home = (spec.spawn_offset[0], spec.spawn_offset[1], 8.0)  # return_home always targets DEFAULT_HEIGHT
            tail, t = _synthetic_path([samples[-1].position, home], t0=t)
            samples += tail
            run_log[spec.name] = samples
            max_t = max(max_t, t)
        return run_log, max_t

    def test_good_run_passes_everything(self):
        run_log, elapsed = self._full_good_run()
        report = score_run(self.scenario, run_log, elapsed)
        self.assertTrue(report.coverage_pass, report.coverage_fraction)
        self.assertTrue(report.targets_pass, report.targets_found)
        self.assertTrue(report.no_fly_pass, report.no_fly_violations)
        self.assertTrue(report.separation_pass, report.separation_violations)
        self.assertTrue(report.battery_pass, report.battery_violations)
        self.assertTrue(report.deadline_pass)
        self.assertTrue(report.all_home_pass)
        self.assertTrue(report.overall_pass)

    def test_no_fly_violation_is_caught(self):
        run_log, elapsed = self._full_good_run()
        zone = self.scenario.no_fly_zones[0]
        mid = ((zone.x_min + zone.x_max) / 2, (zone.y_min + zone.y_max) / 2, 8.0)
        run_log["Drone1"].append(Sample(elapsed + 1.0, mid))
        report = score_run(self.scenario, run_log, elapsed + 1.0)
        self.assertFalse(report.no_fly_pass)
        self.assertTrue(any("Drone1" in v for v in report.no_fly_violations))
        self.assertFalse(report.overall_pass)

    def test_separation_violation_is_caught(self):
        run_log, elapsed = self._full_good_run()
        # force two drones to the same point at the same sample index
        run_log["Drone2"][5] = Sample(run_log["Drone1"][5].t, run_log["Drone1"][5].position)
        report = score_run(self.scenario, run_log, elapsed)
        self.assertFalse(report.separation_pass)
        self.assertFalse(report.overall_pass)

    def test_brief_pass_through_target_is_not_detected(self):
        """A drone that only clips a target's radius for an instant (less
        than dwell_s) must not count as having found it."""
        target = self.scenario.targets[0]
        brief = [Sample(0.0, (target.x, target.y, 8.0)),
                 Sample(0.2, (target.x, target.y, 8.0))]  # well under dwell_s=2.0
        run_log = {spec.name: [] for spec in self.scenario.drones}
        run_log[self.scenario.drones[0].name] = brief
        report = score_run(self.scenario, run_log, 1.0)
        self.assertNotIn(target.id, report.targets_found)
        self.assertFalse(report.targets_pass)

    def test_low_coverage_fails(self):
        run_log = {spec.name: [Sample(0.0, self.scenario.base_station)] for spec in self.scenario.drones}
        report = score_run(self.scenario, run_log, 1.0)
        self.assertFalse(report.coverage_pass)
        self.assertLess(report.coverage_fraction, self.scenario.required_coverage)
        self.assertFalse(report.overall_pass)

    def test_battery_overrun_is_caught(self):
        run_log, elapsed = self._full_good_run()
        spec = self.scenario.drones[0]
        run_log[spec.name].append(Sample(spec.battery_s + 10.0, run_log[spec.name][-1].position))
        report = score_run(self.scenario, run_log, elapsed)
        self.assertFalse(report.battery_pass)
        self.assertTrue(any(spec.name in v for v in report.battery_violations))

    def test_deadline_overrun_is_caught(self):
        run_log, _ = self._full_good_run()
        report = score_run(self.scenario, run_log, self.scenario.deadline_s + 1.0)
        self.assertFalse(report.deadline_pass)
        self.assertFalse(report.overall_pass)


class TestScriptedBaselineIntegration(unittest.TestCase):
    """Slower: actually runs the scripted controller against the kinematic
    mock in real time (no shortcuts), then scores the real recorded log."""

    def test_scripted_baseline_completes_and_passes(self):
        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0)
                    for d in scenario.drones}  # sped up so the test doesn't take minutes
        offsets = {d.name: d.spawn_offset for d in scenario.drones}
        recorder = TelemetryRecorder(adapters, world_offsets=offsets, rate_hz=10.0)
        recorder.start()
        import time
        start = time.monotonic()
        run_scripted_mission(scenario, adapters, height=8.0)
        elapsed = time.monotonic() - start
        recorder.stop()

        report = score_run(scenario, recorder.log, elapsed)
        self.assertTrue(report.coverage_pass, report.coverage_fraction)
        self.assertTrue(report.targets_pass, report.targets_found)
        self.assertTrue(report.no_fly_pass, report.no_fly_violations)
        self.assertTrue(report.overall_pass)


if __name__ == "__main__":
    unittest.main()
