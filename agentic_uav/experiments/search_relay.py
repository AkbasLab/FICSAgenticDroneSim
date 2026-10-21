"""Fly the scripted controller on a scenario and judge it: Phase 4's exit (AUV-05).

    run = fly_on_mock(scenario)            # one flight, one MissionReport
    runs = exit_runs(scenario)             # EXIT_SEEDS, one flight each

The controller is handed `scenario.brief()` and nothing else; the mission
world knows the targets; the evaluator judges the flight from the world's
facts. Each flight is a fresh mock world: drones on their pads, simulated
time from zero, every drone on its own thread and adapter as in Phase 3.

THE EXIT runs EXIT_SEEDS, fixed here before any was flown: seeds 1-20, which
include the canonical 17. The plan does not depend on the seed -- the
controller never sees it -- so what varies is where the targets are, and the
question each seed asks is whether the fixed plan finds, reports and gets
home from that layout. A run meets the exit when the mission succeeds AND
every planned skill succeeded: a mission rescued by a safety landing is not
a scripted controller completing it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Callable

from ..control.scripted import DronePlan, plan_mission
from ..core.scenario import Scenario
from ..core.models import Position
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld
from ..simulator.observer import mock_trajectories
from ..simulator.trajectory import Trajectory
from .evaluation import MissionReport, evaluate
from .team_flight import DroneMission, SkillRecord, fly_team

EXIT_SEEDS = tuple(range(1, 21))


@dataclass(frozen=True)
class ScriptedRun:
    seed: int
    plan: dict[str, DronePlan]
    records: dict[str, list[SkillRecord]]
    report: MissionReport
    trajectories: dict[str, Trajectory] = field(default_factory=dict, repr=False)

    @property
    def skills_ok(self) -> bool:
        return all(r.result is not None and r.result.ok and not r.safety
                   for rs in self.records.values() for r in rs)

    @property
    def met(self) -> bool:
        return self.report.success and self.skills_ok

    def as_json(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "met": self.met,
            "skills_ok": self.skills_ok,
            "report": self.report.as_json(),
            "plan": {d: {"sectors": list(p.sectors), "altitude_m": p.altitude_m,
                         "lane_spacing_m": round(p.lane_spacing_m, 3), "length_m": round(p.length_m, 1),
                         "estimated_s": round(p.estimated_s, 1),
                         "estimated_battery_used": round(p.estimated_battery_used, 2),
                         "skills": [c.skill.value for c in p.commands]}
                     for d, p in self.plan.items()},
            "skills": {d: [{"index": r.index, "skill": r.command.skill.value, "safety": r.safety,
                            "status": None if r.result is None else r.result.status.value,
                            "seconds": None if r.result is None else
                            round(r.result.ended_at - r.result.started_at, 3)}
                           for r in rs] for d, rs in sorted(self.records.items())},
        }


def mock_world_for(scenario: Scenario) -> MockWorld:
    """A fresh mock with the scenario's drones resting on their pads."""
    world = MockWorld(declared=[v.id for v in scenario.vehicles])
    scene = MockVehicleAdapter(world)
    for v in scenario.vehicles:
        scene.place_vehicle(v.id, Position(v.start_x, v.start_y, world.ground_z))
    return world


def fly_on_mock(scenario: Scenario, prepare: Callable[[MockWorld], None] | None = None) -> ScriptedRun:
    """One flight. `prepare` may set up the world first -- inject a fault, in tests."""
    plan = plan_mission(scenario.brief())
    world = mock_world_for(scenario)
    if prepare is not None:
        prepare(world)
    missions = [DroneMission(d, p.commands) for d, p in plan.items()]
    start = world.clock.now()
    records = fly_team(missions, lambda: MockVehicleAdapter(world), world.clock)
    end = world.clock.now()
    trajectories = mock_trajectories(world, list(plan))
    report = evaluate(scenario, trajectories, start, end, contacts=world.contacts(), observer="mock-exact")
    return ScriptedRun(scenario.random_seed, plan, records, report, trajectories)


def exit_runs(scenario: Scenario, seeds: tuple[int, ...] = EXIT_SEEDS) -> list[ScriptedRun]:
    return [fly_on_mock(dataclasses.replace(scenario, random_seed=s)) for s in seeds]
