"""Run one mission through the new architecture.

Reproduces the baseline agents (gemini/llama/mistral) plus the deterministic
rule policy, but routed through MissionPlanner + VehicleAdapter.

Examples:
    python scripts/run_single_mission.py --planner gemini
    python scripts/run_single_mission.py --planner llama --drones 2
    python scripts/run_single_mission.py --planner rule --adapter mock   # no sim
    python scripts/run_single_mission.py --mission configs/missions/example_two_drone.json

Interactive by default: it asks how many drones and what each should do, exactly
like the open-loop baseline. With --mission it reads the drones/instructions
from a JSON file instead.
"""

import argparse
import json
import os
import sys

# allow running from the repo root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments.runner import run_mission
from agentic_uav.experiments.metrics import summarize
from agentic_uav.planners.factory import make_planner, make_adapter


def gather_interactive():
    n = int(input("How many drones? "))
    if n < 1:
        raise SystemExit("need at least 1 drone")
    instructions = {}
    for i in range(1, n + 1):
        vid = f"Drone{i}"
        instructions[vid] = input(f"What should {vid} do? ").strip()
    return instructions


def gather_from_file(path):
    with open(path) as f:
        data = json.load(f)
    # {"drones": {"Drone1": "instruction", ...}}
    return data["drones"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", default="gemini",
                    help="gemini | llama | mistral | rule")
    ap.add_argument("--adapter", default="airsim", help="airsim | mock")
    ap.add_argument("--drones", type=int, default=None,
                    help="skip the count prompt (interactive mode)")
    ap.add_argument("--mission", default=None,
                    help="path to a mission JSON instead of prompting")
    args = ap.parse_args()

    planner_factory = make_planner(args.planner)
    adapter = make_adapter(args.adapter)

    if args.mission:
        instructions = gather_from_file(args.mission)
    elif args.drones is not None:
        instructions = {}
        for i in range(1, args.drones + 1):
            vid = f"Drone{i}"
            instructions[vid] = input(f"What should {vid} do? ").strip()
    else:
        instructions = gather_interactive()

    # Real simulator: make sure the drones exist first (mock doesn't need it).
    if args.adapter.lower() == "airsim":
        from agentic_uav.simulator import scenario_manager
        scenario_manager.spawn_missing_drones(adapter.client, len(instructions))

    results = run_mission(adapter, planner_factory, instructions)
    print("Summary:", summarize(results))


if __name__ == "__main__":
    main()
