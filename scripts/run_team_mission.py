"""Four persistent agents flying together, talking over the message bus (Phase 7).

Each agent searches its own sector while exchanging heartbeats, status updates,
intents and target reports. Communication is perfect here (no latency, no loss) -
degradation comes in a later phase. Exit code 0 if every agent completed.

    python scripts/run_team_mission.py
    python scripts/run_team_mission.py --messages          # per-message log
    python scripts/run_team_mission.py --beliefs           # team belief per agent
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.team_runner import build_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--airsim", action="store_true")
    ap.add_argument("--messages", action="store_true",
                    help="print the per-message delivery log")
    ap.add_argument("--beliefs", action="store_true",
                    help="print each agent's team belief at the end")
    ap.add_argument("--log-json", default=None)
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)

    if args.airsim:
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        shared = AirSimVehicleAdapter()
        factory = lambda vid: shared          # adapter is per-vehicle internally
    else:
        factory = lambda vid: MockVehicleAdapter(ground_z=0.0)

    agents, tasks, bus, _truth = build_team(scenario, factory)
    report = run_team(agents, tasks, bus)

    _print(report, agents)
    if args.messages:
        print("\n=== message log (* = influenced a decision) ===")
        print(report.message_log.format_text())
    if args.beliefs:
        _print_beliefs(agents)
    if args.log_json:
        report.message_log.to_json(args.log_json)
        print(f"\n(message log written to {args.log_json})")
    return 0 if report.all_completed else 1


def _print(report, agents):
    print("\n=== Team mission (perfect communication) ===")
    for vid, r in report.agents.items():
        state = ("COMPLETE" if r.completed else
                 "ABORTED-SAFE" if r.aborted_safely else "FAILED")
        print(f"  {vid}: {r.task_id:<12} {state:<13} "
              f"targets={r.detections or '-'} battery={r.battery_frac_end:.0%}")

    s = report.message_stats
    print(f"\nsectors searched : {report.sectors_searched}")
    print(f"targets found    : {report.targets_found}")
    print(f"\nmessages sent    : {s['sent']}")
    print(f"delivered        : {s['delivered']} ({s['delivery_rate']:.0%})")
    print(f"dropped (link)   : {s['dropped_link']}   <- 0 under perfect comms")
    print(f"dropped (expired): {s['dropped_expired']}")
    print(f"mean delivery gap: {s['mean_delivery_delay_s']:.2f}s")
    print(f"influenced a decision: {s['influential']}")
    print("\nby type:")
    for t, d in sorted(report.message_log.by_type().items()):
        print(f"  {t:<18} sent {d['sent']:>3}  delivered {d['delivered']:>3}")
    print(f"\nTEAM {'SUCCESS' if report.all_completed else 'INCOMPLETE'}\n")


def _print_beliefs(agents):
    print("\n=== each agent's team belief (built only from delivered messages) ===")
    for a in agents:
        b = a.belief
        print(f"\n  {a.vehicle_id} (t={b.now:.0f}s) knows about "
              f"{len(b.team.teammates)} teammate(s):")
        for vid, rec in b.team.teammates.items():
            print(f"    {vid}: pos={_fmt(rec.last_position)} "
                  f"status={rec.status} age={rec.age(b.now):.0f}s "
                  f"conf={rec.status_confidence(b.now):.2f}"
                  f"{'  STALE' if rec.is_stale(b.now) else ''}")
        if b.detections:
            print(f"    targets known: {b.detections}")


def _fmt(p):
    return "?" if p is None else f"[{p.x:.0f},{p.y:.0f}]"


if __name__ == "__main__":
    sys.exit(main())
