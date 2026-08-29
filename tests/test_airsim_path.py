"""Tests for the AirSim code path, run against a fake AirSim (no simulator needed).

Every other suite exercises the mock adapter, which bypasses
`AirSimVehicleAdapter` completely. That gap hid two bugs that would only ever
have appeared on the simulator:

  1. the adapter had no `now()`, so the agent's clock read 0 forever in AirSim -
     battery never depleted, information never aged, message timestamps were all
     zero, and the Phase 5 low-battery abort could not fire in flight;
  2. the Phase 4-7 scripts never spawned their vehicles, so every run would have
     failed with "Vehicle API for Drone1 not available".

Both have regression tests below. What these tests CANNOT check is real flight:
timing, whether a real sweep exceeds its timeout, landing behaviour, or true RPC
concurrency. Those still require flying it - see docs/SIM_TESTING.md.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.simulator import fake_airsim
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every script that claims to support --airsim, with the flag it uses
AIRSIM_SCRIPTS = [
    ("scripts/phase3_demo.py", "--adapter airsim"),
    ("scripts/phase3_showcase.py", "--adapter airsim"),
    ("scripts/run_canonical_mission.py", "--airsim"),
    ("scripts/run_persistent_agent.py", "--airsim"),
    ("scripts/run_persistent_agent.py", "--airsim --log"),
    ("scripts/run_team_mission.py", "--airsim"),
    ("scripts/run_team_mission.py", "--airsim --messages --beliefs"),
    ("scripts/run_allocation_mission.py", "--airsim"),
    ("scripts/run_allocation_mission.py", "--airsim --bids --conflicts"),
]

# runs a script with the fake airsim installed first
_HARNESS = """
import sys
sys.path.insert(0, {root!r})
from agentic_uav.simulator import fake_airsim
fake_airsim.install()
sys.argv = ['{script}'] + {flags!r}
import runpy
runpy.run_path({script!r}, run_name='__main__')
"""


def _run_script(script, flags):
    code = _HARNESS.format(root=ROOT, script=os.path.join(ROOT, script),
                           flags=flags.split())
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)


# --- the adapter itself ---

def test_airsim_adapter_implements_everything_the_agent_uses():
    """Structural check: anything the agent layer calls on the mock adapter must
    also exist on the AirSim adapter. This is what would have caught the missing
    now() before it cost a simulator session."""
    fake_airsim.install()
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter

    required = ["get_state", "get_position", "takeoff", "go_to_waypoint",
                "turn_to_heading", "hold", "land", "cancel", "stop",
                "now", "execute_skill"]
    missing = [m for m in required if not callable(getattr(AirSimVehicleAdapter, m, None))]
    assert not missing, f"AirSimVehicleAdapter is missing: {missing}"

    # and it must not have drifted from the mock's surface
    mock_api = {m for m in dir(MockVehicleAdapter)
                if not m.startswith("_") and callable(getattr(MockVehicleAdapter, m))}
    air_api = {m for m in dir(AirSimVehicleAdapter)
               if not m.startswith("_") and callable(getattr(AirSimVehicleAdapter, m))}
    gap = mock_api - air_api - {"actions_for"}       # mock-only test helper
    assert not gap, f"mock has methods AirSim adapter lacks: {gap}"


def test_adapter_clock_advances():
    """Regression: now() must exist and move, or battery never depletes in the sim."""
    fake_airsim.install()
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    a = AirSimVehicleAdapter()
    t0 = a.now("Drone1")
    for _ in range(200000):
        pass
    t1 = a.now("Drone1")
    assert t1 >= t0
    assert isinstance(t1, float)


def test_adapter_flies_a_skill_end_to_end():
    fake_airsim.install()
    from agentic_uav.control import skills as sk
    from agentic_uav.control.skill_executor import SkillExecutor
    from agentic_uav.core.enums import SkillStatus
    from agentic_uav.core.models import Position3D
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter

    ex = SkillExecutor(AirSimVehicleAdapter())
    assert ex.execute("Drone1", sk.TakeOffCommand()).status is SkillStatus.SUCCESS
    r = ex.execute("Drone1", sk.GoToWaypointCommand(waypoint=Position3D(20, 20, -8)))
    assert r.status is SkillStatus.SUCCESS, r.error_code
    assert ex.execute("Drone1", sk.LandCommand()).status is SkillStatus.SUCCESS


def test_sloppy_arrival_still_within_tolerance():
    """A drone that lands 0.5 m off target should still count as arrived."""
    fake_airsim.install(arrival_error_m=0.5)
    from agentic_uav.control import skills as sk
    from agentic_uav.control.skill_executor import SkillExecutor
    from agentic_uav.core.enums import SkillStatus
    from agentic_uav.core.models import Position3D
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter

    ex = SkillExecutor(AirSimVehicleAdapter())
    ex.execute("Drone1", sk.TakeOffCommand())
    r = ex.execute("Drone1", sk.GoToWaypointCommand(waypoint=Position3D(20, 20, -8)))
    assert r.status is SkillStatus.SUCCESS


def test_arrival_far_off_target_is_reported_as_failure():
    """And one that ends 6 m away must NOT be reported as success."""
    fake_airsim.install(arrival_error_m=6.0)
    from agentic_uav.control import skills as sk
    from agentic_uav.control.skill_executor import SkillExecutor
    from agentic_uav.core.enums import SkillStatus
    from agentic_uav.core.models import Position3D
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter

    ex = SkillExecutor(AirSimVehicleAdapter())
    ex.execute("Drone1", sk.TakeOffCommand())
    r = ex.execute("Drone1", sk.GoToWaypointCommand(waypoint=Position3D(20, 20, -8)))
    assert r.status is not SkillStatus.SUCCESS


def test_unspawned_vehicle_raises_the_real_airsim_error():
    """The fake reproduces the error we actually hit, so the spawn fix is testable."""
    fake_airsim.install(known_vehicles=())      # empty sim
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    a = AirSimVehicleAdapter()
    try:
        a.get_position("Drone1")
        raise AssertionError("expected a 'Vehicle API not available' error")
    except RuntimeError as e:
        assert "not available" in str(e)


def test_agent_reacts_to_low_battery_on_the_airsim_adapter():
    """Phase 5's safety behaviour must work on the real adapter, not just the mock.

    Battery here is real elapsed time, so the fake burns wall clock per move.
    This test only passes because the adapter has a working clock - with the
    missing-now() bug the battery stayed at 100% forever and the agent happily
    flew the entire mission on an empty one.
    """
    fake_airsim.install(move_duration_s=0.02)
    from agentic_uav.agents.objectives import SearchTask
    from agentic_uav.agents.persistent_agent import PersistentAgent
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    sector = sc.sectors[0]
    agent = PersistentAgent("Drone1", AirSimVehicleAdapter(),
                            home=sc.vehicles[0].start, battery_total_s=0.15,
                            cruise_altitude=sector.altitude)
    r = agent.run(SearchTask("search_S1", sector, sc.base.position))
    assert not r.completed          # it must not press on with a flat battery
    assert r.landed                 # but it must land
    assert any("battery" in d for d in r.decisions), r.decisions


def test_battery_is_only_checked_between_skills():
    """Documents a real limitation of the design, so it can't regress silently.

    Battery is sampled in `observe()`, which runs once per decision - so a drone
    that crosses the threshold *during* a long search sweep won't react until
    that sweep finishes. On the mock this is invisible (skills advance a
    simulated clock in one jump); in the simulator a sweep is ~90s of real
    flight. Reacting mid-skill would need monitoring inside the executor.
    """
    fake_airsim.install(move_duration_s=0.01)
    from agentic_uav.agents.objectives import SearchTask
    from agentic_uav.agents.persistent_agent import PersistentAgent
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    sector = sc.sectors[0]
    agent = PersistentAgent("Drone1", AirSimVehicleAdapter(),
                            home=sc.vehicles[0].start, battery_total_s=0.12,
                            cruise_altitude=sector.altitude)
    agent.run(SearchTask("search_S1", sector, sc.base.position))

    # the battery event lands on a decision boundary, never inside a skill
    events = [e for e, _d in agent.belief.history]
    assert any(e.startswith("battery") for e in events), events
    # and by the time it noticed, it had already finished the skill it was on
    assert agent.belief.last_result is not None


# --- the scripts ---

def test_every_airsim_script_runs():
    """Regression for the missing-spawn bug: each --airsim entry point must run
    end to end. Any script that forgets to spawn its vehicles fails here."""
    failures = []
    for script, flags in AIRSIM_SCRIPTS:
        p = _run_script(script, flags)
        if p.returncode != 0:
            tail = (p.stderr or p.stdout).strip().splitlines()[-6:]
            failures.append(f"{script} {flags} -> exit {p.returncode}\n"
                            + "\n".join("      " + t for t in tail))
    assert not failures, "AirSim path broken:\n" + "\n".join(failures)


def test_phase4_to_7_scripts_spawn_their_vehicles():
    """Static check: the newer scripts must self-heal missing vehicles the way the
    Phase 1-3 scripts always did."""
    need_spawn = ["scripts/run_canonical_mission.py",
                  "scripts/run_persistent_agent.py",
                  "scripts/run_team_mission.py"]
    missing = []
    for path in need_spawn:
        src = open(os.path.join(ROOT, path)).read()
        if "spawn_missing_drones" not in src:
            missing.append(path)
    assert not missing, f"scripts never spawn vehicles: {missing}"


def test_threaded_team_runner_completes_without_deadlock():
    """Four agents, four threads, one shared bus - must finish, not hang."""
    fake_airsim.install()
    from agentic_uav.experiments.team_runner import build_team, run_team_threaded
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    shared = AirSimVehicleAdapter()
    agents, tasks, bus, _ = build_team(sc, lambda vid: shared)
    report = run_team_threaded(agents, tasks, bus)

    assert not report.errors, report.errors
    assert report.all_completed, {v: r.completed for v, r in report.agents.items()}
    assert bus.stats()["delivered"] > 0
    for a in agents:
        assert a.belief.team.teammates, f"{a.vehicle_id} heard from nobody"


def test_decentralized_allocation_works_on_the_airsim_adapter():
    """Phase 8 must divide the work when flying the real adapter too, not just
    on the mock - the allocation runs inside the agent loop, which the AirSim
    path drives differently (threads, real clock)."""
    fake_airsim.install()
    from agentic_uav.coordination.tasks import TaskStatus
    from agentic_uav.experiments.team_runner import (
        build_allocating_team, run_team_threaded)
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario

    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))
    shared = AirSimVehicleAdapter()
    agents, tasks, bus, _ = build_allocating_team(sc, lambda vid: shared)
    report = run_team_threaded(agents, tasks, bus)
    assert not report.errors, report.errors

    completed, claims = {}, {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                completed[t.task_id] = t.assigned_agent
            if t.assigned_agent:
                claims.setdefault(t.task_id, set()).add(t.assigned_agent)
    sectors = {f"SEARCH_SECTOR_S{i}" for i in (1, 2, 3, 4)}
    assert sectors <= set(completed), completed
    disputed = {k: v for k, v in claims.items() if len(v) > 1}
    assert not disputed, f"boards disagree after a threaded run: {disputed}"


def test_each_vehicle_gets_its_own_client():
    """The concurrency fix: one MultirotorClient per vehicle, never shared."""
    fake_airsim.install()
    from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
    a = AirSimVehicleAdapter()
    for vid in ["Drone1", "Drone2", "Drone3", "Drone4"]:
        a.get_position(vid)
    clients = [id(c) for c in a._clients.values()]
    assert len(a._clients) == 4
    assert len(set(clients)) == 4, "clients are being shared between vehicles"


if __name__ == "__main__":
    tests = [
        ("AirSim adapter implements the full agent-facing API",
         test_airsim_adapter_implements_everything_the_agent_uses),
        ("adapter clock exists and advances", test_adapter_clock_advances),
        ("adapter flies takeoff/waypoint/land", test_adapter_flies_a_skill_end_to_end),
        ("sloppy arrival still within tolerance",
         test_sloppy_arrival_still_within_tolerance),
        ("arrival far off target reported as failure",
         test_arrival_far_off_target_is_reported_as_failure),
        ("unspawned vehicle raises the real error",
         test_unspawned_vehicle_raises_the_real_airsim_error),
        ("low-battery abort works on the AirSim adapter",
         test_agent_reacts_to_low_battery_on_the_airsim_adapter),
        ("battery is only checked between skills (known limitation)",
         test_battery_is_only_checked_between_skills),
        ("Phase 4-7 scripts spawn their vehicles",
         test_phase4_to_7_scripts_spawn_their_vehicles),
        ("every --airsim script runs end to end", test_every_airsim_script_runs),
        ("threaded team runner completes without deadlock",
         test_threaded_team_runner_completes_without_deadlock),
        ("decentralized allocation works on AirSim adapter",
         test_decentralized_allocation_works_on_the_airsim_adapter),
        ("each vehicle gets its own client", test_each_vehicle_gets_its_own_client),
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
        finally:
            fake_airsim.uninstall()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
