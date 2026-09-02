"""Kill a drone mid-mission and watch the rest carry on (Phase 9 exit criterion).

One agent is switched off partway through: no flight, no sensing, no heartbeats.
Nobody is told. The remaining agents have to notice the silence, decide it is a
failure rather than a passing comms glitch, reclaim the dead drone's sector and
finish the mission — with **no new human command** after launch.

    python scripts/run_failure_recovery.py
    python scripts/run_failure_recovery.py --kill Drone2 --at 60
    python scripts/run_failure_recovery.py --roles      # role change history
    python scripts/run_failure_recovery.py --health     # health state transitions
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination.tasks import TaskStatus
from agentic_uav.experiments.team_runner import (
    build_allocating_team, run_team_with_faults)
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--kill", default="Drone2", help="which drone to stop")
    ap.add_argument("--at", type=float, default=5.0,
                    help="sim time (s) at which to stop it")
    ap.add_argument("--lease", type=float, default=150.0,
                    help="task lease seconds. Must exceed the longest skill "
                         "(~70s sweep) or a busy drone gets its sector stolen; "
                         "failure detection, not the lease, is what frees a "
                         "dead drone's work quickly.")
    ap.add_argument("--heartbeat", type=float, default=15.0,
                    help="expected heartbeat interval, drives failure detection")
    ap.add_argument("--roles", action="store_true", help="show role changes")
    ap.add_argument("--health", action="store_true", help="show health transitions")
    ap.add_argument("--airsim", action="store_true")
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
        scenario, factory, lease_s=args.lease,
        heartbeat_interval_s=args.heartbeat)

    report = run_team_with_faults(agents, tasks, bus,
                                  stop_at={args.kill: args.at})

    ok = _print(report, agents, scenario, args.kill)
    if args.roles:
        _print_roles(agents)
    if args.health:
        _print_health(agents, args.kill)
    return 0 if ok else 1


def _print(report, agents, scenario, killed):
    print(f"\n=== Failure recovery: {killed} stopped mid-mission ===\n")
    for vid, t in report.stopped.items():
        print(f"  !! {vid} switched off at t={t:.0f}s (teammates not informed)\n")

    survivors = [a for a in agents if a.vehicle_id != killed]

    # who noticed?
    noticed = []
    for a in survivors:
        state = a.health.state_of(killed)
        if state.value in ("suspected", "unreachable", "failed"):
            noticed.append(f"{a.vehicle_id}:{state.value}")
    print(f"detected the loss : {', '.join(noticed) if noticed else 'NOBODY'}")

    # who finished what
    completed = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                completed.setdefault(t.task_id, t.assigned_agent)
    print(f"\nsectors completed : {len(completed)}/{len(scenario.sectors)}")
    for tid in sorted(completed):
        by = completed[tid]
        flag = "  <- reassigned after the failure" if by != killed and \
            tid in _tasks_once_held_by(agents, killed) else ""
        print(f"  {tid:<20} by {by}{flag}")

    orphaned = _tasks_once_held_by(agents, killed)
    reclaimed = [t for t in orphaned if completed.get(t) not in (None, killed)]
    print(f"\n{killed} had claimed : {sorted(orphaned) or 'nothing yet'}")
    print(f"reclaimed by others: {sorted(reclaimed) or 'none'}")

    print(f"\nmessages sent     : {report.message_stats['sent']}")
    print("human commands after launch: 0")

    all_done = len(completed) == len(scenario.sectors)
    print(f"\nRECOVERY {'SUCCESS' if all_done else 'INCOMPLETE'}\n")
    return all_done


def _tasks_once_held_by(agents, vehicle_id):
    """Tasks any surviving agent ever saw claimed by the dead drone."""
    out = set()
    for a in agents:
        for e in a.allocator.events:
            if f"lease expired (held by {vehicle_id})" in e:
                out.add(e.split()[1])
    for a in agents:
        if a.vehicle_id == vehicle_id:
            out.update(t.task_id for t in a.allocator.board.all()
                       if t.assigned_agent == vehicle_id)
    return out


def _print_roles(agents):
    print("=== role changes (each agent decided its own) ===")
    any_change = False
    for a in agents:
        s = a.roles.summary()
        if s["changes"]:
            any_change = True
            print(f"  {a.vehicle_id}: now {s['role']}")
            for c in s["changes"]:
                print(f"    t={c['t']:>6.0f}s  {c['from']} -> {c['to']}  ({c['why']})")
        else:
            print(f"  {a.vehicle_id}: stayed {s['role']}")
    if not any_change:
        print("  (no role changes were needed in this run)")
    print()


def _print_health(agents, killed):
    print(f"=== health state transitions (view of {killed}) ===")
    for a in agents:
        if a.vehicle_id == killed:
            continue
        lines = [e for e in a.health.events if killed in e]
        print(f"  {a.vehicle_id}:")
        for line in lines or ["    (never changed state)"]:
            print(f"    {line}")
    print()


if __name__ == "__main__":
    sys.exit(main())
