"""The canonical mission as data: a scenario, and the brief a controller gets.

AUV-05 (4.4): "scenarios live in configuration, not code." Every factor the
study will later vary -- network profile, faults, team size, seed -- is a
field here from the start, so the factorial in AUV-16 becomes a loop over
files rather than a branch in code. `experiments/scenarios.py` loads these
from TOML; nothing here does I/O.

TWO VIEWS OF ONE SCENARIO, deliberately:

* `Scenario` is the ground truth: where the targets are, and the seed that
  places them. Only the simulated world and the evaluator see it.
* `MissionBrief` is what a controller is handed: the base, the sectors, the
  restricted zones, the deadline, how many targets to find -- and NOT where
  they are, nor the seed, which with the placement rule would reveal them.

That split is AUV-06's 6.2 ("ground truth to the simulator and evaluator
only") enforced by what each side can reach, not by convention.

Coordinates are map metres, x and y, the same frame the drones fly in. A
vehicle's start is on the ground. Heights are not scenario data; how high to
fly is the controller's choice.

Every value is checked when built, and `Scenario` checks the whole: ids
unique, sectors not overlapping, nothing starting or placed inside a
restricted zone. All the problems are reported at once (`ScenarioError`), so
a bad file is fixed in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .geometry import Polygon, Region

TARGET_PLACEMENTS = ("random_in_sectors", "fixed")
NETWORK_PROFILES = ("perfect",)            # the others arrive with Phase 10


class ScenarioError(ValueError):
    """A scenario that cannot be flown. Carries every problem found."""

    def __init__(self, problems: list[str], source: str = "") -> None:
        self.problems = list(problems)
        where = f" in {source}" if source else ""
        super().__init__(f"{len(self.problems)} problem(s){where}:\n  - " + "\n  - ".join(self.problems))


def _check(problems: list[str], ok: bool, message: str) -> None:
    if not ok:
        problems.append(message)


@dataclass(frozen=True)
class MissionSpec:
    type: str
    deadline_s: float
    required_coverage: float
    targets_to_find: int

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, self.type == "distributed_search", f"mission.type {self.type!r}: only 'distributed_search' exists")
        _check(p, self.deadline_s > 0, f"mission.deadline_s must be positive, got {self.deadline_s}")
        _check(p, 0 < self.required_coverage <= 1, f"mission.required_coverage must be in (0, 1], got {self.required_coverage}")
        _check(p, self.targets_to_find >= 0, f"mission.targets_to_find cannot be negative, got {self.targets_to_find}")
        return p


@dataclass(frozen=True)
class BaseStation:
    x: float
    y: float


@dataclass(frozen=True)
class NetworkSpec:
    profile: str
    communication_range_m: float

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, self.profile in NETWORK_PROFILES, f"network.profile {self.profile!r}: Phase 4 has only {NETWORK_PROFILES}")
        _check(p, self.communication_range_m > 0, f"network.communication_range_m must be positive, got {self.communication_range_m}")
        return p


@dataclass(frozen=True)
class DetectionSpec:
    radius_m: float
    min_observation_s: float
    line_of_sight: bool = False

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, self.radius_m > 0, f"detection.radius_m must be positive, got {self.radius_m}")
        _check(p, self.min_observation_s >= 0, f"detection.min_observation_s cannot be negative, got {self.min_observation_s}")
        _check(p, not self.line_of_sight, "detection.line_of_sight: not modelled in Phase 4 (AUV-05: 'if easy')")
        return p


@dataclass(frozen=True)
class BatterySpec:
    """A simulated battery, in percent. Simple and uncalibrated, by design."""

    capacity: float
    hover_drain_per_s: float
    move_drain_per_m: float
    reserve: float

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, self.capacity > 0, f"battery.capacity must be positive, got {self.capacity}")
        _check(p, self.hover_drain_per_s >= 0, f"battery.hover_drain_per_s cannot be negative, got {self.hover_drain_per_s}")
        _check(p, self.move_drain_per_m >= 0, f"battery.move_drain_per_m cannot be negative, got {self.move_drain_per_m}")
        _check(p, 0 <= self.reserve < self.capacity, f"battery.reserve must be in [0, capacity), got {self.reserve}")
        return p


@dataclass(frozen=True)
class SafetySpec:
    min_separation_m: float

    def problems(self) -> list[str]:
        return [] if self.min_separation_m > 0 else [
            f"safety.min_separation_m must be positive, got {self.min_separation_m}"]


@dataclass(frozen=True)
class VehicleSpec:
    id: str
    start_x: float
    start_y: float


@dataclass(frozen=True)
class Sector:
    id: str
    region: Region


@dataclass(frozen=True)
class TargetSpec:
    """How the targets are placed. `fixed` lists positions; random uses the seed."""

    count: int
    placement: str
    fixed: tuple[tuple[float, float], ...] = ()
    min_spacing_m: float = 0.0

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, self.count >= 0, f"targets.count cannot be negative, got {self.count}")
        _check(p, self.placement in TARGET_PLACEMENTS, f"targets.placement {self.placement!r}: one of {TARGET_PLACEMENTS}")
        _check(p, self.min_spacing_m >= 0, f"targets.min_spacing_m cannot be negative, got {self.min_spacing_m}")
        if self.placement == "fixed":
            _check(p, len(self.fixed) == self.count,
                   f"targets.fixed has {len(self.fixed)} positions for count = {self.count}")
        else:
            _check(p, not self.fixed, "targets.fixed is only for placement = 'fixed'")
        return p


@dataclass(frozen=True)
class RestrictedZone:
    id: str
    polygon: Polygon


@dataclass(frozen=True)
class MissionBrief:
    """What a controller may know. No target positions, no seed."""

    scenario_id: str
    mission: MissionSpec
    base: BaseStation
    network: NetworkSpec
    detection: DetectionSpec
    battery: BatterySpec
    safety: SafetySpec
    vehicles: tuple[VehicleSpec, ...]
    sectors: tuple[Sector, ...]
    restricted_zones: tuple[RestrictedZone, ...]


@dataclass(frozen=True)
class Scenario:
    """The whole scenario, ground truth included. See the module docstring."""

    scenario_id: str
    random_seed: int
    description: str
    mission: MissionSpec
    base: BaseStation
    network: NetworkSpec
    detection: DetectionSpec
    battery: BatterySpec
    safety: SafetySpec
    vehicles: tuple[VehicleSpec, ...]
    sectors: tuple[Sector, ...]
    targets: TargetSpec
    restricted_zones: tuple[RestrictedZone, ...] = ()
    faults: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        problems = self.problems()
        if problems:
            raise ScenarioError(problems, self.scenario_id)

    def problems(self) -> list[str]:
        p: list[str] = []
        _check(p, bool(self.scenario_id.strip()), "scenario_id is empty")
        for part in (self.mission, self.network, self.detection, self.battery, self.safety, self.targets):
            p += part.problems()

        _check(p, len(self.vehicles) >= 1, "at least one vehicle is needed")
        ids = [v.id for v in self.vehicles]
        _check(p, len(set(ids)) == len(ids), f"vehicle ids repeat: {ids}")
        for i, a in enumerate(self.vehicles):
            for b in self.vehicles[i + 1:]:
                d = ((a.start_x - b.start_x) ** 2 + (a.start_y - b.start_y) ** 2) ** 0.5
                _check(p, d >= self.safety.min_separation_m,
                       f"{a.id} and {b.id} start {d:.2f} m apart, under min_separation_m")

        _check(p, len(self.sectors) >= 1, "at least one sector is needed")
        sids = [s.id for s in self.sectors]
        _check(p, len(set(sids)) == len(sids), f"sector ids repeat: {sids}")
        for i, a in enumerate(self.sectors):
            _check(p, a.region.area > 0, f"sector {a.id} has no area")
            for b in self.sectors[i + 1:]:
                _check(p, not a.region.overlaps(b.region), f"sectors {a.id} and {b.id} overlap")

        zids = [z.id for z in self.restricted_zones]
        _check(p, len(set(zids)) == len(zids), f"restricted zone ids repeat: {zids}")
        for z in self.restricted_zones:
            _check(p, not z.polygon.contains(self.base.x, self.base.y), f"the base is inside restricted zone {z.id}")
            for v in self.vehicles:
                _check(p, not z.polygon.contains(v.start_x, v.start_y), f"{v.id} starts inside restricted zone {z.id}")

        if self.targets.placement == "fixed":
            for i, (x, y) in enumerate(self.targets.fixed):
                _check(p, any(s.region.contains(x, y) for s in self.sectors),
                       f"fixed target {i} at ({x}, {y}) is in no sector")
                _check(p, not any(z.polygon.contains(x, y) for z in self.restricted_zones),
                       f"fixed target {i} at ({x}, {y}) is inside a restricted zone")
        _check(p, self.mission.targets_to_find <= self.targets.count,
               f"mission.targets_to_find = {self.mission.targets_to_find} but only {self.targets.count} targets exist")
        for i, fault in enumerate(self.faults):
            _check(p, isinstance(fault, dict) and "kind" in fault, f"fault {i} has no 'kind'")
        return p

    def brief(self) -> MissionBrief:
        """The controller's view. Targets and the seed are left out on purpose."""
        return MissionBrief(self.scenario_id, self.mission, self.base, self.network,
                            self.detection, self.battery, self.safety, self.vehicles,
                            self.sectors, self.restricted_zones)

    def vehicle(self, vehicle_id: str) -> VehicleSpec:
        for v in self.vehicles:
            if v.id == vehicle_id:
                return v
        raise KeyError(vehicle_id)
