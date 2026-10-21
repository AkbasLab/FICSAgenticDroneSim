"""Load scenarios from TOML, strictly (AUV-05, 4.4).

    from agentic_uav.experiments.scenarios import load_scenario
    scenario = load_scenario("search_relay_001")        # configs/scenarios/<id>.toml
    scenario = load_scenario("path/to/file.toml")

STRICT, because a scenario is an experimental condition. A misspelt key that
fell back to a default would run a different experiment than the file says
and look like the right one -- the same reason the mission runner refuses an
unknown mission id. So: an unknown key is an error, a missing one is an
error, a value of the wrong type is an error, and every problem in a file is
reported at once, with its place, before anything is built.

TOML, not AUV-05's YAML: the project's config format already, read by what
is installed (decided 2026-10-21). The structure is AUV-05's. A vehicle's
`start` may be written [x, y] or, as AUV-05 writes it, [x, y, 0]: a start is
on the ground, so a third value other than 0 is refused.
"""

from __future__ import annotations

import os
from typing import Any

from ..core.geometry import Polygon, Region
from ..core.scenario import (
    BaseStation,
    BatterySpec,
    DetectionSpec,
    MissionSpec,
    NetworkSpec,
    RestrictedZone,
    SafetySpec,
    Scenario,
    ScenarioError,
    Sector,
    TargetSpec,
    VehicleSpec,
)
from .provenance import REPO_ROOT
from .runner import load_toml

SCENARIO_DIR = os.path.join(REPO_ROOT, "configs", "scenarios")

_NUMBER = (int, float)
TOP_LEVEL = {"scenario_id": str, "random_seed": int, "description": str, "faults": list,
             "mission": dict, "base": dict, "network": dict, "detection": dict, "battery": dict,
             "safety": dict, "targets": dict, "vehicles": list, "sectors": list,
             "restricted_zones": list}
OPTIONAL_TOP = {"description", "faults", "restricted_zones"}
SECTIONS = {
    "mission": {"type": str, "deadline_s": _NUMBER, "required_coverage": _NUMBER, "targets_to_find": int},
    "base": {"position": list},
    "network": {"profile": str, "communication_range_m": _NUMBER},
    "detection": {"radius_m": _NUMBER, "min_observation_s": _NUMBER, "line_of_sight": bool},
    "battery": {"capacity": _NUMBER, "hover_drain_per_s": _NUMBER, "move_drain_per_m": _NUMBER, "reserve": _NUMBER},
    "safety": {"min_separation_m": _NUMBER},
    "targets": {"count": int, "placement": str, "fixed": list, "min_spacing_m": _NUMBER},
}
OPTIONAL_KEYS = {"detection": {"line_of_sight"}, "targets": {"fixed", "min_spacing_m"}}
ENTRIES = {
    "vehicles": {"id": str, "start": list},
    "sectors": {"id": str, "bounds": list},
    "restricted_zones": {"id": str, "polygon": list},
}


def scenario_path(scenario: str) -> str:
    """A path for an id (configs/scenarios/<id>.toml), or the path itself."""
    if scenario.endswith(".toml") or os.sep in scenario or "/" in scenario:
        return scenario
    return os.path.join(SCENARIO_DIR, scenario + ".toml")


def load_scenario(scenario: str) -> Scenario:
    path = scenario_path(scenario)
    if not os.path.isfile(path):
        raise ScenarioError([f"no scenario file at {path}"], scenario)
    try:
        data = load_toml(path)
    except Exception as exc:                 # a TOML syntax error, with its line
        raise ScenarioError([f"not valid TOML: {exc}"], path) from None
    return parse(data, source=path)


def _type_ok(value: Any, kind: Any) -> bool:
    if kind is _NUMBER:
        return isinstance(value, _NUMBER) and not isinstance(value, bool)
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, kind)


def _keys(problems: list[str], where: str, data: dict, schema: dict, optional: set[str]) -> None:
    for key in data:
        if key not in schema:
            problems.append(f"{where}: unknown key {key!r} (known: {', '.join(sorted(schema))})")
    for key, kind in schema.items():
        if key not in data:
            if key not in optional:
                problems.append(f"{where}: missing {key!r}")
        elif not _type_ok(data[key], kind):
            name = "number" if kind is _NUMBER else kind.__name__
            problems.append(f"{where}.{key}: expected {name}, got {type(data[key]).__name__} {data[key]!r}")


