"""The runtime safety guardian: every command checked, at the one place commands reach a drone (AUV-11).

    guardian = Guardian(brief, "Drone1", limits, executor.handle(), layer_m=12.0)
    agent = DroneAgent(brief, sensors, guardian.handle(), policy, validator=guardian.review)
    guardian.attach(agent.belief)
    ...
    guardian.log                      # every intervention: proposed, why, outcome, what ran instead
    guardian.approved                 # how many commands it let through as they were

AUV-11 asks for a deterministic guardian between decision and execution,
"always", whatever proposes the command -- the rule policy now, an LLM from
Phase 12. This is it. It replaces Phase 5's validation step for the flights
that pass it one, and keeps that step's two rules in that step's own words
(`agents.validation.zone_problems`, `battery_problems`), so a decision the
Phase 5 step refused it refuses for the same reasons.

WHERE IT SITS. Twice over, so it cannot be gone round:

* as the agent's VALIDATOR -- each decision is reviewed before the agent acts
  on it, and the review's outcome decides what the agent then does; and
* as the agent's EXECUTOR HANDLE (`handle()`) -- the only way the agent can
  start a skill. A command arriving here that the review did not clear is
  reviewed again, as it stands, and refused unless it passes unchanged. So a
  command from anywhere but a reviewed decision -- a second controller, a
  bug, a policy holding the handle -- is checked all the same.

THE CHECKS (11.1), each a pure function of the command and what the drone
knows; a reason names its check, `[check] what`:

    waypoint         every number finite; a region with an inside
    altitude         inside the band [min_altitude_m, max_altitude_m]
    geofence         every point inside the operating box: the sectors, the
                     start line and the base, with fence_margin_m round them
    restricted_zone  the ground track touches no zone (Phase 5's rule)
    speed            at most max_speed_mps
    battery          home on what is left, above the reserve (Phase 5's rule)
    timeout          the decision's information at most command_timeout_s old
    separation       the path passes no teammate's last known position, as
                     heard and still current, closer than the brief's minimum
    landing_site     LAND only within landing_radius_m of home or the base
    conflict         one command per instant: a second is refused
    finish_airborne  a FINISH in the air would leave the drone hovering with
                     nobody deciding
    proposal         an answer that could not be read as a decision
                     (`agents.proposal`)
    keep_out         (added after Phase 9's live collision; on when given a
                     `KeepOutConfig`) the path enters the square round a
                     teammate silent in the air, at any height
                     (`coordination.keepout`)

THE FOUR OUTCOMES (11.2):

    APPROVE                    as proposed
    APPROVE WITH MODIFICATION  only what keeps the command's intent: a speed or
                               an altitude clamped to its limit, a point at
                               most fence_clamp_m outside the fence moved onto
                               it. The modified command is checked again in
                               full and must pass.
    REJECT AND REPLAN          anything else that fails: the agent asks its
                               policy again, with GUARD_REJECTED (Phase 5's
                               loop, unchanged)
    EXECUTE SAFE FALLBACK      on the loop's last ask -- refused
                               REFUSALS_BEFORE_FALLBACK times already at this
                               instant -- or when the drone is UNSAFE NOW (out
                               of the fence, above the band, short of the
                               battery to get home and not heading there, a
                               teammate inside the separation) and the decision
                               is not an approved command

THE FALLBACKS (11.3), chosen by `choose_fallback` from the flight phase, the
battery, hazards and how fresh the drone's news of its teammates is, in this
order: on the ground, stay there (HOLD_POSITION); short of the battery to get
home, LAND_AT_SAFE_LOCATION if over home or the base, else RETURN_HOME; out of
the fence, RETURN_HOME; above the band, CLIMB_OR_DESCEND_TO_SAFE_LAYER (the
drone's own height); a teammate near (within hazard_factor separations), to
its own layer if not there, else HOLD_POSITION; any teammate never heard or no
longer current, HOLD_POSITION -- not knowing where they are, it does not move;
otherwise, with an approved skill still flying, CONTINUE_LAST_VALID_PLAN; and
failing all, HOLD_POSITION. Every fallback command is checked against the zones
and the fence before it is used, and becomes HOLD_POSITION if it fails.

WHAT IT KNOWS (plan, recommendation 3): its own drone's readings (the parts of
the belief the agent loop writes from its sensors each tick), the brief, and
its teammates' last positions from delivered messages (the belief's team
records). Never the policy's reasoning, assumptions or map -- nothing a policy
writes -- and never the truth.

THE LOG (11.4) is its own, apart from the decision trace: one entry per
intervention, with what was proposed, the checks it failed and why, the
outcome, and what ran instead. Plain approvals are counted, not logged, so a
flight with no interventions has an empty log.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from ..agents.belief_state import BeliefState
from ..agents.decision import Decision, DecisionKind
from ..agents.validation import HOME_RADIUS_M, ESTIMATE_SPEED_MPS, Verdict, battery_problems, searched, zone_problems
from ..control import navigation as nav
from ..control.action_executor import Execution, SkillHandle
from ..control.routing import AVOID_CLEARANCE_M, NoRouteError, route, search_path
from ..control.skills import (
    DEFAULT_SPEED_MPS,
    MAX_ALTITUDE_M,
    MAX_SPEED_MPS,
    MIN_FLIGHT_ALTITUDE_M,
    ActAsRelayCommand,
    FollowWaypointsCommand,
    GoToWaypointCommand,
    HoldPositionCommand,
    InspectPointCommand,
    LandCommand,
    RendezvousCommand,
    ReturnHomeCommand,
    SearchRegionCommand,
    SkillCommand,
    SkillName,
    TakeOffCommand,
    command_json,
)
from ..coordination.keepout import KeepOutConfig, keep_outs
from ..core.geometry import Region
from ..core.scenario import MissionBrief

APPROVE = "approve"
MODIFY = "approve_with_modification"
REJECT = "reject_and_replan"
FALLBACK = "execute_safe_fallback"
OUTCOMES = (APPROVE, MODIFY, REJECT, FALLBACK)

CHECKS = ("proposal", "waypoint", "altitude", "geofence", "restricted_zone", "speed", "battery", "timeout",
          "separation", "landing_site", "conflict", "finish_airborne", "keep_out")

HOLD_POSITION = "HOLD_POSITION"
CLIMB_OR_DESCEND = "CLIMB_OR_DESCEND_TO_SAFE_LAYER"
RETURN_HOME = "RETURN_HOME"
LAND_AT_SAFE_LOCATION = "LAND_AT_SAFE_LOCATION"
CONTINUE_LAST_VALID_PLAN = "CONTINUE_LAST_VALID_PLAN"
FALLBACKS = (HOLD_POSITION, CLIMB_OR_DESCEND, RETURN_HOME, LAND_AT_SAFE_LOCATION, CONTINUE_LAST_VALID_PLAN)

REFUSALS_BEFORE_FALLBACK = 3      # the agent loop's MAX_REJECTIONS: its last ask is the guardian's to answer
ALTITUDE_TOL_M = 1.0              # a skill arrives within 1 m (DEFAULT_TOLERANCE_M): "above the band" is beyond it
INSTANT_TOL_S = 1e-9              # two starts this close are at one instant
FALLBACK_CLEARANCE_M = 2.0        # a fallback's way home keeps this far from a zone (the policies' own clearance)
LAYER_TOL_M = 1.0                 # within this of its layer, a drone is on it



class CommandRefused(RuntimeError):
    """A command reached the executor handle without the guardian's clearance, and failed its review."""


