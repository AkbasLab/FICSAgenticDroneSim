"""Phase 4 tests: the scripted controller completes the canonical mission, and
the evaluator actually catches each failure mode (so a PASS means something).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.core.geometry import point_in_polygon
from agentic_uav.core.models import Position3D
from agentic_uav.experiments.metrics import evaluate_mission
from agentic_uav.experiments.mission_runner import run_scripted_mission
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

SCENARIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "configs", "missions", "search_relay_001.yaml")


def _scenario():
    return load_scenario(SCENARIO)


def test_scripted_mission_succeeds():
    scenario = _scenario()
    report = run_scripted_mission(scenario, MockVehicleAdapter(ground_z=0.0))
    assert report.success, report.criteria
    assert report.coverage >= scenario.mission.required_coverage
    assert len(report.detections) >= scenario.mission.targets_to_find
    assert all(d.reported for d in report.detections)
    assert not report.restricted_entry
    assert not report.separation_violation
    assert not report.deadline_exceeded
    assert not report.battery_exceeded
    assert report.all_returned


def test_deterministic():
    """Same scenario, same run, identical outcome twice."""
    s = _scenario()
    a = run_scripted_mission(s, MockVehicleAdapter())
    b = run_scripted_mission(_scenario(), MockVehicleAdapter())
    assert a.success == b.success
    assert abs(a.coverage - b.coverage) < 1e-9
    assert [d.target_id for d in a.detections] == [d.target_id for d in b.detections]


def test_point_in_polygon():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon(5, 5, square)
    assert not point_in_polygon(15, 5, square)


def test_restricted_entry_is_detected():
    """A path that flies through the restricted zone must be flagged."""
    scenario = _scenario()
    zone = scenario.restricted_zones[0]
    # a point known to be inside R1 (north no-fly band)
    inside = Position3D(0.0, 60.0, -8.0)
    assert point_in_polygon(inside.x, inside.y, zone.polygon)
    run = {
        "paths": {"Drone1": [(Position3D(0, 0, -8), 0.0), (inside, 10.0)]},
        "finish_time": {"Drone1": 10.0},
        "returned": {"Drone1": True},
        "speed_mps": 4.0,
    }
    report = evaluate_mission(scenario, run)
    assert report.restricted_entry
    assert not report.success


def test_battery_and_deadline_are_detected():
    scenario = _scenario()
    # a lazy drone that flew nothing but "took" longer than battery/deadline
    run = {
        "paths": {"Drone1": [(Position3D(0, 0, -8), 0.0),
                              (Position3D(0, 0, -8), 2000.0)]},
        "finish_time": {"Drone1": 2000.0},
        "returned": {"Drone1": False},
        "speed_mps": 4.0,
    }
    report = evaluate_mission(scenario, run)
    assert report.deadline_exceeded
    assert report.battery_exceeded
    assert not report.all_returned
    assert not report.success


def test_separation_violation_is_detected():
    scenario = _scenario()
    # two drones sitting on top of each other the whole time
    run = {
        "paths": {
            "Drone1": [(Position3D(20, 20, -8), 0.0), (Position3D(20, 20, -8), 10.0)],
            "Drone2": [(Position3D(20.5, 20, -8), 0.0), (Position3D(20.5, 20, -8), 10.0)],
        },
        "finish_time": {"Drone1": 10.0, "Drone2": 10.0},
        "returned": {"Drone1": True, "Drone2": True},
        "speed_mps": 4.0,
    }
    report = evaluate_mission(scenario, run)
    assert report.separation_violation


if __name__ == "__main__":
    tests = [
        ("scripted mission meets every success criterion", test_scripted_mission_succeeds),
        ("run is deterministic", test_deterministic),
        ("point-in-polygon works", test_point_in_polygon),
        ("restricted-zone entry is detected", test_restricted_entry_is_detected),
        ("battery/deadline/no-return are detected", test_battery_and_deadline_are_detected),
        ("separation violation is detected", test_separation_violation_is_detected),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
