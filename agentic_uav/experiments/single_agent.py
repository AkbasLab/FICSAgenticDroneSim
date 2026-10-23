"""Phase 5's exit runs: one rule-based agent, given only a task, judged by Phase 4's evaluator.

    run = fly_agent_on_mock(scenario, "search S3")          # one flight, one AgentRun
    runs = exit_runs(scenario)                              # EXIT_SEEDS
    checks = trouble_runs(scenario)                         # TROUBLES, one at a time

AUV-06's exit criterion: "one deterministic persistent agent completes a
search task WITHOUT RECEIVING A COMPLETE PREFLIGHT ACTION LIST, recognises
success or failure, and decides what to do next." The parts, and how each
is shown:

* COMPLETES A SEARCH TASK: on `search_single_001` across EXIT_SEEDS, the
  mission report succeeds -- all six of AUV-05's criteria -- and the agent
  itself decided it was finished.
* WITHOUT A PREFLIGHT ACTION LIST: the agent is handed the brief and the
  words "search S3", nothing more; every skill it flies is a START decision
  made in answer to an event (checked in each trace).
* RECOGNISES SUCCESS OR FAILURE, AND DECIDES: under TROUBLES -- a fault that
  strikes once, one that never clears, a slow drone on a tight battery, a
  slow drone against the deadline, a battery too low to start -- each with
  what the agent must do written down here, before any was flown. A trouble
  run meets its check when the agent did that, ended the task itself, and
  (except where landing short is the only safe choice) came home safe.

The seeds are Phase 4's EXIT_SEEDS (1-20). Each flight is a fresh mock
world, the drone on its pad, the agent on its own thread on the shared
simulated clock.

SEVERAL INDEPENDENT AGENTS (Phase 6): `fly_agents_on_mock` flies one agent
per drone, each told only its own task, on one mock world. They share the
clock and the airspace, nothing else: no agent hears another (Phase 7's
messages will change that), and each flies at its own height, Phase 4's
12 m plus 4 m per drone. It is what Phase 6's knowledge log needs to show an
agent that knows a teammate is on the roster and nothing more.
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..agents.decision import DecisionKind
from ..agents.drone_agent import DroneAgent, TraceEntry
from ..agents.rule_policy import RulePolicy
from ..control.action_executor import ActionExecutor
from ..control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M
from ..control.monitor import SeparationMonitor
from ..control.skills import SkillRunner
from ..core.clock import Clock
from ..core.events import Trigger
from ..core.models import Position, PrimitiveKind
from ..core.scenario import BatterySpec, Scenario
from ..simulator.fault_injection import FaultyAdapter, PassingFaults
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld
from ..simulator.observer import DEFAULT_POLL_HZ, PollingObserver, mock_trajectories, trajectories_from_samples
from ..simulator.scenario_manager import ensure_vehicles
from ..simulator.sensing import mock_sensors, polled_sensors
from ..simulator.trajectory import Trajectory
from .evaluation import Contact, MissionReport, evaluate
from .search_relay import EXIT_SEEDS, RESET_SETTLE_S, check_live_pads, wait_at_rest

EXIT_TASK = "search S3"
MAX_FLIGHT_S = 3000.0          # a stuck agent is stopped here and fails its check


@dataclass(frozen=True)
class AgentRun:
    label: str
    seed: int
    task: str
    report: MissionReport
    trace: tuple[TraceEntry, ...]
    finished: bool
    progress: dict[str, Any]
    skills: tuple[tuple[str, str], ...]          # (skill, how it ended), in order
    trajectories: dict[str, Trajectory] = field(default_factory=dict, repr=False)

    def chosen_as_it_went(self) -> bool:
        """Every skill was a START made in answer to an event: no preflight list."""
        starts = [e for e in self.trace if e.decision.kind is DecisionKind.START]
        return bool(starts) and all(e.events for e in starts)

    def decided_after_every_failure(self) -> bool:
        """Each failed skill was followed, at once, by a decision to do something else."""
        failed = [e for e in self.trace if any(ev.trigger is Trigger.SKILL_FAILED for ev in e.events)]
        return all(e.decision.kind in (DecisionKind.START, DecisionKind.FINISH) for e in failed)

    @property
    def met(self) -> bool:
        """The nominal exit: mission success, finished by the agent's own decision, no list."""
        return self.report.success and self.finished and self.chosen_as_it_went()

    def as_json(self) -> dict[str, Any]:
        return {"label": self.label, "seed": self.seed, "task": self.task, "met": self.met,
                "finished": self.finished, "progress": self.progress,
                "skills": [list(s) for s in self.skills],
                "chosen_as_it_went": self.chosen_as_it_went(),
                "decided_after_every_failure": self.decided_after_every_failure(),
                "report": self.report.as_json(), "trace": [e.as_json() for e in self.trace]}


