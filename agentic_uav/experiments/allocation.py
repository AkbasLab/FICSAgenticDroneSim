"""Phase 8: the allocation manifest, read strictly, and the team flown on the mock with nobody told a sector.

    config = load_allocation()                 # default.toml: the weights and timings fixed before any run
    run = fly_team_on_mock(scenario, config)   # every drone told the team mission, and no task
    run.team.met, run.searched, run.nets       # the mission, who searched what, each drone's own book

The manifest is read here, outside the agents' boundary, and handed to the
agents as an `AllocationConfig`: an agent is given its weights, it does not
go looking for them. Every key is required, no unknown key is allowed, so a
typo cannot silently fall back to a default.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from ..agents.drone_agent import DroneAgent
from ..agents.team_policy import TeamPolicy
from ..control.action_executor import ActionExecutor
from ..control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M
from ..control.skills import SkillRunner
from ..coordination.bids import AllocationConfig, BidWeights
from ..coordination.contract_net import ContractNet
from ..coordination.tasks import tasks_from_brief
from ..core.models import Position
from ..core.scenario import Scenario
from ..simulator.message_bus import MessageBus
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld
from ..simulator.observer import mock_trajectories
from ..simulator.sensing import mock_sensors
from .evaluation import evaluate
from .provenance import REPO_ROOT
from .runner import load_toml
from .single_agent import MAX_FLIGHT_S, MESSAGE_DELAY_S, TeamAgentRun

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


# ------------------------------------------------------------ the team, on the mock

@dataclass(frozen=True)
class AllocationRun:
    """A team flown with nobody told a sector: the flight, and each drone's own side of the protocol."""

    team: TeamAgentRun
    config: AllocationConfig
    nets: dict[str, dict[str, Any]] = field(default_factory=dict)     # each drone's ContractNet, as JSON
    searched: dict[str, list[str]] = field(default_factory=dict)      # the tasks each drone completed

    @property
    def met(self) -> bool:
        return self.team.met


def fly_team_on_mock(scenario: Scenario, config: AllocationConfig, label: str = "deliberating",
                     drones: list[str] | None = None, range_m: float | None | str = "scenario") -> AllocationRun:
    """Every drone on the roster (or `drones`) an agent told the team mission, talking; nobody told a sector."""
    roster = [v.id for v in scenario.vehicles]
    drones = list(roster if drones is None else drones)
    unknown = sorted(set(drones) - set(roster))
    if unknown:
        raise ValueError(f"not on {scenario.scenario_id}'s roster: {unknown}")
    world = MockWorld(declared=roster)
    adapter = MockVehicleAdapter(world)
    for v in scenario.vehicles:
        adapter.place_vehicle(v.id, Position(v.start_x, v.start_y, world.ground_z))
    heights = {d: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, d in enumerate(roster)}
    executors = {d: ActionExecutor(SkillRunner(MockVehicleAdapter(world), d, world.clock)) for d in drones}
    sensors = {d: mock_sensors(world, scenario, d) for d in drones}

    def where(drone: str) -> tuple[float, float, float]:
        p = world.position(drone)
        return (p.x, p.y, world.ground_z - p.z)

    reach = scenario.network.communication_range_m if range_m == "scenario" else range_m
    bus = MessageBus(drones, world.clock, where, reach, mission_id=scenario.scenario_id, delay_s=MESSAGE_DELAY_S)
    brief = scenario.brief()
    policies = {d: TeamPolicy(ContractNet(d, tasks_from_brief(brief), config), altitude_m=heights[d]) for d in drones}
    agents: dict[str, DroneAgent] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(len(drones))
    start = world.clock.now()

    def body(drone: str) -> None:
        with world.clock.participate():
            try:
                barrier.wait()
                agent = DroneAgent(brief, sensors[drone], executors[drone], policies[drone],
                                   comms=bus.comms(drone), coordinator=policies[drone])
                agent.assign_team()
                agent.run(max_s=MAX_FLIGHT_S)
                agents[drone] = agent
            except BaseException as exc:          # recorded, never silent
                errors[drone] = exc

    threads = [threading.Thread(target=body, args=(d,), name=f"{d}-agent") for d in drones]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for e in executors.values():
        e.close()
    if errors:
        drone, exc = sorted(errors.items())[0]
        raise RuntimeError(f"{drone}'s agent raised: {type(exc).__name__}: {exc}") from exc
    trajectories = mock_trajectories(world, roster)
    report = evaluate(scenario, trajectories, start, world.clock.now(), contacts=world.contacts())
    skills = {d: tuple((e.command.skill.value, "running" if e.running else
                        (e.result.status.value if e.result is not None else "error"))
                       for e in executors[d].history()) for d in drones}
    searched = {d: list(policies[d].completed) for d in drones}
    team = TeamAgentRun(label, scenario.random_seed, {d: ", ".join(searched[d]) or None for d in drones}, report,
                        {d: tuple(a.trace) for d, a in agents.items()}, {d: a.finished for d, a in agents.items()},
                        skills, start, trajectories, bus.deliveries())
    return AllocationRun(team, config, {d: policies[d].net.as_json() for d in drones}, searched)


def contested(config: AllocationConfig) -> AllocationConfig:
    """The same manifest with no bid window: every drone claims at once, before any bid can arrive."""
    return dataclasses.replace(config, bid_window_s=0.0)
