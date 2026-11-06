"""Phase 13: the architecture is chosen by configuration, one harness flies them all (AUV-13).

    arch = load_architecture("C")                         # configs/architectures/C.toml
    flight = fly_architecture(arch, scenario, seed, stop={"Drone1": 60.0}, ask=EchoAsk())
    flight.run, flight.llm                                # the flight (a RecoveryRun), each drone's LLM log

AUV-13's exit: "The architecture can be selected through configuration rather
than maintaining four unrelated programs." Every arm here goes through ONE
function and ONE harness (`recovery.fly_recovery_on_mock`): the same world,
skills, sensing, bus and network, guardian, keep-out and judge. What a
configuration chooses is only how coordination decisions are made:

    team      decentralized   each drone runs the contract-net, the failure ladder, the roles (C, D)
              independent     each drone given a task at the start, never coordinating (B)
              central         a controller at the base assigns every task (A)
              scripted        Phase 4's preflight plan, no agents (E: history only -- it shares the world, the
                              skills and the judge, not the agent, guardian or network layers)
    decider   rules           the team's own deterministic policy decides
              llm             a model decides, through Phase 12's tools (`LLMPolicy`), over `ask`
              llm-fallback    the LLM machinery with the model replaced by its fallback (an ablation)

and which mechanisms are on: `memory` (the model's own decision history, llm
only), `leases` (a silent holder's task comes back), `roles` (relay,
reserve), `guardian` (and with it `keep_out`), `link_inputs` (each drone keeps
link estimates even on a perfect network), `perfect_comms` (the flight's
network condition is ignored). The model itself (pinned, echo, replay) is
the experiment's choice, passed as `ask`, not the architecture's.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import asdict, dataclass
from typing import Any

from ..agents.llm_policy import LLMPolicy
from .provenance import REPO_ROOT
from .recovery import RecoveryRun, fly_recovery_on_mock
from .runner import load_toml

ARCH_DIR = os.path.join(REPO_ROOT, "configs", "architectures")
TEAMS = ("decentralized", "independent", "central", "scripted")
DECIDERS = ("rules", "llm", "llm-fallback")
MECHANISMS = ("memory", "leases", "roles", "guardian", "keep_out", "link_inputs", "perfect_comms")


@dataclass(frozen=True)
class Architecture:
    name: str
    description: str
    team: str
    decider: str
    memory: bool = True
    leases: bool = True
    roles: bool = True
    guardian: bool = True
    keep_out: bool = True
    link_inputs: bool = False
    perfect_comms: bool = False

    def problems(self) -> list[str]:
        p = []
        if self.team not in TEAMS:
            p.append(f"team {self.team!r}: one of {TEAMS}")
        if self.decider not in DECIDERS:
            p.append(f"decider {self.decider!r}: one of {DECIDERS}")
        if self.decider != "rules" and self.team != "decentralized":
            p.append("a model decides only for the decentralized team (D): A, B and E are rules")
        if not self.memory and self.decider == "rules":
            p.append("memory is the model's decision history: only with an llm decider")
        if not self.roles and self.team != "decentralized":
            p.append("roles exist only in the decentralized team")
        if not self.leases and self.team not in ("decentralized", "central"):
            p.append("leases are the decentralized team's, or the controller's reassignment")
        if self.keep_out and not self.guardian and self.team != "scripted":
            pass                                   # the policies keep out; the guardian is only the backstop
        if self.team == "scripted" and (self.decider != "rules" or not all(
                (self.memory, self.leases, self.roles)) or self.link_inputs or self.perfect_comms):
            p.append("E is Phase 4's preflight plan: no decider or mechanisms to choose")
        return p

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def architecture_path(name: str) -> str:
    return name if name.endswith(".toml") else os.path.join(ARCH_DIR, f"{name}.toml")


def parse_architecture(data: dict[str, Any], source: str = "") -> Architecture:
    """Strictly: [architecture] name, description, team, decider; [mechanisms] each a true/false."""
    problems = [f"unknown section [{k}]" for k in data if k not in ("architecture", "mechanisms")]
    a, m = data.get("architecture"), data.get("mechanisms", {})
    keys = ("name", "description", "team", "decider")
    if not isinstance(a, dict) or set(a) != set(keys) or not all(isinstance(a[k], str) for k in keys):
        problems.append(f"[architecture] must hold exactly {', '.join(keys)}, as text")
    if not isinstance(m, dict):
        problems.append("[mechanisms] must be a table")
        m = {}
    problems += [f"[mechanisms] unknown key {k}" for k in m if k not in MECHANISMS]
    problems += [f"[mechanisms] {k} is not true or false: {m[k]!r}" for k in m if k in MECHANISMS
                 and not isinstance(m[k], bool)]
    if problems:
        raise ValueError(f"not a valid architecture{' ' + source if source else ''}: " + "; ".join(problems))
    arch = Architecture(**a, **m)
    if arch.problems():
        raise ValueError(f"not a valid architecture{' ' + source if source else ''}: " + "; ".join(arch.problems()))
    return arch


def load_architecture(name: str) -> Architecture:
    path = architecture_path(name)
    return parse_architecture(load_toml(path), path)


def all_architectures() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(ARCH_DIR) if f.endswith(".toml"))


@dataclass
class Flight:
    architecture: Architecture
    run: Any                                         # a RecoveryRun; for E a ScriptedRun
    llm: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)


def _fallback_only(request: dict[str, Any]) -> str:
    raise RuntimeError("the model is replaced by the fallback policy (ablation)")


def fly_architecture(arch: Architecture, scenario: Any, seed: int, alloc: Any, health: Any, limits: Any,
                     keep_out: Any, stop: dict[str, float] | None = None, network: Any = None,
                     ask: Any = None, label: str | None = None, wrap_policy: Any = None,
                     wrap_handle: Any = None) -> Flight:
    """One flight of `arch`, seed `seed`, through the one harness.

    `wrap_policy(drone, policy)` and `wrap_handle(drone, handle, guardian)` (Phase 14) are the harness's own
    hooks, passed through for a failure made from outside -- Phase 11's injections. A policy hook wraps the
    drone's whole policy, the model's included, as the outermost layer."""
    sc = dataclasses.replace(scenario, random_seed=seed)
    label = label or ("no stop" if not stop else f"{next(iter(stop))} stopped")
    if arch.team == "scripted":
        if stop:
            raise ValueError("E, Phase 4's preflight plan, has no agents to stop")
        from .search_relay import fly_on_mock
        return Flight(arch, fly_on_mock(sc))
    if arch.decider == "llm" and ask is None:
        raise ValueError(f"{arch.name}: a model decides -- give `ask` (the pinned model, an echo or a replay)")
    policies: dict[str, LLMPolicy] = {}
    wrap = wrap_policy
    if arch.decider != "rules":
        model = ask if arch.decider == "llm" else _fallback_only

        def wrap(drone: str, inner: Any) -> Any:
            policies[drone] = LLMPolicy(inner, model, memory=arch.memory)
            return policies[drone] if wrap_policy is None else wrap_policy(drone, policies[drone])

    run: RecoveryRun = fly_recovery_on_mock(
        sc, alloc, health, label, stop, network=None if arch.perfect_comms else network,
        guardian=limits if arch.guardian else None, keep_out=keep_out if arch.keep_out else None,
        wrap_policy=wrap, wrap_handle=wrap_handle, team=arch.team, leases=arch.leases, roles=arch.roles,
        link_inputs=arch.link_inputs)
    return Flight(arch, run, {d: p.as_json() for d, p in sorted(policies.items())})
