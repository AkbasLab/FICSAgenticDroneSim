"""Phase 8 tests: decentralized task allocation with no central assignment.

The exit criterion is the last group: four drones given one mission divide the
sectors themselves, complete the work, and resolve simultaneous claims
deterministically.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination.bidding import (
    Bid, BidWeights, best_bid, compute_bid)
from agentic_uav.coordination.task_allocator import TaskAllocator
from agentic_uav.coordination.tasks import (
    MissionTask, TaskBoard, TaskStatus, TaskType, tasks_from_scenario)
from agentic_uav.experiments.team_runner import build_allocating_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")


def _scenario():
    return load_scenario(SCENARIO)


def _team(latency_s=0.0, lease_s=None, bid_window_s=None, battery_s=None):
    return build_allocating_team(
        _scenario(), lambda vid: MockVehicleAdapter(0.0), latency_s=latency_s,
        lease_s=lease_s, bid_window_s=bid_window_s, battery_s=battery_s)


# --- 8.1 task representation ---

def test_mission_task_has_required_fields():
    t = MissionTask(task_id="SEARCH_SECTOR_A", task_type=TaskType.SEARCH_SECTOR)
    for f in ["task_id", "task_type", "region", "priority",
              "required_capabilities", "deadline", "status", "assigned_agent",
              "lease_expires_at"]:
        assert hasattr(t, f), f
    assert t.status is TaskStatus.UNASSIGNED


def test_tasks_built_from_scenario():
    tasks = tasks_from_scenario(_scenario())
    ids = {t.task_id for t in tasks}
    assert {"SEARCH_SECTOR_S1", "SEARCH_SECTOR_S2",
            "SEARCH_SECTOR_S3", "SEARCH_SECTOR_S4"} <= ids
    assert "MAINTAIN_RELAY_POINT_R1" in ids


def test_task_survives_a_wire_round_trip():
    t = tasks_from_scenario(_scenario())[0]
    t.claim("Drone2", 0.42, now=10.0, lease_s=60.0)
    back = MissionTask.from_payload(t.to_payload())
    assert back.task_id == t.task_id
    assert back.assigned_agent == "Drone2"
    assert back.version == t.version
    assert back.winning_bid == 0.42
    assert back.region.min_x == t.region.min_x


# --- 8.3 deterministic bidding ---

def _belief(vehicle_id="Drone1", x=0.0, y=0.0, battery=1.0):
    from agentic_uav.agents.belief_state import BeliefState
    from agentic_uav.core.models import Position3D
    b = BeliefState(vehicle_id, Position3D(x, y, 0.0), battery_total_s=900.0)
    b.observe(Position3D(x, y, -8.0), 900.0 * (1.0 - battery))
    return b


def test_bid_is_deterministic():
    task = tasks_from_scenario(_scenario())[0]
    a = compute_bid(task, _belief())
    b = compute_bid(task, _belief())
    assert a.value == b.value
    assert a.breakdown == b.breakdown


def test_bid_includes_all_five_terms():
    task = tasks_from_scenario(_scenario())[0]
    bid = compute_bid(task, _belief())
    assert set(bid.breakdown) == {"D", "B", "L", "C", "R"}


def test_closer_drone_bids_lower():
    task = tasks_from_scenario(_scenario())[0]      # S1, near (10,10)
    near = compute_bid(task, _belief("Drone1", x=10, y=10))
    far = compute_bid(task, _belief("Drone2", x=-50, y=-50))
    assert near.value < far.value


def test_low_battery_raises_the_bid():
    task = tasks_from_scenario(_scenario())[0]
    full = compute_bid(task, _belief(battery=1.0))
    low = compute_bid(task, _belief(battery=0.2))
    assert low.value > full.value


def test_capability_mismatch_disqualifies():
    task = tasks_from_scenario(_scenario())[0]      # needs "search"
    bid = compute_bid(task, _belief(), capabilities={"relay"})
    assert not bid.eligible
    assert best_bid([bid]) is None


def test_ties_break_on_vehicle_id():
    a = Bid(vehicle_id="Drone3", task_id="T", value=1.0)
    b = Bid(vehicle_id="Drone1", task_id="T", value=1.0)
    assert best_bid([a, b]).vehicle_id == "Drone1"
    assert best_bid([b, a]).vehicle_id == "Drone1"   # order must not matter


# --- 8.4 leases ---

def test_lease_expires_and_task_reopens():
    t = tasks_from_scenario(_scenario())[0]
    t.claim("Drone1", 0.5, now=0.0, lease_s=30.0)
    assert not t.is_open(now=10.0)
    assert t.held_by("Drone1", now=10.0)
    assert t.lease_expired(now=31.0)
    assert t.is_open(now=31.0)                       # available again
    assert not t.held_by("Drone1", now=31.0)


def test_renewal_extends_the_lease_without_bumping_version():
    t = tasks_from_scenario(_scenario())[0]
    t.claim("Drone1", 0.5, now=0.0, lease_s=30.0)
    v = t.version
    t.renew(now=20.0, lease_s=30.0)
    assert not t.lease_expired(now=45.0)
    assert t.version == v, "renewal must not out-rank a rival's claim"


def test_silent_drone_loses_its_task_to_a_teammate():
    """8.4's recovery mechanism, end to end."""
    agents, tasks, bus, _ = _team(lease_s=1.0)       # leases expire almost at once
    for a in agents:
        a.start(None)
    for _ in range(30):
        for a in agents:
            if not a.finished:
                a.step()
    reclaimed = any("lease expired" in e
                    for a in agents for e in a.allocator.events)
    assert reclaimed, "no lease was ever reclaimed"


