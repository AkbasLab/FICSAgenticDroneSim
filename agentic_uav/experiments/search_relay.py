"""Fly the scripted controller on a scenario and judge it: Phase 4's exit (AUV-05).

    run = fly_on_mock(scenario)            # one flight, one MissionReport
    runs = exit_runs(scenario)             # EXIT_SEEDS, one flight each
    flight = fly_live(scenario, scene, connect, clock)    # CarlaAir, once
    reports = [flight.judge(s) for s in EXIT_SEEDS]       # that flight, every layout

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

LIVE (Phase 4, step 5): one flight in CarlaAir, observed by polling, can be
judged against every seed. That is not a shortcut: the controller never sees
the targets, so the path it flies is the same whatever they are, and judging
one recorded flight against 20 layouts is the same as flying it 20 times.
What a live flight adds is the simulator -- its drift, its timing, its
contacts -- so repeats measure that, not target layouts. `LiveFlight` keeps
the raw polls and each drone's measured ground, so a saved flight can be
judged again later against any seeds.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ..control.monitor import SeparationMonitor
from ..control.scripted import DronePlan, plan_mission
from ..core.clock import Clock
from ..core.scenario import Scenario
from ..core.models import Position
from ..simulator.mock_adapter import MockVehicleAdapter, MockWorld
from ..simulator.observer import DEFAULT_POLL_HZ, PollingObserver, mock_trajectories, trajectories_from_samples
from ..simulator.scenario_manager import SPACING, ensure_vehicles
from ..simulator.trajectory import Trajectory
from .evaluation import Contact, MissionReport, evaluate
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


# ------------------------------------------------------------------- live

RESET_SETTLE_S = 2.0          # as scenario_manager.reset_world waits


def plan_json(plan: dict[str, DronePlan]) -> dict[str, Any]:
    return {d: {"sectors": list(p.sectors), "altitude_m": p.altitude_m,
                "lane_spacing_m": round(p.lane_spacing_m, 3), "length_m": round(p.length_m, 1),
                "estimated_s": round(p.estimated_s, 1),
                "estimated_battery_used": round(p.estimated_battery_used, 2),
                "searched": [[r.x_min, r.y_min, r.x_max, r.y_max] for r in p.searched],
                "path": [[round(x, 3), round(y, 3)] for x, y in p.path],
                "skills": [c.skill.value for c in p.commands]} for d, p in plan.items()}


def skills_json(records: dict[str, list[SkillRecord]]) -> dict[str, list[dict[str, Any]]]:
    return {d: [{"index": r.index, "skill": r.command.skill.value, "safety": r.safety,
                 "status": None if r.result is None else r.result.status.value,
                 "seconds": None if r.result is None else round(r.result.ended_at - r.result.started_at, 3)}
                for r in rs] for d, rs in sorted(records.items())}


@dataclass(frozen=True)
class LiveFlight:
    """One live flight, before judging: everything any seed is judged on."""

    scenario: Scenario
    plan: dict[str, DronePlan]
    skills: dict[str, list[dict[str, Any]]]
    skills_ok: bool
    samples: dict[str, list[tuple[float, float, float, float]]]
    grounds: dict[str, float]
    contacts: tuple[Contact, ...]
    start: float
    end: float
    poll_hz: float
    layout: dict[str, Any] = field(default_factory=dict)
    monitor: dict[str, Any] = field(default_factory=dict)

    @property
    def observer(self) -> str:
        return f"polled-{self.poll_hz:g}Hz"

    def trajectories(self) -> dict[str, Trajectory]:
        return trajectories_from_samples(self.samples, self.grounds)

    def judge(self, seed: int) -> MissionReport:
        scenario = dataclasses.replace(self.scenario, random_seed=seed)
        return evaluate(scenario, self.trajectories(), self.start, self.end,
                        contacts=self.contacts, observer=self.observer)

    def met(self, report: MissionReport) -> bool:
        return report.success and self.skills_ok

    def as_json(self) -> dict[str, Any]:
        """The flight as a record row: times from its start, metres to the millimetre."""
        t0 = self.start
        return {
            "kind": "flight", "scenario": self.scenario.scenario_id, "observer": self.observer,
            "poll_hz": self.poll_hz, "duration_s": round(self.end - t0, 3),
            "skills_ok": self.skills_ok, "skills": self.skills, "plan": plan_json(self.plan),
            "grounds": {d: round(g, 3) for d, g in self.grounds.items()},
            "layout": self.layout, "monitor": self.monitor,
            "contacts": [{"drone": c.drone, "object": c.object, "at_s": round(c.at - t0, 3)}
                         for c in self.contacts],
            "samples": {d: [[round(t - t0, 3), round(x, 3), round(y, 3), round(z, 3)] for t, x, y, z in rows]
                        for d, rows in self.samples.items()},
        }

    @classmethod
    def from_json(cls, row: dict[str, Any], scenario: Scenario) -> "LiveFlight":
        """A saved flight, its times counted from 0, ready to be judged again."""
        if row.get("kind") != "flight":
            raise ValueError("not a flight row")
        if row["scenario"] != scenario.scenario_id:
            raise ValueError(f"the flight was of {row['scenario']}, not {scenario.scenario_id}")
        return cls(scenario, plan_mission(scenario.brief()), row["skills"], row["skills_ok"],
                   {d: [tuple(r) for r in rows] for d, rows in row["samples"].items()},
                   dict(row["grounds"]),
                   tuple(Contact(c["drone"], c["object"], c["at_s"]) for c in row["contacts"]),
                   0.0, row["duration_s"], row["poll_hz"], row.get("layout", {}), row.get("monitor", {}))


def measured_grounds(records: dict[str, list[SkillRecord]],
                     samples: dict[str, list[tuple[float, float, float, float]]]) -> dict[str, float]:
    """Each drone's ground as its TAKE_OFF measured it; its first resting poll if it never did."""
    grounds = {}
    for drone, rows in samples.items():
        measured = None
        for r in records.get(drone, []):
            if r.result is not None and "ground_z" in r.result.details:
                measured = float(r.result.details["ground_z"])
                break
        if measured is None and rows:
            measured = rows[0][3]
        if measured is not None:
            grounds[drone] = measured
    return grounds


