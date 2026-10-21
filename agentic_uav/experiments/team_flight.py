"""A team of drones flying skill sequences at once, and Phase 3's exit plan.

Phase 3's exit criterion (AUV-04): "a deterministic script makes four drones
take off, navigate to distinct waypoints, hold, return and land -- and each
skill returns a structured result rather than merely printing output."

`exit_plan()` is that script's plan, fixed: no model, no randomness.
`fly_team()` flies any such plan, one thread per drone, each on its own
adapter (one connection per thread, as Phase 1 measured AirSim needs), all on
one clock -- the world's simulated clock for the mock, real time for AirSim.
Every skill's `SkillResult` is kept; nothing is only printed.

THE PLAN, sized like the M09 and M10 legs Phase 1 flew safely: four drones
spawned 4 m apart along +x, climbing to 12, 16, 20 and 24 m -- 4 m apart
vertically -- then each 20 m straight out sideways to its own waypoint,
alternating sides (Drone1 and Drone3 to -y, Drone2 and Drone4 to +y), turning
to face the way it went, holding 5 s, flying home at its own height and
landing. No two tracks cross: neighbours start 4 m apart and diverge. A first
version fanned the drones forward and let Drone1, at 12 m, pass 2.4 m
sideways from Drone2 while Drone2 was still climbing -- 3.5 m apart on the
mock, and in CarlaAir's different timing exactly the kind of crossing that
made M10's contact.

SAFETY ON FAILURE. A drone whose skill does not succeed does not carry on: it
runs EMERGENCY_HOLD and then LAND, and the skills it did not reach are
recorded as skipped. A drone is never left flying because a script stopped.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..control.navigation import Waypoint
from ..control.skills import (
    EmergencyHoldCommand,
    GoToWaypointCommand,
    HoldPositionCommand,
    LandCommand,
    ReturnHomeCommand,
    SkillCommand,
    SkillResult,
    SkillRunner,
    TakeOffCommand,
)
from ..core.clock import Clock, SimClock
from ..simulator.adapter import VehicleAdapter
from ..simulator.scenario_manager import SPACING

EXIT_DRONES = ("Drone1", "Drone2", "Drone3", "Drone4")
EXIT_ALTITUDES_M = (12.0, 16.0, 20.0, 24.0)
EXIT_SIDEWAYS_M = (-20.0, 20.0, -20.0, 20.0)     # y of each waypoint
EXIT_HEADINGS_DEG = (-90.0, 90.0, -90.0, 90.0)    # facing the way it went
EXIT_HOLD_S = 5.0


@dataclass(frozen=True)
class DroneMission:
    drone: str
    commands: tuple[SkillCommand, ...]


@dataclass(frozen=True)
class SkillRecord:
    """One skill of one drone: what was asked, and what came back."""

    drone: str
    index: int
    command: SkillCommand
    result: SkillResult | None          # None: skipped after an earlier failure
    safety: bool = False                # True for the hold-and-land after a failure

    def as_json(self) -> dict[str, Any]:
        from dataclasses import asdict
        command = {k: v for k, v in asdict(self.command).items()}
        return {"drone": self.drone, "index": self.index, "skill": self.command.skill.value,
                "command": command, "safety": self.safety, "skipped": self.result is None,
                "result": None if self.result is None else self.result.as_json()}


def exit_plan(drones: tuple[str, ...] = EXIT_DRONES) -> list[DroneMission]:
    """Phase 3's exit plan: take off, distinct waypoint, hold, home, land."""
    missions = []
    for i, drone in enumerate(drones):
        altitude = EXIT_ALTITUDES_M[i]
        waypoint = Waypoint(i * SPACING, EXIT_SIDEWAYS_M[i], altitude)
        missions.append(DroneMission(drone, (
            TakeOffCommand(altitude_m=altitude),
            GoToWaypointCommand(waypoint, heading_deg=EXIT_HEADINGS_DEG[i]),
            HoldPositionCommand(EXIT_HOLD_S),
            ReturnHomeCommand(),
            LandCommand(),
        )))
    return missions


def fly_team(missions: list[DroneMission], connect: Callable[[], VehicleAdapter],
             clock: Clock) -> dict[str, list[SkillRecord]]:
    """Fly every mission at once, one thread and one adapter per drone.

    With a `SimClock`, every drone thread participates in its timeline, so
    the team shares simulated time and the run is deterministic.
    """
    records: dict[str, list[SkillRecord]] = {m.drone: [] for m in missions}
    errors: dict[str, BaseException] = {}
    start = threading.Barrier(len(missions))

    def fly(mission: DroneMission) -> None:
        sim = isinstance(clock, SimClock)
        with (clock.participate() if sim else contextlib.nullcontext()):
            try:
                start.wait()
                runner = SkillRunner(connect(), mission.drone, clock)
                _fly_one(runner, mission, records[mission.drone])
            except BaseException as exc:          # recorded, never silent
                errors[mission.drone] = exc

    threads = [threading.Thread(target=fly, args=(m,), name=m.drone) for m in missions]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        drone, exc = next(iter(errors.items()))
        raise RuntimeError(f"{drone}'s flight thread raised: {type(exc).__name__}: {exc}") from exc
    return records


def _fly_one(runner: SkillRunner, mission: DroneMission, out: list[SkillRecord]) -> None:
    for index, command in enumerate(mission.commands):
        result = runner.run(command)
        out.append(SkillRecord(mission.drone, index, command, result))
        if result.ok:
            continue
        for later, skipped in enumerate(mission.commands[index + 1:], start=index + 1):
            out.append(SkillRecord(mission.drone, later, skipped, None))
        if command.skill.value != "TAKE_OFF" or runner.home is not None:
            for safety in (EmergencyHoldCommand(), LandCommand()):
                out.append(SkillRecord(mission.drone, len(out), safety, runner.run(safety), True))
        return


def verdict(records: dict[str, list[SkillRecord]]) -> tuple[bool, str]:
    """Whether the run meets Phase 3's exit criterion, and why not if not."""
    problems = []
    for drone, rs in records.items():
        planned = [r for r in rs if not r.safety]
        if any(r.result is None for r in planned):
            problems.append(f"{drone}: skills skipped after a failure")
        for r in planned:
            if r.result is not None and not r.result.ok:
                problems.append(f"{drone}: {r.command.skill.value} {r.result.status.value} "
                                f"({r.result.error_code.value if r.result.error_code else ''}) "
                                f"{r.result.message}")
            if r.result is not None and not isinstance(r.result, SkillResult):
                problems.append(f"{drone}: an unstructured result")
    if len(records) != 4:
        problems.append(f"{len(records)} drones, not four")
    return (not problems, "; ".join(problems) or "every skill of every drone succeeded "
                                                 "and returned a structured result")