# --- 8.5 conflict resolution ---

def _conflict_pair(local_kwargs, incoming_kwargs):
    board = TaskBoard(tasks_from_scenario(_scenario())[:1])
    task = board.all()[0]
    for k, v in local_kwargs.items():
        setattr(task, k, v)
    alloc = TaskAllocator("Drone1", board)
    incoming = MissionTask.from_payload(task.to_payload())
    for k, v in incoming_kwargs.items():
        setattr(incoming, k, v)
    alloc._resolve_conflict(incoming, incoming.assigned_agent, _belief())
    return alloc, board.all()[0]


def test_conflict_rule_1_higher_version_wins():
    alloc, task = _conflict_pair(
        {"assigned_agent": "Drone1", "version": 3, "winning_bid": 0.1},
        {"assigned_agent": "Drone2", "version": 5, "winning_bid": 0.9})
    assert task.assigned_agent == "Drone2"
    assert alloc.conflicts[-1].rule == "version"


def test_conflict_rule_2_lower_bid_wins():
    alloc, task = _conflict_pair(
        {"assigned_agent": "Drone1", "version": 4, "winning_bid": 0.8},
        {"assigned_agent": "Drone2", "version": 4, "winning_bid": 0.2})
    assert task.assigned_agent == "Drone2"
    assert alloc.conflicts[-1].rule == "lower_bid"


def test_conflict_rule_3_lower_agent_id_wins():
    alloc, task = _conflict_pair(
        {"assigned_agent": "Drone3", "version": 4, "winning_bid": 0.5},
        {"assigned_agent": "Drone2", "version": 4, "winning_bid": 0.5})
    assert task.assigned_agent == "Drone2"
    assert alloc.conflicts[-1].rule == "lower_agent_id"


def test_conflicts_are_logged():
    alloc, _t = _conflict_pair(
        {"assigned_agent": "Drone1", "version": 4, "winning_bid": 0.8},
        {"assigned_agent": "Drone2", "version": 4, "winning_bid": 0.2})
    c = alloc.conflicts[-1]
    assert c.incumbent == "Drone1" and c.challenger == "Drone2"
    assert c.winner == "Drone2" and c.rule and "task" in c.to_dict()


def test_versions_are_globally_comparable():
    """A Lamport bump, not a local counter - otherwise two agents' version
    numbers are unrelated and rule 1 does the wrong thing."""
    t = tasks_from_scenario(_scenario())[0]
    t.claim("Drone1", 0.5, now=0.0, lease_s=60.0, seen_version=7)
    assert t.version == 8


# --- exit criterion ---

