"""The frozen model (AUV-12, 12.7), and the team flown with an LLM policy on the mock.

    config = load_llm()                               # configs/llm/default.toml
    problems = preflight(config, endpoint)            # the server serves exactly that model, that digest
    run, logs = fly_llm_on_mock(scenario, alloc, health, ask, stop={...}, guardian=limits, keep_out=ko)

12.7: "use a pinned local model as the primary; temperature zero or lowest
supported; record the exact model identifier and configuration; save all
prompts and structured outputs; do not silently update the model." The
manifest names the model AND its digest; `preflight` refuses a server whose
copy of that name has another digest -- an `ollama pull` between runs would
otherwise change the model under the same name, silently. Every flight's
records keep the manifest, the endpoint and the digest the server reported.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from ..agents.llm_policy import LLMPolicy
from ..planners.llm_ask import served_digest
from .provenance import REPO_ROOT
from .recovery import RecoveryRun, fly_recovery_on_mock
from .runner import load_toml

LLM_DIR = os.path.join(REPO_ROOT, "configs", "llm")
OPTION_KEYS = ("temperature", "seed", "num_ctx", "num_predict")


@dataclass(frozen=True)
class LLMConfig:
    model: str
    digest: str                         # the full sha256 the server reports for `model`; "" until pinned
    options: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 60.0

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def llm_path(name: str = "default") -> str:
    return name if name.endswith(".toml") else os.path.join(LLM_DIR, f"{name}.toml")


def parse_llm(data: dict[str, Any], source: str = "") -> LLMConfig:
    problems = [f"unknown section [{k}]" for k in data if k not in ("model", "options", "call")]
    m, o, c = data.get("model"), data.get("options"), data.get("call")
    if not isinstance(m, dict) or set(m) != {"name", "digest"} or not all(isinstance(v, str) for v in m.values()):
        problems.append("[model] must hold exactly name and digest, as text")
    if not isinstance(o, dict) or set(o) != set(OPTION_KEYS) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in o.values()):
        problems.append(f"[options] must hold exactly {', '.join(OPTION_KEYS)}, as numbers")
    elif o["temperature"] != 0:
        problems.append("[options] temperature must be 0 (12.7)")
    if not isinstance(c, dict) or set(c) != {"timeout_s"} or not isinstance(c.get("timeout_s"), (int, float)) \
            or c["timeout_s"] <= 0:
        problems.append("[call] must hold exactly timeout_s, positive")
    if problems:
        raise ValueError(f"not a valid LLM manifest{' ' + source if source else ''}: " + "; ".join(problems))
    return LLMConfig(m["name"], m["digest"], dict(o), float(c["timeout_s"]))


def load_llm(name: str = "default") -> LLMConfig:
    path = llm_path(name)
    return parse_llm(load_toml(path), path)


def preflight(config: LLMConfig, endpoint: str) -> list[str]:
    """Why this server must not be used for a run of record; nothing if it may."""
    got = served_digest(endpoint, config.model)
    if got is None:
        return [f"{endpoint} does not serve {config.model}"]
    if not config.digest:
        return [f"{config.model} is not pinned: the manifest's digest is empty (the server has {got})"]
    if got != config.digest:
        return [f"{endpoint} serves {config.model} at digest {got}, not the pinned {config.digest}"]
    return []


def fly_llm_on_mock(scenario: Any, config: Any, health: Any, ask: Any, label: str = "llm",
                    stop: dict[str, float] | None = None, **fly: Any) -> tuple[RecoveryRun, dict[str, dict[str, Any]]]:
    """The team flown with every drone's decisions an LLM policy's, over `ask`; and each drone's LLM log."""
    policies: dict[str, LLMPolicy] = {}

    def wrap(drone: str, inner: Any) -> LLMPolicy:
        policies[drone] = LLMPolicy(inner, ask)
        return policies[drone]

    run = fly_recovery_on_mock(scenario, config, health, label, stop, wrap_policy=wrap, **fly)
    return run, {d: p.as_json() for d, p in sorted(policies.items())}
