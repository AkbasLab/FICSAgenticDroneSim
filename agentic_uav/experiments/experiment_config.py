"""The experiment configuration and its manifest (Phase 14.1, 14.2).

One YAML file describes one run completely:

    experiment_id: exp_0042
    architecture: agentic_decentralized
    scenario: search_relay_001
    team_size: 4
    network_profile: severe
    failure_profile: drone_failure_midmission
    random_seed: 42
    planner: llama3.1-8b

Everything the runner needs comes from this file, so a run is reproduced by
re-running the file rather than by remembering which flags were passed. The
manifest then records what was *actually* used, which is not always the same
thing - a model can be unavailable, a default can change - and it is the
manifest, not the config, that describes the run that happened.
"""

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: Long names in configs map to the Phase 13 architecture keys. Configs use the
#: readable name so a file is self-describing; code uses the key.
ARCHITECTURE_ALIASES = {
    "centralized": "A", "centralized_fleet_controller": "A",
    "independent": "B", "independent_persistent_agents": "B",
    "deterministic_decentralized": "C", "decentralized": "C",
    "agentic_decentralized": "D", "agentic": "D",
    "open_loop": "E", "open_loop_baseline": "E",
}

#: Named failure profiles, so "drone_failure_midmission" means the same thing in
#: every experiment rather than being re-specified per file.
#:
#: Times are in simulated seconds and land on skill boundaries, because
#: simulated time advances one whole skill at a time. `early` fires before the
#: sweep begins; `midmission` lands during it, which on this scenario means the
#: drone finishes the sweep it is inside and then stops.
FAILURE_PROFILES: Dict[str, Dict[str, float]] = {
    "none": {},
    "drone_failure_early": {"Drone2": 1.0},
    "drone_failure_midmission": {"Drone2": 30.0},
    "two_drone_failure": {"Drone2": 1.0, "Drone3": 45.0},
    "relay_failure": {"Drone4": 20.0},
}


@dataclass
class ExperimentConfig:
    experiment_id: str
    architecture: str = "agentic_decentralized"
    scenario: str = "search_relay_001"
    team_size: int = 4
    network_profile: str = "nominal"
    failure_profile: str = "none"
    random_seed: int = 42
    planner: str = "scripted"

    # knobs that are not in 14.1's example but must be recorded to reproduce
    heartbeat_s: float = 8.0
    max_steps: int = 600
    notes: str = ""

    @property
    def architecture_key(self):
        a = str(self.architecture).strip()
        return ARCHITECTURE_ALIASES.get(a.lower(), a.upper())

    @property
    def faults(self) -> Dict[str, float]:
        if self.failure_profile not in FAILURE_PROFILES:
            raise KeyError(
                f"unknown failure_profile {self.failure_profile!r}; "
                f"have {', '.join(sorted(FAILURE_PROFILES))}")
        return dict(FAILURE_PROFILES[self.failure_profile])

    def scenario_path(self, root):
        name = self.scenario
        if not name.endswith((".yaml", ".yml")):
            name += ".yaml"
        return os.path.join(root, "configs", "missions", name)

    def as_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d) -> "ExperimentConfig":
        known = {f for f in ExperimentConfig.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            # a silently ignored key is a config that does not do what it says
            raise KeyError(f"unknown configuration key(s): "
                           f"{', '.join(sorted(unknown))}")
        return ExperimentConfig(**d)

    @staticmethod
    def load(path) -> "ExperimentConfig":
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "experiment_id" not in data:
            data["experiment_id"] = os.path.splitext(os.path.basename(path))[0]
        cfg = ExperimentConfig.from_dict(data)
        cfg._source_path = path            # noqa: SLF001 - recorded in the manifest
        return cfg

    @staticmethod
    def load_many(path) -> List["ExperimentConfig"]:
        """A single config, a list of them, or a directory of YAML files."""
        import yaml
        if os.path.isdir(path):
            out = []
            for name in sorted(os.listdir(path)):
                if name.endswith((".yaml", ".yml")):
                    out.extend(ExperimentConfig.load_many(
                        os.path.join(path, name)))
            return out
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, list):
            out = []
            for i, item in enumerate(data):
                item.setdefault("experiment_id",
                                f"{os.path.splitext(os.path.basename(path))[0]}_{i:03d}")
                out.append(ExperimentConfig.from_dict(item))
            return out
        return [ExperimentConfig.load(path)]


# --- the manifest (14.2) -------------------------------------------------


def git_sha(root=None):
    """The commit the run was produced from, with a dirty flag.

    Returns "unknown" outside a repository rather than raising: a run from an
    unversioned copy is still worth recording, and should say so.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=10)
        if sha.returncode != 0:
            return "unknown"
        out = sha.stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, timeout=10)
        if dirty.returncode == 0 and dirty.stdout.strip():
            out += "-dirty"
        return out
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def software_versions():
    versions = {"python": sys.version.split()[0],
                "platform": platform.platform()}
    for mod in ("numpy", "yaml", "matplotlib", "ollama",
                "google.generativeai", "airsim"):
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, "__version__", "present")
        except Exception:                                    # noqa: BLE001
            versions[mod] = "absent"
    return versions


@dataclass
class Manifest:
    """What 14.2 requires, recorded for every run including failed ones."""
    experiment_id: str
    git_sha: str
    architecture: str
    architecture_key: str
    scenario: str
    scenario_path: str
    random_seed: int
    network_profile: str
    failure_profile: str
    faults: Dict[str, float]
    team_size: int
    planner: str
    model: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    config_source: Optional[str] = None
    software: Dict[str, Any] = field(default_factory=dict)

    started_at: str = ""
    finished_at: str = ""
    wall_clock_s: float = 0.0

    completed: bool = False
    status: str = "pending"          # pending | completed | failed
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None

    event_counts: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @staticmethod
    def begin(cfg: ExperimentConfig, root) -> "Manifest":
        return Manifest(
            experiment_id=cfg.experiment_id,
            git_sha=git_sha(root),
            architecture=cfg.architecture,
            architecture_key=cfg.architecture_key,
            scenario=cfg.scenario,
            scenario_path=cfg.scenario_path(root),
            random_seed=cfg.random_seed,
            network_profile=cfg.network_profile,
            failure_profile=cfg.failure_profile,
            faults=cfg.faults,
            team_size=cfg.team_size,
            planner=cfg.planner,
            config=cfg.as_dict(),
            config_source=getattr(cfg, "_source_path", None),
            software=software_versions(),
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            status="running")

    def finish(self, started_monotonic, completed, error=None):
        self.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.wall_clock_s = round(time.monotonic() - started_monotonic, 3)
        self.completed = bool(completed)
        self.status = "completed" if completed else "failed"
        if error is not None:
            import traceback as tb
            self.error_type = type(error).__name__
            self.error_message = str(error)
            self.traceback = "".join(
                tb.format_exception(type(error), error, error.__traceback__))
        return self

    def write(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=1, default=str)
        return path
