"""One mission report from one flight: AUV-05's success criteria, each with its number (4.3).

    report = evaluate(scenario, trajectories, start, end, contacts=world.contacts())
    report.success            # all six criteria
    report.summary()          # one line per criterion
    report.as_json()          # the record, facts included

AUV-05 4.3, for the first version, success requires ALL of:

  C1  all required sectors searched, or the coverage threshold reached
  C2  all targets detected
  C3  detections reported to base, or eventually synchronized
  C4  no restricted-region entry
  C5  no collision or separation violation
  C6  all functioning drones return safely

Each is decided from `mission_world` facts, never from what the controller
says about itself: a controller that believes it searched a sector has not
thereby searched it. The definitions:

* THE WINDOW is the flight from `start` to the deadline (`deadline_s`) or
  the end of the record, whichever is first. Anything after the deadline did
  not happen in time and is not counted -- including landing. So success
  includes finishing on time, and there is no separate deadline criterion.
* C1: coverage of the searchable area (`simulator/coverage.py`: a point is
  searched once a target there would have been detected) at least
  `required_coverage`. Coverage is the scenario's chosen form of "searched".
* C2: at least `targets_to_find` distinct targets detected, by any drone.
* C3: at least `targets_to_find` distinct targets reported: some drone that
  detected it was later connected to the base, directly or relayed.
* C4: no zone entered by any drone.
* C5: no contact with another drone or an obstacle, and no pair of drones
  closer than `min_separation_m` while one flew. A ground contact is a
  landing; a contact with the spectator camera is someone watching
  (`control.contacts.classify_contact`). Neither is a collision; camera
  contacts are counted in the components.
* C6: every functioning drone (not in `failed`; Phase 4 fails none) ends the
  window landed, within RETURN_RADIUS_M of its own start, with its battery
  at or above the reserve and never run flat. "Return" is to its pad: the
  base is a radio, and the pads are where the drones take off and land.

COMPLETION TIME (AUV-14's T_completion) is when the last criterion that
takes time was met: coverage reached the threshold, the last target needed
was reported, the last functioning drone landed. A failed mission has none
-- it is recorded as failed, never as a fast completion.

PARTIAL SCORES (AUV-05: "can later be relaxed") are reported as components
-- coverage, detection, reporting, safe return, and the safety counts -- and
NOT combined. AUV-14 sketches MissionScore = w1 Coverage + w2 Detection +
w3 SafeReturn but sets no weights, and Phase 15's rule is that no metric is
invented after the results are seen; the weights are Phase 15's to fix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..control.contacts import classify_contact
from ..core.scenario import Scenario
from ..simulator.coverage import DEFAULT_CELL_M, Coverage, coverage
from ..simulator.mission_world import MissionFacts, Target, observe
from ..simulator.trajectory import Trajectory

RETURN_RADIUS_M = 2.0       # half the 4 m pad spacing: which pad a drone is on is never ambiguous

CRITERIA = (
    ("C1", "coverage threshold reached"),
    ("C2", "all targets detected"),
    ("C3", "detections reported to base, or eventually synchronized"),
    ("C4", "no restricted-region entry"),
    ("C5", "no collision or separation violation"),
    ("C6", "all functioning drones return safely"),
)


@dataclass(frozen=True)
class Contact:
    """A collision a simulator reported: `drone` touched `object` at simulated or real time `at`."""

    drone: str
    object: str
    at: float


@dataclass(frozen=True)
class Criterion:
    id: str
    description: str
    passed: bool
    measured: Any
    required: Any
    detail: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "description": self.description, "passed": self.passed,
                "measured": self.measured, "required": self.required, "detail": self.detail}


@dataclass(frozen=True)
class MissionReport:
    scenario_id: str
    random_seed: int
    observer: str                         # how the trajectories were obtained
    start: float
    until: float                          # the window's end: deadline or end of record
    success: bool
    criteria: tuple[Criterion, ...]
    components: dict[str, Any]
    completion_s: float | None            # None: the mission failed
    facts: MissionFacts
    coverage: Coverage = field(repr=False)

    def criterion(self, cid: str) -> Criterion:
        for c in self.criteria:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def summary(self) -> str:
        lines = [f"{self.scenario_id} seed {self.random_seed} [{self.observer}]: "
                 f"{'SUCCESS' if self.success else 'FAILED'}"
                 + (f" in {self.completion_s:.1f} s" if self.completion_s is not None else "")]
        for c in self.criteria:
            lines.append(f"  {'PASS' if c.passed else 'FAIL'}  {c.id} {c.description}: "
                         f"{c.measured} (required {c.required})" + (f" -- {c.detail}" if c.detail else ""))
        return "\n".join(lines)

    def as_json(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "random_seed": self.random_seed,
            "observer": self.observer,
            "window_s": round(self.until - self.start, 3),
            "success": self.success,
            "completion_s": None if self.completion_s is None else round(self.completion_s, 3),
            "criteria": [c.as_json() for c in self.criteria],
            "components": self.components,
            "coverage": {"cell_m": self.coverage.cell_m, "cells": self.coverage.cells,
                         "fraction": round(self.coverage.fraction, 6),
                         "by_sector": {k: round(v, 6) for k, v in self.coverage.by_sector.items()}},
            "facts": self.facts.as_json(),
        }


def as_contacts(raw: Iterable[Any]) -> list[Contact]:
    """Contacts from `MockWorld.contacts()` rows ({drone, object, at_s}) or `Contact`s."""
    out = []
    for c in raw:
        out.append(c if isinstance(c, Contact) else Contact(c["drone"], c["object"], float(c["at_s"])))
    return out


def evaluate(scenario: Scenario, trajectories: dict[str, Trajectory] | list[Trajectory],
             start: float, end: float, contacts: Iterable[Any] = (), failed: Iterable[str] = (),
             observer: str = "mock-exact", targets: tuple[Target, ...] | None = None,
             cell_m: float = DEFAULT_CELL_M) -> MissionReport:
    """Judge one flight against `scenario`. See the module docstring for every definition."""
    trajs = list(trajectories.values()) if isinstance(trajectories, dict) else list(trajectories)
    failed = set(failed)
    unknown = failed - {t.drone for t in trajs}
    if unknown:
        raise ValueError(f"failed drones with no trajectory: {sorted(unknown)}")
    until = min(end, start + scenario.mission.deadline_s)
    facts = observe(scenario, trajs, start, until, targets)
    cov = coverage(scenario, trajs, start, until, cell_m)
    need = scenario.mission.targets_to_find

    # C1
    c1 = Criterion("C1", CRITERIA[0][1], cov.fraction >= scenario.mission.required_coverage,
                   round(cov.fraction, 4), scenario.mission.required_coverage,
                   ", ".join(f"{k} {v:.3f}" for k, v in cov.by_sector.items()))

    # C2
    detected = sorted({d.target for d in facts.detections})
    c2 = Criterion("C2", CRITERIA[1][1], len(detected) >= need, len(detected), need,
                   "detected: " + (", ".join(detected) or "none"))

    # C3
    first_reports = {t.id: facts.first_report(t.id) for t in facts.targets}
    reported = {tid: r for tid, r in first_reports.items() if r is not None}
    unreported = [tid for tid in detected if tid not in reported]
    c3 = Criterion("C3", CRITERIA[2][1], len(reported) >= need, len(reported), need,
                   ("reported: " + ", ".join(f"{tid} by {r.drone} at {r.reported_at - start:.1f} s"
                                             for tid, r in sorted(reported.items())) if reported else "none reported")
                   + (f"; detected, never reported: {', '.join(unreported)}" if unreported else ""))

    # C4
    entries = facts.zone_entries
    c4 = Criterion("C4", CRITERIA[3][1], not entries, len(entries), 0,
                   "; ".join(f"{e.drone} entered {e.zone} at {e.at - start:.1f} s ({e.x:.1f}, {e.y:.1f})"
                             for e in entries))

    # C5
    flown = [t.drone for t in trajs]
    in_window = [c for c in as_contacts(contacts) if start <= c.at <= until]
    kinds = [classify_contact(c.object, flown) for c in in_window]
    collisions = [c for c, k in zip(in_window, kinds) if k in ("drone", "obstacle")]
    camera = sum(k == "camera" for k in kinds)
    violations = [(s, v) for s in facts.separations for v in s.violations]
    closest = [s for s in facts.separations if s.min_m is not None]
    nearest = min(closest, key=lambda s: s.min_m) if closest else None
    c5 = Criterion("C5", CRITERIA[4][1], not collisions and not violations,
                   {"collisions": len(collisions), "separation_violations": len(violations)},
                   {"collisions": 0, "separation_violations": 0},
                   "; ".join([f"{c.drone} hit {c.object} at {c.at - start:.1f} s" for c in collisions]
                             + [f"{s.a}-{s.b} under {scenario.safety.min_separation_m} m "
                                f"{v[0] - start:.1f}-{v[1] - start:.1f} s" for s, v in violations])
                   or (f"closest pair {nearest.a}-{nearest.b} {nearest.min_m:.2f} m" if nearest else ""))

    # C6
    functioning = [t for t in trajs if t.drone not in failed]
    batteries = {b.drone: b for b in facts.batteries}
    returned, problems, landings = [], [], []
    for t in functioning:
        why = _not_returned(scenario, t, batteries[t.drone], until)
        if why:
            problems.append(f"{t.drone}: {why}")
        else:
            returned.append(t.drone)
            landings.append(_landed_at(t, start, until))
    c6 = Criterion("C6", CRITERIA[5][1], len(returned) == len(functioning), len(returned), len(functioning),
                   "; ".join(problems) or ", ".join(
                       f"{d} {batteries[d].remaining:.1f}%" for d in returned))

    criteria = (c1, c2, c3, c4, c5, c6)
    success = all(c.passed for c in criteria)
    completion = None
    if success:
        reached = cov.time_to(scenario.mission.required_coverage)
        moments = [start if reached is None else reached]
        report_times = sorted(r.reported_at for r in reported.values())
        if need:
            moments.append(report_times[need - 1])
        moments += [t for t in landings if t is not None]
        completion = max(moments) - start

    components = {
        "coverage": round(cov.fraction, 4),
        "target_detection": round(min(1.0, len(detected) / need), 4) if need else 1.0,
        "reporting": round(min(1.0, len(reported) / need), 4) if need else 1.0,
        "safe_return": round(len(returned) / len(functioning), 4) if functioning else None,
        "zone_entries": len(entries),
        "collisions": len(collisions),
        "camera_contacts": camera,
        "separation_violations": len(violations),
        "min_separation_m": None if nearest is None else round(nearest.min_m, 3),
        "drones_flown": len(trajs),
        "drones_failed": sorted(failed),
    }
    return MissionReport(scenario.scenario_id, scenario.random_seed, observer, start, until, success,
                         criteria, components, completion, facts, cov)


def _not_returned(scenario: Scenario, traj: Trajectory, battery, until: float) -> str:
    """Why `traj`'s drone did not return safely by `until`; empty if it did."""
    reasons = []
    if traj.airborne_at(until):
        reasons.append("still airborne")
    home = scenario.vehicle(traj.drone)
    x, y, _ = traj.position_at(until)
    off = math.hypot(x - home.start_x, y - home.start_y)
    if off > RETURN_RADIUS_M:
        reasons.append(f"{off:.1f} m from its pad")
    if battery.depleted_at is not None:
        reasons.append(f"battery flat at {battery.depleted_at - traj.start:.1f} s")
    elif battery.remaining < battery.reserve:
        reasons.append(f"battery {battery.remaining:.1f}% under the {battery.reserve:g}% reserve")
    return ", ".join(reasons)


def _landed_at(traj: Trajectory, start: float, until: float) -> float | None:
    """The moment the drone last went from flying to landed, within the window."""
    landed = None
    previous = traj.airborne_at(start)
    for k in traj.knots:
        if k.t < start or k.t > until:
            continue
        if previous and not k.airborne:
            landed = k.t
        previous = k.airborne
    return landed