# ------------------------------------------------------------------ limits

LIMIT_KEYS = {"limits": ("fence_margin_m", "fence_clamp_m", "min_altitude_m", "max_altitude_m", "max_speed_mps",
                         "command_timeout_s", "landing_radius_m"),
              "fallback": ("hold_s", "hazard_factor")}


@dataclass(frozen=True)
class GuardianLimits:
    """The guardian's manifest (`configs/guardian/<name>.toml`). The battery reserve and the separation
    are the brief's own, not repeated here."""

    fence_margin_m: float
    fence_clamp_m: float
    min_altitude_m: float
    max_altitude_m: float
    max_speed_mps: float
    command_timeout_s: float
    landing_radius_m: float
    hold_s: float
    hazard_factor: float

    def __post_init__(self) -> None:
        problems = []
        values = asdict(self)
        for name in ("fence_margin_m", "fence_clamp_m"):
            if not values[name] >= 0:
                problems.append(f"{name} must not be negative")
        for name in ("max_speed_mps", "command_timeout_s", "landing_radius_m", "hold_s"):
            if not values[name] > 0:
                problems.append(f"{name} must be positive")
        if not MIN_FLIGHT_ALTITUDE_M <= self.min_altitude_m < self.max_altitude_m <= MAX_ALTITUDE_M:
            problems.append(f"the band [{self.min_altitude_m}, {self.max_altitude_m}] must lie inside the skills' "
                            f"[{MIN_FLIGHT_ALTITUDE_M}, {MAX_ALTITUDE_M}]")
        if not self.max_speed_mps <= MAX_SPEED_MPS:
            problems.append(f"max_speed_mps above the skills' own {MAX_SPEED_MPS}")
        if not self.hazard_factor >= 1:
            problems.append("hazard_factor must be at least 1")
        if problems:
            raise ValueError("guardian limits: " + "; ".join(problems))

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_limits(data: dict[str, Any], source: str = "") -> GuardianLimits:
    """Strictly: every section and key required, none unknown, numbers only."""
    problems = [f"unknown section [{k}]" for k in data if k not in LIMIT_KEYS]
    values: dict[str, float] = {}
    for section, keys in LIMIT_KEYS.items():
        got = data.get(section)
        if not isinstance(got, dict):
            problems.append(f"missing section [{section}]")
            continue
        problems += [f"[{section}] missing {k}" for k in keys if k not in got]
        problems += [f"[{section}] unknown key {k}" for k in got if k not in keys]
        for k in keys:
            if k in got:
                v = got[k]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    problems.append(f"[{section}] {k} is not a number: {v!r}")
                else:
                    values[k] = float(v)
    if problems:
        raise ValueError(f"not a valid guardian manifest{' ' + source if source else ''}: " + "; ".join(problems))
    return GuardianLimits(**values)


