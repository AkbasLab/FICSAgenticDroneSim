"""The scenario family for the main experiment (Phase 18.1, 18.2).

One fixed scenario cannot support a factorial experiment: every seed would fly
the same targets in the same places, so "20 seeds" would be 20 replays of one
mission that differ only in packet luck. This module generates a mission per
seed from the canonical layout, and it does so with **common random numbers**:
the seed alone decides

  * where the two targets are,
  * where the restricted region is,
  * each vehicle's initial battery,
  * which vehicle fails, and when (used only in the failure condition),

so for seed 42 every architecture, and every network condition, flies exactly
the same mission. The draws are made in a fixed order and for the largest team
(8) every time, so a 2-drone and a 4-drone run on the same seed also share
targets, region and the batteries of the drones they have in common.

**Splits (18.2).** Seeds belong to exactly one split:

  development   any seed not listed below - implementation, prompt adjustment
  validation    the seeds the pilots and the calibration used (configs/...)
  test          the held-out seeds in configs/frozen/heldout_seeds.yaml

`generate()` refuses a seed that is not in the split it is asked for, so a
held-out scenario cannot be produced by a development run, and a development
seed cannot be passed off as a test result.

Layout that does not change with the seed: base at the origin, the four
quadrant sectors of `search_relay_001` (split into eight half-sectors for an
8-drone team, so the total area to search is the same), pads 4 m apart along
the x axis, and the mission specification.
"""

import random
from typing import Dict, List

from ..core.geometry import Rect
from ..core.mission_models import (BaseStation, MissionScenario, MissionSpec,
                                   NetworkSpec, RestrictedZone, Sector, Target,
                                   VehicleSpec)
from ..core.models import Position3D

SPLITS = ("development", "validation", "test")
MAX_TEAM = 8
SECTOR_ALTITUDE = -8.0

QUADRANTS = {"S1": (10, 10, 50, 50), "S2": (-50, 10, -10, 50),
             "S3": (-50, -50, -10, -10), "S4": (10, -50, 50, -10)}

#: Every random quantity, and its range. Recorded so the family is documented
#: by the same object that generates it.
PARAMETERS = {
    "targets": 2,
    "target_margin_m": 4.0,
    "zone_size_m": 12.0,
    "zone_distance_m": 60.0,            # centre of the zone from the base
    "zone_offset_m": 20.0,              # +/- along its band
    "battery_s": (810.0, 990.0),        # 900 s +/- 10%
    "fault_window_s": (10.0, 90.0),     # one vehicle fails in this window
}


def sectors_for(team_size) -> List[Sector]:
    if team_size <= 4:
        return [Sector(sid, Rect(*fp), SECTOR_ALTITUDE) for sid, fp in QUADRANTS.items()]
    out = []
    for i, (sid, (x0, y0, x1, y1)) in enumerate(QUADRANTS.items()):
        ym = (y0 + y1) / 2
        out.append(Sector(f"S{2 * i + 1}", Rect(x0, ym, x1, y1), SECTOR_ALTITUDE))
        out.append(Sector(f"S{2 * i + 2}", Rect(x0, y0, x1, ym), SECTOR_ALTITUDE))
    return out


def split_of(seed) -> str:
    from ..experiments.freeze import heldout_seeds, validation_seeds
    seed = int(seed)
    if seed in set(heldout_seeds()):
        return "test"
    if seed in set(validation_seeds()):
        return "validation"
    return "development"


def seeds_for(split, count, start=1, skip=0):
    """The first `count` seeds of a split, in a fixed order. Test seeds come
    from the held-out list in its stored order; development seeds are the
    smallest positive integers that belong to no other split."""
    from ..experiments.freeze import heldout_seeds, validation_seeds
    if split == "test":
        held = heldout_seeds()
        if len(held) < skip + count:
            raise ValueError(f"only {len(held)} held-out seeds exist, "
                             f"{skip} + {count} requested")
        return held[skip:skip + count]
    if split == "validation":
        return validation_seeds()[:count]
    taken = set(heldout_seeds()) | set(validation_seeds())
    out, s = [], start
    while len(out) < count:
        if s not in taken:
            out.append(s)
        s += 1
    return out


