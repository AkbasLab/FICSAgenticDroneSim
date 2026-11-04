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


# ------------------------------------------------------------ the team, on the mock, with a stop

import threading  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402

from ..agents.drone_agent import DroneAgent  # noqa: E402
from ..agents.recovery_policy import RecoveryPolicy  # noqa: E402
from ..control.action_executor import ActionExecutor  # noqa: E402
from ..control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M  # noqa: E402
from ..control.skills import SkillRunner  # noqa: E402
from ..coordination.bids import AllocationConfig  # noqa: E402
from ..coordination.contract_net import ContractNet  # noqa: E402
from ..coordination.tasks import tasks_from_brief  # noqa: E402
from ..core.models import Position  # noqa: E402
from ..core.scenario import Scenario  # noqa: E402
from ..simulator.message_bus import MessageBus  # noqa: E402
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from ..simulator.observer import mock_trajectories  # noqa: E402
from ..simulator.sensing import mock_sensors  # noqa: E402
from .evaluation import evaluate  # noqa: E402
from .single_agent import MAX_FLIGHT_S, MESSAGE_DELAY_S, TeamAgentRun  # noqa: E402


@dataclass(frozen=True)
class RecoveryRun:
    """A team flown with the recovery policy, perhaps with drones stopped: the flight and each drone's record."""

    team: TeamAgentRun
    config: AllocationConfig
    health: HealthConfig
    stopped: dict[str, float] = field(default_factory=dict)             # drone -> when it was stopped
    policies: dict[str, dict[str, Any]] = field(default_factory=dict)    # each drone's policy record
    searched: dict[str, list[str]] = field(default_factory=dict)

    @property
    def survivors(self) -> list[str]:
        return sorted(d for d in self.team.traces if d not in self.stopped)

    @property
    def met(self) -> bool:
        """The mission met by the drones still flying, each ending its part itself."""
        return self.team.report.success and all(self.team.finished.get(d, False) for d in self.survivors)


def fly_recovery_on_mock(scenario: Scenario, config: AllocationConfig, health: HealthConfig,
                         label: str = "no stop", stop: dict[str, float] | None = None,
                         range_m: float | None | str = None) -> RecoveryRun:
    """The team told the team mission, with the recovery policy; each drone in `stop` stopped at its time.

    A stop is made FROM OUTSIDE, at a set time from the flight's start: the
    drone's agent stops deciding and talking, its running skill is aborted,
    and the drone holds where it is -- a companion computer dying while the
    autopilot holds. No agent code knows about it. The judge is told which
    drones were stopped (AUV-05: "all functioning drones return safely").
    """
    stop = dict(stop or {})
    roster = [v.id for v in scenario.vehicles]
    unknown = sorted(set(stop) - set(roster))
    if unknown:
        raise ValueError(f"not on {scenario.scenario_id}'s roster: {unknown}")
    world = MockWorld(declared=roster)
    adapter = MockVehicleAdapter(world)
    for v in scenario.vehicles:
        adapter.place_vehicle(v.id, Position(v.start_x, v.start_y, world.ground_z))
    heights = {d: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, d in enumerate(roster)}
    executors = {d: ActionExecutor(SkillRunner(MockVehicleAdapter(world), d, world.clock)) for d in roster}
    sensors = {d: mock_sensors(world, scenario, d) for d in roster}

    def where(drone: str) -> tuple[float, float, float]:
        p = world.position(drone)
        return (p.x, p.y, world.ground_z - p.z)

    reach = scenario.network.communication_range_m if range_m == "scenario" else range_m
    bus = MessageBus(roster, world.clock, where, reach, mission_id=scenario.scenario_id, delay_s=MESSAGE_DELAY_S)
    brief = scenario.brief()
    policies = {d: RecoveryPolicy(ContractNet(d, tasks_from_brief(brief), config), health, altitude_m=heights[d])
                for d in roster}
    agents: dict[str, DroneAgent] = {}
    stopped: dict[str, float] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(len(roster))
    start = world.clock.now()

    def body(drone: str) -> None:
        with world.clock.participate():
            try:
                barrier.wait()
                agent = DroneAgent(brief, sensors[drone], executors[drone], policies[drone],
                                   comms=bus.comms(drone), coordinator=policies[drone])
                agents[drone] = agent
                agent.assign_team()
                if drone in stop:
                    agent.run(max_s=stop[drone])
                    if not agent.finished:
                        executors[drone].abort()              # the drone holds where it is
                        stopped[drone] = world.clock.now() - start
                else:
                    agent.run(max_s=MAX_FLIGHT_S)
            except BaseException as exc:          # recorded, never silent
                errors[drone] = exc

    threads = [threading.Thread(target=body, args=(d,), name=f"{d}-agent") for d in roster]
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
    report = evaluate(scenario, trajectories, start, world.clock.now(), contacts=world.contacts(), failed=list(stopped))
    skills = {d: tuple((e.command.skill.value, "running" if e.running else
                        (e.result.status.value if e.result is not None else "error"))
                       for e in executors[d].history()) for d in roster}
    searched = {d: list(policies[d].completed) for d in roster}
    team = TeamAgentRun(label, scenario.random_seed, {d: ", ".join(searched[d]) or None for d in roster}, report,
                        # In roster order, not the order the threads happened to run in.
                        {d: tuple(agents[d].trace) for d in roster if d in agents},
                        {d: agents[d].finished for d in roster if d in agents},
                        skills, start, trajectories, bus.deliveries())
    return RecoveryRun(team, config, health, stopped, {d: policies[d].as_json() for d in roster}, searched)


