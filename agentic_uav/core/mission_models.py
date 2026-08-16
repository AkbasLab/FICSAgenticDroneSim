"""Data models for a mission scenario and its result (Phase 4).

A MissionScenario is the fixed, configurable world: a base station, search
sectors, targets, a restricted region, vehicles, a network profile, faults, a
battery budget and a deadline. It is loaded from a config file so the canonical
mission stays stable while the architecture around it changes.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import Rect
from .models import Position3D


@dataclass
class BaseStation:
    position: Position3D
    comm_range_m: float = 60.0   # detections are "reported" within this range


@dataclass
class Sector:
    sector_id: str
    footprint: Rect
    altitude: float = -8.0


@dataclass
class Target:
    target_id: str
    position: Position3D
    detection_radius_m: float = 8.0
    observation_period_s: float = 1.0


@dataclass
class RestrictedZone:
    zone_id: str
    polygon: List[Tuple[float, float]]   # (x, y) vertices


@dataclass
class VehicleSpec:
    vehicle_id: str
    start: Position3D
    battery_s: float = 900.0             # simulated flight-time budget


@dataclass
class MissionSpec:
    mission_type: str = "distributed_search"
    deadline_s: float = 900.0
    required_coverage: float = 0.95
    targets_to_find: int = 2
    min_separation_m: float = 3.0


@dataclass
class NetworkSpec:
    profile: str = "perfect"             # perfect for Phase 4; degraded later


@dataclass
class MissionScenario:
    scenario_id: str
    random_seed: int
    mission: MissionSpec
    base: BaseStation
    sectors: List[Sector]
    targets: List[Target]
    restricted_zones: List[RestrictedZone]
    vehicles: List[VehicleSpec]
    network: NetworkSpec = field(default_factory=NetworkSpec)
    faults: List[dict] = field(default_factory=list)


# --- run/result types ---


@dataclass
class Detection:
    target_id: str
    by_vehicle: str
    at_time_s: float
    position: Position3D
    reported: bool = False


@dataclass
class MissionReport:
    """The evaluated outcome against the Phase 4.3 success criteria."""
    success: bool = False
    coverage: float = 0.0
    sectors_searched: List[str] = field(default_factory=list)
    detections: List[Detection] = field(default_factory=list)
    restricted_entry: bool = False
    separation_violation: bool = False
    battery_exceeded: bool = False
    deadline_exceeded: bool = False
    all_returned: bool = False
    criteria: Dict[str, bool] = field(default_factory=dict)
    detail: str = ""
