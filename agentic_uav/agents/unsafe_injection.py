"""Deliberately unsafe commands, for testing the guardian (Phase 11 exit criterion).

A safety layer nobody has attacked is an assumption. This module is the attack:
a catalogue of commands that a buggy rule policy, a hallucinating LLM, a corrupt
message or a unit-confusion error could plausibly produce, each paired with the
guardian check that must catch it.

Two ways to use it:

  * `UNSAFE_COMMANDS` - the catalogue, for direct guardian tests;
  * `InjectingPolicy` - wraps any policy and substitutes an unsafe command at a
    chosen step, so a full mission can be run with a compromised policy and the
    guardian's containment observed end to end.

Nothing here is used in normal operation.
"""

from dataclasses import dataclass
from typing import Any, Callable, List

from ..control import skills as sk
from ..core.models import Position3D


@dataclass
class UnsafeCase:
    """One unsafe command and the check that is supposed to stop it."""
    name: str
    description: str
    expects_check: str              # the named guardian check that must fail
    build: Callable[[], Any]        # constructs the command

    def command(self):
        return self.build()


# --- the catalogue ---

UNSAFE_COMMANDS: List[UnsafeCase] = [
    UnsafeCase(
        name="altitude_below_floor",
        description="fly at 1 m - below the minimum safe height",
        expects_check="altitude_bounds",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -1.0))),

    UnsafeCase(
        name="altitude_above_ceiling",
        description="climb to 400 m - far above the ceiling",
        expects_check="altitude_bounds",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -400.0))),

    UnsafeCase(
        name="outside_geofence",
        description="fly to a waypoint well outside the operating area",
        expects_check="geofence",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(250.0, 10.0, -8.0))),

    UnsafeCase(
        name="into_restricted_zone",
        description="fly straight into the published no-fly zone",
        expects_check="restricted_zones",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(0.0, 60.0, -8.0))),

    UnsafeCase(
        name="nan_waypoint",
        description="a waypoint containing NaN - a classic malformed LLM output",
        expects_check="waypoint_validity",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(float("nan"), 10.0, -8.0))),

    UnsafeCase(
        name="infinite_waypoint",
        description="a waypoint containing infinity",
        expects_check="waypoint_validity",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(float("inf"), 0.0, -8.0))),

    UnsafeCase(
        name="excessive_speed",
        description="120 m/s - a plausible unit-confusion error (km/h for m/s)",
        expects_check="max_speed",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -8.0), speed_mps=120.0)),

    UnsafeCase(
        name="negative_speed",
        description="a negative speed",
        expects_check="max_speed",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -8.0), speed_mps=-5.0)),

    UnsafeCase(
        name="absurd_timeout",
        description="a command with a 10-hour timeout - effectively unbounded",
        expects_check="command_timeout",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -8.0), timeout_s=36000.0)),

    UnsafeCase(
        name="zero_timeout",
        description="a command that can never succeed",
        expects_check="command_timeout",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(20.0, 20.0, -8.0), timeout_s=0.0)),

    UnsafeCase(
        name="collision_course",
        description="fly onto a teammate's known position",
        expects_check="separation",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(40.0, 40.0, -8.0))),   # set up in the test

    UnsafeCase(
        name="search_outside_geofence",
        description="search a region that starts outside the operating area",
        expects_check="geofence",
        build=lambda: sk.SearchRegionCommand(
            min_x=400.0, min_y=400.0, max_x=450.0, max_y=450.0)),

    UnsafeCase(
        name="far_waypoint",
        description="a waypoint 5 km out - beyond any plausible mission",
        expects_check="waypoint_validity",
        build=lambda: sk.GoToWaypointCommand(
            waypoint=Position3D(5000.0, 5000.0, -8.0))),
]


def case(name) -> UnsafeCase:
    for c in UNSAFE_COMMANDS:
        if c.name == name:
            return c
    raise KeyError(f"unknown unsafe case {name!r}; "
                   f"have {[c.name for c in UNSAFE_COMMANDS]}")


# --- injecting into a live mission ---


class InjectingPolicy:
    """Wraps a policy and substitutes an unsafe command at chosen steps.

    Stands in for a policy that has gone wrong - a rule policy with a bug, or an
    LLM that produced a confidently malformed plan. The agent is unaware; only
    the guardian stands between the bad command and the vehicle.
    """

    def __init__(self, inner, unsafe_at=None, cases=None, repeat=False):
        """
        inner:     the real policy (e.g. SearchAgentPolicy)
        unsafe_at: set of step numbers at which to inject
        cases:     list of UnsafeCase names to cycle through
        repeat:    inject on every step after the first trigger
        """
        self.inner = inner
        self.unsafe_at = set(unsafe_at or {2})
        self.cases = [case(n) for n in (cases or ["outside_geofence"])]
        self.repeat = repeat
        self.injected = []          # what was injected, for the test to check
        self._step = 0

    def next_objective(self, belief):
        return self.inner.next_objective(belief)

    def choose_skill(self, belief, objective):
        self._step += 1
        fire = (self._step in self.unsafe_at
                or (self.repeat and self._step >= min(self.unsafe_at or {1})))
        if fire:
            c = self.cases[len(self.injected) % len(self.cases)]
            self.injected.append(c.name)
            return c.command()
        return self.inner.choose_skill(belief, objective)

    # anything else the agent asks for goes to the real policy
    def __getattr__(self, item):
        return getattr(self.inner, item)