@dataclass(frozen=True)
class Trouble:
    """One kind of trouble, and what the agent must do about it -- fixed before flying."""

    name: str
    what: str
    expect: str
    prepare: Callable[[MockWorld], None] | None = None
    changes: dict[str, Any] = field(default_factory=dict)          # to the scenario
    success: bool = False                                          # must the mission still succeed
    gave_up: str | None = None                                     # words the agent's reason must contain
    safe: bool = True                                              # must C6 pass (home, landed, above reserve)
    skills: tuple[str, ...] | None = None                          # the exact skills, when it matters

    def check(self, run: AgentRun) -> tuple[bool, list[str]]:
        problems = []
        if not run.finished:
            problems.append("the agent never ended the task itself")
        if not run.decided_after_every_failure():
            problems.append("a failed skill was not followed by a decision")
        if self.success and not run.report.success:
            problems.append("the mission should still have succeeded")
        if self.gave_up and self.gave_up not in run.progress.get("gave_up", ""):
            problems.append(f"its reason should say {self.gave_up!r}; it said {run.progress.get('gave_up')!r}")
        if self.safe and not run.report.criterion("C6").passed:
            problems.append("it should have come home safe: " + run.report.criterion("C6").detail)
        if self.skills is not None and tuple(s for s, _ in run.skills) != self.skills:
            problems.append(f"skills {[s for s, _ in run.skills]}, expected {list(self.skills)}")
        return not problems, problems


def _fault(kind: PrimitiveKind, times: int | None) -> Callable[[MockWorld], None]:
    def prepare(world: MockWorld) -> None:
        if times is None:
            world.faults.raise_on[("Drone1", kind)] = "injected fault that does not clear"
        else:
            world.faults.raise_times[("Drone1", kind)] = times
    return prepare


def _slow(world: MockWorld) -> None:
    world.faults.speed_factor["Drone1"] = 0.5


TROUBLES = (
    Trouble("fault once", "the first horizontal move fails, once (the transit round R1)",
            "retry from where it is, then complete the task", _fault(PrimitiveKind.MOVE_TO_POSITION, 1),
            success=True),
    Trouble("fault for good", "every horizontal move fails",
            "retry twice, give up, land on its pad", _fault(PrimitiveKind.MOVE_TO_POSITION, None),
            gave_up="gave up"),
    Trouble("slow, short battery", "half speed, hover drain 0.25 %/s (enough at full speed)",
            "turn back on battery, land above the reserve", _slow,
            {"battery": BatterySpec(100.0, 0.25, 0.02, 20.0)}, gave_up="low battery"),
    Trouble("slow, short deadline", "half speed, deadline 260 s (enough at full speed)",
            "turn back on time, land before the deadline", _slow,
            {"deadline_s": 260.0}, gave_up="short of time"),
    Trouble("too little battery", "hover drain 0.5 %/s: the search cannot be flown at all",
            "not begin the search; land", None,
            {"battery": BatterySpec(100.0, 0.5, 0.02, 20.0)}, gave_up="low battery",
            skills=("TAKE_OFF", "LAND")),
)


def with_changes(scenario: Scenario, changes: dict[str, Any]) -> Scenario:
    changes = dict(changes)
    if "deadline_s" in changes:
        changes["mission"] = dataclasses.replace(scenario.mission, deadline_s=changes.pop("deadline_s"))
    return dataclasses.replace(scenario, **changes)


