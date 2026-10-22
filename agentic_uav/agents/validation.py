"""The lifecycle's "Validate" step: refuse a decision that breaks a hard rule (AUV-06, 5.1).

    verdict = validate(decision, belief)          # Verdict(ok, reasons)

AUV-06 puts a guardian "between decision and execution, always". The
guardian proper -- independent, with four outcomes and five fallbacks -- is
Phase 11's (AUV-11). Phase 5 needs the step to exist, so that a refusal is a
real event the agent must handle (GUARD_REJECTED), and checks two rules
that need nothing but the belief:

* NO RESTRICTED ZONE. The ground track the skill would fly -- from where the
  drone is, through the skill's waypoints -- must not touch a restricted
  zone. Clearance is the planner's business; this is the hard line.
* HOME ON WHAT IS LEFT. After flying the skill and then straight home, the
  battery must still be at or above the reserve, by the brief's own model.
  A skill that heads home or holds (RETURN_HOME, LAND, HOLD_POSITION,
  EMERGENCY_HOLD) is always allowed: refusing the way home would be worse
  than the risk it avoids.

Heights and speeds are already checked when a command is built.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..control import navigation as nav
from ..control.skills import (
    FollowWaypointsCommand,
    GoToWaypointCommand,
    InspectPointCommand,
    RendezvousCommand,
    ActAsRelayCommand,
    SearchRegionCommand,
    SkillCommand,
    SkillName,
)
from .belief_state import BeliefState
from .decision import Decision, DecisionKind

ALWAYS_ALLOWED = frozenset({SkillName.RETURN_HOME, SkillName.LAND, SkillName.HOLD_POSITION,
                            SkillName.EMERGENCY_HOLD, SkillName.TAKE_OFF})
ESTIMATE_SPEED_MPS = 5.0          # the skills' default cruise; the estimate's only speed


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[str, ...] = ()


def ground_track(command: SkillCommand, here: tuple[float, float]) -> list[tuple[float, float]]:
    """The points the skill flies through, from `here`, on the ground (x, y)."""
    if isinstance(command, GoToWaypointCommand | RendezvousCommand | ActAsRelayCommand):
        points = [(command.waypoint.x, command.waypoint.y)]
    elif isinstance(command, FollowWaypointsCommand):
        points = [(w.x, w.y) for w in command.waypoints]
    elif isinstance(command, SearchRegionCommand):
        points = [(w.x, w.y) for w in nav.lawnmower(command.region, command.spacing_m, command.altitude_m)]
    elif isinstance(command, InspectPointCommand):
        points = [(command.target.x, command.target.y)]
    else:
        points = []
    return [here] + points


def validate(decision: Decision, belief: BeliefState) -> Verdict:
    if decision.kind is not DecisionKind.START or decision.command is None:
        return Verdict(True)
    command = decision.command
    if command.skill in ALWAYS_ALLOWED:
        return Verdict(True)
    me = belief.self_
    track = ground_track(command, (me.x, me.y))
    reasons = []
    for zone in belief.brief.restricted_zones:
        for a, b in zip(track, track[1:]):
            if zone.polygon.crosses(a, b):
                reasons.append(f"the path {a} -> {b} enters restricted zone {zone.id}")
                break
    flown = sum(math.dist(a, b) for a, b in zip(track, track[1:]))
    home = math.dist(track[-1], me.home)
    battery = belief.brief.battery
    seconds = (flown + home) / ESTIMATE_SPEED_MPS
    cost = battery.hover_drain_per_s * seconds + battery.move_drain_per_m * (flown + home)
    if me.battery - cost < battery.reserve:
        reasons.append(f"{me.battery:.1f} % left, about {cost:.1f} % to fly this and home: "
                       f"under the {battery.reserve:g} % reserve")
    return Verdict(not reasons, tuple(reasons))