# -------------------------------------------------------------- the view

@dataclass(frozen=True)
class Teammate:
    drone: str
    x: float
    y: float
    altitude_m: float
    at: float                 # when the position was true
    current: bool             # still within its lifetime


@dataclass(frozen=True)
class GuardianView:
    """What the guardian knows at one instant: own readings, home, teammates as heard."""

    now: float
    drone: str
    x: float
    y: float
    altitude_m: float
    airborne: bool
    battery: float
    home: tuple[float, float]
    teammates: tuple[Teammate, ...]
    unheard: tuple[str, ...]             # teammates never heard from

    @classmethod
    def of(cls, belief: BeliefState, now: float) -> "GuardianView":
        me = belief.self_
        mates, unheard = [], []
        for drone, record in sorted(belief.team.members.items()):
            if record is None or record.report.position is None:
                unheard.append(drone)
                continue
            p = record.report.position
            mates.append(Teammate(drone, float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0,
                                  record.report.at, record.current(now)))
        return cls(now, me.vehicle_id, me.x, me.y, me.altitude_m, me.airborne, me.battery, me.home,
                   tuple(mates), tuple(unheard))

    @property
    def here(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.altitude_m)


# ----------------------------------------------------------- geometry

def operating_box(brief: MissionBrief, margin_m: float) -> Region:
    """The geofence: everything the mission names -- sectors, start line, base -- and `margin_m` round it."""
    xs = [v.start_x for v in brief.vehicles] + [brief.base.x]
    ys = [v.start_y for v in brief.vehicles] + [brief.base.y]
    for s in brief.sectors:
        xs += [s.region.x_min, s.region.x_max]
        ys += [s.region.y_min, s.region.y_max]
    return Region(min(xs) - margin_m, min(ys) - margin_m, max(xs) + margin_m, max(ys) + margin_m)


def outside_by(box: Region, x: float, y: float) -> float:
    """How far (x, y) lies outside `box`; 0 inside or on it."""
    dx = max(box.x_min - x, 0.0, x - box.x_max)
    dy = max(box.y_min - y, 0.0, y - box.y_max)
    return math.hypot(dx, dy)


def onto(box: Region, x: float, y: float) -> tuple[float, float]:
    return (min(box.x_max, max(box.x_min, x)), min(box.y_max, max(box.y_min, y)))


def segment_distance(a: tuple[float, ...], b: tuple[float, ...], p: tuple[float, ...]) -> float:
    """The distance from `p` to the segment a-b, in as many dimensions as they have."""
    ab = [bi - ai for ai, bi in zip(a, b)]
    ap = [pi - ai for ai, pi in zip(a, p)]
    length2 = sum(c * c for c in ab)
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, sum(u * v for u, v in zip(ab, ap)) / length2))
    return math.dist([ai + t * c for ai, c in zip(a, ab)], p)


