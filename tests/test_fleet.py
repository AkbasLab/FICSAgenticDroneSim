"""Multi-drone orchestration tests - no simulator, no LLM. Fake planner +
MockVehicleAdapter satisfy the same interfaces the real ones do."""

from fics_drone.control.fleet import FleetController
from fics_drone.core.interfaces import MissionPlanner
from fics_drone.core.models import SkillCommand
from fics_drone.planners.base_planner import PlanError
from fics_drone.simulator.mock_adapter import MockVehicleAdapter


class FakePlanner(MissionPlanner):
    """'bad' raises PlanError, 'land' -> [land], anything else -> [hover]."""
    def plan(self, instruction):
        if instruction == "bad":
            raise PlanError("unknown action 'bad'")
        if instruction == "land":
            return [SkillCommand("land", {})]
        return [SkillCommand("hover", {"duration": 1.0})]


def make_fleet(delay=0.0):
    adapters = {n: MockVehicleAdapter(n, step_delay=delay) for n in ("Drone1", "Drone2")}
    return FleetController(FakePlanner(), adapters), adapters


def test_each_drone_gets_its_own_plan():
    fleet, a = make_fleet()
    fleet.takeoff_all()
    fleet.run({"Drone1": "forward", "Drone2": "land"})
    assert a["Drone1"].log == [("takeoff", None), ("execute", ["hover"])]
    assert a["Drone2"].log == [("takeoff", None), ("execute", ["land"])]
    assert fleet.landed == {"Drone2"}
    print("  ok    each drone executes its own plan; land is tracked")


def test_bad_plan_means_nobody_flies():
    fleet, a = make_fleet()
    fleet.takeoff_all()
    try:
        fleet.run({"Drone1": "forward", "Drone2": "bad"})
        assert False, "should have raised PlanError"
    except PlanError:
        pass
    assert all(("execute", ["hover"]) not in d.log for d in a.values())
    assert not any(k == "execute" for d in a.values() for k, _ in d.log)
    print("  ok    Drone2's bad plan stops Drone1 before it moves")


def test_drones_run_concurrently():
    fleet, a = make_fleet(delay=0.3)
    fleet.run({"Drone1": "forward", "Drone2": "forward"})
    d1, d2 = a["Drone1"], a["Drone2"]
    assert d1.start_time < d2.end_time and d2.start_time < d1.end_time
    span = max(d1.end_time, d2.end_time) - min(d1.start_time, d2.start_time)
    assert span < 0.5, f"took {span:.2f}s - ran one at a time"
    print("  ok    two 0.3s plans overlap (ran in ~0.3s, not 0.6s)")


def test_unknown_and_landed_drones_rejected():
    fleet, a = make_fleet()
    try:
        fleet.run({"Drone9": "forward"})
        assert False
    except ValueError as e:
        assert "unknown drone" in str(e)
    fleet.run({"Drone1": "land"})
    try:
        fleet.run({"Drone1": "forward"})
        assert False
    except ValueError as e:
        assert "already landed" in str(e)
    print("  ok    unknown and already-landed drones rejected before flying")


def test_land_all_skips_already_landed():
    fleet, a = make_fleet()
    fleet.run({"Drone1": "land"})
    fleet.land_all()
    assert [k for k, _ in a["Drone1"].log].count("land") == 0  # its plan landed it, not land()
    assert ("land", None) in a["Drone2"].log
    assert fleet.all_landed
    print("  ok    land_all only lands drones still airborne")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} passed, 0 failed")
