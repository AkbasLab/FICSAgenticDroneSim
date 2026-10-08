"""The Phase 4 world, as data. Nothing in here is a rule about how to score a
run - it's just the numbers describing one fixed mission (base, sectors,
targets, no-fly zones, per-drone battery). See fics_drone/evaluation/ for the
rules that judge a run against this."""

import json
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class DroneSpec:
    name: str
    battery_s: float
    sector: str  # which Sector.id this drone is responsible for
    spawn_offset: Tuple[float, float, float]  # this drone's real-world spawn point.
    # Skills/adapters operate in each drone's own LOCAL frame (its own (0,0,*) is its own
    # spawn point - the convention since Phase 1), but sectors/no-fly-zones/separation are
    # all defined in one shared WORLD frame. spawn_offset is what converts local -> world:
    # TelemetryRecorder adds it to every raw sample before the scorer ever sees it. Must
    # match whatever's actually configured in AirSim's settings.json for live flight -
    # these are placeholder values until verified against the real file.


@dataclass
class Sector:
    id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float


@dataclass
class Target:
    id: str
    x: float
    y: float
    detection_radius_m: float
    dwell_s: float  # must stay inside detection_radius_m for at least this long


@dataclass
class NoFlyZone:
    id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


@dataclass
class Scenario:
    scenario_id: str
    random_seed: int
    base_station: Tuple[float, float, float]
    deadline_s: float
    comms_range_m: float
    min_separation_m: float
    required_coverage: float
    drones: List[DroneSpec]
    sectors: List[Sector]
    targets: List[Target]
    no_fly_zones: List[NoFlyZone]

    def sector(self, sector_id: str) -> Sector:
        for s in self.sectors:
            if s.id == sector_id:
                return s
        raise KeyError(f"no sector '{sector_id}' in scenario '{self.scenario_id}'")


def load_scenario(path: str) -> Scenario:
    with open(path) as f:
        data = json.load(f)
    base = data["base_station"]
    return Scenario(
        scenario_id=data["scenario_id"],
        random_seed=data["random_seed"],
        base_station=(base["x"], base["y"], base["z"]),
        deadline_s=data["deadline_s"],
        comms_range_m=data["comms_range_m"],
        min_separation_m=data["min_separation_m"],
        required_coverage=data["required_coverage"],
        drones=[DroneSpec(name=d["name"], battery_s=d["battery_s"], sector=d["sector"],
                          spawn_offset=tuple(d["spawn_offset"])) for d in data["drones"]],
        sectors=[Sector(**s) for s in data["sectors"]],
        targets=[Target(**t) for t in data["targets"]],
        no_fly_zones=[NoFlyZone(**z) for z in data["no_fly_zones"]],
    )