def _point(problems: list[str], where: str, value: Any, allow_ground_z: bool = False) -> tuple[float, float] | None:
    ok_len = len(value) == 2 or (allow_ground_z and len(value) == 3) if isinstance(value, list) else False
    if not ok_len or not all(_type_ok(v, _NUMBER) for v in value):
        problems.append(f"{where}: expected [x, y]{' or [x, y, 0]' if allow_ground_z else ''}, got {value!r}")
        return None
    if len(value) == 3 and value[2] != 0:
        problems.append(f"{where}: a start is on the ground; the third value must be 0, got {value[2]}")
        return None
    return float(value[0]), float(value[1])


def parse(data: dict, source: str = "") -> Scenario:
    """Build a Scenario from parsed TOML, or raise ScenarioError with every problem."""
    problems: list[str] = []
    _keys(problems, "scenario", data, TOP_LEVEL, OPTIONAL_TOP)
    for name, schema in SECTIONS.items():
        section = data.get(name)
        if isinstance(section, dict):
            _keys(problems, name, section, schema, OPTIONAL_KEYS.get(name, set()))
    for name, schema in ENTRIES.items():
        entries = data.get(name, [])
        if isinstance(entries, list):
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    problems.append(f"{name}[{i}]: expected a table, got {entry!r}")
                else:
                    _keys(problems, f"{name}[{i}]", entry, schema, set())
    if problems:
        raise ScenarioError(problems, source)

    m, n, d, b, s, t = (data[k] for k in ("mission", "network", "detection", "battery", "safety", "targets"))
    base = _point(problems, "base.position", data["base"]["position"])
    vehicles = []
    for i, v in enumerate(data["vehicles"]):
        start = _point(problems, f"vehicles[{i}].start", v["start"], allow_ground_z=True)
        if start:
            vehicles.append(VehicleSpec(v["id"], *start))
    sectors = []
    for i, sec in enumerate(data["sectors"]):
        bounds = sec["bounds"]
        if len(bounds) != 4 or not all(_type_ok(x, _NUMBER) for x in bounds):
            problems.append(f"sectors[{i}].bounds: expected [x_min, y_min, x_max, y_max], got {bounds!r}")
            continue
        try:
            sectors.append(Sector(sec["id"], Region(*map(float, bounds))))
        except ValueError as exc:
            problems.append(f"sectors[{i}] ({sec['id']}): {exc}")
    zones = []
    for i, z in enumerate(data.get("restricted_zones", [])):
        points = [_point(problems, f"restricted_zones[{i}].polygon[{j}]", p) for j, p in enumerate(z["polygon"])]
        if None in points:
            continue
        try:
            zones.append(RestrictedZone(z["id"], Polygon(tuple(points))))
        except ValueError as exc:
            problems.append(f"restricted_zones[{i}] ({z['id']}): {exc}")
    fixed = tuple(p for p in (_point(problems, f"targets.fixed[{j}]", p)
                              for j, p in enumerate(t.get("fixed", []))) if p)
    if problems:
        raise ScenarioError(problems, source)

    return Scenario(
        scenario_id=data["scenario_id"],
        random_seed=data["random_seed"],
        description=data.get("description", ""),
        mission=MissionSpec(m["type"], float(m["deadline_s"]), float(m["required_coverage"]), m["targets_to_find"]),
        base=BaseStation(*base),
        network=NetworkSpec(n["profile"], float(n["communication_range_m"])),
        detection=DetectionSpec(float(d["radius_m"]), float(d["min_observation_s"]), d.get("line_of_sight", False)),
        battery=BatterySpec(float(b["capacity"]), float(b["hover_drain_per_s"]),
                            float(b["move_drain_per_m"]), float(b["reserve"])),
        safety=SafetySpec(float(s["min_separation_m"])),
        vehicles=tuple(vehicles),
        sectors=tuple(sectors),
        targets=TargetSpec(t["count"], t["placement"], fixed, float(t.get("min_spacing_m", 0.0))),
        restricted_zones=tuple(zones),
        faults=tuple(data.get("faults", [])),
    )
