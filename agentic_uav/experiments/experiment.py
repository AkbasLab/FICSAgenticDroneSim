"""Phase 14: one experiment configuration, and a batch of them (AUV-14, 14.1).

    batch = load_batch("configs/experiments/phase14_exit.toml")
    for run in batch.runs:                     # each an ExperimentConfig, in a fixed order
        run.run_id, run.architecture, run.network, run.failure, run.seed, run.planner

A run is named by the eight things AUV-14 lists: an experiment id, the
architecture (a Phase 13 configuration), the scenario, the team size, the
network profile, the failure profile, the random seed and the planner. A batch
file gives any of them as a list, and expands to every combination, in a fixed
order, each run with a stable id:

    [batch]
    id = "phase14-exit"
    description = "..."

    [[experiment]]
    id = "arms"
    architecture = ["A", "B", "C", "D"]
    scenario = "search_relay_001"
    team_size = 4
    network = ["nominal", "severe"]      # a configs/network profile, or "perfect" (no network model)
    failure = ["none", "drone1-at-60s"]  # a configs/failures profile
    seed = "1-3"                         # an integer, a list, or "a-b"
    planner = "echo"                     # where a model decides: echo | llm:<configs/llm name> | replay:<record>

Read strictly, like every manifest here: an unknown key, a wrong type, or a
combination that cannot fly is refused before anything runs -- a team size the
scenario does not have, a network whose partition names drones the scenario
lacks, a stop or an injection for a drone that is not there, an injection
without the guardian that must catch it, a model for an arm whose rules decide
(or none for one whose model does), and E (Phase 4's plan, no agents) on
anything but a perfect network with no failure.

A FAILURE PROFILE (`configs/failures/*.toml`) is what goes wrong, made from
outside the agents: drones stopped at set times (Phase 9's stop), and/or one of
Phase 11's injections -- an unsafe proposal the guardian must catch.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .architecture import architecture_path, load_architecture
from .conditions import load_network, network_path
from .llm import llm_path, load_llm
from .provenance import REPO_ROOT
from .runner import load_toml
from .scenarios import load_scenario, scenario_path

FAILURE_DIR = os.path.join(REPO_ROOT, "configs", "failures")
EXPERIMENT_DIR = os.path.join(REPO_ROOT, "configs", "experiments")
PERFECT = "perfect"                       # no network model: every message delivered at the bus's own delay
RUN_KEYS = ("id", "architecture", "scenario", "team_size", "network", "failure", "seed", "planner")
PLANNER_KINDS = ("none", "echo", "llm", "replay")


# ------------------------------------------------------------------ failures

@dataclass(frozen=True)
class FailureProfile:
    name: str
    description: str
    stop: dict[str, float] = field(default_factory=dict)      # drone -> seconds from the flight's start
    injection: str | None = None                               # a Phase 11 injection's name

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def failure_path(name: str) -> str:
    return name if name.endswith(".toml") else os.path.join(FAILURE_DIR, f"{name}.toml")


def parse_failure(data: dict[str, Any], source: str = "") -> FailureProfile:
    from .guardian_exit import INJECTIONS
    problems = [f"unknown section [{k}]" for k in data if k != "failure"]
    f = data.get("failure")
    if not isinstance(f, dict):
        problems.append("[failure] is missing")
        f = {}
    problems += [f"[failure] unknown key {k}" for k in f if k not in ("name", "description", "stop", "injection")]
    for k in ("name", "description"):
        if not isinstance(f.get(k), str) or not f.get(k):
            problems.append(f"[failure] {k} must be text")
    stop = f.get("stop", {})
    if not isinstance(stop, dict) or not all(isinstance(d, str) and isinstance(t, (int, float))
                                             and not isinstance(t, bool) and t > 0 for d, t in stop.items()):
        problems.append("[failure] stop must map drones to positive seconds")
        stop = {}
    injection = f.get("injection")
    if injection is not None and injection not in {i.name for i in INJECTIONS}:
        problems.append(f"[failure] injection {injection!r} is not one of Phase 11's")
    if problems:
        raise ValueError(f"not a valid failure profile{' ' + source if source else ''}: " + "; ".join(problems))
    return FailureProfile(f["name"], f["description"], {d: float(t) for d, t in stop.items()}, injection)


def load_failure(name: str) -> FailureProfile:
    path = failure_path(name)
    profile = parse_failure(load_toml(path), path)
    if not name.endswith(".toml") and profile.name != name:
        raise ValueError(f"{path}: named {profile.name!r}, not {name!r}")
    return profile


def injection_named(name: str) -> Any:
    from .guardian_exit import INJECTIONS
    return next(i for i in INJECTIONS if i.name == name)


# ------------------------------------------------------------------ planners

@dataclass(frozen=True)
class Planner:
    kind: str                     # none | echo | llm | replay
    arg: str = ""                 # llm: the configs/llm name; replay: the record's repo-relative path

    @property
    def text(self) -> str:
        return self.kind if not self.arg else f"{self.kind}:{self.arg}"


def parse_planner(text: Any) -> Planner:
    if not isinstance(text, str):
        raise ValueError(f"planner must be text: {text!r}")
    kind, _, arg = text.partition(":")
    if kind not in PLANNER_KINDS or (kind in ("none", "echo") and arg) or (kind in ("llm", "replay") and not arg):
        raise ValueError(f"planner {text!r}: none, echo, llm:<configs/llm name> or replay:<record path>")
    return Planner(kind, arg)


def replay_label(stop: dict[str, float]) -> str:
    """The flight label a Phase 12 record files a flight under."""
    return "no stop" if not stop else f"{next(iter(stop))} stopped"


def replay_records(path: str) -> dict[tuple[int, str], dict[str, Any]]:
    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    with io.open(full, encoding="utf-8") as h:
        return {(r["seed"], r["flight"]): r for r in map(json.loads, h) if r.get("kind") == "flight"}


# ------------------------------------------------------------------- one run

@dataclass(frozen=True)
class ExperimentConfig:
    index: int
    experiment_id: str
    architecture: str
    scenario: str
    team_size: int
    network: str
    failure: str
    seed: int
    planner: str

    @property
    def run_id(self) -> str:
        return (f"{self.index:04d}-{self.architecture}-{self.scenario}-{self.network}-{self.failure}"
                f"-s{self.seed}")

    def as_json(self) -> dict[str, Any]:
        return {"run_id": self.run_id, **asdict(self)}

    def files(self) -> dict[str, str]:
        """Every configuration file this run reads, by role (repo-relative where inside the repo)."""
        out = {"architecture": architecture_path(self.architecture), "scenario": scenario_path(self.scenario),
               "failure": failure_path(self.failure)}
        if self.network != PERFECT:
            out["network"] = network_path(self.network)
        p = parse_planner(self.planner)
        if p.kind == "llm":
            out["llm"] = llm_path(p.arg)
        if p.kind == "replay":
            out["replay_record"] = p.arg if os.path.isabs(p.arg) else os.path.join(REPO_ROOT, p.arg)
        return out


@dataclass(frozen=True)
class Batch:
    batch_id: str
    description: str
    runs: tuple[ExperimentConfig, ...]
    source: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"batch_id": self.batch_id, "description": self.description, "source": self.source,
                "runs": [r.as_json() for r in self.runs]}


def _seeds(value: Any) -> list[int] | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return [value]
    if isinstance(value, list) and value and all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return list(value)
    if isinstance(value, str):
        a, sep, b = value.partition("-")
        if sep and a.strip().isdigit() and b.strip().isdigit() and int(a) <= int(b):
            return list(range(int(a), int(b) + 1))
    return None


def _texts(value: Any) -> list[str] | None:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
        return list(value)
    return None


def run_problems(run: ExperimentConfig, _cache: dict[str, Any] | None = None) -> list[str]:
    """Why this run cannot fly; nothing if it can."""
    c = {} if _cache is None else _cache

    def get(kind: str, name: str, loader: Any) -> Any:
        key = f"{kind}:{name}"
        if key not in c:
            try:
                c[key] = loader(name)
            except (OSError, ValueError, KeyError) as exc:
                c[key] = exc
        return c[key]

    p: list[str] = []
    arch = get("architecture", run.architecture, load_architecture)
    sc = get("scenario", run.scenario, load_scenario)
    fail = get("failure", run.failure, load_failure)
    for what, v in (("architecture", arch), ("scenario", sc), ("failure", fail)):
        if isinstance(v, Exception):
            p.append(f"{what} {getattr(run, what)!r}: {v}")
    net = None
    if run.network != PERFECT:
        net = get("network", run.network, load_network)
        if isinstance(net, Exception):
            p.append(f"network {run.network!r}: {net}")
            net = None
    try:
        planner = parse_planner(run.planner)
    except ValueError as exc:
        p.append(str(exc))
        planner = None
    if p:
        return p
    roster = [v.id for v in sc.vehicles]
    if run.team_size != len(roster):
        p.append(f"team size {run.team_size}: {run.scenario} flies {len(roster)} ({', '.join(roster)})")
    if net is not None:
        try:
            net.check_roster(roster)
        except ValueError as exc:
            p.append(f"network {run.network!r} does not fit {run.scenario}: {exc}")
    for d in fail.stop:
        if d not in roster:
            p.append(f"failure {run.failure!r} stops {d}, not in {run.scenario}")
    if fail.injection is not None:
        inj = injection_named(fail.injection)
        if inj.drone not in roster:
            p.append(f"failure {run.failure!r} injects into {inj.drone}, not in {run.scenario}")
        if not arch.guardian:
            p.append(f"failure {run.failure!r} injects an unsafe proposal: {run.architecture} has no guardian to "
                     "catch it")
    if arch.team == "scripted" and (run.network != PERFECT or fail.stop or fail.injection):
        p.append(f"{run.architecture} is Phase 4's preflight plan, no agents: only a perfect network and no failure")
    model = arch.decider == "llm"
    if planner is not None:
        if model and planner.kind == "none":
            p.append(f"{run.architecture}: a model decides -- give a planner (echo, llm:<name>, replay:<record>)")
        if not model and planner.kind != "none":
            p.append(f"{run.architecture}: its {'fallback' if arch.decider == 'llm-fallback' else 'rules'} decide "
                     f"-- planner must be none, not {planner.text!r}")
        if planner.kind == "llm":
            cfg = get("llm", planner.arg, load_llm)
            if isinstance(cfg, Exception):
                p.append(f"planner {planner.text!r}: {cfg}")
        if planner.kind == "replay":
            rec = get("replay", planner.arg, replay_records)
            if isinstance(rec, Exception):
                p.append(f"planner {planner.text!r}: {rec}")
            elif (run.seed, replay_label(fail.stop)) not in rec:
                p.append(f"planner {planner.text!r} has no flight for seed {run.seed}, {replay_label(fail.stop)!r}")
    return p


def parse_batch(data: dict[str, Any], source: str = "") -> Batch:
    """Strictly: [batch] id, description; [[experiment]] blocks, each expanded in a fixed order."""
    where = f" {source}" if source else ""
    problems = [f"unknown section [{k}]" for k in data if k not in ("batch", "experiment")]
    b = data.get("batch")
    if not isinstance(b, dict) or set(b) != {"id", "description"} or not all(isinstance(v, str) and v
                                                                             for v in b.values()):
        problems.append("[batch] must hold exactly id and description, as text")
    blocks = data.get("experiment")
    if not isinstance(blocks, list) or not blocks or not all(isinstance(x, dict) for x in blocks):
        problems.append("at least one [[experiment]] is needed")
        blocks = []
    runs: list[ExperimentConfig] = []
    seen_ids: set[str] = set()
    for n, blk in enumerate(blocks, 1):
        here = f"[[experiment]] {n}"
        unknown = [k for k in blk if k not in RUN_KEYS]
        missing = [k for k in RUN_KEYS if k not in blk]
        if unknown or missing:
            problems += [f"{here}: unknown key {k}" for k in unknown] + [f"{here}: missing {k}" for k in missing]
            continue
        exp_id = blk["id"]
        if not isinstance(exp_id, str) or not exp_id or exp_id in seen_ids:
            problems.append(f"{here}: id must be text, unique in the batch: {exp_id!r}")
            continue
        seen_ids.add(exp_id)
        lists = {k: _texts(blk[k]) for k in ("architecture", "scenario", "network", "failure")}
        seeds = _seeds(blk["seed"])
        size = blk["team_size"]
        bad = [k for k, v in lists.items() if v is None]
        if bad or seeds is None or not isinstance(blk["planner"], str) or not isinstance(size, int) \
                or isinstance(size, bool) or size < 1:
            problems.append(f"{here} ({exp_id}): architecture, scenario, network and failure must be text or lists "
                            "of text; seed an integer, a list or 'a-b'; team_size a positive integer; planner text")
            continue
        for arch in lists["architecture"]:
            for scen in lists["scenario"]:
                for net in lists["network"]:
                    for fail in lists["failure"]:
                        for seed in seeds:
                            runs.append(ExperimentConfig(len(runs) + 1, exp_id, arch, scen, size, net, fail, seed,
                                                         blk["planner"] if load_ok_model(arch) else "none"))
    if problems:
        raise ValueError(f"not a valid batch{where}: " + "; ".join(problems))
    cache: dict[str, Any] = {}
    for r in runs:
        problems += [f"run {r.run_id}: {x}" for x in run_problems(r, cache)]
    if problems:
        raise ValueError(f"not a valid batch{where}: " + "; ".join(problems[:40])
                         + (f"; ... {len(problems)} problems" if len(problems) > 40 else ""))
    planners = {(blk["id"], blk["planner"]) for blk in blocks}
    for exp_id, text in planners:
        if text != "none" and not any(r.planner != "none" for r in runs if r.experiment_id == exp_id):
            raise ValueError(f"not a valid batch{where}: [[experiment]] {exp_id} gives planner {text!r}, but no "
                             "architecture in it is decided by a model")
    return Batch(b["id"], b["description"], tuple(runs), source)


def load_ok_model(architecture: str) -> bool:
    """Whether a model decides for this architecture (unknown names are refused later, with the reason)."""
    try:
        return load_architecture(architecture).decider == "llm"
    except (OSError, ValueError):
        return True


def batch_path(name: str) -> str:
    return name if name.endswith(".toml") else os.path.join(EXPERIMENT_DIR, f"{name}.toml")


def load_batch(name: str) -> Batch:
    path = batch_path(name)
    return parse_batch(load_toml(path), os.path.relpath(path, REPO_ROOT) if path.startswith(REPO_ROOT) else path)