def fly_agent_on_mock(scenario: Scenario, task: str = EXIT_TASK, label: str = "nominal",
                      prepare: Callable[[MockWorld], None] | None = None) -> AgentRun:
    """One flight: a fresh world, the drone on its pad, the agent told `task` and nothing else."""
    (drone,) = [v.id for v in scenario.vehicles]
    world = MockWorld(declared=[drone])
    v = scenario.vehicle(drone)
    MockVehicleAdapter(world).place_vehicle(drone, Position(v.start_x, v.start_y, world.ground_z))
    if prepare is not None:
        prepare(world)
    executor = ActionExecutor(SkillRunner(MockVehicleAdapter(world), drone, world.clock))
    sensors = mock_sensors(world, scenario, drone)
    out: dict[str, DroneAgent] = {}
    start = world.clock.now()

    def body() -> None:
        with world.clock.participate():
            agent = DroneAgent(scenario.brief(), sensors, executor, RulePolicy())
            agent.assign(task)
            agent.run(max_s=MAX_FLIGHT_S)
            out["agent"] = agent

    thread = threading.Thread(target=body, name=f"{drone}-agent")
    thread.start()
    thread.join()
    executor.close()
    agent = out["agent"]
    trajectories = mock_trajectories(world, [drone])
    report = evaluate(scenario, trajectories, start, world.clock.now(), contacts=world.contacts())
    skills = tuple((e.command.skill.value, "running" if e.running else
                    (e.result.status.value if e.result is not None else "error")) for e in executor.history())
    return AgentRun(label, scenario.random_seed, task, report, tuple(agent.trace), agent.finished,
                    dict(agent.belief.mission.progress), skills, trajectories)


def exit_runs(scenario: Scenario, seeds: tuple[int, ...] = EXIT_SEEDS, task: str = EXIT_TASK) -> list[AgentRun]:
    return [fly_agent_on_mock(dataclasses.replace(scenario, random_seed=s), task) for s in seeds]


def trouble_runs(scenario: Scenario, task: str = EXIT_TASK,
                 troubles: tuple[Trouble, ...] = TROUBLES) -> list[tuple[Trouble, AgentRun, bool, list[str]]]:
    out = []
    for trouble in troubles:
        run = fly_agent_on_mock(with_changes(scenario, trouble.changes), task, trouble.name, trouble.prepare)
        ok, problems = trouble.check(run)
        out.append((trouble, run, ok, problems))
    return out


# ------------------------------------------------- several independent agents

PAIR_TASKS = {"Drone1": "search S1", "Drone2": "search S2"}


@dataclass(frozen=True)
class TeamAgentRun:
    """Several agents flown together on one mock world, each given only its own task."""

    label: str
    seed: int
    tasks: dict[str, str]
    report: MissionReport
    traces: dict[str, tuple[TraceEntry, ...]]
    finished: dict[str, bool]
    skills: dict[str, tuple[tuple[str, str], ...]]
    start: float
    trajectories: dict[str, Trajectory] = field(default_factory=dict, repr=False)

    @property
    def met(self) -> bool:
        """Mission success, every agent ended its task itself, every skill chosen as it went."""
        chosen = all(any(e.decision.kind is DecisionKind.START for e in t)
                     and all(e.events for e in t if e.decision.kind is DecisionKind.START)
                     for t in self.traces.values())
        return self.report.success and all(self.finished.values()) and chosen


