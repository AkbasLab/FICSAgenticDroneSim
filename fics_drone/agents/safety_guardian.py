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
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Optional, Tuple

from ..core.scenario import NoFlyZone, Scenario


class Severity(str, Enum):
    HARD = "hard"  # cannot be narrowed - refuse outright
    SOFT = "soft"  # can be narrowed into the envelope instead of refused


class FallbackAction(str, Enum):
    HOLD_POSITION = "hold_position"
    CLIMB_OR_DESCEND_TO_SAFE_LAYER = "climb_or_descend_to_safe_layer"
    RETURN_HOME = "return_home"
    LAND_AT_SAFE_LOCATION = "land_at_safe_location"
    CONTINUE_LAST_VALID_PLAN = "continue_last_valid_plan"


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

    @classmethod
    def from_scenario(cls, scenario: Scenario, margin_m: float = 40.0) -> "SafetyLimits":
        """Geofence is a margin around the scenario's own sector extents -
        not FICS's base+sectors union exactly (this scenario's sectors
        already bound the base), but the same idea: flyable space plus a
        margin, not the raw sector box itself."""
        xs = [s.x_min for s in scenario.sectors] + [s.x_max for s in scenario.sectors]
        ys = [s.y_min for s in scenario.sectors] + [s.y_max for s in scenario.sectors]
        half_extent = max(max(abs(v) for v in xs + ys), 1.0) + margin_m
        return cls(restricted_zones=scenario.no_fly_zones, geofence_half_extent_m=half_extent,
                    min_separation_m=scenario.min_separation_m)


@dataclass
class GuardianEvaluation:
    outcome: GuardianOutcome
    command: Command  # original if APPROVE/REJECT, narrowed if APPROVE_WITH_MODIFICATION,
    # the fallback's own command if EXECUTE_SAFE_FALLBACK
    reason: Optional[str]
    fallback: Optional[FallbackAction]
    failed_checks: List[str]


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

    def evaluate(self, command: Command, belief) -> GuardianEvaluation:
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
        checks = self._run_checks(command, belief)
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

    def preview(self, command: Command, belief) -> List[SafetyCheck]:
        """Dry run: which checks would this command fail? Touches NO guardian state - no
        counters, no in-flight flag, no escalation - so a caller (the Phase 12.5 reasoning
        tools) can ask "is this point legal?" any number of times without ever affecting a
        real evaluate(). Skips conflicting_commands, which is about the vehicle's current
        activity, not about whether the destination itself is acceptable."""
        return [c for c in self._run_checks(command, belief)
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
    def _is_at_home(belief) -> bool:
        x, y, _ = belief.position
        return math.hypot(x, y) <= 3.0

    @staticmethod
    def _home_world(belief) -> Tuple[float, float, float]:
        # Belief positions are already in this agent's own local frame, where
        # (0, 0, *) at home has a well-defined meaning everywhere this class
        # is used (persistent_agent.py's own RETURN_HOME target) - the
        # guardian reasons in the same frame its caller hands it, not world.
        return (0.0, 0.0, belief.position[2] if belief.position else 0.0)

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

    def _run_checks(self, command: Command, belief) -> List[SafetyCheck]:
        checks = [
            self._check_altitude_bounds(command),
            self._check_geofence(command),
            self._check_restricted_zones(command),
            self._check_waypoint_validity(command),
            self._check_max_speed(command),
            self._check_command_timeout(command),
            self._check_battery_reserve(command, belief),
            self._check_separation(command, belief),
            self._check_landing_site(command),
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

    def _check_restricted_zones(self, command: Command) -> SafetyCheck:
        if command.kind != "fly" or command.target is None:
            return SafetyCheck("restricted_zones", True)
        x, y, _ = command.target
        for zone in self.limits.restricted_zones:
            if zone.contains(x, y):
                return SafetyCheck("restricted_zones", False, f"({x}, {y}) inside {zone.id}", Severity.HARD)
        return SafetyCheck("restricted_zones", True)

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

    def _check_separation(self, command: Command, belief) -> SafetyCheck:
        if command.kind != "fly" or command.target is None or command.purpose != "mission":
            return SafetyCheck("separation", True)
        for name, record in belief.team.teammates.items():
            if record.last_known_position is None:
                continue
            if math.dist(command.target, record.last_known_position) < self.limits.min_separation_m:
                return SafetyCheck("separation", False,
                                    f"{command.target} within {self.limits.min_separation_m}m of {name}",
                                    Severity.HARD)
        return SafetyCheck("separation", True)

    def _check_landing_site(self, command: Command) -> SafetyCheck:
        if command.kind != "land" or command.target is None:
            return SafetyCheck("landing_site", True)
        x, y, _ = command.target
        for zone in self.limits.restricted_zones:
            if zone.contains(x, y):
                return SafetyCheck("landing_site", False, f"landing at ({x}, {y}) inside {zone.id}", Severity.HARD)
        return SafetyCheck("landing_site", True)

    def _check_conflicting_commands(self, command: Command) -> SafetyCheck:
        if self._command_in_flight:
            return SafetyCheck("conflicting_commands", False,
                                "a command is already in flight - command_completed() was never called",
                                Severity.HARD)
        return SafetyCheck("conflicting_commands", True)
