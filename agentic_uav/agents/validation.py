"""The lifecycle's "Validate" step: refuse a decision that breaks a hard rule (AUV-06, 5.1).

    verdict = validate(decision, belief)          # Verdict(ok, reasons)

AUV-06 puts a guardian "between decision and execution, always". The
guardian proper -- independent, with four outcomes and five fallbacks -- is
Phase 11's (AUV-11). Phase 5 needs the step to exist, so that a refusal is a
real event the agent must handle (GUARD_REJECTED), and checks two rules
that need nothing but the belief:

* NO RESTRICTED ZONE, for every skill that moves. The ground track it would
  fly -- from where the drone is, through its waypoints, or straight home for
  RETURN_HOME -- must not touch a restricted zone. Clearance is the
  planner's business; this is the hard line, and it has no exceptions.
* HOME ON WHAT IS LEFT. After flying the skill and then straight home, the
  battery must still be at or above the reserve, by the brief's own model.
  Waived for a skill that goes home or stays put -- RETURN_HOME, LAND,
  HOLD_POSITION, EMERGENCY_HOLD, TAKE_OFF, or any route that ends at home --
  because refusing the way home would be worse than the risk it avoids.

(Step 3's first version waived BOTH rules for the way home, and traced no
path for RETURN_HOME at all, so a straight line home through a zone would
have passed. Found while writing step 4's policy; fixed there.)

Heights and speeds are already checked when a command is built.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..control import navigation as nav
from ..control.skills import (
    ActAsRelayCommand,
    FollowWaypointsCommand,
    GoToWaypointCommand,
    InspectPointCommand,
    RendezvousCommand,
    ReturnHomeCommand,
    SearchRegionCommand,
    SkillCommand,
    SkillName,
)
from .belief_state import BeliefState
from .decision import Decision, DecisionKind

BATTERY_WAIVED = frozenset({SkillName.RETURN_HOME, SkillName.LAND, SkillName.HOLD_POSITION,
                            SkillName.EMERGENCY_HOLD, SkillName.TAKE_OFF})
HOME_RADIUS_M = 2.0               # a route ending this close to home is the way home
ESTIMATE_SPEED_MPS = 5.0          # the skills' default cruise; the estimate's only speed


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[str, ...] = ()


def ground_track(command: SkillCommand, here: tuple[float, float],
                 home: tuple[float, float] | None = None) -> list[tuple[float, float]]:
    """The points the skill flies through, from `here`, on the ground (x, y)."""
    if isinstance(command, GoToWaypointCommand | RendezvousCommand | ActAsRelayCommand):
        points = [(command.waypoint.x, command.waypoint.y)]
    elif isinstance(command, FollowWaypointsCommand):
        points = [(w.x, w.y) for w in command.waypoints]
    elif isinstance(command, SearchRegionCommand):
        points = [(w.x, w.y) for w in nav.lawnmower(command.region, command.spacing_m, command.altitude_m)]
    elif isinstance(command, InspectPointCommand):
        points = [(command.target.x, command.target.y)]
    elif isinstance(command, ReturnHomeCommand) and home is not None:
        points = [home]
    else:
        points = []
    return [here] + points


def validate(decision: Decision, belief: BeliefState) -> Verdict:
    if decision.kind is not DecisionKind.START or decision.command is None:
        return Verdict(True)
    command = decision.command
    me = belief.self_
    track = ground_track(command, (me.x, me.y), me.home)
    reasons = []
    for zone in belief.brief.restricted_zones:
        for a, b in zip(track, track[1:]):
            if zone.polygon.crosses(a, b):
                reasons.append(f"the path {a} -> {b} enters restricted zone {zone.id}")
                break
    heads_home = command.skill in BATTERY_WAIVED or math.dist(track[-1], me.home) <= HOME_RADIUS_M
    if not heads_home:
        flown = sum(math.dist(a, b) for a, b in zip(track, track[1:]))
        home = math.dist(track[-1], me.home)
        battery = belief.brief.battery
        seconds = (flown + home) / ESTIMATE_SPEED_MPS
        cost = battery.hover_drain_per_s * seconds + battery.move_drain_per_m * (flown + home)
        if me.battery - cost < battery.reserve:
            reasons.append(f"{me.battery:.1f} % left, about {cost:.1f} % to fly this and home: "
                           f"under the {battery.reserve:g} % reserve")
    return Verdict(not reasons, tuple(reasons))
