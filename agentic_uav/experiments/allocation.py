"""Phase 8's allocation manifest, read strictly (`configs/allocation/<name>.toml`).

    config = load_allocation()                 # default.toml: the weights and timings fixed before any run
    config.as_json()                           # what every run records

The manifest is read here, outside the agents' boundary, and handed to the
agents as an `AllocationConfig`: an agent is given its weights, it does not
go looking for them. Every key is required, no unknown key is allowed, so a
typo cannot silently fall back to a default.
"""

from __future__ import annotations

import os
from typing import Any

from ..coordination.bids import AllocationConfig, BidWeights
from .provenance import REPO_ROOT
from .runner import load_toml

ALLOCATION_DIR = os.path.join(REPO_ROOT, "configs", "allocation")
WEIGHT_KEYS = ("w_d", "w_b", "w_l", "w_c", "w_r")
PROTOCOL_KEYS = ("bid_window_s", "progress_period_s", "lease_s")


def allocation_path(name: str = "default") -> str:
    return name if name.endswith(".toml") else os.path.join(ALLOCATION_DIR, f"{name}.toml")


def parse_allocation(data: dict[str, Any], source: str = "") -> AllocationConfig:
    problems = [f"unknown section [{k}]" for k in data if k not in ("weights", "protocol")]
    for section, keys in (("weights", WEIGHT_KEYS), ("protocol", PROTOCOL_KEYS)):
        got = data.get(section)
        if not isinstance(got, dict):
            problems.append(f"missing section [{section}]")
            continue
        problems += [f"[{section}] missing {k}" for k in keys if k not in got]
        problems += [f"[{section}] unknown key {k}" for k in got if k not in keys]
        problems += [f"[{section}] {k} is not a number: {got[k]!r}" for k in keys
                     if k in got and (not isinstance(got[k], (int, float)) or isinstance(got[k], bool))]
    if problems:
        raise ValueError(f"not a valid allocation manifest{' ' + source if source else ''}: " + "; ".join(problems))
    w, p = data["weights"], data["protocol"]
    return AllocationConfig(BidWeights(*(float(w[k]) for k in WEIGHT_KEYS)), float(p["bid_window_s"]),
                            float(p["progress_period_s"]), float(p["lease_s"]))


def load_allocation(name: str = "default") -> AllocationConfig:
    path = allocation_path(name)
    return parse_allocation(load_toml(path), path)
