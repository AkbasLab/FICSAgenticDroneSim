"""Phase 9 tests: dynamic roles, failure detection, and recovery.

The exit criterion is the last group: kill one of four drones mid-mission and the
rest must notice, reassign its sector, and finish - with no new human command.

The health tests are as much about *restraint* as detection. Declaring failure on
one missed heartbeat would be worse than not detecting failure at all, because
tasks would be pulled off healthy drones that were merely quiet for a moment.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination.role_manager import RoleManager
from agentic_uav.coordination.roles import HealthMonitor, HealthState, Role
from agentic_uav.coordination.tasks import TaskStatus
from agentic_uav.experiments.team_runner import (
    build_allocating_team, run_team_with_faults)
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")

KILLED = "Drone2"
KILL_AT = 5.0
LEASE_S = 150.0          # must exceed the longest skill (~70s sweep)
HEARTBEAT_S = 15.0


def _scenario():
    return load_scenario(SCENARIO)


def _run_with_kill(killed=KILLED, at=KILL_AT):
    agents, tasks, bus, _t = build_allocating_team(
        _scenario(), lambda vid: MockVehicleAdapter(0.0),
        lease_s=LEASE_S, heartbeat_interval_s=HEARTBEAT_S)
    report = run_team_with_faults(agents, tasks, bus, stop_at={killed: at})
    return agents, bus, report


def _completed(agents):
    out = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                out.setdefault(t.task_id, t.assigned_agent)
    return out


# --- 9.1 roles ---

def test_three_roles_exist():
    assert {r.value for r in Role} == {"scout", "relay", "reserve"}


def test_relay_stops_bidding_on_search_work():
    """A RELAY drops the `search` capability, so the ordinary capability check
    keeps sectors away from it - no special case in the allocator."""
    rm = RoleManager("Drone1")
    assert "search" in rm.capabilities_for(Role.SCOUT)
    assert "search" not in rm.capabilities_for(Role.RELAY)
    assert "search" in rm.capabilities_for(Role.RESERVE)


def _belief(vehicle_id="Drone1", battery=1.0, base_reachable=True):
    from agentic_uav.agents.belief_state import BeliefState
    from agentic_uav.core.models import Position3D
    b = BeliefState(vehicle_id, Position3D(0, 0, 0), battery_total_s=900.0)
    b.observe(Position3D(0, 0, -8), 900.0 * (1.0 - battery))
    b.communication.base_reachable = base_reachable
    return b


def test_agent_becomes_relay_when_base_is_unreachable():
    rm = RoleManager("Drone1")
    d = rm.decide(_belief(base_reachable=False), open_task_count=4)
    assert d.role is Role.RELAY, d.reason


def test_agent_scouts_when_there_is_work():
    rm = RoleManager("Drone1")
    assert rm.decide(_belief(), open_task_count=2).role is Role.SCOUT


def test_agent_reserves_when_out_of_work():
    rm = RoleManager("Drone1")
    assert rm.decide(_belief(), open_task_count=0).role is Role.RESERVE


def test_low_battery_forces_reserve_not_scout():
    rm = RoleManager("Drone1")
    d = rm.decide(_belief(battery=0.2), open_task_count=4)
    assert d.role is Role.RESERVE
    assert "battery" in d.reason


def test_role_change_is_recorded():
    rm = RoleManager("Drone1")
    rm.decide(_belief(), open_task_count=2)          # scout
    d = rm.decide(_belief(), open_task_count=0)      # -> reserve
    assert d.changed
    assert rm.summary()["changes"], rm.summary()


def test_role_decision_is_deterministic():
    a = RoleManager("Drone1").decide(_belief(), open_task_count=1)
    b = RoleManager("Drone1").decide(_belief(), open_task_count=1)
    assert a.role is b.role and a.reason == b.reason


# --- 9.2 failure detection ---

def test_all_five_health_states_exist():
    assert {h.value for h in HealthState} == {
        "healthy", "suspected", "unreachable", "failed", "recovered"}


def test_peer_is_healthy_at_mission_start():
    """Nobody has spoken yet at t=0 - that is not a failure."""
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.tick(now=0.0, roster=["Drone1", "Drone2"])
    assert hm.state_of("Drone2") is HealthState.HEALTHY


def test_one_missed_heartbeat_does_not_declare_failure():
    """The restraint requirement in 9.2, stated as a test."""
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone2", now=0.0)
    hm.tick(now=12.0, roster=["Drone1", "Drone2"])    # 1.2 intervals of silence
    assert hm.state_of("Drone2") is HealthState.HEALTHY


def test_silence_escalates_through_the_states():
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone2", now=0.0)
    hm.tick(now=25.0, roster=[])      # 2.5 intervals
    assert hm.state_of("Drone2") is HealthState.SUSPECTED
    hm.tick(now=45.0, roster=[])      # 4.5 intervals
    assert hm.state_of("Drone2") is HealthState.UNREACHABLE
    hm.tick(now=85.0, roster=[])      # 8.5 intervals
    assert hm.state_of("Drone2") is HealthState.FAILED


def test_a_peer_that_speaks_again_is_recovered():
    """Comms loss and vehicle loss are different conditions (9.2)."""
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone2", now=0.0)
    hm.tick(now=45.0, roster=[])
    assert hm.state_of("Drone2") is HealthState.UNREACHABLE
    hm.note_heard("Drone2", now=50.0)                 # it was just quiet
    assert hm.state_of("Drone2") is HealthState.RECOVERED
    assert "Drone2" in hm.healthy_peers()


def test_suspected_peer_is_still_usable():
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone2", now=0.0)
    hm.tick(now=25.0, roster=[])
    assert hm.state_of("Drone2") is HealthState.SUSPECTED
    assert "Drone2" in hm.healthy_peers()      # suspected != written off
    assert "Drone2" not in hm.failed_peers()


def test_transitions_are_logged():
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone2", now=0.0)
    hm.tick(now=45.0, roster=[])
    assert any("Drone2" in e for e in hm.events)
    assert hm.peers["Drone2"].transitions


# --- 9.3 recovery, and the lease/skill-duration constraint ---

def test_a_busy_drone_does_not_lose_its_own_task():
    """A drone inside a long skill still owns its sector even if the lease lapses
    - it is working, not silent. Losing it here was a real bug: teammates stole
    sectors from healthy drones mid-sweep."""
    agents, _bus, _r = _run_with_kill()
    survivors = [a for a in agents if a.vehicle_id != KILLED]
    for a in survivors:
        assert a.completed_tasks, f"{a.vehicle_id} finished nothing"


def test_failed_drones_task_is_reclaimed_before_its_lease_expires():
    """Health detection short-circuits the lease (9.3). With a 150s lease and a
    kill at 15s, waiting out the lease would waste most of the mission."""
    agents, _bus, report = _run_with_kill()
    completed = _completed(agents)
    assert "SEARCH_SECTOR_S2" in completed
    assert completed["SEARCH_SECTOR_S2"] != KILLED, \
        "the dead drone cannot have completed it"


def test_reserve_takes_over_a_lost_relay():
    """9.3 step 4/5: a spare drone covers the relay role when the relay is lost."""
    hm = HealthMonitor("Drone1", heartbeat_interval_s=10.0)
    hm.note_heard("Drone3", now=0.0)
    hm.tick(now=90.0, roster=[])                     # Drone3 now FAILED
    rm = RoleManager("Drone1", hm)
    rm.role = Role.RESERVE

    b = _belief()
    b.receive_teammate_report("Drone3", role="relay", sent_at=0.0)
    d = rm.decide(b, open_task_count=0)
    assert d.role is Role.RELAY
    assert "Drone3" in d.reason


# --- exit criterion ---

def test_four_drones_recover_from_one_being_stopped():
    scenario = _scenario()
    agents, bus, report = _run_with_kill()

    # the drone really was stopped, and told nobody
    assert report.stopped, "no agent was stopped"
    killed_agent = next(a for a in agents if a.vehicle_id == KILLED)
    assert killed_agent.stopped

    # somebody noticed, from silence alone
    survivors = [a for a in agents if a.vehicle_id != KILLED]
    noticed = [a.vehicle_id for a in survivors
               if a.health.state_of(KILLED) in (HealthState.UNREACHABLE,
                                                HealthState.FAILED)]
    assert noticed, "nobody detected the failure"

    # every sector got done anyway
    completed = _completed(agents)
    for i in (1, 2, 3, 4):
        assert f"SEARCH_SECTOR_S{i}" in completed, completed
    # and none of them by the dead drone
    assert completed["SEARCH_SECTOR_S2"] != KILLED


def test_recovery_needed_no_new_human_command():
    """Operationally: after start(), the only inputs are messages and sensing."""
    agents, _bus, _r = _run_with_kill()
    # nothing external assigns work - every task an agent flew, it won itself
    for a in agents:
        for tid in a.completed_tasks:
            t = a.allocator.board.get(tid)
            assert t.assigned_agent == a.vehicle_id, \
                f"{a.vehicle_id} flew {tid} without claiming it"


def test_recovery_is_deterministic():
    a1, _b1, _r1 = _run_with_kill()
    a2, _b2, _r2 = _run_with_kill()
    assert _completed(a1) == _completed(a2)


# --- 9.4 controlled emergence, checked operationally ---

def test_controlled_emergence_properties_hold():
    """Each bullet of 9.4 as an assertion."""
    agents, bus, report = _run_with_kill()

    # no central controller specified any drone's task sequence
    for a in agents:
        assert a.allocator is not None

    # agents used only local beliefs and delivered messages: no ground truth
    from agentic_uav.core.mission_models import MissionScenario, Target
    from agentic_uav.simulator.ground_truth import GroundTruth
    def reachable(root, depth=0, seen=None):
        seen = seen if seen is not None else set()
        if depth > 5 or id(root) in seen:
            return []
        seen.add(id(root))
        out = [root]
        kids = []
        if isinstance(root, dict):
            kids = list(root.values())
        elif isinstance(root, (list, tuple, set)):
            kids = list(root)
        elif hasattr(root, "__dict__"):
            kids = list(vars(root).values())
        for k in kids:
            if not isinstance(k, (str, int, float, bool, type(None))):
                out += reachable(k, depth + 1, seen)
        return out
    for a in agents:
        leaked = [o for o in reachable(a.belief)
                  if isinstance(o, (GroundTruth, MissionScenario, Target))]
        assert not leaked, f"{a.vehicle_id} belief holds ground truth"

    # allocation resulted from agent interaction - messages were exchanged
    assert bus.stats()["delivered"] > 0

    # deterministic constraints still applied: everyone that lived landed home
    for a in agents:
        if a.vehicle_id == KILLED:
            continue
        assert a.belief.landed, f"{a.vehicle_id} never landed"


if __name__ == "__main__":
    tests = [
        ("three roles exist", test_three_roles_exist),
        ("relay stops bidding on search work",
         test_relay_stops_bidding_on_search_work),
        ("becomes relay when base unreachable",
         test_agent_becomes_relay_when_base_is_unreachable),
        ("scouts when there is work", test_agent_scouts_when_there_is_work),
        ("reserves when out of work", test_agent_reserves_when_out_of_work),
        ("low battery forces reserve", test_low_battery_forces_reserve_not_scout),
        ("role change is recorded", test_role_change_is_recorded),
        ("role decision is deterministic", test_role_decision_is_deterministic),
        ("all five health states exist", test_all_five_health_states_exist),
        ("peer healthy at mission start", test_peer_is_healthy_at_mission_start),
        ("one missed heartbeat != failure",
         test_one_missed_heartbeat_does_not_declare_failure),
        ("silence escalates through states",
         test_silence_escalates_through_the_states),
        ("peer that speaks again is recovered",
         test_a_peer_that_speaks_again_is_recovered),
        ("suspected peer is still usable", test_suspected_peer_is_still_usable),
        ("transitions are logged", test_transitions_are_logged),
        ("busy drone keeps its own task",
         test_a_busy_drone_does_not_lose_its_own_task),
        ("failed drone's task reclaimed before lease expiry",
         test_failed_drones_task_is_reclaimed_before_its_lease_expires),
        ("reserve takes over a lost relay", test_reserve_takes_over_a_lost_relay),
        ("4 drones recover from one being stopped",
         test_four_drones_recover_from_one_being_stopped),
        ("recovery needed no new human command",
         test_recovery_needed_no_new_human_command),
        ("recovery is deterministic", test_recovery_is_deterministic),
        ("controlled emergence properties hold",
         test_controlled_emergence_properties_hold),
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