# ------------------------------------------------------------------- live

from ..control.monitor import SeparationMonitor  # noqa: E402
from ..core.clock import Clock  # noqa: E402
from ..simulator.observer import DEFAULT_POLL_HZ, PollingObserver  # noqa: E402
from ..simulator.scenario_manager import ensure_vehicles  # noqa: E402
from ..simulator.sensing import polled_sensors  # noqa: E402
from .evaluation import Contact  # noqa: E402
from .search_relay import RESET_SETTLE_S, check_live_pads, wait_at_rest  # noqa: E402
from .single_agent import FIRST_POLL_TIMEOUT_S, LiveTeamFlight  # noqa: E402


@dataclass(frozen=True)
class LiveRecoveryFlight:
    """One live flight of the team with a drone stopped: the flight, and each drone's record."""

    flight: LiveTeamFlight
    config: AllocationConfig
    health: HealthConfig
    stopped: dict[str, float] = field(default_factory=dict)
    policies: dict[str, dict[str, Any]] = field(default_factory=dict)
    searched: dict[str, list[str]] = field(default_factory=dict)

    def as_run(self, label: str = "live") -> RecoveryRun:
        """As a RecoveryRun -- the stopped drones told to the judge -- so the exit's checks apply as they stand."""
        return RecoveryRun(self.flight.as_run(label, failed=tuple(self.stopped)), self.config, self.health,
                           dict(self.stopped), dict(self.policies), dict(self.searched))

    def as_json(self) -> dict[str, Any]:
        return {**self.flight.as_json(), "allocation": self.config.as_json(), "health": self.health.as_json(),
                "stopped": self.stopped, "policies": self.policies, "searched": self.searched}