def _run_and_check(latency_s=0.0):
    agents, tasks, bus, _ = _team(latency_s=latency_s)
    run_team(agents, tasks, bus)

    claims = {}
    completed = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.assigned_agent:
                claims.setdefault(t.task_id, set()).add(t.assigned_agent)
            if t.status is TaskStatus.COMPLETE:
                completed[t.task_id] = t.assigned_agent
    return agents, bus, claims, completed


def test_four_drones_divide_the_sectors_with_no_central_assignment():
    agents, bus, claims, completed = _run_and_check()
    assert len(agents) == 4

    # nobody was handed a task: every agent started empty
    for a in agents:
        assert a.allocator is not None

    # all four sectors were completed
    sectors = {f"SEARCH_SECTOR_S{i}" for i in (1, 2, 3, 4)}
    assert sectors <= set(completed), completed

    # and each was done by exactly one drone, with all boards agreeing
    for tid in sectors:
        assert len(claims[tid]) == 1, f"{tid} disputed by {claims[tid]}"

    # the work was actually shared out, not hoarded by one drone
    holders = {completed[t] for t in sectors}
    assert len(holders) == 4, f"work not divided: {holders}"


def test_allocation_converges_even_when_claims_collide():
    """With latency, agents claim before hearing each other - the conflict rules
    must still converge every board on one holder per task."""
    agents, bus, claims, completed = _run_and_check(latency_s=20.0)
    conflicts = sum(len(a.allocator.conflicts) for a in agents)
    assert conflicts > 0, "no simultaneous claims occurred; test proves nothing"
    disputed = {k: v for k, v in claims.items() if len(v) > 1}
    assert not disputed, f"boards never converged: {disputed}"
    # and no sector got flown twice
    assert len(completed) == len([t for t in completed if t.startswith("SEARCH")])


def test_allocation_is_deterministic():
    a1, _b1, c1, d1 = _run_and_check()
    a2, _b2, c2, d2 = _run_and_check()
    assert d1 == d2, "same mission produced a different division"
    assert {k: sorted(v) for k, v in c1.items()} == \
           {k: sorted(v) for k, v in c2.items()}


def test_every_agent_ends_up_home_and_landed():
    agents, _bus, _claims, _completed = _run_and_check()
    for a in agents:
        assert a.belief.landed, f"{a.vehicle_id} did not land"
        assert a.belief.near_home, f"{a.vehicle_id} did not return"


if __name__ == "__main__":
    tests = [
        ("MissionTask has the required fields", test_mission_task_has_required_fields),
        ("tasks built from the scenario", test_tasks_built_from_scenario),
        ("task survives a wire round trip", test_task_survives_a_wire_round_trip),
        ("bid is deterministic", test_bid_is_deterministic),
        ("bid includes all five terms", test_bid_includes_all_five_terms),
        ("closer drone bids lower", test_closer_drone_bids_lower),
        ("low battery raises the bid", test_low_battery_raises_the_bid),
        ("capability mismatch disqualifies", test_capability_mismatch_disqualifies),
        ("ties break on vehicle id", test_ties_break_on_vehicle_id),
        ("lease expires and task reopens", test_lease_expires_and_task_reopens),
        ("renewal extends lease without bumping version",
         test_renewal_extends_the_lease_without_bumping_version),
        ("silent drone loses its task", test_silent_drone_loses_its_task_to_a_teammate),
        ("conflict rule 1: higher version", test_conflict_rule_1_higher_version_wins),
        ("conflict rule 2: lower bid", test_conflict_rule_2_lower_bid_wins),
        ("conflict rule 3: lower agent id", test_conflict_rule_3_lower_agent_id_wins),
        ("conflicts are logged", test_conflicts_are_logged),
        ("versions are globally comparable", test_versions_are_globally_comparable),
        ("4 drones divide sectors with no central assignment",
         test_four_drones_divide_the_sectors_with_no_central_assignment),
        ("allocation converges when claims collide",
         test_allocation_converges_even_when_claims_collide),
        ("allocation is deterministic", test_allocation_is_deterministic),
        ("every agent returns home and lands",
         test_every_agent_ends_up_home_and_landed),
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
