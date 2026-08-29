"""Four drones divide a mission between themselves, with no central assignment.

This is the Phase 8 exit criterion. Every drone is given the same task board and
nothing else - who searches which sector is decided entirely by the contract-net
protocol running independently on each agent.

    python scripts/run_allocation_mission.py
    python scripts/run_allocation_mission.py --bids       # show every bid
    python scripts/run_allocation_mission.py --conflicts  # conflict resolutions
    python scripts/run_allocation_mission.py --airsim     # fly it
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.team_runner import (
    build_allocating_team, run_team, run_team_threaded)
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--airsim", action="store_true")
    ap.add_argument("--bids", action="store_true", help="show every bid computed")
    ap.add_argument("--conflicts", action="store_true",
                    help="show duplicate-claim resolutions")
    ap.add_argument("--lease", type=float, default=None,
                    help="lease seconds (short values force re-allocation)")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)

    if args.airsim:
        from agentic_uav.simulator import scenario_manager
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        shared = AirSimVehicleAdapter()
        scenario_manager.spawn_missing_drones(shared.client,
                                              len(scenario.vehicles))
        factory = lambda vid: shared
    else:
        factory = lambda vid: MockVehicleAdapter(ground_z=0.0)

    agents, tasks, bus, _truth = build_allocating_team(
        scenario, factory, lease_s=args.lease)
    report = (run_team_threaded(agents, tasks, bus) if args.airsim
              else run_team(agents, tasks, bus))
    if report.errors:
        print("\nERRORS:")
        for vid, err in report.errors.items():
            print(f"  {vid}: {err}")

    _print(report, agents, scenario)
    if args.bids:
        _print_bids(agents)
    if args.conflicts:
        _print_conflicts(agents)
    return 0 if _all_sectors_done(agents, scenario) else 1


def _all_sectors_done(agents, scenario):
    """Every sector claimed and completed by somebody, with no duplicates."""
    done = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status.value == "complete":
                done[t.task_id] = t.assigned_agent or done.get(t.task_id)
    return len(done) == len(scenario.sectors)


def _print(report, agents, scenario):
    print("\n=== Decentralized allocation (no central assignment) ===\n")
    print("who ended up doing what:")
    for a in agents:
        held = [t.task_id for t in a.allocator.board.all()
                if t.assigned_agent == a.vehicle_id]
        r = report.agents[a.vehicle_id]
        print(f"  {a.vehicle_id}: {', '.join(held) or '(nothing)':<22} "
              f"searched={r.sector_searched} targets={r.detections or '-'}")

    # consensus check: do all four agents agree on the final division?
    print("\nfinal task board (each agent's own view):")
    for a in agents:
        summary = a.allocator.board.summary(a.belief.now)
        line = "  ".join(f"{k}={v}" for k, v in summary.items())
        print(f"  {a.vehicle_id}: {line}")

    claims = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.assigned_agent:
                claims.setdefault(t.task_id, set()).add(t.assigned_agent)
    disputed = {k: v for k, v in claims.items() if len(v) > 1}
    print(f"\nunresolved disagreements: {disputed or 'none'}")

    conflicts = sum(len(a.allocator.conflicts) for a in agents)
    s = report.message_stats
    print(f"conflicts resolved      : {conflicts}")
    print(f"messages sent           : {s['sent']}  delivered {s['delivered']}")

    ok = not disputed and _all_sectors_done(agents, scenario)
    print(f"\nALLOCATION {'SUCCESS' if ok else 'INCOMPLETE'}\n")


def _print_bids(agents):
    from agentic_uav.coordination.bidding import explain
    print("=== bids (lowest wins; ties broken by vehicle id) ===")
    seen = {}
    for a in agents:
        for tid, by_vehicle in a.allocator.bids.items():
            for vid, bid in by_vehicle.items():
                seen[(tid, vid)] = bid
    for (tid, vid) in sorted(seen):
        print("  " + explain(seen[(tid, vid)]))
    print()


def _print_conflicts(agents):
    print("=== conflict resolutions ===")
    any_found = False
    for a in agents:
        for c in a.allocator.conflicts:
            any_found = True
            print(f"  [{a.vehicle_id}] t={c.at_time_s:.0f}s {c.task_id}: "
                  f"{c.incumbent} vs {c.challenger} -> {c.winner} "
                  f"(rule: {c.rule}, {c.detail})")
    if not any_found:
        print("  none - the bidding separated cleanly")
    print("\n=== allocation event log ===")
    for a in agents:
        for e in a.allocator.events:
            print(f"  [{a.vehicle_id}] {e}")
    print()


if __name__ == "__main__":
    sys.exit(main())
