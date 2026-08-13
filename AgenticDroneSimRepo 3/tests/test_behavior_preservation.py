"""Verify the refactor didn't change behavior.

Runs missions through the pipeline with the MOCK adapter (no sim, no LLM) using
the deterministic rule policy, and checks the exact sequence of skills each
drone executes. This is the objective 'same missions produce the same actions'
check Dr. Akbas asked for. Run:  python tests/test_behavior_preservation.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.rule_policy import RulePolicy
from agentic_uav.experiments.runner import run_mission
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  ok    {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}\n        got:      {got}\n        expected: {expected}")
        failed += 1


def run(instruction):
    adapter = MockVehicleAdapter()
    run_mission(adapter, RulePolicy, {"Drone1": instruction}, concurrent=False)
    return adapter.actions_for("Drone1")


print("Every mission is bookended by arm_takeoff ... stop (the baseline lifecycle):\n")

# hover then land
check("hover 3s then land",
      run("hover for 3 seconds then land"),
      ["arm_takeoff", "hover", "land", "stop"])

# forward then land
check("fly forward then land",
      run("fly forward for 5 seconds then land"),
      ["arm_takeoff", "fly_straight", "land", "stop"])

# backward, return home, land
check("backward, return home, land",
      run("fly backward for 4 seconds, return home, then land"),
      ["arm_takeoff", "fly_backward", "fly_to", "land", "stop"])

# altitude + directional
check("go up, fly left, land",
      run("go up to 15 meters, fly left for 3 seconds, then land"),
      ["arm_takeoff", "set_altitude", "fly_left", "land", "stop"])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