def check_split(split, seed):
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, not {split!r}")
    actual = split_of(seed)
    if actual != split:
        raise ValueError(f"seed {seed} belongs to the {actual} split, not {split}: "
                         + {"test": "held-out seeds are for final results only",
                            "validation": "it was used by a pilot or the calibration",
                            "development": "it is not a held-out seed"}[actual])


def draws(seed) -> Dict[str, object]:
    """Every random quantity for one seed, independent of team size."""
    rng = random.Random(f"FICSAgenticDroneSim/scenario/{int(seed)}")
    p = PARAMETERS
    quads = list(QUADRANTS)
    target_quads = rng.sample(quads, p["targets"])
    targets = []
    for q in target_quads:
        x0, y0, x1, y1 = QUADRANTS[q]
        m = p["target_margin_m"]
        targets.append((rng.uniform(x0 + m, x1 - m), rng.uniform(y0 + m, y1 - m)))
    band = rng.choice(["north", "south", "east", "west"])
    offset = rng.uniform(-p["zone_offset_m"], p["zone_offset_m"])
    batteries = [rng.uniform(*p["battery_s"]) for _ in range(MAX_TEAM)]
    fault_u = rng.random()
    fault_t = rng.uniform(*p["fault_window_s"])
    return {"targets": targets, "zone_band": band, "zone_offset": offset,
            "batteries": batteries, "fault_u": fault_u, "fault_t": fault_t}


def _zone(band, offset):
    d, h = PARAMETERS["zone_distance_m"], PARAMETERS["zone_size_m"] / 2
    cx, cy = {"north": (offset, d), "south": (offset, -d),
              "east": (d, offset), "west": (-d, offset)}[band]
    pts = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    return RestrictedZone("R1", [(round(x, 2), round(y, 2)) for x, y in pts])


def generate(split, seed, team_size=4) -> MissionScenario:
    """The mission for one seed and team size, refusing seeds outside `split`."""
    check_split(split, seed)
    if not 1 <= int(team_size) <= MAX_TEAM:
        raise ValueError(f"team_size must be 1..{MAX_TEAM}")
    n = int(team_size)
    d = draws(seed)
    vehicles = [VehicleSpec(f"Drone{i + 1}", Position3D(4.0 * i, 0.0, 0.0),
                            round(d["batteries"][i], 1)) for i in range(n)]
    fault_vehicle = vehicles[min(int(d["fault_u"] * n), n - 1)].vehicle_id
    return MissionScenario(
        scenario_id=f"{split}_{int(seed)}_n{n}",
        random_seed=int(seed),
        mission=MissionSpec(mission_type="distributed_search", deadline_s=900.0,
                            required_coverage=0.95, targets_to_find=2,
                            min_separation_m=3.0),
        base=BaseStation(Position3D(0.0, 0.0, 0.0), comm_range_m=120.0),
        sectors=sectors_for(n),
        targets=[Target(f"T{i + 1}", Position3D(round(x, 2), round(y, 2), SECTOR_ALTITUDE),
                        detection_radius_m=8.0, observation_period_s=1.0)
                 for i, (x, y) in enumerate(d["targets"])],
        restricted_zones=[_zone(d["zone_band"], d["zone_offset"])],
        vehicles=vehicles,
        network=NetworkSpec(profile="configured per experiment"),
        faults=[{"vehicle": fault_vehicle, "at_s": round(d["fault_t"], 2),
                 "kind": "vehicle_stopped"}])


def fault_of(scenario) -> Dict[str, float]:
    """{vehicle: time} for the scenario's one failure."""
    return {f["vehicle"]: float(f["at_s"]) for f in (scenario.faults or [])}


def describe(scenario) -> Dict[str, object]:
    """What a seed decided, for the manifest."""
    return {"scenario_id": scenario.scenario_id,
            "targets": {t.target_id: [t.position.x, t.position.y] for t in scenario.targets},
            "restricted_zone": scenario.restricted_zones[0].polygon,
            "batteries": {v.vehicle_id: v.battery_s for v in scenario.vehicles},
            "fault": fault_of(scenario),
            "sectors": [s.sector_id for s in scenario.sectors]}
