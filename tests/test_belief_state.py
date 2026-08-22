"""Phase 6 tests: structured belief, truth/belief separation, staleness, and the
decision log that shows what the agent knew and did not know.

The leak tests are the important ones. A decentralized experiment is only
meaningful if the agent genuinely lacks global information, so these check that
claim two ways: structurally (no ground-truth objects reachable from the belief)
and behaviourally (a target outside sensing range is never learned about).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.belief_schema import (
    Provenance, Source, TeamBelief,
)
from agentic_uav.agents.objectives import SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.core.mission_models import MissionScenario, Target
from agentic_uav.core.models import Position3D
from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

SCENARIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "configs", "missions", "search_relay_001.yaml")


def _agent(sector_id="S1", battery=None, scenario=None, with_sensor=True):
    scenario = scenario or load_scenario(SCENARIO)
    sector = next(s for s in scenario.sectors if s.sector_id == sector_id)
    vehicle = scenario.vehicles[0]
    truth = GroundTruth(scenario)
    sensor = SensorModel(truth) if with_sensor else None
    agent = PersistentAgent(
        vehicle.vehicle_id, MockVehicleAdapter(0.0), home=vehicle.start,
        battery_total_s=battery or vehicle.battery_s,
        cruise_altitude=sector.altitude, sensor=sensor,
        roster=truth.roster(), sector_ids=truth.sector_ids())
    agent.belief.brief(scenario)
    task = SearchTask(task_id=f"search_{sector_id}", sector=sector,
                      report_to=scenario.base.position)
    return agent, task, scenario


# --- 6.1 structure ---

def test_belief_has_all_schema_sections():
    agent, _task, _s = _agent()
    b = agent.belief
    for section in ["self_", "mission", "local_map", "team",
                    "communication", "assumptions"]:
        assert hasattr(b, section), section
    k = b.known()
    for section in ["self", "mission", "local_map", "team",
                    "communication", "assumptions"]:
        assert section in k, section


def test_phase5_accessors_still_work():
    """The flat Phase 5 API must survive the restructure (behavior preservation)."""
    agent, _task, _s = _agent()
    b = agent.belief
    assert b.vehicle_id == "Drone1"
    assert b.battery_frac == 1.0
    assert not b.low_battery and not b.critical_battery
    assert b.near_home
    assert b.detections == []


# --- 6.2 truth vs belief ---

def _reachable_objects(root, max_depth=6):
    """Walk an object graph collecting instances (for the leak test)."""
    seen, out, stack = set(), [], [(root, 0)]
    while stack:
        obj, depth = stack.pop()
        if depth > max_depth or id(obj) in seen:
            continue
        seen.add(id(obj))
        out.append(obj)
        children = []
        if isinstance(obj, dict):
            children = list(obj.keys()) + list(obj.values())
        elif isinstance(obj, (list, tuple, set)):
            children = list(obj)
        elif hasattr(obj, "__dict__"):
            children = list(vars(obj).values())
        for c in children:
            if not isinstance(c, (str, int, float, bool, type(None))):
                stack.append((c, depth + 1))
    return out


def test_belief_contains_no_ground_truth():
    """No GroundTruth / MissionScenario / Target objects reachable from belief."""
    agent, task, _s = _agent()
    agent.run(task)
    leaked = [o for o in _reachable_objects(agent.belief)
              if isinstance(o, (GroundTruth, SensorModel, MissionScenario, Target))]
    assert not leaked, f"ground truth leaked into belief: {leaked}"


def test_task_carries_no_target_list():
    _agent_, task, _s = _agent()
    assert not hasattr(task, "targets_of_interest")


def test_target_outside_sensing_range_is_never_learned():
    """Behavioural proof of no global information: a target in a sector the agent
    does not search must not appear in its belief."""
    agent, task, scenario = _agent("S1")   # T1 is in S1, T2 is far away in S3
    r = agent.run(task)
    assert "T1" in r.detections            # it flew over T1, so it saw it
    assert "T2" not in r.detections        # it never went near T2
    assert "T2" not in agent.belief.local_map.target_ids


def test_agent_without_sensor_perceives_nothing():
    agent, task, _s = _agent(with_sensor=False)
    r = agent.run(task)
    assert r.detections == []              # no sensor, no knowledge
    assert r.completed                     # but it still completes the task


# --- 6.3 staleness ---

def test_teammate_confidence_decays_with_age():
    team = TeamBelief()
    team.update("Drone2", now=0.0, source=Source.PEER_MESSAGE,
                position=Position3D(10, 10, -8), status="ok")
    rec = team.teammates["Drone2"]
    assert rec.status_confidence(0.0) == 1.0
    mid = rec.status_confidence(20.0)      # one half-life
    assert 0.4 < mid < 0.6
    assert rec.status_confidence(0.0) > mid > rec.status_confidence(29.0)


def test_stale_and_expired_records_are_flagged():
    team = TeamBelief()
    team.update("Drone2", now=0.0, source=Source.PEER_MESSAGE,
                position=Position3D(10, 10, -8), status="ok")
    rec = team.teammates["Drone2"]
    assert not rec.is_stale(0.0)
    assert rec.is_stale(40.0)              # confidence decayed below threshold
    assert rec.is_expired(31.0)            # past the peer-message TTL (30s)
    assert rec.status_confidence(31.0) == 0.0
    assert team.fresh(0.0) and not team.fresh(40.0)


def test_old_position_report_is_not_treated_as_current():
    """The whole point of 6.3: an old report must be visibly stale in the belief."""
    agent, _task, _s = _agent()
    b = agent.belief
    b.receive_teammate_report("Drone2", position=Position3D(40, 40, -8),
                              status="ok", sent_at=0.0)
    b.now = 45.0                            # 45 seconds later, no new contact
    snapshot = b.known()["team"]["Drone2"]
    assert snapshot["stale"] is True
    assert snapshot["age_s"] == 45.0
    assert snapshot["status_confidence"] < 0.5
    assert "Drone2" in " ".join(b.unknown(roster=["Drone1", "Drone2"]))


# --- exit criterion: the log shows knowledge AND gaps ---

def test_decision_log_records_known_and_unknown():
    agent, task, _s = _agent()
    r = agent.run(task)
    log = r.log
    assert len(log.records) == r.steps
    for rec in log.records:
        assert rec.known["self"]["vehicle_id"] == "Drone1"
        assert "local_map" in rec.known and "team" in rec.known
        assert isinstance(rec.unknown, list)
        assert rec.objective
    # early on it knows of no targets; by the end it has observed one
    assert "no targets observed yet" in log.records[0].unknown
    assert log.records[-1].known["local_map"]["observed_targets"] == ["T1"]
    # and the gaps shrink as it learns
    assert "sector S1 not searched by me" in log.records[0].unknown
    assert "sector S1 not searched by me" not in log.records[-1].unknown


def test_decision_log_serialises_to_json():
    import json
    agent, task, _s = _agent()
    r = agent.run(task)
    data = json.loads(r.log.to_json())
    assert isinstance(data, list) and data
    assert {"step", "triggers", "known", "unknown", "objective"} <= set(data[0])


if __name__ == "__main__":
    tests = [
        ("belief has all six schema sections", test_belief_has_all_schema_sections),
        ("Phase 5 flat accessors still work", test_phase5_accessors_still_work),
        ("no ground truth reachable from belief", test_belief_contains_no_ground_truth),
        ("task carries no target list", test_task_carries_no_target_list),
        ("target outside sensing range is never learned",
         test_target_outside_sensing_range_is_never_learned),
        ("agent without a sensor perceives nothing",
         test_agent_without_sensor_perceives_nothing),
        ("teammate confidence decays with age",
         test_teammate_confidence_decays_with_age),
        ("stale and expired records are flagged",
         test_stale_and_expired_records_are_flagged),
        ("old position report is not treated as current",
         test_old_position_report_is_not_treated_as_current),
        ("decision log records known AND unknown",
         test_decision_log_records_known_and_unknown),
        ("decision log serialises to JSON", test_decision_log_serialises_to_json),
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
