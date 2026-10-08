"""Skill contract tests - no simulator. MockVehicleAdapter's `reachable` and
`position_sequence` knobs let these prove the polling-loop behavior
(bounded timeout, drift detection, continue-past-failure) deterministically."""

from fics_drone.control import skills
from fics_drone.core.skill_result import SkillStatus
from fics_drone.simulator.mock_adapter import MockVehicleAdapter

FAST = dict(timeout_s=0.25)  # short timeout so a deliberate TIMEOUT test stays quick


def test_go_to_waypoint_succeeds_when_reachable():
    a = MockVehicleAdapter(reachable=True)
    r = skills.go_to_waypoint(a, 5.0, 0.0, 8.0, **FAST)
    assert r.status == SkillStatus.SUCCESS
    assert r.final_position == (5.0, 0.0, 8.0)
    assert ("move_to", (5.0, 0.0, 8.0)) in a.log
    print("  ok    go_to_waypoint succeeds and reports the arrival position")


def test_go_to_waypoint_times_out_when_stuck():
    a = MockVehicleAdapter(reachable=False, start_position=(0.0, 0.0, 8.0))
    r = skills.go_to_waypoint(a, 500.0, 0.0, 8.0, **FAST)
    assert r.status == SkillStatus.TIMEOUT
    assert r.final_position == (0.0, 0.0, 8.0)  # never moved
    assert r.elapsed_s < 1.0  # bounded - proves it didn't block forever
    print("  ok    go_to_waypoint gives up and reports TIMEOUT, not stuck forever")


def test_hold_position_succeeds_without_drift():
    a = MockVehicleAdapter(position_sequence=[(0, 0, 8)] * 10)
    r = skills.hold_position(a, duration_s=0.2, drift_tolerance=1.0)
    assert r.status == SkillStatus.SUCCESS
    assert ("hover", None) in a.log
    print("  ok    hold_position succeeds when position doesn't move")


def test_hold_position_fails_on_drift():
    a = MockVehicleAdapter(position_sequence=[(0, 0, 8), (0, 0, 8), (10, 0, 8)])
    r = skills.hold_position(a, duration_s=5.0, drift_tolerance=1.0)
    assert r.status == SkillStatus.FAILED
    assert "drifted" in r.error
    print("  ok    hold_position reports FAILED as soon as drift exceeds tolerance")


def test_return_home_skips_landing_if_never_arrived():
    a = MockVehicleAdapter(reachable=False, start_position=(50.0, 0.0, 8.0))
    r = skills.return_home(a, timeout_s=0.2)
    assert r.status == SkillStatus.TIMEOUT
    assert ("land", None) not in a.log
    print("  ok    return_home does not land if it never reached home")


def test_return_home_lands_after_arriving():
    a = MockVehicleAdapter(reachable=True)
    r = skills.return_home(a, timeout_s=0.2)
    assert r.status == SkillStatus.SUCCESS
    assert ("land", None) in a.log
    print("  ok    return_home lands once it actually reaches home")


def test_follow_waypoints_continues_past_a_failed_leg():
    # middle waypoint (99,99,8) is never reachable; the other two are.
    a = MockVehicleAdapter(reachable=True)
    real_start_move = a.start_move_to

    def flaky_start_move(x, y, z):
        if (x, y, z) == (99.0, 99.0, 8.0):
            return  # silently refuse this one leg - position stays put
        real_start_move(x, y, z)

    a.start_move_to = flaky_start_move
    route = [(5.0, 0.0, 8.0), (99.0, 99.0, 8.0), (10.0, 0.0, 8.0)]
    result = skills.follow_waypoints(a, route, timeout_s=0.2)

    assert result.status == SkillStatus.PARTIAL
    assert len(result.leg_results) == 3
    assert result.leg_results[0].status == SkillStatus.SUCCESS
    assert result.leg_results[1].status == SkillStatus.TIMEOUT  # knows WHEN
    assert result.leg_results[1].final_position is not None      # knows WHERE
    assert result.leg_results[2].status == SkillStatus.SUCCESS   # kept going after leg 2
    print("  ok    follow_waypoints reports each leg and continues past a timeout")


def test_take_off_and_land_report_success():
    a = MockVehicleAdapter()
    assert skills.take_off(a).status == SkillStatus.SUCCESS
    assert skills.land(a).status == SkillStatus.SUCCESS
    assert a.log == [("takeoff", None), ("land", None)]
    print("  ok    take_off and land wrap the adapter calls with a SkillResult")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} passed, 0 failed")
