"""Phase 9's recovery manifest, read strictly (`configs/recovery/<name>.toml`).

    config = load_recovery()                   # default.toml: the failure detector's thresholds
    config.as_json()                           # what every run records

Read here, outside the agents' boundary, and handed to the agents: an agent is
given its thresholds, it does not go looking for them. Every key required,
none unknown, numbers only.
"""

from __future__ import annotations

import os
from typing import Any

from ..coordination.health import HealthConfig
from .provenance import REPO_ROOT
from .runner import load_toml

RECOVERY_DIR = os.path.join(REPO_ROOT, "configs", "recovery")
HEALTH_KEYS = ("suspected_s", "unreachable_s", "failed_s")


def recovery_path(name: str = "default") -> str:
    return name if name.endswith(".toml") else os.path.join(RECOVERY_DIR, f"{name}.toml")


def parse_recovery(data: dict[str, Any], source: str = "") -> HealthConfig:
    problems = [f"unknown section [{k}]" for k in data if k != "health"]
    got = data.get("health")
    if not isinstance(got, dict):
        problems.append("missing section [health]")
    else:
        problems += [f"[health] missing {k}" for k in HEALTH_KEYS if k not in got]
        problems += [f"[health] unknown key {k}" for k in got if k not in HEALTH_KEYS]
        problems += [f"[health] {k} is not a number: {got[k]!r}" for k in HEALTH_KEYS
                     if k in got and (not isinstance(got[k], (int, float)) or isinstance(got[k], bool))]
    if problems:
        raise ValueError(f"not a valid recovery manifest{' ' + source if source else ''}: " + "; ".join(problems))
    return HealthConfig(*(float(got[k]) for k in HEALTH_KEYS))


def load_recovery(name: str = "default") -> HealthConfig:
    path = recovery_path(name)
    return parse_recovery(load_toml(path), path)
