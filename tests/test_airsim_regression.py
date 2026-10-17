"""AirSim regression missions (Phase 16.3) - the five 16.3 names, one test each.

    python tests/test_airsim_regression.py           # against the fake simulator
    python tests/test_airsim_regression.py --real    # against a running CARLA-Air

By default these run against `fake_airsim`, a model of the AirSim API contract,
with every move taking a little real time so that drones flying concurrently
interleave the way they do in the simulator. That is what lets them run in CI.

With `--real` the same five missions fly in CARLA-Air (ports 2000 / 41451) at
real timings. That is the "manual, or on a designated machine" half of 16.5:
nothing in the fake can tell you whether a real sweep clears the buildings or a
real landing settles, and the defects this project found only in the simulator
- frame offsets, dropped moves, a timeout handed to every leg - are each now
modelled by the fake *because* a real run found them first.

  1. single-drone waypoint mission
  2. two-drone non-conflicting mission
  3. four-drone search mission
  4. task reassignment during flight
  5. return-home fallback
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.control import skills as sk
from agentic_uav.control.skill_executor import SkillExecutor
from agentic_uav.core.enums import SkillStatus
from agentic_uav.core.models import Position3D
from agentic_uav.simulator import fake_airsim
from agentic_uav.simulator.scenario_manager import load_scenario, spawn_missing_drones

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001_sim.yaml")
REAL = "--real" in sys.argv or os.environ.get("CARLA_AIR") == "1"

#: Timings. On the fake everything is scaled down, keeping the proportions the
#: system depends on: one sweep < presumed-lost threshold (4 heartbeats) < lease.
#: In CARLA-Air those are ~85 s < 120 s < 150 s.
if REAL:
    T = dict(move_s=None, heartbeat=30.0, lease=150.0, window=5.0, hold=5.0, kill=25.0)
else:
    T = dict(move_s=0.5, heartbeat=2.2, lease=10.0, window=0.5, hold=0.5, kill=1.2)


def _adapter(move_s=0.05):
    """A fresh AirSim adapter - on the fake unless --real."""
    if not REAL:
        fake_airsim.install(move_duration_s=move_s)
    import importlib
    import agentic_uav.simulator.airsim_adapter as aa
    importlib.reload(aa)                         # bind to the fake (or real) airsim
    return aa.AirSimVehicleAdapter()


def _done():
    if not REAL:
        fake_airsim.uninstall()


class _SimBehaviours:
    """Switch on what `scenario_manager.for_simulator` switches on, then restore."""

    def __enter__(self):
        from agentic_uav.agents import persistent_agent as pa, search_policy as sp
        self._pa, self._sp = pa, sp
        self._saved = (pa.STAND_BY_FOR_TEAMMATES, pa.GOSSIP_COMPLETIONS,
                       sp.STAND_BY_HOLD_S)
        pa.STAND_BY_FOR_TEAMMATES = True
        pa.GOSSIP_COMPLETIONS = True
        sp.STAND_BY_HOLD_S = T["hold"]
        return self

    def __exit__(self, *exc):
        (self._pa.STAND_BY_FOR_TEAMMATES, self._pa.GOSSIP_COMPLETIONS,
         self._sp.STAND_BY_HOLD_S) = self._saved


def _flown(agents):
    """{sector: [vehicles]} counting only sectors a drone actually flew."""
    out = {}
    for a in agents:
        for r in a.belief.local_map.searched_regions:
            if r.by_vehicle == a.vehicle_id:
                out.setdefault(r.region_id, []).append(a.vehicle_id)
    return out


def _team(n_drones, n_sectors=None, **kw):
    import dataclasses
    from agentic_uav.experiments.team_runner import build_allocating_team
    sc = load_scenario(SIM_SCENARIO)
    sc = dataclasses.replace(sc, vehicles=sc.vehicles[:n_drones],
                             sectors=sc.sectors[:n_sectors or n_drones])
    ad = _adapter(move_s=0.05 if "move_s" not in kw else kw.pop("move_s"))
    spawn_missing_drones(ad.client, n_drones)
    agents, tasks, bus, _ = build_allocating_team(
        sc, lambda v: ad, lease_s=kw.get("lease", T["lease"]),
        heartbeat_interval_s=kw.get("heartbeat", T["heartbeat"]),
        bid_window_s=kw.get("window", T["window"]))
    return sc, agents, tasks, bus


# --- 1. single-drone waypoint mission ----------------------------------------

def test_1_single_drone_waypoint_mission():
    ad = _adapter()
    try:
        ad.place("Drone1", Position3D(0.0, 0.0, 0.0))
        ex = SkillExecutor(ad)
        home = Position3D(0.0, 0.0, -15.0)
        steps = [
            ("take off", sk.TakeOffCommand(target_altitude=-15.0, timeout_s=60.0)),
            ("fly to waypoint", sk.GoToWaypointCommand(
                waypoint=Position3D(20.0, 20.0, -15.0), speed_mps=4.0,
                tolerance_m=1.5, timeout_s=60.0)),
            ("return home", sk.ReturnHomeCommand(home=home, speed_mps=4.0,
                                                 tolerance_m=1.5, timeout_s=60.0)),
            ("land", sk.LandCommand(timeout_s=60.0)),
        ]
        for name, cmd in steps:
            r = ex.execute("Drone1", cmd)
            assert r.status is SkillStatus.SUCCESS, f"{name}: {r.status} {r.error_code}"
        p = ad.get_position("Drone1")
        assert p.horizontal_distance_to(home) <= 2.0, f"not home: {p}"
    finally:
        _done()


# --- 2. two-drone non-conflicting mission ----------------------------------------

def test_2_two_drone_non_conflicting_mission():
    from agentic_uav.experiments.team_runner import run_team_threaded
    with _SimBehaviours():
        try:
            sc, agents, tasks, bus = _team(2)
            run_team_threaded(agents, tasks, bus)
            flown = _flown(agents)
        finally:
            _done()
    assert sorted(flown) == ["S1", "S2"], f"both sectors searched: {flown}"
    assert all(len(v) == 1 for v in flown.values()), f"no sector twice: {flown}"
    assert len({v[0] for v in flown.values()}) == 2, f"one sector each: {flown}"
    assert all(a.report().landed for a in agents)


# --- 3. four-drone search mission ---------------------------------------------------

def test_3_four_drone_search_mission():
    from agentic_uav.experiments.team_runner import run_team_threaded
    with _SimBehaviours():
        try:
            sc, agents, tasks, bus = _team(4)
            run_team_threaded(agents, tasks, bus)
            flown = _flown(agents)
        finally:
            _done()
    assert sorted(flown) == ["S1", "S2", "S3", "S4"], f"every sector: {flown}"
    assert all(len(v) == 1 for v in flown.values()), f"no sector twice: {flown}"
    assert all(a.report().landed for a in agents)
    detections = set().union(*(a.reported_detections for a in agents))
    assert {"T1", "T2"} <= detections, f"both targets reported: {detections}"


# --- 4. task reassignment during flight ----------------------------------------------

def test_4_task_reassignment_during_flight():
    """Drone2 is switched off after it has claimed S2 and set off, before it
    sweeps. The rest must notice from silence alone, take S2 over and fly it."""
    from agentic_uav.experiments.team_runner import run_team_threaded
    with _SimBehaviours():
        try:
            sc, agents, tasks, bus = _team(4, move_s=T["move_s"] or 0.05)
            report = run_team_threaded(agents, tasks, bus,
                                       stop_at={"Drone2": T["kill"]})
            flown = _flown(agents)
        finally:
            _done()
    assert "Drone2" in report.stopped, report.stopped
    assert "Drone2" not in flown.get("S2", []), f"Drone2 stopped before sweeping: {flown}"
    assert sorted(flown) == ["S1", "S2", "S3", "S4"], f"S2 reassigned and flown: {flown}"
    assert all(len(v) == 1 for v in flown.values()), f"no sector twice: {flown}"
    assert all(a.report().landed for a in agents if a.vehicle_id != "Drone2")


# --- 5. return-home fallback ------------------------------------------------------------

def test_5_return_home_fallback():
    """A policy that stays broken all mission. The guardian refuses every unsafe
    command and, once the policy has shown it will not recover, flies the drone
    home itself - on the AirSim adapter, not just the mock."""
    from agentic_uav.agents.objectives import SearchTask
    from agentic_uav.agents.persistent_agent import PersistentAgent
    from agentic_uav.agents.safety_guardian import SafetyGuardian, SafetyLimits
    from agentic_uav.agents.search_policy import SearchAgentPolicy
    from agentic_uav.agents.unsafe_injection import InjectingPolicy
    from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel

    sc = load_scenario(SIM_SCENARIO)
    sector, v = sc.sectors[0], sc.vehicles[0]
    ad = _adapter()
    try:
        ad.place(v.vehicle_id, v.start)
        truth = GroundTruth(sc)
        policy = InjectingPolicy(SearchAgentPolicy(), unsafe_at={2, 3, 4},
                                 cases=["outside_geofence", "excessive_speed",
                                        "nan_waypoint"], repeat=True)
        agent = PersistentAgent(
            v.vehicle_id, ad, policy=policy, home=v.start,
            battery_total_s=v.battery_s, cruise_altitude=sector.altitude,
            sensor=SensorModel(truth), roster=truth.roster(),
            sector_ids=truth.sector_ids(),
            guardian=SafetyGuardian(limits=SafetyLimits.from_scenario(sc)))
        agent.belief.brief(sc)
        report = agent.run(SearchTask(f"search_{sector.sector_id}", sector,
                                      sc.base.position))
        final = ad.get_position(v.vehicle_id)
    finally:
        _done()
    stats = agent.guardian_log.stats()
    assert len(policy.injected) > 0, "the broken policy proposed unsafe commands"
    assert stats["interventions"] > 0, stats
    assert stats["by_fallback"], f"the guardian fell back to a safe action: {stats}"
    approved_unsafe = [r for r in agent.guardian_log.records
                       if r.outcome == "approve" and r.failed_checks]
    assert not approved_unsafe, "no unsafe command was approved"
    assert report.landed, "the drone is on the ground"
    assert final.horizontal_distance_to(v.start) <= 3.0, f"landed at home: {final}"


def main():
    tests = [
        ("1 single-drone waypoint mission", test_1_single_drone_waypoint_mission),
        ("2 two-drone non-conflicting mission", test_2_two_drone_non_conflicting_mission),
        ("3 four-drone search mission", test_3_four_drone_search_mission),
        ("4 task reassignment during flight", test_4_task_reassignment_during_flight),
        ("5 return-home fallback", test_5_return_home_fallback),
    ]
    where = "CARLA-Air (live)" if REAL else "fake AirSim"
    print(f"Phase 16.3 AirSim regression missions - {where}\n")
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