def check_live_pads(scenario: Scenario) -> list[str]:
    """The drones in spawn order, if the scenario's pads are the live spawn layout.

    Live, `ensure_vehicles` puts drone i at (i x SPACING, 0); a scenario whose
    pads are elsewhere would take off from the wrong places.
    """
    drones = sorted(scenario.vehicles, key=lambda v: v.id)
    wrong = [f"{v.id} at ({v.start_x:g}, {v.start_y:g}), not ({i * SPACING:g}, 0)"
             for i, v in enumerate(drones) if (v.start_x, v.start_y) != (i * SPACING, 0.0)]
    if wrong:
        raise ValueError("a live flight needs the pads to be the spawn layout: " + "; ".join(wrong))
    return [v.id for v in drones]


def fly_live(scenario: Scenario, scene: Any, connect: Callable[[], Any], clock: Clock,
             poll_hz: float = DEFAULT_POLL_HZ, settle_s: float = RESET_SETTLE_S) -> LiveFlight:
    """Reset the scene, place the drones, fly the plan once, and keep what was seen.

    The flight threads, the observer and the separation monitor each have
    their own connection (Phase 1: one per thread).
    """
    drones = check_live_pads(scenario)
    plan = plan_mission(scenario.brief())
    scene.reset()
    clock.sleep(settle_s)
    scene.confirm_connection()
    layout = ensure_vehicles(scene, drones, settle=clock.sleep)
    observer = PollingObserver(connect, drones, clock=clock, hz=poll_hz)
    monitor = SeparationMonitor(connect(), drones)
    observer.start()
    monitor.start()
    monitor_t0 = clock.now()                 # the monitor's contact times count from here
    start = clock.now()
    try:
        records = fly_team([DroneMission(d, plan[d].commands) for d in drones], connect, clock)
    finally:
        end = clock.now()
        watched = monitor.stop()
        observer.stop()
    samples = observer.samples()
    contacts = tuple(Contact(c["drone"], c["object"], monitor_t0 + c["first_at_s"])
                     for c in watched.get("collisions_polled", []))
    skills_ok = all(r.result is not None and r.result.ok and not r.safety
                    for rs in records.values() for r in rs)
    summary = {k: watched.get(k) for k in ("samples", "min_separation_m", "per_pair_min_m")}
    return LiveFlight(scenario, plan, skills_json(records), skills_ok, samples,
                      measured_grounds(records, samples), contacts, start, end, poll_hz,
                      {"added": layout.get("added", []), "layout": layout.get("layout", {})}, summary)


def compare_to_mock(flight: LiveFlight, mock: ScriptedRun) -> dict[str, Any]:
    """How the live flight differed from the mock flight of the same plan and seed."""
    trajs = flight.trajectories()
    out: dict[str, Any] = {"drones": {}}
    for drone, plan in flight.plan.items():
        traj = trajs.get(drone)
        if traj is None:
            continue
        flying = [k for k in traj.knots if k.airborne and flight.start <= k.t <= flight.end]
        off = [distance_to_path((k.x, k.y), plan.path) for k in flying]
        # Cruise: from the first poll within 0.5 m of the planned height to the
        # last, so the climb and the descent are not counted as height error.
        near = [i for i, k in enumerate(flying) if abs(k.altitude_m - plan.altitude_m) <= 0.5]
        level = ([abs(k.altitude_m - plan.altitude_m) for k in flying[near[0]:near[-1] + 1]]
                 if near else [])
        last, pad = traj.knots[-1], plan.path[0]
        out["drones"][drone] = {
            "max_off_track_m": round(max(off), 2) if off else None,
            "median_off_track_m": round(sorted(off)[len(off) // 2], 2) if off else None,
            "max_height_error_at_cruise_m": round(max(level), 2) if level else None,
            "pad_error_m": round(math.hypot(last.x - pad[0], last.y - pad[1]), 2),
            "samples": len(traj.knots),
        }
    live = flight.judge(mock.seed)
    out["completion_s"] = {"live": None if live.completion_s is None else round(live.completion_s, 1),
                           "mock": None if mock.report.completion_s is None else round(mock.report.completion_s, 1)}
    out["coverage"] = {"live": round(live.coverage.fraction, 4), "mock": round(mock.report.coverage.fraction, 4)}
    out["closest_pair_m"] = {"live": live.components["min_separation_m"],
                             "mock": mock.report.components["min_separation_m"]}
    mock_used = {b.drone: b.used for b in mock.report.facts.batteries}
    out["battery_used"] = {b.drone: {"live": round(b.used, 2), "mock": round(mock_used[b.drone], 2),
                                     "estimated": round(flight.plan[b.drone].estimated_battery_used, 2)}
                           for b in live.facts.batteries}
    return out


def distance_to_path(p: tuple[float, float], path: tuple[tuple[float, float], ...]) -> float:
    """Horizontal distance from `p` to the nearest point of a polyline."""
    best = math.inf
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = dx * dx + dy * dy
        f = 0.0 if span == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
        best = min(best, math.hypot(p[0] - a[0] - f * dx, p[1] - a[1] - f * dy))
    return best
