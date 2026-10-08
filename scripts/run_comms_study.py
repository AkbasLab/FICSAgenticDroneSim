"""Phase 10: replays the same allocation mission under each named network
condition and prints delivery stats, so "the agentic version holds up under
severe comms" means something checkable, not just claimed.

    python scripts/run_comms_study.py                  # all conditions
    python scripts/run_comms_study.py --condition severe
    python scripts/run_comms_study.py --seed 42         # a different draw
    python scripts/run_comms_study.py --estimates       # agents' own view of link quality
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents.comms_estimator import CommsEstimator
from fics_drone.core.scenario import load_scenario
from fics_drone.coordination.comms_conditions import BY_NAME, ORDER
from fics_drone.coordination.message_bus import MessageBus
from fics_drone.coordination.network_model import NetworkModel
from fics_drone.experiments.team_runner import run_team_threaded
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "configs", "missions",
                                 "search_relay_001.json")


def run_condition(scenario, condition_name: str, seed: int, with_estimates: bool):
    profile = BY_NAME[condition_name]
    network_model = NetworkModel(profile, seed=seed)
    bus = MessageBus(network_model=network_model)
    adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
    estimators = {d.name: CommsEstimator() for d in scenario.drones} if with_estimates else None
    reports, agents, bus = run_team_threaded(scenario, adapters, bus=bus, comms_estimators=estimators)

    sent = len(bus.log)
    delivered_entries = [e for e in bus.log if e.delivered]
    delivered = len(delivered_entries)
    mean_delay_ms = (sum(e.delay_s for e in delivered_entries) / delivered * 1000.0) if delivered else 0.0
    drops = {}
    for e in bus.log:
        if not e.delivered:
            drops[e.reason] = drops.get(e.reason, 0) + 1
    # Sector assignment is static here (Phase 7's run_team_threaded, on purpose -
    # see team_runner.py), so "sectors" reports whether each drone's own mission
    # actually ran to completion despite the degraded link, not whether it won a sector.
    sectors_done = sum(1 for r in reports.values() if r.trace and r.trace[-1] == "skill_succeeded->done")

    stats = {
        "condition": condition_name, "sectors": f"{sectors_done}/{len(scenario.sectors)}",
        "sent": sent, "delivered": delivered,
        "rate": f"{(delivered / sent * 100.0) if sent else 0.0:.0f}%",
        "delay": f"{mean_delay_ms / 1000.0:.2f}s", "drops": drops,
    }
    return stats, agents, estimators


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--condition", choices=ORDER, default=None, help="default: run all")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--estimates", action="store_true")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    conditions = [args.condition] if args.condition else ORDER

    print(f"{'condition':<12}{'sectors':<9}{'sent':<7}{'deliv':<7}{'rate':<7}{'delay':<9}drops")
    for name in conditions:
        stats, agents, estimators = run_condition(scenario, name, args.seed, args.estimates)
        drops_str = ", ".join(f"{k}={v}" for k, v in stats["drops"].items()) or "none"
        print(f"{stats['condition']:<12}{stats['sectors']:<9}{stats['sent']:<7}{stats['delivered']:<7}"
              f"{stats['rate']:<7}{stats['delay']:<9}{drops_str}")

        if estimators:
            for agent_name, est in estimators.items():
                for peer in agents:
                    if peer == agent_name:
                        continue
                    loss = est.estimated_loss_rate(peer)
                    if loss is not None:
                        print(f"    {agent_name} estimates {peer}: loss={loss:.2f}")


if __name__ == "__main__":
    main()
