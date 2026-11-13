"""Phase 11: every phase so far has trusted the policy. This stops doing
that. A deterministic safety layer sits between whatever proposed a command
and the vehicle, so a buggy rule policy, a future LLM policy, a corrupt
message, or a unit-confusion error cannot fly the drone somewhere it
shouldn't go. Supersedes Phase 5's `Guardian` (no-fly-zones only, binary
pass/fail) as PersistentAgent's default - `Guardian` itself is left alone
(still its own class, still covered by its own tests) rather than deleted,
since nothing requires removing it to build this.

Deterministic on purpose: no model, no learned component, no randomness.
Same command plus same belief always produces the same verdict, and every
rejection names which check failed and why. A guardrail implemented as a
second language model would inherit exactly the failure modes it's meant to
contain.

Ten checks, matching FICS's own list: altitude_bounds, geofence,
restricted_zones, waypoint_validity, max_speed, command_timeout,
battery_reserve, separation, landing_site, conflicting_commands. Three are
SOFT (narrowable into the envelope instead of refused outright - altitude,
speed, timeout), the rest are HARD (refused, because there's no meaningful
way to narrow a NaN waypoint or a no-fly-zone entry into something safe).

Scoping note, found while wiring this in: `battery_reserve` and `separation`
only apply to purpose="mission" commands, not "home"/"land"/"hold" ones.
Without that scoping, the battery check would block the exact RETURN_HOME
a low-battery drone needs most, and separation would fire on every mission's
own ending - every drone in this scenario returns to the same shared home
point, so teammates converging there are expected, not a near-miss.
"""

import math
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Optional, Tuple

from ..core import moving
from ..core.scenario import DRONE_RADIUS_M, NoFlyZone, Scenario


INTENT_FRESH_S = 30.0  # a teammate's announced destination counts for this long after its heartbeat


def _distance_to_segment(point, a, b) -> float:
    """Straight-line distance from `point` to the segment a-b (all three are x, y, z)."""
    ab = [b[i] - a[i] for i in range(3)]
    length_sq = sum(v * v for v in ab)
    if length_sq == 0.0:
        return math.dist(point, a)
    t = sum((point[i] - a[i]) * ab[i] for i in range(3)) / length_sq
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * ab[i] for i in range(3)])


class Severity(str, Enum):
    HARD = "hard"  # cannot be narrowed - refuse outright
    SOFT = "soft"  # can be narrowed into the envelope instead of refused


EXIT_DETOUR_LIMIT_M = 4.0  # an exit that clears the keep-out margin may be this much farther than one that only clears the keep-out


class FallbackAction(str, Enum):
    HOLD_POSITION = "hold_position"
    CLIMB_OR_DESCEND_TO_SAFE_LAYER = "climb_or_descend_to_safe_layer"
    RETURN_HOME = "return_home"
    LAND_AT_SAFE_LOCATION = "land_at_safe_location"
    CONTINUE_LAST_VALID_PLAN = "continue_last_valid_plan"
    EXIT_ZONE = "exit_zone"  # a no-fly zone became active on top of the aircraft: leave it


