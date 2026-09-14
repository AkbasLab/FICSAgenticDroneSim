"""Inject unsafe commands and watch the guardian stop them (Phase 11).

Two parts:

1. **Catalogue** — every unsafe command in `unsafe_injection.py` is put to the
   guardian directly, and the outcome plus the named check that caught it are
   printed. Nothing flies.
2. **Live mission** — a mission is flown with a deliberately compromised policy
   that substitutes an unsafe command partway through. The agent does not know;
   the guardian is the only thing between the bad command and the vehicle.

Exit code 0 means every unsafe command was blocked.

    python scripts/run_guardian_demo.py
    python scripts/run_guardian_demo.py --live          # also fly the mission
    python scripts/run_guardian_demo.py --case nan_waypoint
    python scripts/run_guardian_demo.py --live --repeat # policy stays broken
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.objectives import SearchTask
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.agents.safety_guardian import (
    GuardianOutcome, SafetyGuardian, SafetyLimits)
from agentic_uav.agents.search_policy import SearchAgentPolicy
from agentic_uav.agents.unsafe_injection import UNSAFE_COMMANDS, InjectingPolicy, case
from agentic_uav.core.models import Position3D
from agentic_uav.experiments.guardian_log import GuardianLog
from agentic_uav.simulator.ground_truth import GroundTruth, SensorModel
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def _belief(scenario, airborne=True, battery=1.0, with_teammate=True):
    from agentic_uav.agents.belief_state import BeliefState
    v = scenario.vehicles[0]
    b = BeliefState(v.vehicle_id, v.start, battery_total_s=900.0)
    b.brief(scenario)
    b.observe(Position3D(10.0, 10.0, -8.0), 900.0 * (1.0 - battery))
    b.airborne = airborne
    if with_teammate:
        # a fresh teammate sitting at (40,40) so the separation check has
        # something real to work with
        b.receive_teammate_report("Drone2", position=Position3D(40.0, 40.0, -8.0),
                                  status="ok", sent_at=b.now)
    return b


def run_catalogue(scenario, only=None):
    print("\n=== Unsafe command catalogue ===")
    print("Each command is put to the guardian directly. Nothing flies.\n")

    limits = SafetyLimits.from_scenario(scenario)
    cases = [case(only)] if only else UNSAFE_COMMANDS

    header = f"  {'case':<26} {'outcome':<28} {'caught by':<22} fallback"
    print(header)
    print("  " + "-" * (len(header) - 2))

    blocked = 0
    for c in cases:
        guardian = SafetyGuardian(limits=limits, log=GuardianLog("Drone1"))
        belief = _belief(scenario)
        decision = guardian.evaluate(c.command(), belief)

        caught = [k.name for k in decision.failed]
        expected_hit = c.expects_check in caught
        if decision.blocked:
            blocked += 1

        mark = " " if (decision.blocked and expected_hit) else "!"
        print(f" {mark}{c.name:<26} {decision.outcome.value:<28} "
              f"{','.join(caught)[:21]:<22} "
              f"{decision.fallback.value if decision.fallback else '-'}")

    print(f"\n  blocked {blocked}/{len(cases)} "
          f"({'all unsafe commands stopped' if blocked == len(cases) else 'SOME GOT THROUGH'})")
    return blocked == len(cases)


def run_live(scenario, repeat=False, cases=None):
    print("\n=== Live mission with a compromised policy ===")
    print("The policy substitutes unsafe commands mid-mission. The agent does")
    print("not know. Only the guardian stands between them and the vehicle.\n")

    truth = GroundTruth(scenario)
    sector = scenario.sectors[0]
    vehicle = scenario.vehicles[0]

    policy = InjectingPolicy(
        SearchAgentPolicy(),
        unsafe_at={2, 3, 4},
        cases=cases or ["outside_geofence", "excessive_speed", "nan_waypoint"],
        repeat=repeat)

    agent = PersistentAgent(
        vehicle.vehicle_id, MockVehicleAdapter(0.0), policy=policy,
        home=vehicle.start, battery_total_s=vehicle.battery_s,
        cruise_altitude=sector.altitude, sensor=SensorModel(truth),
        roster=truth.roster(), sector_ids=truth.sector_ids(),
        guardian=SafetyGuardian(limits=SafetyLimits.from_scenario(scenario)))
    agent.belief.brief(scenario)

    report = agent.run(SearchTask(f"search_{sector.sector_id}", sector,
                                  scenario.base.position))

    print(f"  unsafe commands injected : {policy.injected}")
    print()
    print(agent.guardian_log.format_summary())
    print()
    print("=== guardian interventions ===")
    print(agent.guardian_log.format_text())

    stats = agent.guardian_log.stats()
    unsafe_executed = _unsafe_reached_vehicle(agent, policy)
    print(f"  unsafe commands that reached the vehicle: {unsafe_executed}")
    print(f"  drone landed safely at home: {report.landed and report.returned_home}")
    return unsafe_executed == 0 and report.landed


def _unsafe_reached_vehicle(agent, policy):
    """Count injected commands that the guardian approved unchanged."""
    n = 0
    for r in agent.guardian_log.records:
        if r.outcome == "approve":
            d = r.proposed_detail or {}
            wp = d.get("waypoint")
            speed = d.get("speed_mps")
            if wp and (abs(wp[0]) > 200 or abs(wp[1]) > 200):
                n += 1
            elif speed is not None and speed > 12.0:
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--case", default=None, help="run a single catalogue case")
    ap.add_argument("--live", action="store_true",
                    help="also fly a mission with a compromised policy")
    ap.add_argument("--repeat", action="store_true",
                    help="the policy stays broken for the whole mission")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)
    ok = run_catalogue(scenario, only=args.case)
    if args.live:
        ok = run_live(scenario, repeat=args.repeat) and ok

    print(f"\nGUARDIAN {'HELD' if ok else 'FAILED TO CONTAIN'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
