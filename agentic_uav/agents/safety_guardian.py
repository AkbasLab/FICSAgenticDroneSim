"""Independent runtime-safety guardian (Phase 11).

Every command an agent proposes passes through here before it reaches the
vehicle. The guardian is **deterministic and auditable by design** — it contains
no model, no learned component and no randomness. Given the same command and the
same belief it always returns the same verdict, and it can always say which
named check failed and why.

That is the whole point. A guardrail implemented as a second language model
inherits exactly the failure modes it is meant to contain: it can be wrong in
novel ways, cannot be exhaustively tested, and cannot explain itself in terms an
auditor can check. A fixed list of bounded predicates can be.

The guardian sits *outside* the policy, so it holds regardless of what proposed
the command — the deterministic rule policy, a future LLM policy, or a
deliberately malformed command injected by a test. It has no authority to invent
new work; it may only approve, narrow, refuse, or substitute one of a small set
of pre-agreed safe fallbacks.

Structure:
  SafetyLimits   - the numeric envelope (altitude, geofence, speed, reserve...)
  SafetyCheck    - one named predicate's result
  GuardianOutcome- APPROVE / APPROVE_WITH_MODIFICATION / REJECT_AND_REPLAN /
                   EXECUTE_SAFE_FALLBACK
  FallbackAction - the five permitted fallbacks
  SafetyGuardian - runs the checks, decides the outcome, records the decision
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..control import skills as sk
from ..core.geometry import point_in_polygon
from ..core.models import Position3D


# --- 11.2 outcomes ---


class GuardianOutcome(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_MODIFICATION = "approve_with_modification"
    REJECT_AND_REPLAN = "reject_and_replan"
    EXECUTE_SAFE_FALLBACK = "execute_safe_fallback"


# --- 11.3 fallbacks ---


class FallbackAction(str, Enum):
    HOLD_POSITION = "hold_position"
    CLIMB_OR_DESCEND_TO_SAFE_LAYER = "climb_or_descend_to_safe_layer"
    RETURN_HOME = "return_home"
    LAND_AT_SAFE_LOCATION = "land_at_safe_location"
    CONTINUE_LAST_VALID_PLAN = "continue_last_valid_plan"


class FlightPhase(str, Enum):
    ON_GROUND = "on_ground"
    CLIMBING = "climbing"
    CRUISING = "cruising"
    RETURNING = "returning"
    LANDING = "landing"


# --- the envelope ---


@dataclass
class SafetyLimits:
    """The numeric envelope. Everything here is a hard bound, not a preference."""
    # altitude (NED: negative is up, so min_altitude is the *most negative*)
    max_altitude: float = -3.0        # no closer to the ground than 3 m while flying
    min_altitude: float = -60.0       # no higher than 60 m
    safe_layer_altitude: float = -12.0  # the layer to move to when deconflicting

    # geofence, as an axis-aligned box in metres
    geofence_min_x: float = -120.0
    geofence_max_x: float = 120.0
    geofence_min_y: float = -120.0
    geofence_max_y: float = 120.0

    max_speed_mps: float = 12.0
    min_battery_reserve_frac: float = 0.10   # never start work below this
    max_command_timeout_s: float = 900.0
    min_separation_m: float = 3.0
    max_waypoint_range_m: float = 300.0      # sanity bound on coordinates

    restricted_zones: List[Any] = field(default_factory=list)
    home: Optional[Position3D] = None

    def inside_geofence(self, p: Position3D) -> bool:
        return (self.geofence_min_x <= p.x <= self.geofence_max_x
                and self.geofence_min_y <= p.y <= self.geofence_max_y)

    @staticmethod
    def from_scenario(scenario, margin_m=40.0):
        """Build limits from a scenario: geofence around the sectors, plus its
        restricted zones and separation requirement."""
        xs, ys = [], []
        for s in scenario.sectors:
            r = s.footprint
            xs += [r.min_x, r.max_x]
            ys += [r.min_y, r.max_y]
        base = scenario.base.position
        xs.append(base.x)
        ys.append(base.y)
        return SafetyLimits(
            geofence_min_x=min(xs) - margin_m, geofence_max_x=max(xs) + margin_m,
            geofence_min_y=min(ys) - margin_m, geofence_max_y=max(ys) + margin_m,
            min_separation_m=scenario.mission.min_separation_m,
            restricted_zones=list(scenario.restricted_zones),
            home=base)


# --- results ---


@dataclass
class SafetyCheck:
    name: str
    passed: bool
    detail: str = ""
    severity: str = "hard"      # "hard" = cannot be modified around, "soft" = fixable

    def __str__(self):
        return f"{'OK  ' if self.passed else 'FAIL'} {self.name}: {self.detail}"


@dataclass
class GuardianDecision:
    outcome: GuardianOutcome
    command: Any                       # what should actually be executed (may differ)
    proposed: Any = None               # what the agent asked for
    checks: List[SafetyCheck] = field(default_factory=list)
    fallback: Optional[FallbackAction] = None
    reason: str = ""

    @property
    def failed(self):
        return [c for c in self.checks if not c.passed]

    @property
    def approved_unchanged(self):
        return self.outcome is GuardianOutcome.APPROVE

    @property
    def blocked(self):
        """The proposed command did NOT reach the vehicle as written."""
        return self.outcome is not GuardianOutcome.APPROVE


# --- the guardian ---


class SafetyGuardian:
    """Deterministic pre-execution safety layer. No model, no randomness."""

    #: consecutive rejections before the guardian stops asking for a replan.
    #: REJECT_AND_REPLAN assumes the policy can produce something better next
    #: time. A permanently broken policy never will, and an agent that is asked
    #: to replan forever stays airborne forever - contained, but not safe. After
    #: this many rejections in a row with nothing valid in between, the guardian
    #: stops negotiating and flies the aircraft home itself.
    MAX_CONSECUTIVE_REJECTIONS = 3

    #: consecutive *interventions* - rejections, clamps and fallbacks alike -
    #: before the same escalation fires.
    #:
    #: Counting rejections alone is evadable, and a live run proved it: a policy
    #: alternating an out-of-bounds waypoint (rejected) with a 120 m/s speed
    #: (clamped and approved) resets the rejection counter every other command
    #: and can keep a drone airborne indefinitely while never once being
    #: rejected three times in a row. A clamp is not a success - it still means
    #: the policy proposed something unflyable - so the counter that matters
    #: resets only on a command that passed every check untouched.
    MAX_CONSECUTIVE_INTERVENTIONS = 5

    def __init__(self, limits: SafetyLimits = None, log=None,
                 max_consecutive_rejections=None,
                 max_consecutive_interventions=None):
        self.limits = limits or SafetyLimits()
        self.log = log
        self.last_valid_command = None
        self._active_command = None      # for the conflicting-command check
        self.max_consecutive_rejections = (
            self.MAX_CONSECUTIVE_REJECTIONS if max_consecutive_rejections is None
            else max_consecutive_rejections)
        self.max_consecutive_interventions = (
            self.MAX_CONSECUTIVE_INTERVENTIONS if max_consecutive_interventions is None
            else max_consecutive_interventions)
        self.consecutive_rejections = 0
        self.consecutive_interventions = 0

    # --- entry point ---

    def evaluate(self, command, belief) -> GuardianDecision:
        checks = self.run_checks(command, belief)
        failures = [c for c in checks if not c.passed]

        if not failures:
            self.last_valid_command = command
            decision = GuardianDecision(
                outcome=GuardianOutcome.APPROVE, command=command,
                proposed=command, checks=checks, reason="all checks passed")
        else:
            decision = self._handle_failures(command, belief, checks, failures)

        # a policy that keeps proposing unsafe commands is not going to replan
        # its way out; the counters are what turn endless rejection into action.
        if decision.outcome is GuardianOutcome.REJECT_AND_REPLAN:
            self.consecutive_rejections += 1
        else:
            self.consecutive_rejections = 0

        if decision.outcome is GuardianOutcome.APPROVE:
            self.consecutive_interventions = 0
        else:
            self.consecutive_interventions += 1

        if self.log is not None:
            self.log.record(decision, belief)
        return decision

    # --- 11.1 the checks ---

    def run_checks(self, command, belief) -> List[SafetyCheck]:
        """Run every applicable check. Always returns all of them, passed or not,
        so the log shows what was verified as well as what failed."""
        L = self.limits
        checks = [
            self._check_command_timeout(command),
            self._check_max_speed(command),
            self._check_battery_reserve(command, belief),
            self._check_conflicting_commands(command),
        ]
        target = _target_of(command)
        if target is not None:
            checks += [
                self._check_waypoint_validity(target),
                self._check_altitude_bounds(command, target),
                self._check_geofence(target),
                self._check_restricted_zones(target, belief),
                self._check_separation(target, belief),
            ]
        if isinstance(command, sk.LandCommand):
            checks.append(self._check_landing_site(belief))
        return checks

    def _check_altitude_bounds(self, command, target) -> SafetyCheck:
        L = self.limits
        z = target.z
        # NED: more negative is higher. max_altitude is the floor, min is ceiling.
        if z > L.max_altitude:
            return SafetyCheck("altitude_bounds", False,
                               f"z={z:.1f} is below the {L.max_altitude:.1f} floor",
                               severity="soft")
        if z < L.min_altitude:
            return SafetyCheck("altitude_bounds", False,
                               f"z={z:.1f} is above the {L.min_altitude:.1f} ceiling",
                               severity="soft")
        return SafetyCheck("altitude_bounds", True, f"z={z:.1f}")

    def _check_geofence(self, target) -> SafetyCheck:
        if self.limits.inside_geofence(target):
            return SafetyCheck("geofence", True,
                               f"({target.x:.0f},{target.y:.0f}) inside")
        return SafetyCheck("geofence", False,
                           f"({target.x:.0f},{target.y:.0f}) outside the geofence")

    def _check_restricted_zones(self, target, belief) -> SafetyCheck:
        zones = self.limits.restricted_zones or list(
            getattr(belief.local_map, "restricted_zones", []) or [])
        for z in zones:
            poly = getattr(z, "polygon", None)
            if poly and point_in_polygon(target.x, target.y, poly):
                return SafetyCheck("restricted_zones", False,
                                   f"target is inside {getattr(z, 'zone_id', 'zone')}")
        return SafetyCheck("restricted_zones", True, f"{len(zones)} zone(s) clear")

    def _check_waypoint_validity(self, target) -> SafetyCheck:
        for name, v in (("x", target.x), ("y", target.y), ("z", target.z)):
            if v is None or math.isnan(v) or math.isinf(v):
                return SafetyCheck("waypoint_validity", False,
                                   f"{name} is not a finite number ({v})")
        r = math.hypot(target.x, target.y)
        if r > self.limits.max_waypoint_range_m:
            return SafetyCheck("waypoint_validity", False,
                               f"{r:.0f} m from origin exceeds the "
                               f"{self.limits.max_waypoint_range_m:.0f} m bound")
        return SafetyCheck("waypoint_validity", True, "finite and in range")

    def _check_max_speed(self, command) -> SafetyCheck:
        speed = getattr(command, "speed_mps", None)
        if speed is None:
            return SafetyCheck("max_speed", True, "n/a")
        if speed <= 0 or math.isnan(speed) or math.isinf(speed):
            return SafetyCheck("max_speed", False, f"invalid speed {speed}",
                               severity="soft")
        if speed > self.limits.max_speed_mps:
            return SafetyCheck("max_speed", False,
                               f"{speed:.1f} exceeds "
                               f"{self.limits.max_speed_mps:.1f} m/s",
                               severity="soft")
        return SafetyCheck("max_speed", True, f"{speed:.1f} m/s")

    def _check_battery_reserve(self, command, belief) -> SafetyCheck:
        frac = belief.battery_frac
        reserve = self.limits.min_battery_reserve_frac
        extends = isinstance(command, (sk.SearchRegionCommand,
                                       sk.GoToWaypointCommand,
                                       sk.FollowWaypointsCommand,
                                       sk.InspectPointCommand,
                                       sk.TakeOffCommand))
        if extends and frac < reserve:
            return SafetyCheck("battery_reserve", False,
                               f"{frac:.0%} below the {reserve:.0%} reserve")
        return SafetyCheck("battery_reserve", True, f"{frac:.0%}")

    def _check_command_timeout(self, command) -> SafetyCheck:
        t = getattr(command, "timeout_s", None)
        if t is None:
            return SafetyCheck("command_timeout", True, "n/a")
        if t <= 0 or math.isnan(t) or math.isinf(t):
            return SafetyCheck("command_timeout", False, f"invalid timeout {t}",
                               severity="soft")
        if t > self.limits.max_command_timeout_s:
            return SafetyCheck("command_timeout", False,
                               f"{t:.0f}s exceeds the "
                               f"{self.limits.max_command_timeout_s:.0f}s bound",
                               severity="soft")
        return SafetyCheck("command_timeout", True, f"{t:.0f}s")

    def _check_separation(self, target, belief) -> SafetyCheck:
        """Against teammates we currently believe in - stale records are ignored,
        because acting on a two-minute-old position is its own hazard."""
        now = belief.now
        closest, who = None, None
        for vid, rec in belief.team.teammates.items():
            if rec.last_position is None or rec.is_stale(now):
                continue
            d = target.horizontal_distance_to(rec.last_position)
            if closest is None or d < closest:
                closest, who = d, vid
        if closest is None:
            return SafetyCheck("separation", True, "no fresh teammate positions")
        if closest < self.limits.min_separation_m:
            return SafetyCheck("separation", False,
                               f"{closest:.1f} m from {who}, minimum is "
                               f"{self.limits.min_separation_m:.1f} m")
        return SafetyCheck("separation", True, f"{closest:.1f} m from {who}")

    def _check_landing_site(self, belief) -> SafetyCheck:
        """A landing is only safe if where we are standing is legal to land on."""
        p = belief.position
        if not self.limits.inside_geofence(p):
            return SafetyCheck("landing_site", False,
                               "current position is outside the geofence")
        zones = self.limits.restricted_zones or list(
            getattr(belief.local_map, "restricted_zones", []) or [])
        for z in zones:
            poly = getattr(z, "polygon", None)
            if poly and point_in_polygon(p.x, p.y, poly):
                return SafetyCheck("landing_site", False,
                                   f"inside {getattr(z, 'zone_id', 'zone')}")
        return SafetyCheck("landing_site", True, "clear")

    def _check_conflicting_commands(self, command) -> SafetyCheck:
        """One vehicle, one command. A second command issued while another is
        still open is a controller bug, and executing both is how drones end up
        fighting themselves."""
        if self._active_command is None:
            return SafetyCheck("conflicting_commands", True, "no command in flight")
        return SafetyCheck("conflicting_commands", False,
                           f"{_name(self._active_command)} is still active")

    # --- lifecycle, for the conflicting-command check ---

    def begin(self, command):
        self._active_command = command

    def end(self, command=None):
        self._active_command = None

    # --- 11.2 / 11.3 deciding what to do about a failure ---

    def _handle_failures(self, command, belief, checks, failures):
        hard = [c for c in failures if c.severity == "hard"]
        soft = [c for c in failures if c.severity == "soft"]

        # only soft failures - try to narrow the command into the envelope
        if not hard:
            modified = self._modify(command, soft)
            if modified is not None:
                self.last_valid_command = modified
                return GuardianDecision(
                    outcome=GuardianOutcome.APPROVE_WITH_MODIFICATION,
                    command=modified, proposed=command, checks=checks,
                    reason="clamped to the safety envelope: "
                           + "; ".join(c.name for c in soft))

        # a hard failure that the agent could reasonably replan around
        replannable = {"restricted_zones", "geofence", "separation",
                       "waypoint_validity"}
        if hard and all(c.name in replannable for c in hard) and self._can_replan(belief):
            return GuardianDecision(
                outcome=GuardianOutcome.REJECT_AND_REPLAN,
                command=None, proposed=command, checks=checks,
                reason="rejected: " + "; ".join(f"{c.name} ({c.detail})"
                                                for c in hard))

        # otherwise substitute a fallback
        escalated = self._escalating()
        fallback = self._select_fallback(belief, failures, escalated=escalated)
        prefix = (f"escalated after {self.consecutive_rejections} consecutive "
                  f"rejections / {self.consecutive_interventions} consecutive "
                  f"interventions; " if escalated else "")
        return GuardianDecision(
            outcome=GuardianOutcome.EXECUTE_SAFE_FALLBACK,
            command=self._fallback_command(fallback, belief),
            proposed=command, checks=checks, fallback=fallback,
            reason=prefix + f"{fallback.value} after: "
                   + "; ".join(f"{c.name} ({c.detail})" for c in failures))

    def _modify(self, command, soft_failures):
        """Clamp a command into the envelope. Only narrows; never widens."""
        import copy
        L = self.limits
        out = copy.deepcopy(command)
        changed = False
        for c in soft_failures:
            if c.name == "max_speed":
                out.speed_mps = L.max_speed_mps
                changed = True
            elif c.name == "command_timeout":
                out.timeout_s = L.max_command_timeout_s
                changed = True
            elif c.name == "altitude_bounds":
                target = _target_of(out)
                if target is not None:
                    z = min(max(target.z, L.min_altitude), L.max_altitude)
                    _set_target_z(out, z)
                    changed = True
                elif hasattr(out, "target_altitude"):
                    out.target_altitude = min(max(out.target_altitude,
                                                  L.min_altitude), L.max_altitude)
                    changed = True
        return out if changed else None

    def _can_replan(self, belief):
        """Replanning only helps if the agent is in a position to try again -
        and if there is any reason left to believe the policy will do better.

        After `max_consecutive_rejections` rejections with no valid command in
        between, there is not. Asking a broken policy to try once more is how a
        drone ends up holding station until the battery decides the outcome.
        """
        if self._escalating():
            return False
        return belief.airborne and not belief.critical_battery

    def _escalating(self):
        """True once the policy has failed often enough that further negotiation
        is not warranted. Either counter alone is sufficient."""
        return (self.consecutive_rejections >= self.max_consecutive_rejections
                or self.consecutive_interventions >= self.max_consecutive_interventions)

    def _select_fallback(self, belief, failures, escalated=False) -> FallbackAction:
        """11.3 - choose by flight phase, battery, comms, hazards and certainty."""
        phase = self.flight_phase(belief)
        names = {c.name for c in failures}

        # battery first: nothing else matters if we cannot stay up
        if belief.critical_battery:
            return FallbackAction.LAND_AT_SAFE_LOCATION
        if belief.low_battery or "battery_reserve" in names:
            return FallbackAction.RETURN_HOME

        # on the ground, the safe thing is to stay there
        if phase is FlightPhase.ON_GROUND:
            return FallbackAction.HOLD_POSITION

        # escalation: the policy has been rejected repeatedly and is not
        # recovering. Do not hold, and do not repeat its last good command -
        # terminate the mission under the guardian's own authority.
        if escalated:
            return (FallbackAction.LAND_AT_SAFE_LOCATION if belief.near_home
                    else FallbackAction.RETURN_HOME)

        # a separation problem is resolved by changing layer, not by stopping
        if "separation" in names:
            return FallbackAction.CLIMB_OR_DESCEND_TO_SAFE_LAYER

        # out of bounds or in a hazard: come home rather than hover there
        if names & {"geofence", "restricted_zones", "landing_site"}:
            return FallbackAction.RETURN_HOME

        # out of contact and unsure of the team: returning is the conservative act
        comms = belief.communication
        if not comms.base_reachable and self._belief_uncertain(belief):
            return FallbackAction.RETURN_HOME

        # a malformed command with an otherwise-healthy aircraft: if we have a
        # known-good previous command, repeat it; else hold
        if "waypoint_validity" in names or "conflicting_commands" in names:
            if self.last_valid_command is not None:
                return FallbackAction.CONTINUE_LAST_VALID_PLAN
            return FallbackAction.HOLD_POSITION

        return FallbackAction.HOLD_POSITION

    def _belief_uncertain(self, belief):
        """True when the agent's picture of the team is mostly stale."""
        mates = belief.team.teammates
        if not mates:
            return True
        stale = sum(1 for r in mates.values() if r.is_stale(belief.now))
        return stale >= max(1, len(mates) // 2)

    def _fallback_command(self, fallback, belief):
        L = self.limits
        home = L.home or belief.home
        if fallback is FallbackAction.HOLD_POSITION:
            return sk.HoldPositionCommand(duration_s=5.0)
        if fallback is FallbackAction.CLIMB_OR_DESCEND_TO_SAFE_LAYER:
            p = belief.position
            return sk.GoToWaypointCommand(
                waypoint=Position3D(p.x, p.y, L.safe_layer_altitude),
                speed_mps=min(3.0, L.max_speed_mps), timeout_s=60.0)
        if fallback is FallbackAction.RETURN_HOME:
            return sk.ReturnHomeCommand(
                home=Position3D(home.x, home.y, belief.cruise_altitude),
                speed_mps=min(4.0, L.max_speed_mps), timeout_s=300.0)
        if fallback is FallbackAction.LAND_AT_SAFE_LOCATION:
            return sk.LandCommand(timeout_s=120.0)
        if fallback is FallbackAction.CONTINUE_LAST_VALID_PLAN:
            return self.last_valid_command or sk.HoldPositionCommand(duration_s=5.0)
        return sk.HoldPositionCommand(duration_s=5.0)

    # --- helpers ---

    def flight_phase(self, belief) -> FlightPhase:
        if belief.landed or not belief.airborne:
            return FlightPhase.ON_GROUND
        if getattr(belief, "rtb_forced", False):
            return FlightPhase.RETURNING
        obj = getattr(belief, "last_objective", None)
        name = getattr(obj, "value", str(obj or ""))
        if name == "take_off":
            return FlightPhase.CLIMBING
        if name == "land":
            return FlightPhase.LANDING
        if name == "return_home":
            return FlightPhase.RETURNING
        return FlightPhase.CRUISING


# --- module helpers ---


def _target_of(command) -> Optional[Position3D]:
    """The point a command would send the drone to, if it has one."""
    for attr in ("waypoint", "point", "position", "home"):
        p = getattr(command, attr, None)
        if p is not None:
            return p
    wps = getattr(command, "waypoints", None)
    if wps:
        return wps[-1]
    if isinstance(command, sk.SearchRegionCommand):
        return Position3D(command.min_x, command.min_y, command.altitude)
    return None


def _set_target_z(command, z):
    for attr in ("waypoint", "point", "position", "home"):
        p = getattr(command, attr, None)
        if p is not None:
            setattr(command, attr, Position3D(p.x, p.y, z))
            return
    if isinstance(command, sk.SearchRegionCommand):
        command.altitude = z


def _name(command):
    st = getattr(command, "skill_type", None)
    return getattr(st, "value", type(command).__name__)
