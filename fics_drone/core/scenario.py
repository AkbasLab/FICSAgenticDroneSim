"""The Phase 4 world, as data. Nothing in here is a rule about how to score a
run - it's just the numbers describing one fixed mission (base, sectors,
targets, no-fly zones, per-drone battery). See fics_drone/evaluation/ for the
rules that judge a run against this."""

import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .obstacles import TreeObstacle  # noqa: E402

# Half the drone's width, metres. The simulator's drone body measures 0.49 m either side of its centre; a zone, a keep-out
# or a scoring check that tests only the centre point lets almost half the aircraft cross the edge before it counts.
DRONE_RADIUS_M = 0.5


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
    """A box the drones must not enter. By default it is static and always
    active. GMB (dynamic boundaries) adds an optional schedule, all in mission
    seconds: active from `active_from_s` until `active_until_s` (None = never
    expires), and drifting at (vx, vy) m/s from the moment it activates. Every
    field has a default, so existing scenario files load unchanged.

    `contains(x, y)` with no time ignores the schedule and tests the base box,
    which is the conservative reading (treat the zone as always there). Pass t
    to get the scheduled answer."""
    id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    active_from_s: float = 0.0
    active_until_s: Optional[float] = None
    vx: float = 0.0
    vy: float = 0.0

    @property
    def is_dynamic(self) -> bool:
        return (self.active_from_s > 0.0 or self.active_until_s is not None
                or self.vx != 0.0 or self.vy != 0.0)

    def active_at(self, t: float) -> bool:
        return t >= self.active_from_s and (self.active_until_s is None or t < self.active_until_s)

    def bounds_at(self, t: float) -> Tuple[float, float, float, float]:
        """(x_min, x_max, y_min, y_max) at time t. The drift starts when the zone activates."""
        dt = max(0.0, t - self.active_from_s)
        dx, dy = self.vx * dt, self.vy * dt
        return self.x_min + dx, self.x_max + dx, self.y_min + dy, self.y_max + dy

    def contains(self, x: float, y: float, t: Optional[float] = None, radius: float = 0.0) -> bool:
        """True if a point (radius 0) or a body of this half-width centred on (x, y) touches the zone: the box is grown by
        `radius` on every side, so an aircraft counts as inside as soon as its edge crosses."""
        if t is None:
            return self.x_min - radius <= x <= self.x_max + radius and self.y_min - radius <= y <= self.y_max + radius
        if not self.active_at(t):
            return False
        x0, x1, y0, y1 = self.bounds_at(t)
        return x0 - radius <= x <= x1 + radius and y0 - radius <= y <= y1 + radius


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
    # objects the aircraft must not fly through that the simulator does not stop it from flying through (trees);
    # empty unless a live script fills it in (see core/obstacles.py)
    obstacles: list = field(default_factory=list)
    # "surveillance": the whole sector must be swept, so coverage gates the pass. "search": the mission is to find the targets and
    # come home, a drone stops when its target is found, and coverage is reported but does not gate the pass.
    mission_kind: str = "surveillance"
    # sector id -> [[x, y], ...] in world metres: a path a drone flies instead of a lawnmower sweep (streets, where a straight
    # lane would run through buildings). Empty = every sector is swept in lanes.
    search_routes: dict = field(default_factory=dict)
    # height above ground the agents cruise at when the caller does not say; None = the navigation default
    cruise_height: Optional[float] = None
    # half-width of the drone body, for every zone test (see DRONE_RADIUS_M)
    drone_radius_m: float = DRONE_RADIUS_M

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
        obstacles=[TreeObstacle(**t) for t in data.get("obstacles", [])],
        mission_kind=data.get("mission_kind", "surveillance"),
        search_routes=data.get("search_routes", {}),
        cruise_height=data.get("cruise_height"),
        drone_radius_m=data.get("drone_radius_m", DRONE_RADIUS_M),
    )