def fly_agents_on_mock(scenario: Scenario, tasks: dict[str, str] | None = None,
                       label: str = "independent") -> TeamAgentRun:
    """One agent per drone in `tasks` (default: every drone on PAIR_TASKS), together, none hearing another."""
    tasks = dict(PAIR_TASKS if tasks is None else tasks)
    drones = [v.id for v in scenario.vehicles]
    unknown = sorted(set(tasks) - set(drones))
    if unknown:
        raise ValueError(f"not on {scenario.scenario_id}'s roster: {unknown}")
    world = MockWorld(declared=drones)
    adapter = MockVehicleAdapter(world)
    for v in scenario.vehicles:
        adapter.place_vehicle(v.id, Position(v.start_x, v.start_y, world.ground_z))
    heights = {d: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, d in enumerate(drones)}
    executors = {d: ActionExecutor(SkillRunner(MockVehicleAdapter(world), d, world.clock)) for d in tasks}
    sensors = {d: mock_sensors(world, scenario, d) for d in tasks}
    agents: dict[str, DroneAgent] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(len(tasks))
    start = world.clock.now()

    def body(drone: str) -> None:
        with world.clock.participate():
            try:
                barrier.wait()                    # every agent on the timeline before time moves
                agent = DroneAgent(scenario.brief(), sensors[drone], executors[drone],
                                   RulePolicy(altitude_m=heights[drone]))
                agent.assign(tasks[drone])
                agent.run(max_s=MAX_FLIGHT_S)
                agents[drone] = agent
            except BaseException as exc:          # recorded, never silent
                errors[drone] = exc

    threads = [threading.Thread(target=body, args=(d,), name=f"{d}-agent") for d in tasks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for e in executors.values():
        e.close()
    if errors:
        drone, exc = next(iter(errors.items()))
        raise RuntimeError(f"{drone}'s agent raised: {type(exc).__name__}: {exc}") from exc
    trajectories = mock_trajectories(world, drones)
    report = evaluate(scenario, trajectories, start, world.clock.now(), contacts=world.contacts())
    skills = {d: tuple((e.command.skill.value, "running" if e.running else
                        (e.result.status.value if e.result is not None else "error"))
                       for e in executors[d].history()) for d in tasks}
    return TeamAgentRun(label, scenario.random_seed, tasks, report,
                        {d: tuple(a.trace) for d, a in agents.items()},
                        {d: a.finished for d, a in agents.items()}, skills, start, trajectories)


# ------------------------------------------------------------------- live

FIRST_POLL_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class LiveAgentFlight:
    """One live flight of the agent: what it decided, and the polls it is judged on."""

    scenario: Scenario
    task: str
    samples: dict[str, list[tuple[float, float, float, float]]]
    grounds: dict[str, float]
    contacts: tuple[Contact, ...]
    start: float
    end: float
    poll_hz: float
    trace: tuple[TraceEntry, ...] = ()
    trace_json: tuple[dict[str, Any], ...] = ()                  # for a flight read back from a record
    finished: bool = False
    progress: dict[str, Any] = field(default_factory=dict)
    skills: tuple[tuple[str, str], ...] = ()
    faults_struck: tuple[tuple[str, str], ...] = ()
    layout: dict[str, Any] = field(default_factory=dict)
    monitor: dict[str, Any] = field(default_factory=dict)

    @property
    def observer(self) -> str:
        return f"polled-{self.poll_hz:g}Hz"

    def trajectories(self) -> dict[str, Trajectory]:
        return trajectories_from_samples(self.samples, self.grounds)

    def judge(self, seed: int | None = None) -> MissionReport:
        """The flight against `seed`'s targets (default: the scenario's own).

        Valid for any seed with this policy: it reacts to a sighting only by
        carrying on, so the path it flies does not depend on where the
        targets are -- though the events in its trace do.
        """
        scenario = self.scenario if seed is None else dataclasses.replace(self.scenario, random_seed=seed)
        return evaluate(scenario, self.trajectories(), self.start, self.end,
                        contacts=self.contacts, observer=self.observer)

    def as_run(self, label: str) -> AgentRun:
        """The flight as an AgentRun, so the same checks apply live as on the mock."""
        return AgentRun(label, self.scenario.random_seed, self.task, self.judge(), self.trace, self.finished,
                        dict(self.progress), self.skills, self.trajectories())

    def as_json(self) -> dict[str, Any]:
        t0 = self.start
        return {
            "kind": "flight", "scenario": self.scenario.scenario_id, "task": self.task,
            "observer": self.observer, "poll_hz": self.poll_hz, "duration_s": round(self.end - t0, 3),
            "finished": self.finished, "progress": self.progress, "skills": [list(s) for s in self.skills],
            "faults_struck": [list(f) for f in self.faults_struck],
            "grounds": {d: round(g, 3) for d, g in self.grounds.items()},
            "layout": self.layout, "monitor": self.monitor,
            "contacts": [{"drone": c.drone, "object": c.object, "at_s": round(c.at - t0, 3)} for c in self.contacts],
            "trace": [e.as_json() for e in self.trace] if self.trace else list(self.trace_json),
            "samples": {d: [[round(t - t0, 3), round(x, 3), round(y, 3), round(z, 3)] for t, x, y, z in rows]
                        for d, rows in self.samples.items()},
        }

    @classmethod
    def from_json(cls, row: dict[str, Any], scenario: Scenario) -> "LiveAgentFlight":
        """A saved flight, its times from 0, ready to be judged again (its trace kept as data)."""
        if row.get("kind") != "flight" or row["scenario"] != scenario.scenario_id:
            raise ValueError("not a flight of this scenario")
        return cls(scenario, row["task"], {d: [tuple(r) for r in rows] for d, rows in row["samples"].items()},
                   dict(row["grounds"]),
                   tuple(Contact(c["drone"], c["object"], c["at_s"]) for c in row["contacts"]),
                   0.0, row["duration_s"], row["poll_hz"], (), tuple(row["trace"]), row["finished"],
                   dict(row["progress"]), tuple(tuple(s) for s in row["skills"]),
                   tuple(tuple(f) for f in row.get("faults_struck", [])), row.get("layout", {}),
                   row.get("monitor", {}))


def fly_agent_live(scenario: Scenario, task: str, scene: Any, connect: Callable[[], Any], clock: Clock,
                   poll_hz: float = DEFAULT_POLL_HZ, fault_once: bool = False,
                   settle_s: float = RESET_SETTLE_S) -> LiveAgentFlight:
    """Reset, place, wait for rest, then run the agent on its task, live, and keep what was seen.

    The agent runs on the calling thread on the real clock. Every skill
    flies on its own thread on its own connection; the poller and the
    separation monitor have theirs; the agent aborts through its own. With
    `fault_once`, the first horizontal move the skills send is refused once,
    in our code (`FaultyAdapter`), never in the simulator.
    """
    drones = check_live_pads(scenario)
    if len(drones) != 1:
        raise ValueError("fly_agent_live flies one agent; the scenario has " + ", ".join(drones))
    (drone,) = drones
    scene.reset()
    clock.sleep(settle_s)
    scene.confirm_connection()
    layout = ensure_vehicles(scene, drones, settle=clock.sleep)
    layout["at_rest_s"] = wait_at_rest(scene, drones, clock)
    grounds = {d: scene.get_pose(d).z for d in drones}             # at rest: TAKE_OFF's own reading
    faults = PassingFaults({(drone, PrimitiveKind.MOVE_TO_POSITION): 1}) if fault_once else None

    def skill_connection() -> Any:
        adapter = connect()
        return FaultyAdapter(adapter, faults) if faults is not None else adapter

    observer = PollingObserver(connect, drones, grounds, clock=clock, hz=poll_hz)
    monitor = SeparationMonitor(connect(), drones)
    observer.start()
    monitor.start()
    monitor_t0 = clock.now()
    began = clock.now()
    while not all(observer.samples().get(d) for d in drones):      # the first poll, before anything reads
        if clock.now() - began > FIRST_POLL_TIMEOUT_S:
            observer.stop()
            monitor.stop()
            raise RuntimeError(f"no poll of {drones} within {FIRST_POLL_TIMEOUT_S:g} s")
        clock.sleep(0.05)
    executor = ActionExecutor(SkillRunner(skill_connection(), drone, clock), clock,
                              abort_via=connect(), connect=skill_connection)
    sensors = polled_sensors(observer, scenario, drone, grounds)
    agent = DroneAgent(scenario.brief(), sensors, executor, RulePolicy())
    start = clock.now()
    try:
        agent.assign(task)
        agent.run(max_s=MAX_FLIGHT_S)
    finally:
        executor.close()
        end = clock.now()
        watched = monitor.stop()
        observer.stop()
    contacts = tuple(Contact(c["drone"], c["object"], monitor_t0 + c["first_at_s"])
                     for c in watched.get("collisions_polled", []))
    skills = tuple((e.command.skill.value, "running" if e.running else
                    (e.result.status.value if e.result is not None else "error")) for e in executor.history())
    summary = {k: watched.get(k) for k in ("samples", "min_separation_m", "per_pair_min_m")}
    return LiveAgentFlight(scenario, task, observer.samples(), grounds, contacts, start, end, poll_hz,
                           tuple(agent.trace), (), agent.finished, dict(agent.belief.mission.progress), skills,
                           tuple(faults.struck) if faults is not None else (),
                           {"added": layout.get("added", []), "layout": layout.get("layout", {}),
                            "at_rest_s": layout.get("at_rest_s", {})}, summary)
