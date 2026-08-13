"""Sets up the drones in the simulator before a mission runs.

Reproduces the baseline's two setup steps: write an AirSim settings.json for the
fleet, and spawn any drones that aren't already in the world at runtime. For the
mock adapter this is a no-op. Kept separate from the adapter so scenario setup
(number of drones, spawn layout) can grow independently of flight control.
"""

import json
import os

from ..control.navigation import SPACING


def write_airsim_settings(num_drones: int):
    """Write settings.json declaring Drone1..DroneN (SimpleFlight vehicles)."""
    settings_dir = os.path.join(os.path.expanduser("~"), "Documents", "AirSim")
    os.makedirs(settings_dir, exist_ok=True)
    path = os.path.join(settings_dir, "settings.json")

    vehicles = {}
    for i in range(1, num_drones + 1):
        vehicles[f"Drone{i}"] = {
            "VehicleType": "SimpleFlight",
            "AutoCreate": True,
            "X": (i - 1) * SPACING, "Y": 0.0, "Z": 0.0,
        }
    with open(path, "w") as f:
        json.dump({
            "SettingsVersion": 1.2,
            "SimMode": "Multirotor",
            "Vehicles": vehicles,
        }, f, indent=4)
    return path


def spawn_missing_drones(client, num_drones: int):
    """Add Drone1..DroneN at runtime if the sim doesn't already have them.

    `client` is an airsim.MultirotorClient. Self-heals if settings.json didn't
    create them (e.g. after a sim restart), matching the baseline behavior.
    """
    import airsim
    existing = set(client.listVehicles())
    for i in range(1, num_drones + 1):
        name = f"Drone{i}"
        if name in existing:
            continue
        client.simAddVehicle(
            vehicle_name=name, vehicle_type="SimpleFlight",
            pose=airsim.Pose(
                airsim.Vector3r((i - 1) * SPACING, 0.0, 0.0),
                airsim.Quaternionr(0.0, 0.0, 0.0, 1.0),
            ),
        )
