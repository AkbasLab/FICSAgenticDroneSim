"""Interactive multi-drone session: connect and take off every drone once, then
each round ask for one instruction per drone (blank = leave that drone as-is).
Drones run concurrently; land only when told to, or when a plan says 'land'.

Drone names must match the vehicles in AirSim's settings.json.
"""

import sys

from .control.fleet import FleetController
from .planners.base_planner import PlanError
from .planners.llama_planner import LlamaPlanner
from .simulator.airsim_adapter import AirSimVehicleAdapter

DEFAULT_DRONES = ["Drone1", "Drone2"]


def main():
    names = sys.argv[1:] or DEFAULT_DRONES
    fleet = FleetController(
        LlamaPlanner(), {n: AirSimVehicleAdapter(n) for n in names},
    )
    fleet.takeoff_all()
    print(f"{', '.join(names)} airborne. Blank line skips a drone; 'stop' lands everyone.")

    while not fleet.all_landed:
        instructions = {}
        for name in names:
            if name in fleet.landed:
                continue
            text = input(f"{name}> ").strip()
            if text.lower() in ("stop", "exit", "quit"):
                fleet.land_all()
                print("Done.")
                return
            if text:
                instructions[name] = text

        if not instructions:
            continue
        try:
            fleet.run(instructions)
        except (PlanError, ValueError) as e:
            print(f"Nothing flew. {e}. Try rewording.")

    print("Everyone landed - session over.")


if __name__ == "__main__":
    main()
