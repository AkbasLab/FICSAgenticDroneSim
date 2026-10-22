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
from ..control.skills import SkillRunner
from ..core.events import Trigger
from ..core.models import Position, PrimitiveKind
from ..core.scenario import BatterySpec, Scenario
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld
from ..simulator.observer import mock_trajectories
from ..simulator.sensing import mock_sensors
from ..simulator.trajectory import Trajectory
from .evaluation import MissionReport, evaluate
from .search_relay import EXIT_SEEDS

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
