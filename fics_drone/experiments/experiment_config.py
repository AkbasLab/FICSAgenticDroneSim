"""One experiment = one ExperimentConfig, so every run is recorded and repeatable.

The dynamic-zone conditions that used to live inside scripts/run_dynamic_zone_study.py
are named ZONE_PROFILES here; the runner (experiment_runner.py) turns a config into a
results folder.
"""
import copy
import itertools
import json
import os
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Optional

from ..coordination.comms_conditions import BY_NAME
from ..core.scenario import NoFlyZone, Scenario, load_scenario

DEFAULT_SCENARIO = os.path.join(os.path.dirname(__file__), "..", "..", "configs",
                                "missions", "search_relay_001.json")

#: Zones sit over Sector A (x 24-40, y 24-40), which Drone2 searches.
#: bounds = (x_min, x_max, y_min, y_max). `static` adds nothing: the base scenario
#: already holds one static zone far from every sector (the control).
def zone_specs(profile: str, appear_s: float = 5.0, expire_s: float = 12.0,
                drift_s: float = 3.0) -> List[dict]:
    """The zones a profile adds. Zone times are mission seconds; LLM runs are slow, so
    they set them much later than the mock study's defaults."""
    specs = {
        "static": [],
        "appear": [dict(name="DZ_appear", bounds=(24.0, 40.0, 24.0, 40.0),
                        active_from_s=appear_s)],
        "appear_expire": [dict(name="DZ_appear", bounds=(24.0, 40.0, 24.0, 40.0),
                               active_from_s=appear_s, active_until_s=expire_s)],
        "drift": [dict(name="DZ_drift", bounds=(38.0, 46.0, 28.0, 36.0),
                       active_from_s=drift_s, vx=-2.5)],
        # the medium scenario (configs/missions/medium_001.json): a block that appears over T3's area and expires, a box
        # that drifts west across sector A, and one that appears over T2's area and stays
        "medium_none": [],
        "medium_dynamic": [dict(name="DZ_appear", bounds=(5.0, 30.0, 55.0, 80.0), active_from_s=appear_s * 1.3,
                              active_until_s=expire_s * 1.6),
                         dict(name="DZ_drift", bounds=(38.0, 46.0, 28.0, 36.0), active_from_s=drift_s * 2, vx=-2.5),
                         dict(name="DZ_stay", bounds=(-45.0, -25.0, -45.0, -25.0), active_from_s=appear_s * 2.5)],
        # the large scenario (configs/missions/large_001.json, street level): one block that appears over T3's road and
        # expires, one that drifts west along a road in sector D, one that appears over T2's road and stays
        "large_none": [],
        "large_dynamic": [dict(name="DZ_appear", bounds=(79.0, 103.0, -171.0, -147.0), active_from_s=appear_s * 1.3,
                               active_until_s=expire_s * 1.6),
                          dict(name="DZ_drift", bounds=(150.0, 158.0, -174.0, -166.0), active_from_s=drift_s * 2, vx=-2.5),
                          dict(name="DZ_stay", bounds=(131.0, 151.0, -259.0, -239.0), active_from_s=appear_s * 2.5)],
    }
    for scenario_name in ("xlarge", "full_map"):
        if profile == f"{scenario_name}_none":
            return []
        if profile == f"{scenario_name}_dynamic":
            return _planned_zones(scenario_name, appear_s, expire_s, drift_s)
    return specs[profile]