def track3d(command: SkillCommand, here: tuple[float, float, float],
            home: tuple[float, float]) -> list[tuple[float, float, float]]:
    """The points the skill flies through, from `here`, with heights."""
    x, y, alt = here
    if isinstance(command, TakeOffCommand):
        points = [(x, y, command.altitude_m)]
    elif isinstance(command, GoToWaypointCommand | RendezvousCommand | ActAsRelayCommand):
        w = command.waypoint
        points = [(w.x, w.y, w.altitude_m)]
    elif isinstance(command, FollowWaypointsCommand):
        points = [(w.x, w.y, w.altitude_m) for w in command.waypoints]
    elif isinstance(command, SearchRegionCommand):
        points = [(w.x, w.y, w.altitude_m) for w in searched(command)]
    elif isinstance(command, InspectPointCommand):
        points = [(command.target.x, command.target.y, command.altitude_m)]
    elif isinstance(command, ReturnHomeCommand):
        points = [(home[0], home[1], alt if command.altitude_m is None else command.altitude_m)]
    elif isinstance(command, LandCommand):
        points = [(x, y, 0.0)]
    else:
        points = []
    return [here] + points


def _numbers(command: SkillCommand) -> list[tuple[str, Any]]:
    """Every number in the command, named. (By `asdict`: no reflection in this package -- the boundary.)"""
    out: list[tuple[str, Any]] = []

    def walk(name: str, v: Any) -> None:
        if isinstance(v, dict):
            for k, item in v.items():
                walk(f"{name}.{k}" if name else k, item)
        elif isinstance(v, (tuple, list)):
            for i, item in enumerate(v):
                walk(f"{name}[{i}]", item)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((name, v))

    walk("", asdict(command))
    return out


def waypoint_problems(command: SkillCommand) -> list[tuple[str, str]]:
    bad = [f"{name} is {v!r}" for name, v in _numbers(command) if not math.isfinite(v)]
    if bad:
        return [("waypoint", f"not a number a drone can fly to: {', '.join(bad)}")]
    if isinstance(command, SearchRegionCommand) and command.avoid:
        try:
            search_path(command.region, command.spacing_m, command.altitude_m, command.avoid)
        except NoRouteError as exc:
            return [("waypoint", f"the search cannot go round what it must avoid: {exc}")]
    return []


def modify(command: SkillCommand, limits: GuardianLimits,
           box: Region) -> tuple[SkillCommand, list[tuple[str, str]], list[tuple[str, str]]]:
    """The command with what can be fixed fixed: (command, changes made, what cannot be fixed)."""
    changes: list[tuple[str, str]] = []
    refusals: list[tuple[str, str]] = []
    lo, hi = limits.min_altitude_m, limits.max_altitude_m

    def height(v: float, what: str) -> float:
        if lo <= v <= hi:
            return v
        c = min(hi, max(lo, v))
        changes.append(("altitude", f"{what} {v:g} m outside the {lo:g}-{hi:g} m band: {c:g} m"))
        return c

    def place(x: float, y: float, what: str) -> tuple[float, float]:
        d = outside_by(box, x, y)
        if d == 0:
            return (x, y)
        if d <= limits.fence_clamp_m:
            nx, ny = onto(box, x, y)
            changes.append(("geofence", f"{what} ({x:g}, {y:g}) is {d:.1f} m outside the geofence: "
                                        f"moved onto it at ({nx:g}, {ny:g})"))
            return (nx, ny)
        refusals.append(("geofence", f"{what} ({x:g}, {y:g}) is {d:.1f} m outside the geofence, more than the "
                                     f"{limits.fence_clamp_m:g} m a point may be moved"))
        return (x, y)

    def point(w: nav.Waypoint, what: str) -> nav.Waypoint:
        x, y = place(w.x, w.y, what)
        a = height(w.altitude_m, f"{what} altitude")
        return w if (x, y, a) == (w.x, w.y, w.altitude_m) else nav.Waypoint(x, y, a)

    updates: dict[str, Any] = {}
    speed = asdict(command).get("speed_mps")
    if speed is not None and speed > limits.max_speed_mps:
        updates["speed_mps"] = limits.max_speed_mps
        changes.append(("speed", f"speed {speed:g} m/s over the {limits.max_speed_mps:g} m/s limit: "
                                 f"{limits.max_speed_mps:g} m/s"))
    if isinstance(command, TakeOffCommand | SearchRegionCommand | InspectPointCommand) or (
            isinstance(command, ReturnHomeCommand) and command.altitude_m is not None):
        a = height(command.altitude_m, "altitude")
        if a != command.altitude_m:
            updates["altitude_m"] = a
    if isinstance(command, GoToWaypointCommand | RendezvousCommand | ActAsRelayCommand):
        w = point(command.waypoint, "waypoint")
        if w is not command.waypoint:
            updates["waypoint"] = w
    if isinstance(command, FollowWaypointsCommand):
        ws = tuple(point(w, f"waypoint {i + 1}") for i, w in enumerate(command.waypoints))
        if any(a is not b for a, b in zip(ws, command.waypoints)):
            updates["waypoints"] = ws
    if isinstance(command, InspectPointCommand):
        x, y = place(command.target.x, command.target.y, "target")
        if (x, y) != (command.target.x, command.target.y):
            updates["target"] = nav.Waypoint(x, y, command.target.altitude_m)
    if isinstance(command, SearchRegionCommand):
        r = command.region
        over = max(box.x_min - r.x_min, r.x_max - box.x_max, box.y_min - r.y_min, r.y_max - box.y_max)
        if over > 0:
            clipped = (max(r.x_min, box.x_min), max(r.y_min, box.y_min), min(r.x_max, box.x_max),
                       min(r.y_max, box.y_max))
            if over <= limits.fence_clamp_m and clipped[0] <= clipped[2] and clipped[1] <= clipped[3]:
                updates["region"] = Region(*clipped)
                changes.append(("geofence", f"region reaches {over:.1f} m outside the geofence: cut to it"))
            else:
                refusals.append(("geofence", f"region reaches {over:.1f} m outside the geofence, more than the "
                                             f"{limits.fence_clamp_m:g} m it may be cut"))
    if refusals or not updates:
        return command, changes, refusals
    return replace(command, **updates), changes, refusals


