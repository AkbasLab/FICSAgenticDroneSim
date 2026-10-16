"""Replay the same mission under all four communication conditions (Phase 10).

Same scenario, same seed, same agents — only the network changes. That is the
point: any difference in outcome is attributable to communication, because
nothing else varied.

    python scripts/run_comms_study.py
    python scripts/run_comms_study.py --seed 42
    python scripts/run_comms_study.py --estimates   # what agents *think* the link is
    python scripts/run_comms_study.py --condition severe --messages
    python scripts/run_comms_study.py --airsim                # fly it (severe)
    python scripts/run_comms_study.py --airsim --condition partitioned

With --airsim only one condition is flown. Each condition is a full four-drone
mission, the drones finish on their pads, and the simulator has to be reset
between runs for the next one to start from the same state - so the four-way
comparison stays a mock-only study, and the simulator run is for watching one
condition play out.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination import comms_conditions as cc
from agentic_uav.coordination.tasks import TaskStatus
from agentic_uav.experiments.team_runner import build_allocating_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "missions", "search_relay_001.yaml")


def run_one(scenario, profile, seed, lease_s, heartbeat_s, factory=None):
    factory = factory or (lambda vid: MockVehicleAdapter(0.0))
    agents, tasks, bus, _truth = build_allocating_team(
        scenario, factory,
        network=profile, seed=seed, lease_s=lease_s,
        heartbeat_interval_s=heartbeat_s)
    report = run_team(agents, tasks, bus)

    completed = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                completed.setdefault(t.task_id, t.assigned_agent)
    return agents, bus, report, completed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=DEFAULT_SCENARIO)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--condition", default=None,
                    help="run just one: nominal | moderate | severe | partitioned")
    ap.add_argument("--lease", type=float, default=150.0)
    ap.add_argument("--heartbeat", type=float, default=15.0)
    ap.add_argument("--estimates", action="store_true",
                    help="show each agent's ESTIMATE of link quality")
    ap.add_argument("--messages", action="store_true")
    ap.add_argument("--airsim", action="store_true",
                    help="fly ONE condition in CARLA-Air (default: severe)")
    args = ap.parse_args()
    from agentic_uav.simulator.scenario_manager import for_simulator
    args.scenario = for_simulator(args.scenario, getattr(args, "airsim", False))

    scenario = load_scenario(args.scenario)

    factory = None
    if args.airsim:
        from agentic_uav.simulator import scenario_manager
        from agentic_uav.simulator.airsim_adapter import AirSimVehicleAdapter
        if not args.condition:
            args.condition = "severe"
            print("\n--airsim flies one condition; using 'severe' "
                  "(pass --condition to choose another)")
        shared = AirSimVehicleAdapter()
        scenario_manager.spawn_missing_drones(shared.client,
                                              len(scenario.vehicles))
        factory = lambda vid: shared

    names = [args.condition] if args.condition else cc.ORDER

    print(f"\n=== Communication study (seed {args.seed}) ===")
    print("conditions are experimental parameters, not a model of a real radio:\n")
    print(cc.summary())
    print()

    header = (f"{'condition':<13} {'sectors':>8} {'sent':>6} {'deliv':>6} "
              f"{'rate':>6} {'delay':>8}  drops")
    print(header)
    print("-" * len(header))

    results = {}
    for name in names:
        profile = cc.condition(name)
        agents, bus, report, completed = run_one(
            scenario, profile, args.seed, args.lease, args.heartbeat,
            factory=factory)
        s = bus.stats()
        results[name] = (agents, bus, completed, s)

        drops = ", ".join(f"{k}={v}" for k, v in sorted(
            s["drop_reasons"].items())) or "none"
        print(f"{name:<13} {len(completed):>4}/{len(scenario.sectors):<3} "
              f"{s['sent']:>6} {s['delivered']:>6} "
              f"{s['delivery_rate']:>5.0%} {s['mean_delivery_delay_s']:>7.2f}s  {drops}")

    if args.estimates:
        _print_estimates(results)
    if args.messages and len(names) == 1:
        print("\n=== message log ===")
        print(results[names[0]][1].log.format_text(limit=25))

    print()
    return 0


def _print_estimates(results):
    """What each agent BELIEVES the link is doing, vs what it was configured to do.

    The agent never reads the configuration - these estimates come only from
    sequence gaps, arrival times and heartbeat rates.

    Two things to read carefully:
      * `msg_age` is how old messages are when the agent reads them, NOT wire
        latency. It is dominated by decision cadence (tens of seconds), so it is
        expected to be far larger than the configured latency.
      * `est_loss` counts everything that failed to arrive, including messages
        the rate limiter refused. Under `severe` that is most of them, so the
        estimate legitimately exceeds the configured packet-loss probability.
    """
    print("\n=== agents' own estimates vs the configured values ===")
    for name, (agents, bus, _completed, _s) in results.items():
        cfg = bus.network.profile if bus.network else None
        cfg_loss = cfg.packet_loss_probability if cfg else 0.0
        cfg_lat = (cfg.latency_ms_mean / 1000.0) if cfg else 0.0
        print(f"\n  {name}  (configured: loss {cfg_loss:.0%}, "
              f"wire latency {cfg_lat:.2f}s)")
        for a in agents:
            if a.comms is None:
                continue
            est = a.comms.summary(a.belief.now)
            print(f"    {a.vehicle_id}: est_loss={est['estimated_loss_rate']:.0%} "
                  f"msg_age={est['estimated_message_age_s']:.1f}s "
                  f"heartbeat_rate={est['heartbeat_arrival_rate']:.2f} "
                  f"silence={est['silence_s']:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