def _planned_zones(scenario_name: str, appear_s: float, expire_s: float, drift_s: float) -> List[dict]:
    """The dynamic profile of a generated street scenario: its file holds a `zone_plan` over its own routes (a block that appears
    over T3 and expires, a box that drifts west clear of every spawn, one that appears over T2 and stays)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "missions", f"{scenario_name}_001.json")
    with open(path) as f:
        plan = json.load(f)["zone_plan"]
    zones = [dict(name="DZ_appear", bounds=tuple(plan["appear"]), active_from_s=appear_s * 1.3, active_until_s=expire_s * 1.6)]
    if plan.get("drift"):
        zones.append(dict(name="DZ_drift", bounds=tuple(plan["drift"]), active_from_s=drift_s * 2, vx=-2.5))
    zones.append(dict(name="DZ_stay", bounds=tuple(plan["stay"]), active_from_s=appear_s * 2.5))
    return zones


ZONE_PROFILES: Dict[str, List[dict]] = {
    n: zone_specs(n) for n in ("static", "appear", "appear_expire", "drift", "medium_none", "medium_dynamic", "large_none", "large_dynamic",
              "xlarge_none", "xlarge_dynamic", "full_map_none", "full_map_dynamic")}

#: cmd = guardian acts at command boundaries only; tick = per-control-tick zone monitor.
ZONE_MONITORS = ("cmd", "tick")

#: who decides each drone's actions: the deterministic policy, a scripted stand-in
#: backend (plumbing check, no model), or a local Ollama model
POLICIES = ("deterministic", "scripted", "ollama")


@dataclass
class ExperimentConfig:
    experiment_id: str
    zone_profile: str = "appear"
    zone_monitor: str = "cmd"
    scenario: str = DEFAULT_SCENARIO
    repeats: int = 3
    mock_speed_mps: float = 15.0
    #: whether the sim's P-key noclip was on; None for the mock, which has no ground
    noclip: Optional[bool] = None
    seed: int = 0
    #: switch this drone off kill_at_s seconds in (None = no fault). Uses the
    #: allocate-then-fly engine, which has no per-tick zone monitor.
    kill_vehicle: Optional[str] = None
    kill_at_s: float = 15.0
    #: comms condition (comms_conditions.BY_NAME key) applied to the message bus;
    #: `seed` seeds its loss/delay draws. None = ideal link, no comms metrics.
    network_profile: Optional[str] = None
    #: give each drone a CommsEstimator of its peers' link loss (threaded engine only)
    comms_estimates: bool = False
    appear_s: float = 5.0
    expire_s: float = 12.0
    drift_s: float = 3.0
    #: multiplies a drifting zone's speed (see apply_zones)
    zone_speed_scale: float = 1.0
    #: how an approved leg is flown: "straight" (one move command) or "navrl" (NavRL's policy, one velocity per
    #: tick; needs torch and a NavRL checkout, see planners/navrl_planner.py). Threaded engine, deterministic policy.
    leg_planner: str = "straight"
    #: per-leg give-up time in seconds (the skill default of 30 s is too short for a slow flier)
    leg_timeout_s: float = 30.0
    #: LLM arm: which backend decides, and (ollama only) which model. The model card,
    #: which pins the exact weights, is recorded in manifest.json.
    policy: str = "deterministic"
    model: str = "llama3.1:8b"
    llm_timeout_s: float = 30.0
    notes: str = ""

    def validate(self) -> "ExperimentConfig":
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if self.zone_profile not in ZONE_PROFILES:
            raise ValueError(f"unknown zone_profile {self.zone_profile!r}; "
                             f"choose from {sorted(ZONE_PROFILES)}")
        if self.zone_monitor not in ZONE_MONITORS:
            raise ValueError(f"unknown zone_monitor {self.zone_monitor!r}; "
                             f"choose from {ZONE_MONITORS}")
        if self.repeats < 1:
            raise ValueError("repeats must be >= 1")
        if self.leg_planner not in ("straight", "navrl"):
            raise ValueError(f"unknown leg_planner {self.leg_planner!r}; choose straight or navrl")
        if self.leg_planner != "straight" and (self.kill_vehicle or self.policy != "deterministic"):
            raise ValueError("leg_planner other than straight needs the deterministic policy and no kill_vehicle")
        if self.kill_at_s < 0:
            raise ValueError("kill_at_s must be >= 0")
        if self.network_profile is not None and self.network_profile not in BY_NAME:
            raise ValueError(f"unknown network_profile {self.network_profile!r}; "
                             f"choose from {sorted(BY_NAME)}")
        if self.comms_estimates and self.kill_vehicle:
            raise ValueError("comms_estimates is not supported with kill_vehicle")
        if self.comms_estimates and self.policy != "deterministic":
            raise ValueError("comms_estimates is not supported with an LLM policy")
        if self.policy not in POLICIES:
            raise ValueError(f"unknown policy {self.policy!r}; choose from {POLICIES}")
        if self.policy != "deterministic" and (self.kill_vehicle or self.zone_monitor == "tick"):
            raise ValueError("an LLM policy runs on the plain fault engine only: "
                             "no kill_vehicle and no zone_monitor 'tick'")
        if self.kill_vehicle and self.zone_monitor == "tick":
            raise ValueError("zone_monitor 'tick' is not supported with kill_vehicle")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentConfig":
        known = {f.name for f in fields(cls)}
        extra = set(data) - known
        if extra:
            raise ValueError(f"unknown config keys: {sorted(extra)}")
        return cls(**data).validate()


def load_config(path: str) -> ExperimentConfig:
    with open(path) as f:
        if path.endswith((".yaml", ".yml")):
            import yaml
            data = yaml.safe_load(f)
        else:
            data = json.load(f)
    return ExperimentConfig.from_dict(data)


def apply_zones(base: Scenario, profile: str, appear_s: float = 5.0,
                expire_s: float = 12.0, drift_s: float = 3.0, zone_speed_scale: float = 1.0) -> Scenario:
    """A copy of `base` with the profile's zones added. `zone_speed_scale` multiplies a drifting zone's speed (a
    slow flier's run is stretched in time, so its zones drift slower by the same factor)."""
    scenario = copy.deepcopy(base)
    zones = []
    for z in zone_specs(profile, appear_s, expire_s, drift_s):
        extra = {k: v for k, v in z.items() if k not in ("name", "bounds")}
        for key in ("vx", "vy"):
            if key in extra:
                extra[key] = extra[key] * zone_speed_scale
        zones.append(NoFlyZone(z["name"], *z["bounds"], **extra))
    scenario.no_fly_zones = list(scenario.no_fly_zones) + zones
    return scenario


def build_scenario(cfg: ExperimentConfig) -> Scenario:
    """The base scenario with this config's zone profile added."""
    return apply_zones(load_scenario(cfg.scenario), cfg.zone_profile,
                       cfg.appear_s, cfg.expire_s, cfg.drift_s, cfg.zone_speed_scale)


def sweep(base: ExperimentConfig, **axes: List[Any]) -> List[ExperimentConfig]:
    """Expand axes into configs, e.g. sweep(base, zone_profile=[...], zone_monitor=[...])."""
    names = list(axes)
    out = []
    for combo in itertools.product(*(axes[n] for n in names)):
        data = base.to_dict()
        data.update(dict(zip(names, combo)))
        data["experiment_id"] = "_".join([base.experiment_id] + [str(v) for v in combo])
        out.append(ExperimentConfig.from_dict(data))
    return out
