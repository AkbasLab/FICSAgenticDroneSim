"""Phase 10's network conditions, read strictly (`configs/network/<name>.toml`).

    model = load_network("severe").seeded(seed)    # handed to the bus, the sensing, the judge -- never an agent

Each manifest is one level of the network factor (AUV-10, 10.2), fixed before
any run and recorded with every run that uses it. Read here, outside the
agents' boundary: known sections and keys only, numbers where numbers go.
"""

from __future__ import annotations

import os
from typing import Any

from ..simulator.network import NetworkModel, Partition
from .provenance import REPO_ROOT
from .runner import load_toml

NETWORK_DIR = os.path.join(REPO_ROOT, "configs", "network")

_SECTIONS = {
    "latency": {"mean_s": True, "jitter_s": False, "floor_s": False},
    "loss": {"probability": False},
    "limits": {"rate_per_s": False, "bandwidth_bytes_per_s": False},
    "range": {"m": False},
}
_PARTITION_KEYS = {"groups", "start_s", "end_s"}


def network_path(name: str) -> str:
    return name if name.endswith(".toml") else os.path.join(NETWORK_DIR, f"{name}.toml")


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_network(data: dict[str, Any], name: str, source: str = "") -> NetworkModel:
    """A network manifest, read strictly: known sections and keys only, numbers where numbers go."""
    problems = [f"unknown section [{k}]" for k in data if k not in _SECTIONS and k not in ("partition", "about")]
    if "about" in data and not isinstance(data["about"], str):
        problems.append("about must be text")
    got: dict[str, dict[str, Any]] = {}
    for sec, keys in _SECTIONS.items():
        block = data.get(sec, {})
        if not isinstance(block, dict):
            problems.append(f"[{sec}] must be a table")
            continue
        problems += [f"[{sec}] unknown key {k}" for k in block if k not in keys]
        problems += [f"[{sec}] missing {k}" for k, required in keys.items() if required and k not in block]
        problems += [f"[{sec}] {k} is not a number: {v!r}" for k, v in block.items() if k in keys and not _number(v)]
        got[sec] = block
    parts = data.get("partition", [])
    if not isinstance(parts, list):
        problems.append("[[partition]] must be an array of tables")
        parts = []
    partitions = []
    for i, part in enumerate(parts):
        if not isinstance(part, dict):
            problems.append(f"partition {i + 1} is not a table")
            continue
        problems += [f"partition {i + 1}: unknown key {k}" for k in part if k not in _PARTITION_KEYS]
        problems += [f"partition {i + 1}: missing {k}" for k in sorted(_PARTITION_KEYS) if k not in part]
        groups = part.get("groups")
        if not (isinstance(groups, list) and all(isinstance(g, list) and all(isinstance(n, str) for n in g)
                                                  for g in groups)):
            problems.append(f"partition {i + 1}: groups must be lists of names")
            continue
        if not (_number(part.get("start_s")) and _number(part.get("end_s"))):
            problems.append(f"partition {i + 1}: start_s and end_s must be numbers")
            continue
        partitions.append(Partition(tuple(frozenset(g) for g in groups), float(part["start_s"]), float(part["end_s"])))
    if problems:
        raise ValueError(f"not a valid network manifest{' ' + source if source else ''}: " + "; ".join(problems))
    lat, loss, lim, rng = got["latency"], got["loss"], got["limits"], got["range"]

    def opt(block: dict[str, Any], key: str) -> float | None:
        return float(block[key]) if key in block else None

    return NetworkModel(name, float(lat["mean_s"]), float(lat.get("jitter_s", 0.0)), float(lat.get("floor_s", 0.05)),
                        float(loss.get("probability", 0.0)), opt(lim, "rate_per_s"), opt(lim, "bandwidth_bytes_per_s"),
                        opt(rng, "m"), tuple(partitions))


def load_network(name: str) -> NetworkModel:
    path = network_path(name)
    stem = os.path.splitext(os.path.basename(path))[0]
    return parse_network(load_toml(path), stem, path)


CONDITIONS = ("nominal", "moderate", "severe", "partitioned")