def fly_recovery_live(scenario: Scenario, config: AllocationConfig, health: HealthConfig, scene: Any, connect: Any,
                      clock: Clock, stop: dict[str, float], poll_hz: float = DEFAULT_POLL_HZ,
                      settle_s: float = RESET_SETTLE_S) -> LiveRecoveryFlight:
    """Phase 8's live team, with the recovery policy, and the drones in `stop` stopped at their times, live.

    A stop is made from outside, as on the mock: the agent stops, its skill is
    aborted, the drone hovers where it is -- and is left hovering when the flight
    ends (reset the simulator before the next one). Every message delivered.
    """
    drones = check_live_pads(scenario)
    unknown = sorted(set(stop) - set(drones))
    if unknown:
        raise ValueError(f"not on {scenario.scenario_id}'s pads: {unknown}")
    scene.reset()
    clock.sleep(settle_s)
    scene.confirm_connection()
    layout = ensure_vehicles(scene, drones, settle=clock.sleep)
    layout["at_rest_s"] = wait_at_rest(scene, drones, clock)
    grounds = {d: scene.get_pose(d).z for d in drones}
    heights = {d: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, d in enumerate([v.id for v in scenario.vehicles])}
    observer = PollingObserver(connect, drones, grounds, clock=clock, hz=poll_hz)
    monitor = SeparationMonitor(connect(), drones)
    observer.start()
    monitor.start()
    monitor_t0 = clock.now()
    began = clock.now()
    while not all(observer.samples().get(d) for d in drones):
        if clock.now() - began > FIRST_POLL_TIMEOUT_S:
            observer.stop()
            monitor.stop()
            raise RuntimeError(f"no poll of {drones} within {FIRST_POLL_TIMEOUT_S:g} s")
        clock.sleep(0.05)

    def where(drone: str) -> tuple[float, float, float]:
        t, x, y, z = observer.samples()[drone][-1]
        return (x, y, grounds[drone] - z)

    bus = MessageBus(drones, clock, where, None, mission_id=scenario.scenario_id, delay_s=MESSAGE_DELAY_S)
    brief = scenario.brief()
    executors = {d: ActionExecutor(SkillRunner(connect(), d, clock), clock, abort_via=connect(), connect=connect)
                 for d in drones}
    sensors = {d: polled_sensors(observer, scenario, d, grounds) for d in drones}
    policies = {d: RecoveryPolicy(ContractNet(d, tasks_from_brief(brief), config), health, altitude_m=heights[d])
                for d in drones}
    agents: dict[str, DroneAgent] = {}
    stopped: dict[str, float] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(len(drones))
    start = clock.now()

    def body(drone: str) -> None:
        try:
            agent = DroneAgent(brief, sensors[drone], executors[drone], policies[drone], comms=bus.comms(drone),
                               coordinator=policies[drone])
            agents[drone] = agent
            barrier.wait()
            agent.assign_team()
            if drone in stop:
                agent.run(max_s=stop[drone] - (clock.now() - start))
                if not agent.finished:
                    executors[drone].abort()
                    stopped[drone] = round(clock.now() - start, 3)
            else:
                agent.run(max_s=MAX_FLIGHT_S)
        except BaseException as exc:              # recorded, never silent
            errors[drone] = exc
            barrier.abort()

    threads = [threading.Thread(target=body, args=(d,), name=f"{d}-agent") for d in drones]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        for e in executors.values():
            e.close()
        end = clock.now()
        watched = monitor.stop()
        observer.stop()
    if errors:
        drone, exc = sorted(errors.items())[0]
        raise RuntimeError(f"{drone}'s agent raised: {type(exc).__name__}: {exc}") from exc
    contacts = tuple(Contact(c["drone"], c["object"], monitor_t0 + c["first_at_s"])
                     for c in watched.get("collisions_polled", []))
    skills = {d: tuple((e.command.skill.value, "running" if e.running else
                        (e.result.status.value if e.result is not None else "error"))
                       for e in executors[d].history()) for d in drones}
    searched = {d: list(policies[d].completed) for d in drones}
    summary = {k: watched.get(k) for k in ("samples", "min_separation_m", "per_pair_min_m")}
    flight = LiveTeamFlight(scenario, {d: ", ".join(searched[d]) for d in drones}, observer.samples(), grounds,
                            contacts, start, end, poll_hz, {d: tuple(agents[d].trace) for d in drones if d in agents},
                            {d: agents[d].finished for d in drones if d in agents}, skills, bus.deliveries(), None,
                            {"added": layout.get("added", []), "layout": layout.get("layout", {}),
                             "at_rest_s": layout.get("at_rest_s", {})}, summary)
    return LiveRecoveryFlight(flight, config, health, stopped, {d: policies[d].as_json() for d in drones}, searched)