class GuardianOutcome(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_MODIFICATION = "approve_with_modification"
    REJECT_AND_REPLAN = "reject_and_replan"
    EXECUTE_SAFE_FALLBACK = "execute_safe_fallback"


@dataclass
class SafetyCheck:
    name: str
    passed: bool
    reason: Optional[str] = None
    severity: Optional[Severity] = None


@dataclass
class Command:
    """What a policy is asking the vehicle to do, in WORLD coordinates - same
    convention as the Phase 5 Guardian and the Phase 4 scorer. `purpose`
    distinguishes "new work" (subject to the battery-reserve and separation
    checks) from safety/administrative moves (home, landing, holding) that
    must never be blocked by the same checks meant to protect against those
    moves never happening."""
    kind: str  # "fly" | "hold" | "land"
    target: Optional[Tuple[float, float, float]] = None
    speed_mps: float = 0.0
    timeout_s: float = 0.0
    purpose: str = "mission"  # "mission" | "home" | "hold" | "land"


@dataclass
class SafetyLimits:
    altitude_floor_m: float = 3.0
    altitude_ceiling_m: float = 60.0
    geofence_half_extent_m: float = 80.0  # box is [-extent, extent] on x and y
    restricted_zones: List[NoFlyZone] = field(default_factory=list)
    obstacles: list = field(default_factory=list)  # trees: core/obstacles.py
    obstacle_margin_m: float = float(os.environ.get("NAVRL_TREE_MARGIN", 0.5))   # a fast aircraft coasts about 0.7 m per m/s on a turn
    home_world: tuple = (0.0, 0.0)  # where this aircraft's home is, world metres: its own spawn point (the agent sets it)
    max_coordinate_m: float = 300.0
    max_speed_mps: float = 30.0  # comfortably above every real adapter speed this repo
    # configures (5-25 m/s across various mock/live scripts) - FICS's own 12 m/s assumes a
    # per-command speed the policy actually proposes, which this architecture's adapters
    # don't expose; see _guarded_fly's own note. The catalogue's excessive_speed (120) and
    # negative_speed (-5) cases are still caught comfortably under this ceiling.
    min_timeout_s: float = 1.0
    max_timeout_s: float = 120.0
    battery_reserve_frac: float = 0.10
    min_separation_m: float = 5.0
    exit_margin_m: float = 3.0  # how far outside a zone's edge an exit point is placed
    exit_settle_s: float = 2.0  # an exit point must stay clear this long after the drone has arrived
    drone_radius_m: float = DRONE_RADIUS_M  # half the aircraft's width: a zone counts as entered when the body's edge crosses
    # vehicles and pedestrians: a callable returning the current list of core.moving.MovingObject (None = there are none)
    moving_fn: object = None
    moving_pad_m: float = 1.5        # clearance kept round a moving object's body
    moving_lookahead_s: float = 3.0  # keep clear of where it will be this many seconds on, as well
    moving_vertical_pad_m: float = 4.0  # an aircraft this far above a person's or car's top is clear of it
    moving_check_range_m: Optional[float] = None  # None: a leg is refused if a moving body crosses any of it. A number: only if the body
    #   is within this far of the aircraft (set when a reactive leg planner flies the leg: it steers round a far body in flight,
    #   and a leg held back for something 25 m off never starts)

    def moving_columns(self) -> list:
        """Keep-out columns for every vehicle and pedestrian right now (and where each is going), or []."""
        if self.moving_fn is None:
            return []
        try:
            return moving.columns(self.moving_fn(), self.moving_pad_m, self.moving_lookahead_s, self.moving_vertical_pad_m)
        except Exception:
            return []

    def standing_columns(self, max_speed_mps: float = 0.3) -> list:
        """Keep-out columns for the vehicles and pedestrians that are standing still (they will still be there, so a leg is
        planned round them like a tree). A moving one is left out: it will have passed, and a detour planned round it runs
        far off the road; the flight code steers round it and the guardian holds the leg until it is clear."""
        if self.moving_fn is None:
            return []
        try:
            standing = [o for o in self.moving_fn() if o.speed <= max_speed_mps]
            return moving.columns(standing, self.moving_pad_m, self.moving_lookahead_s, self.moving_vertical_pad_m)
        except Exception:
            return []

    @classmethod
    def from_scenario(cls, scenario: Scenario, margin_m: float = 40.0) -> "SafetyLimits":
        """Geofence is a margin around the scenario's own sector extents -
        not FICS's base+sectors union exactly (this scenario's sectors
        already bound the base), but the same idea: flyable space plus a
        margin, not the raw sector box itself."""
        xs = [s.x_min for s in scenario.sectors] + [s.x_max for s in scenario.sectors]
        ys = [s.y_min for s in scenario.sectors] + [s.y_max for s in scenario.sectors]
        half_extent = max(max(abs(v) for v in xs + ys), 1.0) + margin_m
        return cls(restricted_zones=scenario.no_fly_zones, obstacles=list(getattr(scenario, "obstacles", [])),
                    geofence_half_extent_m=half_extent,
                    min_separation_m=scenario.min_separation_m,
                    drone_radius_m=getattr(scenario, "drone_radius_m", DRONE_RADIUS_M))


@dataclass
class GuardianEvaluation:
    outcome: GuardianOutcome
    command: Command  # original if APPROVE/REJECT, narrowed if APPROVE_WITH_MODIFICATION,
    # the fallback's own command if EXECUTE_SAFE_FALLBACK
    reason: Optional[str]
    fallback: Optional[FallbackAction]
    failed_checks: List[str]
    move_m: Optional[float] = None  # EXIT_ZONE only: how far the steer-out moves the aircraft


class SafetyGuardian:
    """One instance per agent - escalation state (the two counters) is
    per-agent, not shared or global, same as the belief it reads."""

    def __init__(self, limits: SafetyLimits = None, max_consecutive_rejections: int = 3,
                 max_consecutive_interventions: int = 5):
        self.limits = limits or SafetyLimits()
        self.max_consecutive_rejections = max_consecutive_rejections
        self.max_consecutive_interventions = max_consecutive_interventions
        self.consecutive_rejections = 0
        self.consecutive_interventions = 0
        self.last_valid_command: Optional[Command] = None
        self._command_in_flight = False
        self.escalated = False  # sticky once True - see evaluate()

    def command_completed(self):
        """Call once the vehicle has actually finished (or given up on) the
        command this evaluate() approved - closes the window
        conflicting_commands checks against."""
        self._command_in_flight = False

    def evaluate(self, command: Command, belief, position_world=None) -> GuardianEvaluation:
        """`position_world` is the aircraft's own position in the shared WORLD frame (the frame
        zones are defined in). A belief only knows its local frame, so a caller whose drone
        spawned away from the origin must pass this; without it the belief position is used,
        which is correct only where local and world coincide."""
        if self.escalated:
            # Once escalated, the guardian stops asking the policy and steers the
            # aircraft home itself - sticky on purpose. Without this, a policy that's
            # unsafe in a DIFFERENT way on its very next proposal (e.g. narrowable
            # instead of a hard rejection) would get evaluated normally again, fly off
            # toward whatever it just proposed, and undo the fallback already in
            # progress. The guardian keeps steering (home, then land) regardless of
            # what's proposed until it actually reaches home - at which point
            # _escalate() itself clears this flag, since there's nothing left to steer.
            return self._escalate(belief, ["escalated"])
        exit_evaluation = self._exit_active_zone(belief, position_world)
        if exit_evaluation is not None:
            return exit_evaluation
        checks = self._run_checks(command, belief, position_world)
        failed = [c for c in checks if not c.passed]

        if not failed:
            self._command_in_flight = True
            self.consecutive_rejections = 0
            self.consecutive_interventions = 0
            self.last_valid_command = command
            return GuardianEvaluation(GuardianOutcome.APPROVE, command, None, None, [])

        hard = [c for c in failed if c.severity == Severity.HARD]
        if hard:
            self.consecutive_rejections += 1
            self.consecutive_interventions += 1
            reason = "; ".join(f"{c.name}: {c.reason}" for c in hard)
            if self._should_escalate():
                return self._escalate(belief, [c.name for c in failed])
            return GuardianEvaluation(GuardianOutcome.REJECT_AND_REPLAN, command, reason, None,
                                       [c.name for c in failed])

        # every failure is SOFT - narrow instead of refusing
        narrowed = self._narrow(command, failed)
        self.consecutive_rejections = 0  # a narrowed command isn't a rejection...
        self.consecutive_interventions += 1  # ...but it IS an intervention, the exact
        # evasion FICS's own build found: alternating reject/narrow never looks like two
        # consecutive rejections, so the counter that actually has to catch a policy that
        # never once proposes a clean command is the one that resets ONLY on APPROVE.
        if self._should_escalate():
            return self._escalate(belief, [c.name for c in failed])
        self._command_in_flight = True
        self.last_valid_command = narrowed
        reason = "; ".join(f"{c.name}: {c.reason}" for c in failed)
        return GuardianEvaluation(GuardianOutcome.APPROVE_WITH_MODIFICATION, narrowed, reason, None,
                                   [c.name for c in failed])

    def preview(self, command: Command, belief, position_world=None) -> List[SafetyCheck]:
        """Dry run: which checks would this command fail? Touches NO guardian state - no
        counters, no in-flight flag, no escalation - so a caller (the Phase 12.5 reasoning
        tools) can ask "is this point legal?" any number of times without ever affecting a
        real evaluate(). Skips conflicting_commands, which is about the vehicle's current
        activity, not about whether the destination itself is acceptable."""
        return [c for c in self._run_checks(command, belief, position_world)
                if not c.passed and c.name != "conflicting_commands"]

    def _should_escalate(self) -> bool:
        return (self.consecutive_rejections >= self.max_consecutive_rejections or
                self.consecutive_interventions >= self.max_consecutive_interventions)

    def _escalate(self, belief, failed_check_names: List[str]) -> GuardianEvaluation:
        """An escalated fallback must terminate the flight, never just hold
        or repeat - a permanently broken policy will never produce something
        better by being asked again, so asking again (REJECT_AND_REPLAN
        forever) is contained but not safe."""
        self.consecutive_rejections = 0
        self.consecutive_interventions = 0
        self._command_in_flight = True  # the fallback itself is about to be issued
        at_home = self._is_at_home(belief)
        self.escalated = not at_home  # cleared once the land fallback is actually issued
        fallback = FallbackAction.LAND_AT_SAFE_LOCATION if at_home else FallbackAction.RETURN_HOME
        home_world = self._home_world(belief)
        target = belief.position if at_home else home_world
        command = Command(kind="land" if at_home else "fly", target=target,
                           speed_mps=self.limits.max_speed_mps, timeout_s=self.limits.max_timeout_s,
                           purpose="land" if at_home else "home")
        reason = f"escalated after repeated unsafe proposals ({', '.join(failed_check_names)})"
        return GuardianEvaluation(GuardianOutcome.EXECUTE_SAFE_FALLBACK, command, reason, fallback, failed_check_names)

    @staticmethod
    def _now(belief) -> Optional[float]:
        """Mission time in seconds, or None if the belief doesn't carry one - in which case
        zones are read as always-active (the conservative, pre-GMB behaviour)."""
        return getattr(belief, "elapsed_s", None)

    def in_active_dynamic_zone(self, position_world, t: Optional[float]) -> bool:
        """True if this world (x, y) is inside a dynamic zone that is active at mission time t.
        Cheap and stateless, so a caller can poll it on every control tick (GMB zone monitor).
        Same test _exit_active_zone uses, so the two can never disagree."""
        if t is None or position_world is None:
            return False
        x, y = position_world[0], position_world[1]
        r = self.limits.drone_radius_m
        return any(zone.is_dynamic and zone.contains(x, y, t, r) for zone in self.limits.restricted_zones)

    def _exit_active_zone(self, belief, position_world=None) -> Optional[GuardianEvaluation]:
        """GMB: a scheduled or drifting zone can switch on, or move, on top of an aircraft
        that was legal a moment ago. Static zones can't (a drone never enters one, the
        restricted_zones check stops it first), so only dynamic zones trigger this. When it
        happens the guardian stops asking the policy and steers to the nearest point outside
        every active zone, instead of waiting for the policy to notice. One-shot per
        evaluation: the next proposal is judged normally once the aircraft is out."""
        t = self._now(belief)
        position = position_world if position_world is not None else getattr(belief, "position", None)
        if t is None or position is None:
            return None
        x, y, z = position
        zones = [zone for zone in self.limits.restricted_zones if zone.is_dynamic]
        r = self.limits.drone_radius_m
        inside = [zone for zone in zones if zone.contains(x, y, t, r)]
        if not inside:
            return None
        margin = self.limits.exit_margin_m
        extent = self.limits.geofence_half_extent_m
        candidates = []
        for zone in inside:
            x0, x1, y0, y1 = zone.bounds_at(t)
            candidates += [(x0 - margin, y), (x1 + margin, y), (x, y0 - margin), (x, y1 + margin)]
        usable = [(cx, cy) for cx, cy in candidates
                  if abs(cx) <= extent and abs(cy) <= extent
                  and not any(zn.contains(cx, cy, t, r) for zn in self.limits.restricted_zones)]
        candidates_all = list(usable)
        # an exit point inside a keep-out, or a straight way to it through one, is not an exit (a street scenario has them on
        # every side); if every one is blocked the nearest is still used
        keep = self.limits.obstacle_margin_m
        unblocked = [c for c in usable
                     if not any(o.blocks_point(c[0], c[1], z, margin=keep) or o.blocks_segment((x, y, z), (c[0], c[1], z), margin=keep)
                                for o in self.limits.obstacles)]
        usable = unblocked or usable
        # Every second spent inside the zone counts against the mission, a thin keep-out margin does not: when the only
        # margin-clear exits are far (a narrow street, a tree on the near side), take a near one that clears the keep-out
        # itself by half the margin rather than fly the length of the zone
        slim = self.limits.obstacle_margin_m / 4.0
        close_enough = [c for c in candidates_all
                        if not any(o.blocks_point(c[0], c[1], z, margin=slim) or o.blocks_segment((x, y, z), (c[0], c[1], z), margin=slim)
                                   for o in self.limits.obstacles)]
        if close_enough and unblocked:
            if min(math.dist((x, y), c) for c in close_enough) + EXIT_DETOUR_LIMIT_M < min(math.dist((x, y), c) for c in unblocked):
                usable = close_enough
        elif close_enough and not unblocked:
            usable = close_enough
        names = [zone.id for zone in inside]
        if not usable:
            return self._escalate(belief, [f"inside_active_zone({', '.join(names)})"])
        # A drifting zone keeps moving while the aircraft escapes, so the nearest edge right now can be the one the
        # zone is heading for (found live: a 3 m exit toward the drift was overrun). Prefer exit points that stay
        # clear of every zone until the aircraft has arrived and settled; if none do, use the nearest as before.
        exit_speed = min(5.0, self.limits.max_speed_mps) or 5.0

        def stays_clear(c):
            until = t + math.dist((x, y), c) / exit_speed + self.limits.exit_settle_s
            step = t
            while step <= until:
                if any(zn.contains(c[0], c[1], step, r) for zn in self.limits.restricted_zones):
                    return False
                step += 0.5
            return True

        durable = [c for c in usable if stays_clear(c)]
        cx, cy = min(durable or usable, key=lambda c: math.dist((x, y), c))
        command = Command(kind="fly", target=(cx, cy, z), speed_mps=min(5.0, self.limits.max_speed_mps),
                           timeout_s=30.0, purpose="home")
        self._command_in_flight = True
        reason = f"inside active no-fly zone {', '.join(names)} at t={t:.1f}s; exiting to ({cx:.1f}, {cy:.1f})"
        return GuardianEvaluation(GuardianOutcome.EXECUTE_SAFE_FALLBACK, command, reason,
                                   FallbackAction.EXIT_ZONE, ["inside_active_zone"],
                                   move_m=math.dist((x, y), (cx, cy)))

    @staticmethod
    def _is_at_home(belief) -> bool:
        x, y, _ = belief.position
        return math.hypot(x, y) <= 3.0

    def _home_world(self, belief) -> Tuple[float, float, float]:
        # Belief positions are already in this agent's own local frame, where
        # (0, 0, *) at home has a well-defined meaning everywhere this class
        # is used (persistent_agent.py's own RETURN_HOME target) - the
        # guardian reasons in the same frame its caller hands it, not world.
        return (self.limits.home_world[0], self.limits.home_world[1], belief.position[2] if belief.position else 0.0)

    def _narrow(self, command: Command, failed: List[SafetyCheck]) -> Command:
        updated = command
        for check in failed:
            if check.name == "altitude_bounds" and updated.target is not None:
                x, y, z = updated.target
                z = max(self.limits.altitude_floor_m, min(self.limits.altitude_ceiling_m, z))
                updated = replace(updated, target=(x, y, z))
            elif check.name == "max_speed":
                speed = abs(updated.speed_mps)
                speed = min(speed, self.limits.max_speed_mps) or 0.1
                updated = replace(updated, speed_mps=speed)
            elif check.name == "command_timeout":
                timeout = max(self.limits.min_timeout_s, min(self.limits.max_timeout_s, updated.timeout_s))
                updated = replace(updated, timeout_s=timeout)
        return updated

    def _run_checks(self, command: Command, belief, position_world=None) -> List[SafetyCheck]:
        checks = [
            self._check_altitude_bounds(command),
            self._check_geofence(command),
            self._check_restricted_zones(command, belief),
            self._check_obstacles(command, position_world),
            self._check_waypoint_validity(command),
            self._check_max_speed(command),
            self._check_command_timeout(command),
            self._check_battery_reserve(command, belief),
            self._check_separation(command, belief, position_world),
            self._check_landing_site(command, belief),
            self._check_conflicting_commands(command),
        ]
        return checks

    def _check_altitude_bounds(self, command: Command) -> SafetyCheck:
        if command.kind != "fly" or command.target is None:
            return SafetyCheck("altitude_bounds", True)
        z = command.target[2]
        if z < self.limits.altitude_floor_m or z > self.limits.altitude_ceiling_m:
            return SafetyCheck("altitude_bounds", False,
                                f"z={z} outside [{self.limits.altitude_floor_m}, {self.limits.altitude_ceiling_m}]",
                                Severity.SOFT)
        return SafetyCheck("altitude_bounds", True)

    def _check_geofence(self, command: Command) -> SafetyCheck:
        if command.kind != "fly" or command.target is None:
            return SafetyCheck("geofence", True)
        x, y, _ = command.target
        extent = self.limits.geofence_half_extent_m
        if abs(x) > extent or abs(y) > extent:
            return SafetyCheck("geofence", False, f"({x}, {y}) outside +/-{extent}m box", Severity.HARD)
        return SafetyCheck("geofence", True)

    def _check_restricted_zones(self, command: Command, belief=None) -> SafetyCheck:
        if command.kind != "fly" or command.target is None:
            return SafetyCheck("restricted_zones", True)
        x, y, _ = command.target
        t = self._now(belief)
        for zone in self.limits.restricted_zones:
            if zone.contains(x, y, t, self.limits.drone_radius_m):
                return SafetyCheck("restricted_zones", False, f"({x}, {y}) inside {zone.id}", Severity.HARD)
        return SafetyCheck("restricted_zones", True)

    def _check_obstacles(self, command: Command, position_world=None) -> SafetyCheck:
        """A leg must not end in, or (when the aircraft's own position is known) cross, a tree. The sim does not stop
        a drone flying through a palm, so this is the only protection."""
        if command.kind != "fly" or command.target is None:
            return SafetyCheck("obstacles", True)
        movers = self.limits.moving_columns()
        if not self.limits.obstacles and not movers:
            return SafetyCheck("obstacles", True)
        margin = self.limits.obstacle_margin_m
        for column in movers:     # vehicles and pedestrians: already padded, so no extra margin
            if column.blocks_point(*command.target, margin=0.0):
                return SafetyCheck("obstacles", False,
                                    f"{command.target} too close to a moving vehicle or pedestrian near ({column.x:.1f}, {column.y:.1f})",
                                    Severity.HARD)
            if position_world is not None and column.blocks_segment(position_world, command.target, margin=0.0):
                reach = self.limits.moving_check_range_m
                if reach is None or math.hypot(column.x - position_world[0], column.y - position_world[1]) <= reach:
                    return SafetyCheck("obstacles", False,
                                        f"path to {command.target} passes a moving vehicle or pedestrian near ({column.x:.1f}, {column.y:.1f})",
                                        Severity.HARD)
        for tree in self.limits.obstacles:
            if tree.blocks_point(*command.target, margin=margin):
                return SafetyCheck("obstacles", False, f"{command.target} inside the tree at ({tree.x}, {tree.y})",
                                    Severity.HARD)
            if position_world is not None and tree.blocks_segment(position_world, command.target, margin=margin):
                return SafetyCheck("obstacles", False,
                                    f"path to {command.target} passes through the tree at ({tree.x}, {tree.y})",
                                    Severity.HARD)
        return SafetyCheck("obstacles", True)

    def _check_waypoint_validity(self, command: Command) -> SafetyCheck:
        if command.target is None:
            return SafetyCheck("waypoint_validity", True)
        for v in command.target:
            if math.isnan(v) or math.isinf(v):
                return SafetyCheck("waypoint_validity", False, f"non-finite coordinate in {command.target}",
                                    Severity.HARD)
            if abs(v) > self.limits.max_coordinate_m:
                return SafetyCheck("waypoint_validity", False,
                                    f"{v} beyond {self.limits.max_coordinate_m}m", Severity.HARD)
        return SafetyCheck("waypoint_validity", True)

    def _check_max_speed(self, command: Command) -> SafetyCheck:
        if command.kind != "fly":
            return SafetyCheck("max_speed", True)
        if command.speed_mps < 0 or command.speed_mps > self.limits.max_speed_mps:
            return SafetyCheck("max_speed", False,
                                f"speed={command.speed_mps} outside [0, {self.limits.max_speed_mps}]",
                                Severity.SOFT)
        return SafetyCheck("max_speed", True)

    def _check_command_timeout(self, command: Command) -> SafetyCheck:
        if command.timeout_s <= 0 or command.timeout_s > self.limits.max_timeout_s:
            return SafetyCheck("command_timeout", False,
                                f"timeout={command.timeout_s} outside (0, {self.limits.max_timeout_s}]",
                                Severity.SOFT)
        return SafetyCheck("command_timeout", True)

    def _check_battery_reserve(self, command: Command, belief) -> SafetyCheck:
        if command.purpose != "mission":
            return SafetyCheck("battery_reserve", True)
        if belief.battery_frac_remaining < self.limits.battery_reserve_frac:
            return SafetyCheck("battery_reserve", False,
                                f"battery={belief.battery_frac_remaining:.2f} below reserve "
                                f"{self.limits.battery_reserve_frac}", Severity.HARD)
        return SafetyCheck("battery_reserve", True)

    def _claimed_points(self, record, belief) -> List[Tuple[float, float, float]]:
        """Where a teammate is, or has said it is going: its last reported position, and (while its heartbeat is
        recent) the destination it announced when it set off."""
        points = []
        if record.last_known_position is not None:
            points.append(tuple(record.last_known_position))
        if record.heading_to is not None:
            now = self._now(belief)
            if now is None or now - record.provenance.timestamp <= INTENT_FRESH_S:
                points.append(tuple(record.heading_to))
        return points

    def _check_separation(self, command: Command, belief, position_world=None) -> SafetyCheck:
        """The target must stay clear of every point a teammate holds or is heading for. When the aircraft's own
        position is known, the straight path to the target must stay clear too: two drones sent to the same
        corner from different sides each looked fine on their own target, and met there 0.1 m apart."""
        if command.kind != "fly" or command.target is None or command.purpose != "mission":
            return SafetyCheck("separation", True)
        sep = self.limits.min_separation_m
        for name, record in belief.team.teammates.items():
            for point in self._claimed_points(record, belief):
                if math.dist(command.target, point) < sep:
                    return SafetyCheck("separation", False,
                                        f"{command.target} within {sep}m of {name}", Severity.HARD)
                if position_world is not None and _distance_to_segment(point, position_world, command.target) < sep:
                    return SafetyCheck("separation", False,
                                        f"path to {command.target} passes within {sep}m of {name}", Severity.HARD)
        return SafetyCheck("separation", True)

    def _check_landing_site(self, command: Command, belief=None) -> SafetyCheck:
        if command.kind != "land" or command.target is None:
            return SafetyCheck("landing_site", True)
        x, y, _ = command.target
        t = self._now(belief)
        for zone in self.limits.restricted_zones:
            if zone.contains(x, y, t, self.limits.drone_radius_m):
                return SafetyCheck("landing_site", False, f"landing at ({x}, {y}) inside {zone.id}", Severity.HARD)
        return SafetyCheck("landing_site", True)

    def _check_conflicting_commands(self, command: Command) -> SafetyCheck:
        if self._command_in_flight:
            return SafetyCheck("conflicting_commands", False,
                                "a command is already in flight - command_completed() was never called",
                                Severity.HARD)
        return SafetyCheck("conflicting_commands", True)
