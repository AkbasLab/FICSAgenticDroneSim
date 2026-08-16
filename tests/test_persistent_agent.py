"""Phase 5 tests: the deterministic persistent agent completes a search task
from a task alone (no preflight plan), and reacts correctly to low battery and
to a failed navigation skill.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.objectives import AgentEvent, SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.core.models import NavOutcome, Position3D
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

SCENARIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "configs", "missions", "search_relay_001.yaml")


def _setup(sector_id="S1"):
    scenario = load_scenario(SCENARIO)
    sector = next(s for s in scenario.sectors if s.sector_id == sector_id)
    vehicle = scenario.vehicles[0]
    task = SearchTask(task_id=f"search_{sector_id}", sector=sector,
                      report_to=scenario.base.position,
                      targets_of_interest=scenario.targets)
    return scenario, sector, vehicle, task


def test_agent_completes_search_task():
    scenario, sector, vehicle, task = _setup("S1")
    agent = PersistentAgent(vehicle.vehicle_id, MockVehicleAdapter(0.0),
                            home=vehicle.start, battery_total_s=vehicle.battery_s,
                            cruise_altitude=sector.altitude)
    r = agent.run(task)
    assert r.completed, r.decisions
    assert r.sector_searched and r.reported and r.returned_home and r.landed


def test_no_preflight_plan_one_skill_at_a_time():
    """The agent must decide skills incrementally, not emit a full plan up front.
    Each decision is a single (event -> objective) step, in the right order."""
    scenario, sector, vehicle, task = _setup("S1")
    agent = PersistentAgent(vehicle.vehicle_id, MockVehicleAdapter(0.0),
                            home=vehicle.start, battery_total_s=vehicle.battery_s,
                            cruise_altitude=sector.altitude)
    r = agent.run(task)
    objectives = [d.split("->")[1] for d in r.decisions]
    # the first decision reacts to task assignment, not a precomputed plan
    assert r.decisions[0].startswith("task_assigned")
    # objectives appear in the expected closed-loop order
    for step in ["take_off", "go_to_sector", "search_sector", "report",
                 "return_home", "land", "done"]:
        assert step in objectives, (step, objectives)
    assert objectives.index("take_off") < objectives.index("search_sector")
    assert objectives.index("search_sector") < objectives.index("land")


def test_detects_target_in_sector():
    scenario, sector, vehicle, task = _setup("S1")  # T1 lives in S1
    agent = PersistentAgent(vehicle.vehicle_id, MockVehicleAdapter(0.0),
                            home=vehicle.start, battery_total_s=vehicle.battery_s,
                            cruise_altitude=sector.altitude)
    r = agent.run(task)
    assert "T1" in r.detections


def test_low_battery_returns_without_finishing_search():
    scenario, sector, vehicle, task = _setup("S1")
    # only enough battery to take off and start heading out
    agent = PersistentAgent(vehicle.vehicle_id, MockVehicleAdapter(0.0),
                            home=vehicle.start, battery_total_s=8.0,
                            cruise_altitude=sector.altitude)
    r = agent.run(task)
    assert not r.completed
    assert r.aborted_safely          # it still landed safely
    assert not r.sector_searched     # it did NOT keep searching on low battery
    assert r.landed
    events = [e.split(":")[0] for e in r.detail.split(" | ")]
    assert AgentEvent.BATTERY_LOW.value in events


class FlakyAdapter(MockVehicleAdapter):
    """Times out the first go_to_waypoint call, then behaves normally.
    Used to prove the agent recovers from a failed navigation skill."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._failed_once = False

    def go_to_waypoint(self, vehicle_id, waypoint, speed_mps, timeout_s):
        if not self._failed_once:
            self._failed_once = True
            self._p(vehicle_id)          # ensure state exists
            self._advance(vehicle_id, 1.0)
            return NavOutcome(final_position=self.get_position(vehicle_id),
                              elapsed_s=1.0, timed_out=True)
        return super().go_to_waypoint(vehicle_id, waypoint, speed_mps, timeout_s)


def test_recovers_from_failed_navigation():
    scenario, sector, vehicle, task = _setup("S1")
    agent = PersistentAgent(vehicle.vehicle_id, FlakyAdapter(0.0),
                            home=vehicle.start, battery_total_s=vehicle.battery_s,
                            cruise_altitude=sector.altitude)
    r = agent.run(task)
    # despite the first nav failure, it retried and finished the task
    assert r.completed, r.decisions
    assert any("go_to_sector" in d and ("skill_timeout" in d or "skill_failed" in d)
               for d in r.decisions) or "skill_timeout" in r.detail


if __name__ == "__main__":
    tests = [
        ("agent completes the search task from a task alone",
         test_agent_completes_search_task),
        ("decides one skill at a time (no preflight plan)",
         test_no_preflight_plan_one_skill_at_a_time),
        ("detects the target in its sector", test_detects_target_in_sector),
        ("low battery -> return/land without finishing search",
         test_low_battery_returns_without_finishing_search),
        ("recovers from a failed navigation skill",
         test_recovers_from_failed_navigation),
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