def heads_home(command: SkillCommand | None, home: tuple[float, float]) -> bool:
    """Going home or down: RETURN_HOME, LAND, or a route that ends over home."""
    if command is None:
        return False
    if command.skill in (SkillName.RETURN_HOME, SkillName.LAND):
        return True
    end = track3d(command, (math.nan, math.nan, 0.0), home)[-1]
    return math.isfinite(end[0]) and math.dist(end[:2], home) <= HOME_RADIUS_M


def cost_home(view: GuardianView, battery: Any) -> float:
    """The brief's model of the battery it takes to fly straight home from here."""
    d = math.dist((view.x, view.y), view.home)
    return battery.hover_drain_per_s * d / ESTIMATE_SPEED_MPS + battery.move_drain_per_m * d


def problem_check(problem: str) -> str:
    """The check a problem string names, "[check] what"; "proposal" if it names none."""
    return _split(problem)[0]


def _split(problem: str) -> tuple[str, str]:
    """"[check] what" -> (check, what); untagged -> ("proposal", problem)."""
    if problem.startswith("[") and "] " in problem:
        check, rest = problem[1:].split("] ", 1)
        if check and all(c.isalpha() or c == "_" for c in check):
            return check, rest
    return "proposal", problem


def _tagged(found: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(f"[{c}] {r}" for c, r in found)


# --------------------------------------------------------------- guardian

class Guardian:
    """One drone's guardian: reviews its decisions, guards its executor handle, falls back, keeps a log."""

    def __init__(self, brief: MissionBrief, drone: str, limits: GuardianLimits, handle: SkillHandle,
                 layer_m: float, keep_out: KeepOutConfig | None = None) -> None:
        self.brief = brief
        self.drone = drone
        self.limits = limits
        self.box = operating_box(brief, limits.fence_margin_m)
        self.layer_m = min(limits.max_altitude_m, max(limits.min_altitude_m, layer_m))
        self.separation_m = brief.safety.min_separation_m
        self.keep_out = keep_out          # after Phase 9's live collision; None: the check is off
        self._inner = handle
        self.clock = handle.clock
        self.log: list[dict[str, Any]] = []
        self.approved = 0
        self._belief: BeliefState | None = None
        self._cleared: SkillCommand | None = None
        self._instant: float | None = None
        self._refusals = 0
        self._last_start_at: float | None = None
        self._last_started: SkillCommand | None = None

    def attach(self, belief: BeliefState) -> None:
        """The belief whose loop-written parts the handle reads when a command arrives unreviewed."""
        self._belief = belief

    # --------------------------------------------------------- review

    def review(self, decision: Decision, belief: BeliefState) -> Verdict:
        """The agent's validator: the outcome for this decision, and what runs instead, if anything."""
        now = self.clock.now()
        if self._instant is None or abs(now - self._instant) > INSTANT_TOL_S:
            self._instant, self._refusals = now, 0
        view = GuardianView.of(belief, now)
        found: list[tuple[str, str]] = []
        changes: list[tuple[str, str]] = []
        command = decision.command
        if decision.kind is DecisionKind.INVALID:
            found += [_split(p) for p in decision.reason.split("; ") if p] or                 [("proposal", "an answer that could not be read as a decision")]
        elif decision.kind is DecisionKind.START and command is not None:
            if decision.issued_at is not None and now - decision.issued_at > self.limits.command_timeout_s + 1e-9:
                found.append(("timeout", f"decided on news {now - decision.issued_at:.1f} s old, over the "
                                         f"{self.limits.command_timeout_s:g} s a command may wait"))
            found += waypoint_problems(command)
            if not found:
                command, changes, refusals = modify(command, self.limits, self.box)
                found += refusals
                if not refusals:
                    found += self._hard(command, view)
        elif decision.kind is DecisionKind.FINISH and view.airborne:
            found.append(("finish_airborne", "finishing in the air would leave the drone hovering with nobody "
                                             "deciding: land first"))
        hazards = self._unsafe_now(view, command if decision.kind is DecisionKind.START and not found else None)
        if hazards and not (decision.kind is DecisionKind.START and not found):
            return self._fall_back(decision, view, hazards, "unsafe now")
        if found:
            self._refusals += 1
            if self._refusals > REFUSALS_BEFORE_FALLBACK:
                return self._fall_back(decision, view, found, f"refused {self._refusals} times")
            self._note(decision.as_json(), "decision", REJECT, found, None, None)
            return Verdict(False, tuple(r for _, r in found))
        self._refusals = 0
        if changes:
            modified = replace(decision, command=command)
            self._cleared = command
            self._note(decision.as_json(), "decision", MODIFY, changes, modified.as_json(), None)
            return Verdict(True, tuple(r for _, r in changes), MODIFY, modified)
        if decision.kind is DecisionKind.START:
            self._cleared = command
        self.approved += 1
        return Verdict(True)

    def _hard(self, command: SkillCommand, view: GuardianView) -> list[tuple[str, str]]:
        """The checks no modification can satisfy, on the command as it would fly."""
        here2 = (view.x, view.y)
        found = [("restricted_zone", r) for r in zone_problems(command, here2, view.home,
                                                               self.brief.restricted_zones)]
        found += [("battery", r) for r in battery_problems(command, here2, view.home, view.battery,
                                                           self.brief.battery)]
        track = track3d(command, view.here, view.home)
        for mate in view.teammates:
            if not mate.current:
                continue
            p = (mate.x, mate.y, mate.altitude_m)
            near = min(segment_distance(a, b, p) for a, b in zip(track, track[1:])) if len(track) > 1 else \
                math.dist(track[0], p)
            if near < self.separation_m:
                found.append(("separation", f"the path passes {near:.1f} m from {mate.drone}'s last known "
                                            f"position ({view.now - mate.at:.1f} s old), under the "
                                            f"{self.separation_m:g} m separation"))
        for drone, zone in self._keep_outs(view):
            if any(zone.crosses(a[:2], b[:2]) or zone.contains(*b[:2]) for a, b in zip(track, track[1:])):
                found.append(("keep_out", f"the path enters the keep-out round {drone}'s last known position, "
                                          f"{self.keep_out.half_width_m:g} m either side, at any height: "
                                          f"silent there {view.now - self._heard_at(view, drone):.1f} s"))
        if isinstance(command, LandCommand):
            sites = {"home": view.home, "the base": (self.brief.base.x, self.brief.base.y)}
            if min(math.dist(here2, s) for s in sites.values()) > self.limits.landing_radius_m:
                found.append(("landing_site", f"landing at ({view.x:.1f}, {view.y:.1f}): not within "
                                              f"{self.limits.landing_radius_m:g} m of home or the base"))
        return found

    def _unsafe_now(self, view: GuardianView, proposed: SkillCommand | None) -> list[tuple[str, str]]:
        if not view.airborne:
            return []
        out = []
        if outside_by(self.box, view.x, view.y) > 0:
            out.append(("geofence", f"the drone is {outside_by(self.box, view.x, view.y):.1f} m outside the geofence"))
        if view.altitude_m > self.limits.max_altitude_m + ALTITUDE_TOL_M:
            out.append(("altitude", f"the drone is at {view.altitude_m:.1f} m, above the "
                                    f"{self.limits.max_altitude_m:g} m band"))
        reserve = self.brief.battery.reserve
        running = self._running()
        if view.battery - cost_home(view, self.brief.battery) < reserve and not heads_home(proposed, view.home) \
                and not heads_home(running, view.home):
            out.append(("battery", f"{view.battery:.1f} % left, short of getting home above the {reserve:g} % "
                                   "reserve, and not heading there"))
        for mate in view.teammates:
            d = math.dist(view.here, (mate.x, mate.y, mate.altitude_m))
            if mate.current and d < self.separation_m:
                out.append(("separation", f"{mate.drone} last known {d:.1f} m away, inside the "
                                          f"{self.separation_m:g} m separation"))
        return out

    def _keep_outs(self, view: GuardianView) -> list:
        """The squares round teammates silent in the air, as the policies plan them (`coordination.keepout`)."""
        if self.keep_out is None:
            return []
        heard = [(m.drone, m.x, m.y, m.altitude_m, m.at) for m in view.teammates]
        pads = {v.id: (v.start_x, v.start_y) for v in self.brief.vehicles}
        return keep_outs(heard, view.now, self.keep_out, (view.x, view.y), AVOID_CLEARANCE_M, pads)

    @staticmethod
    def _heard_at(view: GuardianView, drone: str) -> float:
        return next(m.at for m in view.teammates if m.drone == drone)

    def _running(self) -> SkillCommand | None:
        latest = self._inner.current()
        return latest.command if latest is not None and latest.running else None

    # -------------------------------------------------------- fallback

    def choose_fallback(self, view: GuardianView, hazards: list[tuple[str, str]]) -> tuple[str, Decision]:
        """11.3: the safe action for this state. Table order is priority order (module docstring)."""
        checks = {c for c, _ in hazards}
        if not view.airborne:
            return HOLD_POSITION, Decision.abort("hold", "guardian fallback: on the ground, stay there")
        reserve = self.brief.battery.reserve
        if "battery" in checks or view.battery - cost_home(view, self.brief.battery) < reserve:
            sites = (view.home, (self.brief.base.x, self.brief.base.y))
            if min(math.dist((view.x, view.y), s) for s in sites) <= self.limits.landing_radius_m:
                return LAND_AT_SAFE_LOCATION, Decision.start(LandCommand(), "land", "guardian fallback: battery")
            return self._checked(RETURN_HOME, self._way_home(view), view, "battery")
        if "geofence" in checks:
            return self._checked(RETURN_HOME, self._way_home(view), view, "outside the geofence")
        if "altitude" in checks:
            return self._checked(CLIMB_OR_DESCEND, self._to_layer(view), view, "outside the band")
        near = self.limits.hazard_factor * self.separation_m
        if any(m.current and math.dist(view.here, (m.x, m.y, m.altitude_m)) < near for m in view.teammates):
            if abs(view.altitude_m - self.layer_m) > LAYER_TOL_M:
                return self._checked(CLIMB_OR_DESCEND, self._to_layer(view), view, "a teammate near")
            return self._hold(view, "a teammate near, on its own layer already")
        if view.unheard or any(not m.current for m in view.teammates):
            return self._hold(view, "not knowing where every teammate is, it does not move")
        if self._running() is not None:
            return CONTINUE_LAST_VALID_PLAN, Decision.carry_on(None, "guardian fallback: the approved skill flies on")
        return self._hold(view, "nothing approved is flying")

    def _hold(self, view: GuardianView, why: str) -> tuple[str, Decision]:
        return HOLD_POSITION, Decision.start(HoldPositionCommand(duration_s=self.limits.hold_s), "hold",
                                             f"guardian fallback: {why}")

    def _to_layer(self, view: GuardianView) -> SkillCommand:
        return GoToWaypointCommand(nav.Waypoint(view.x, view.y, self.layer_m),
                                   speed_mps=min(DEFAULT_SPEED_MPS, self.limits.max_speed_mps))

    def _way_home(self, view: GuardianView) -> SkillCommand:
        speed = min(DEFAULT_SPEED_MPS, self.limits.max_speed_mps)
        try:
            leg = route((view.x, view.y), view.home, [z.polygon for z in self.brief.restricted_zones]
                        + [zone for _, zone in self._keep_outs(view)], FALLBACK_CLEARANCE_M)
        except NoRouteError:
            return ReturnHomeCommand(altitude_m=self.layer_m, speed_mps=speed)
        return FollowWaypointsCommand(tuple(nav.Waypoint(x, y, self.layer_m) for x, y in leg[1:]) or
                                      (nav.Waypoint(view.home[0], view.home[1], self.layer_m),), speed_mps=speed)

    def _checked(self, name: str, command: SkillCommand, view: GuardianView, why: str) -> tuple[str, Decision]:
        here2 = (view.x, view.y)
        bad = zone_problems(command, here2, view.home, self.brief.restricted_zones)
        bad += [p for p in (track3d(command, view.here, view.home)[1:]) if outside_by(self.box, p[0], p[1]) > 0]
        track = track3d(command, view.here, view.home)
        bad += [d for d, zone in self._keep_outs(view)
                if any(zone.crosses(a[:2], b[:2]) or zone.contains(*b[:2]) for a, b in zip(track, track[1:]))]
        if bad:
            return self._hold(view, f"{why}; its {name} would not be safe")
        return name, Decision.start(command, name.lower(), f"guardian fallback: {why}")

    def _fall_back(self, decision: Decision, view: GuardianView, found: list[tuple[str, str]],
                   why: str) -> Verdict:
        name, chosen = self.choose_fallback(view, found)
        if chosen.command is not None:
            self._cleared = chosen.command
        self._refusals = 0
        self._note(decision.as_json(), "decision", FALLBACK, found, chosen.as_json(), name, why)
        return Verdict(True, tuple(r for _, r in found), FALLBACK, chosen, name)

    # ------------------------------------------------------------ handle

    def handle(self) -> SkillHandle:
        """The executor handle to give the agent: starts pass the guardian; the rest pass straight through."""
        guardian, inner = self, self._inner

        def start(command: SkillCommand) -> Execution:
            return guardian._start(command)

        def abort() -> bool:
            return inner.abort()

        def current() -> Execution | None:
            return inner.current()

        def history() -> tuple[Execution, ...]:
            return inner.history()

        def is_busy() -> bool:
            return inner.is_busy()

        def wait(timeout_s: float | None = None) -> Execution | None:
            return inner.wait(timeout_s)

        return SkillHandle(inner.clock, start, abort, current, history, is_busy, wait)

    def _start(self, command: SkillCommand) -> Execution:
        now = self.clock.now()
        cleared = self._cleared is not None and self._cleared is command
        self._cleared = None
        found: list[tuple[str, str]] = []
        if self._last_start_at is not None and abs(now - self._last_start_at) <= INSTANT_TOL_S:
            found.append(("conflict", f"{self._last_started.skill.value} was started at this instant: a second "
                                      "command at the same instant conflicts with it"))
        if not cleared and not found:
            found += waypoint_problems(command)
            if not found:
                if self._belief is None:
                    found.append(("proposal", "an unreviewed command, and no belief attached to review it against"))
                else:
                    view = GuardianView.of(self._belief, now)
                    fixed, changes, refusals = modify(command, self.limits, self.box)
                    found += refusals + [(c, f"{r} (an unreviewed command is not modified: refused)")
                                         for c, r in changes]
                    if not refusals:
                        found += self._hard(command, view)
        if found:
            self._note({"skill": command.skill.value, "command": command_json(command)}, "direct", REJECT, found, None,
                       None)
            raise CommandRefused("; ".join(_tagged(found)))
        execution = self._inner.start(command)
        self._last_start_at, self._last_started = now, command
        return execution

    # --------------------------------------------------------------- log

    def _note(self, proposed: dict[str, Any], source: str, outcome: str, found: list[tuple[str, str]],
              executed: dict[str, Any] | None, fallback: str | None, why: str | None = None) -> None:
        entry = {"at": round(self.clock.now(), 3), "drone": self.drone, "source": source, "proposed": proposed,
                 "outcome": outcome, "checks": sorted({c for c, _ in found}), "reasons": [r for _, r in found],
                 "executed": executed, "fallback": fallback}
        if why is not None:
            entry["why"] = why
        self.log.append(entry)

    def as_json(self) -> dict[str, Any]:
        return {"drone": self.drone, "limits": self.limits.as_json(), "layer_m": self.layer_m,
                "geofence": asdict(self.box), "approved": self.approved, "log": self.log}
