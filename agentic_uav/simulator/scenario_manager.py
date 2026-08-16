"""Scenario setup and loading.

Two jobs:
  1. Simulator setup - write an AirSim settings.json for the fleet and spawn any
     drones that aren't already in the world (unchanged from earlier phases).
  2. Load a MissionScenario from a config file (Phase 4), so the canonical
     search-and-relay mission is defined declaratively and stays stable.
"""

import json
import os

from ..control.navigation import SPACING
from ..core.geometry import Rect
from ..core.mission_models import (
    BaseStation, MissionScenario, MissionSpec, NetworkSpec, RestrictedZone,
    Sector, Target, VehicleSpec,
)
from ..core.models import Position3D


def load_scenario(path_or_dict) -> MissionScenario:
    """Load a mission scenario from a YAML/JSON file path or an in-memory dict."""
    if isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        with open(path_or_dict) as f:
            if str(path_or_dict).endswith((".yaml", ".yml")):
                import yaml  # only needed when loading YAML files
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
    return _build_scenario(data)


def _pos(seq, default_z=-8.0):
    x = seq[0]
    y = seq[1]
    z = seq[2] if len(seq) > 2 else default_z
    return Position3D(float(x), float(y), float(z))


def _build_scenario(d) -> MissionScenario:
    m = d.get("mission", {})
    mission = MissionSpec(
        mission_type=m.get("type", "distributed_search"),
        deadline_s=float(m.get("deadline_s", 900)),
        required_coverage=float(m.get("required_coverage", 0.95)),
        targets_to_find=int(m.get("targets_to_find", 2)),
        min_separation_m=float(m.get("min_separation_m", 3.0)),
    )
    b = d.get("base", {"position": [0, 0, 0], "comm_range_m": 60})
    base = BaseStation(position=_pos(b.get("position", [0, 0, 0])),
                       comm_range_m=float(b.get("comm_range_m", 60)))

    sectors = []
    for s in d.get("sectors", []):
        r = s["footprint"]
        sectors.append(Sector(
            sector_id=s["id"],
            footprint=Rect(r[0], r[1], r[2], r[3]),
            altitude=float(s.get("altitude", -8.0))))

    targets = []
    for t in d.get("targets", []):
        targets.append(Target(
            target_id=t["id"], position=_pos(t["position"]),
            detection_radius_m=float(t.get("detection_radius_m", 8.0)),
            observation_period_s=float(t.get("observation_period_s", 1.0))))

    zones = [RestrictedZone(zone_id=z.get("id", f"zone{i}"),
                            polygon=[tuple(p) for p in z["polygon"]])
             for i, z in enumerate(d.get("restricted_zones", []))]

    vehicles = [VehicleSpec(vehicle_id=v["id"], start=_pos(v["start"], 0.0),
                            battery_s=float(v.get("battery_s", 900)))
                for v in d.get("vehicles", [])]

    net = d.get("network", {})
    return MissionScenario(
        scenario_id=d.get("scenario_id", "scenario"),
        random_seed=int(d.get("random_seed", 0)),
        mission=mission, base=base, sectors=sectors, targets=targets,
        restricted_zones=zones, vehicles=vehicles,
        network=NetworkSpec(profile=net.get("profile", "perfect")),
        faults=d.get("faults", []) or [])


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
