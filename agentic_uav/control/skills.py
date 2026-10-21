"""The eleven mission-level skills, their contracts, and what they report.

AUV-04 (3.1, 3.3): replace low-level directional commands, as the interface
an agent sees, with skills that say what a drone should achieve -- take off,
go to a waypoint, search a region -- each with a formal contract and a
STRUCTURED RESULT. "An agent cannot recognise failure and decide what to do
next if the layer beneath it only prints to a console." Every skill here
returns a `SkillResult` whose `status` is success, failed, aborted or
timeout, and never raises for a flight that went wrong.

    TAKE_OFF          GO_TO_WAYPOINT     FOLLOW_WAYPOINTS
    SEARCH_REGION     INSPECT_POINT      HOLD_POSITION
    RENDEZVOUS        ACT_AS_RELAY       RETURN_HOME
    LAND              EMERGENCY_HOLD

LAYERING. A skill is written once, against `VehicleAdapter`, so the same code
flies AirSim or the mock. It reaches the simulator only through primitives
(`PrimitiveCommand`), measures time only on a `Clock`, and converts heights
only through `navigation`: a command speaks metres above the ground, never
NED. Two Phase 1 lessons the baseline's executor learnt are kept here:

* The ground is measured with the drone at rest and UNCONTROLLED. An armed
  drone is held wherever it is, so measuring after taking control measures
  a hover -- one run was 17 m wrong that way.
* This build has no terrain collision, so a landing descends slowly to the
  remembered ground and is then VERIFIED: both calls can return without the
  aircraft having moved.

RELAY AND RENDEZVOUS are geometric in Phase 3: go to a point and hold, until
a deadline for a rendezvous. What makes them relay and rendezvous --
messages -- arrives with Phases 7 and 9.

ABORT. Another thread calls `SkillRunner.request_abort`, which cancels the
movement in progress (on that thread's own adapter, for AirSim). The skill
then does what its contract's abort behaviour says -- hold position -- and
returns `aborted`. `EMERGENCY_HOLD` is the same thing as a skill.

KNOWN LIMIT. Altitude is measured from the ground at take-off. There is no
terrain map, so over higher or lower terrain "8 m up" is relative to the
take-off point, exactly as in the baseline.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, ClassVar

from ..core.clock import Clock, RealClock
from ..core.models import Position, PrimitiveCommand
from ..core.protocol import CRUISE_ALTITUDE, MOVE_SPEED
from ..simulator.adapter import VehicleAdapter
from . import navigation as nav
from .navigation import Region, Waypoint

# --------------------------------------------------------------- constants
#
# Defaults agree with the baseline's executor, which Phase 1 measured.

DEFAULT_SPEED_MPS = MOVE_SPEED               # 5 m/s, as the baseline flies
DEFAULT_TAKEOFF_ALTITUDE_M = -CRUISE_ALTITUDE  # 8 m, the baseline's cruise height
DEFAULT_TOLERANCE_M = 1.0                    # arrival sphere radius
MAX_SPEED_MPS = 20.0
MIN_FLIGHT_ALTITUDE_M = 2.0                  # below this a waypoint is the ground (plan schema: -2)
MAX_ALTITUDE_M = 120.0                       # plan schema: -120
AIRBORNE_ALTITUDE_M = 1.0                    # executor AIRBORNE_MARGIN
LANDED_ALTITUDE_M = 3.0                      # executor LANDED_AGL_MAX: above this, land did not land
LANDING_DESCENT_SPEED_MPS = 2.0              # as the baseline descends before landAsync
LANDING_DESCENT_STOP_M = 1.0                 # descend to the ground minus this, as the baseline does
TAKEOFF_SETTLE_S = 3.0                       # executor TAKEOFF_SETTLE
GROUND_SETTLE_TIMEOUT_S = 15.0               # executor GROUND_SETTLE_TIMEOUT
GROUND_SETTLE_TOLERANCE_M = 0.05             # executor GROUND_SETTLE_TOLERANCE
GROUND_SETTLE_INTERVAL_S = 0.3
HEADING_TOLERANCE_DEG = 5.0                  # AirSim's own rotateToYaw margin
TIMEOUT_FACTOR = 2.0                         # default timeout: twice the travel time...
TIMEOUT_MARGIN_S = 10.0                      # ...plus this
LAND_TIMEOUT_S = 60.0                        # executor LAND_DESCENT_TIMEOUT + LAND_TIMEOUT, rounded
HOLD_SLICE_S = 0.5                           # how often a hold looks for an abort


# ------------------------------------------------------------- vocabulary

class SkillName(str, Enum):
    TAKE_OFF = "TAKE_OFF"
    GO_TO_WAYPOINT = "GO_TO_WAYPOINT"
    FOLLOW_WAYPOINTS = "FOLLOW_WAYPOINTS"
    SEARCH_REGION = "SEARCH_REGION"
    INSPECT_POINT = "INSPECT_POINT"
    HOLD_POSITION = "HOLD_POSITION"
    RENDEZVOUS = "RENDEZVOUS"
    ACT_AS_RELAY = "ACT_AS_RELAY"
    RETURN_HOME = "RETURN_HOME"
    LAND = "LAND"
    EMERGENCY_HOLD = "EMERGENCY_HOLD"


class SkillStatus(str, Enum):
    """AUV-04's four states. Each maps onto a replanning trigger in Phase 5."""

    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"
    TIMEOUT = "timeout"


class ErrorCode(str, Enum):
    PRECONDITION_FAILED = "PRECONDITION_FAILED"   # not in a state to start
    NOT_REACHED = "NOT_REACHED"                   # finished short of the target
    HEADING_NOT_REACHED = "HEADING_NOT_REACHED"
    TIMEOUT = "TIMEOUT"                           # the skill's time ran out
    LATE = "LATE"                                 # a rendezvous reached after its deadline
    LANDING_FAILED = "LANDING_FAILED"             # landed nowhere near the ground
    ABORTED = "ABORTED"
    SIMULATOR_ERROR = "SIMULATOR_ERROR"           # a primitive raised


@dataclass(frozen=True)
class SkillResult:
    """What a skill did. AUV-04, 3.3, plus what a reader needs to act on it.

    Positions are NED as the simulator reports them, and `final_altitude_m`
    is the same point as metres above the take-off ground, so neither has to
    be converted to be read. `details` carries what is particular to a skill
    -- the legs of a waypoint list, the drift during a hold.
    """

    skill: SkillName
    vehicle_id: str
    status: SkillStatus
    started_at: float
    ended_at: float
    final_position: Position | None = None
    final_altitude_m: float | None = None
    final_yaw_deg: float | None = None
    error_code: ErrorCode | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is SkillStatus.SUCCESS

    @property
    def duration_s(self) -> float:
        return self.ended_at - self.started_at

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["skill"] = self.skill.value
        out["status"] = self.status.value
        out["error_code"] = None if self.error_code is None else self.error_code.value
        return out


# --------------------------------------------------------------- commands
#
# One command per skill, validated when it is built: an impossible command is
# refused before any drone moves, the way the planner refuses an invalid plan.

def _speed(v: float) -> None:
    if not 0 < v <= MAX_SPEED_MPS:
        raise ValueError(f"speed {v} m/s outside (0, {MAX_SPEED_MPS}]")


def _positive(name: str, v: float | None, allow_none: bool = True) -> None:
    if v is None and allow_none:
        return
    if v is None or v <= 0:
        raise ValueError(f"{name} must be positive, got {v}")


def _not_negative(name: str, v: float) -> None:
    if v < 0:
        raise ValueError(f"{name} cannot be negative, got {v}")


def _flight_altitude(v: float) -> None:
    if not MIN_FLIGHT_ALTITUDE_M <= v <= MAX_ALTITUDE_M:
        raise ValueError(f"altitude {v} m outside [{MIN_FLIGHT_ALTITUDE_M}, {MAX_ALTITUDE_M}]")


def _waypoint(wp: Waypoint) -> None:
    if not isinstance(wp, Waypoint):
        raise ValueError(f"expected a Waypoint, got {type(wp).__name__}")
    _flight_altitude(wp.altitude_m)


@dataclass(frozen=True)
class SkillCommand:
    """Base of every skill's command. `skill` names the skill it is for."""

    skill: ClassVar[SkillName]


@dataclass(frozen=True)
class TakeOffCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.TAKE_OFF
    altitude_m: float = DEFAULT_TAKEOFF_ALTITUDE_M
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        _flight_altitude(self.altitude_m)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class GoToWaypointCommand(SkillCommand):
    """AUV-04's example command, with an optional heading to face on arrival."""

    skill: ClassVar[SkillName] = SkillName.GO_TO_WAYPOINT
    waypoint: Waypoint = None  # type: ignore[assignment]
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None
    heading_deg: float | None = None

    def __post_init__(self) -> None:
        _waypoint(self.waypoint)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class FollowWaypointsCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.FOLLOW_WAYPOINTS
    waypoints: tuple[Waypoint, ...] = ()
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None          # for the whole list

    def __post_init__(self) -> None:
        object.__setattr__(self, "waypoints", tuple(self.waypoints))
        if not self.waypoints:
            raise ValueError("a waypoint list needs at least one waypoint")
        for wp in self.waypoints:
            _waypoint(wp)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class SearchRegionCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.SEARCH_REGION
    region: Region = None  # type: ignore[assignment]
    altitude_m: float = 15.0
    spacing_m: float = 10.0                 # lane spacing: the sensor footprint's width
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region, Region):
            raise ValueError("SEARCH_REGION needs a Region")
        _flight_altitude(self.altitude_m)
        _positive("spacing_m", self.spacing_m, allow_none=False)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class InspectPointCommand(SkillCommand):
    """Fly to `standoff_m` from `target`, at `altitude_m`, face it, and dwell."""

    skill: ClassVar[SkillName] = SkillName.INSPECT_POINT
    target: Waypoint = None  # type: ignore[assignment]   altitude 0 is a point on the ground
    altitude_m: float = 10.0
    standoff_m: float = 5.0
    dwell_s: float = 3.0
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, Waypoint):
            raise ValueError("INSPECT_POINT needs a target Waypoint")
        _flight_altitude(self.altitude_m)
        _not_negative("standoff_m", self.standoff_m)
        _not_negative("dwell_s", self.dwell_s)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class HoldPositionCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.HOLD_POSITION
    duration_s: float = 5.0

    def __post_init__(self) -> None:
        _not_negative("duration_s", self.duration_s)


@dataclass(frozen=True)
class RendezvousCommand(SkillCommand):
    """Be at `waypoint` by `arrive_by`, then hold until `hold_until` (clock times)."""

    skill: ClassVar[SkillName] = SkillName.RENDEZVOUS
    waypoint: Waypoint = None  # type: ignore[assignment]
    arrive_by: float | None = None
    hold_until: float | None = None
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        _waypoint(self.waypoint)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)
        if (self.arrive_by is not None and self.hold_until is not None
                and self.hold_until < self.arrive_by):
            raise ValueError("hold_until is before arrive_by")


@dataclass(frozen=True)
class ActAsRelayCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.ACT_AS_RELAY
    waypoint: Waypoint = None  # type: ignore[assignment]
    duration_s: float = 30.0
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None          # to reach the relay point

    def __post_init__(self) -> None:
        _waypoint(self.waypoint)
        _not_negative("duration_s", self.duration_s)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class ReturnHomeCommand(SkillCommand):
    """Fly back over the take-off point. `altitude_m` None keeps the current height."""

    skill: ClassVar[SkillName] = SkillName.RETURN_HOME
    altitude_m: float | None = None
    speed_mps: float = DEFAULT_SPEED_MPS
    tolerance_m: float = DEFAULT_TOLERANCE_M
    timeout_s: float | None = None

    def __post_init__(self) -> None:
        if self.altitude_m is not None:
            _flight_altitude(self.altitude_m)
        _speed(self.speed_mps)
        _positive("tolerance_m", self.tolerance_m, allow_none=False)
        _positive("timeout_s", self.timeout_s)


@dataclass(frozen=True)
class LandCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.LAND
    timeout_s: float = LAND_TIMEOUT_S

    def __post_init__(self) -> None:
        _positive("timeout_s", self.timeout_s, allow_none=False)


@dataclass(frozen=True)
class EmergencyHoldCommand(SkillCommand):
    skill: ClassVar[SkillName] = SkillName.EMERGENCY_HOLD


# -------------------------------------------------------------- contracts

@dataclass(frozen=True)
class SkillContract:
    """AUV-04, 3.3: what a skill needs, promises and does when stopped."""

    skill: SkillName
    command: type
    parameters: str
    preconditions: str
    success: str
    failure: str
    timeout: str
    abort: str
    state_change: str


_TRAVEL_TIMEOUT = (f"the command's `timeout_s`, or by default {TIMEOUT_FACTOR:g} x the "
                   f"straight-line travel time at the commanded speed + {TIMEOUT_MARGIN_S:g} s")
_AIRBORNE = (f"under API control and airborne: more than {AIRBORNE_ALTITUDE_M:g} m above "
             "the take-off ground")
_HOLD_ON_ABORT = "cancel the movement in progress and hold position where the drone is"

CONTRACTS: dict[SkillName, SkillContract] = {c.skill: c for c in (
    SkillContract(
        SkillName.TAKE_OFF, TakeOffCommand,
        parameters=f"altitude_m (default {DEFAULT_TAKEOFF_ALTITUDE_M:g}, within "
                   f"[{MIN_FLIGHT_ALTITUDE_M:g}, {MAX_ALTITUDE_M:g}]), speed_mps, tolerance_m, timeout_s",
        preconditions="on the ground, NOT under API control, so the ground can be measured at rest "
                      "(an armed drone is held wherever it is); or, if a ground is already known, "
                      f"no more than {AIRBORNE_ALTITUDE_M:g} m above it",
        success="within tolerance_m of altitude_m above the measured ground",
        failure="altitude not reached; the ground never settled; a primitive raised",
        timeout=f"{_TRAVEL_TIMEOUT}, for the climb",
        abort=_HOLD_ON_ABORT,
        state_change="under API control, armed, airborne at altitude_m; the take-off point "
                     "becomes this drone's home",
    ),
    SkillContract(
        SkillName.GO_TO_WAYPOINT, GoToWaypointCommand,
        parameters="waypoint (x, y, altitude_m above the ground), speed_mps, tolerance_m, "
                   "timeout_s, heading_deg (optional, faced on arrival)",
        preconditions=_AIRBORNE,
        success="within tolerance_m of the waypoint (3D), and within "
                f"{HEADING_TOLERANCE_DEG:g} degrees of heading_deg if one was given",
        failure="arrived short of the waypoint (NOT_REACHED) or off the heading "
                "(HEADING_NOT_REACHED); a primitive raised",
        timeout=_TRAVEL_TIMEOUT,
        abort=_HOLD_ON_ABORT,
        state_change="at the waypoint, hovering",
    ),
    SkillContract(
        SkillName.FOLLOW_WAYPOINTS, FollowWaypointsCommand,
        parameters="waypoints (one or more), speed_mps, tolerance_m, timeout_s for the whole list",
        preconditions=_AIRBORNE,
        success="every waypoint reached within tolerance_m, in order",
        failure="the first leg that fails ends the list; `details.legs` says which and why",
        timeout=f"{_TRAVEL_TIMEOUT}, summed over the legs",
        abort=_HOLD_ON_ABORT,
        state_change="at the last waypoint, hovering",
    ),
    SkillContract(
        SkillName.SEARCH_REGION, SearchRegionCommand,
        parameters="region (axis-aligned rectangle), altitude_m, spacing_m (lane width), "
                   "speed_mps, tolerance_m, timeout_s",
        preconditions=_AIRBORNE,
        success="the whole lawnmower path flown: every point of the region within "
                "spacing_m/2 of a lane",
        failure="a lane not completed; `details` gives the lanes flown and the coverage fraction",
        timeout=f"{_TRAVEL_TIMEOUT}, over the whole path",
        abort=_HOLD_ON_ABORT,
        state_change="at the end of the last lane, hovering. Detection is Phase 4's, not this skill's",
    ),
    SkillContract(
        SkillName.INSPECT_POINT, InspectPointCommand,
        parameters="target (x, y, altitude_m of the point), altitude_m to inspect from, "
                   "standoff_m, dwell_s, speed_mps, tolerance_m, timeout_s",
        preconditions=_AIRBORNE,
        success="at the stand-off point within tolerance_m, facing the target within "
                f"{HEADING_TOLERANCE_DEG:g} degrees, for dwell_s",
        failure="stand-off point or heading not reached; a primitive raised",
        timeout=f"{_TRAVEL_TIMEOUT}, to the stand-off point",
        abort=_HOLD_ON_ABORT,
        state_change="at the stand-off point, facing the target, hovering",
    ),
    SkillContract(
        SkillName.HOLD_POSITION, HoldPositionCommand,
        parameters="duration_s",
        preconditions=_AIRBORNE,
        success="hovered for duration_s; `details.drift_m` says how far it moved",
        failure="a primitive raised",
        timeout="none beyond duration_s",
        abort="stop holding and return at once, still hovering",
        state_change="none: where it was, hovering",
    ),
    SkillContract(
        SkillName.RENDEZVOUS, RendezvousCommand,
        parameters="waypoint, arrive_by and hold_until (clock times, optional), speed_mps, "
                   "tolerance_m, timeout_s",
        preconditions=_AIRBORNE,
        success="at the waypoint within tolerance_m by arrive_by, then held until hold_until",
        failure="NOT_REACHED, or LATE: reached after arrive_by (it does not then hold)",
        timeout=_TRAVEL_TIMEOUT,
        abort=_HOLD_ON_ABORT,
        state_change="at the rendezvous point, hovering. Geometric in Phase 3; the meeting "
                     "itself is coordination, Phases 7 and 9",
    ),
    SkillContract(
        SkillName.ACT_AS_RELAY, ActAsRelayCommand,
        parameters="waypoint (the relay position), duration_s, speed_mps, tolerance_m, timeout_s",
        preconditions=_AIRBORNE,
        success="at the relay position within tolerance_m, held for duration_s",
        failure="relay position not reached; a primitive raised",
        timeout=f"{_TRAVEL_TIMEOUT}, to the relay position",
        abort=_HOLD_ON_ABORT,
        state_change="at the relay position, hovering. Geometric in Phase 3; relaying messages "
                     "is Phase 7's and Phase 9's",
    ),
    SkillContract(
        SkillName.RETURN_HOME, ReturnHomeCommand,
        parameters="altitude_m (optional: default the current height, at least "
                   f"{MIN_FLIGHT_ALTITUDE_M:g} m), speed_mps, tolerance_m, timeout_s",
        preconditions=f"{_AIRBORNE}; a home recorded by TAKE_OFF",
        success="over the home point within tolerance_m, at the return altitude",
        failure="home not reached; no home known (PRECONDITION_FAILED)",
        timeout=_TRAVEL_TIMEOUT,
        abort=_HOLD_ON_ABORT,
        state_change="over home, hovering. It does not land: LAND does",
    ),
    SkillContract(
        SkillName.LAND, LandCommand,
        parameters="timeout_s",
        preconditions="under API control, or already on the ground (then nothing to do)",
        success=f"no more than {LANDED_ALTITUDE_M:g} m above the take-off ground; control "
                "released",
        failure="LANDING_FAILED: still above that after descending and landing; control is "
                "then KEPT, because releasing an airborne drone cuts its motors",
        timeout="timeout_s, for the descent and the landing together",
        abort="cancel the descent and hold at the current height, keeping control",
        state_change="on the ground, disarmed, control released",
    ),
    SkillContract(
        SkillName.EMERGENCY_HOLD, EmergencyHoldCommand,
        parameters="none",
        preconditions="none: allowed in any state",
        success="the movement in progress cancelled, and hovering",
        failure="a primitive raised",
        timeout="none",
        abort="not abortable: it is the abort",
        state_change="hovering where it was when called",
    ),
)}


# ----------------------------------------------------------------- runner

class _Aborted(Exception):
    pass


class _Outcome(Exception):
    """Ends a skill with a non-success status; raised inside the handlers."""

    def __init__(self, status: SkillStatus, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class SkillRunner:
    """Runs skills for ONE drone, on ONE adapter, one skill at a time.

    `ground_z` may be given when already known (a drone already flying);
    otherwise TAKE_OFF measures it. `home` is set by TAKE_OFF, or given.
    """

    def __init__(self, vehicle: VehicleAdapter, vehicle_id: str,
                 clock: Clock | None = None, ground_z: float | None = None,
                 home: Position | None = None) -> None:
        self.vehicle = vehicle
        self.vehicle_id = vehicle_id
        self.clock = clock if clock is not None else RealClock()
        self.ground_z = ground_z
        self.home = home
        self._abort = threading.Event()
        self._handlers: dict[SkillName, Callable[[Any, dict[str, Any]], None]] = {
            SkillName.TAKE_OFF: self._take_off,
            SkillName.GO_TO_WAYPOINT: self._go_to_waypoint,
            SkillName.FOLLOW_WAYPOINTS: self._follow_waypoints,
            SkillName.SEARCH_REGION: self._search_region,
            SkillName.INSPECT_POINT: self._inspect_point,
            SkillName.HOLD_POSITION: self._hold_position,
            SkillName.RENDEZVOUS: self._rendezvous,
            SkillName.ACT_AS_RELAY: self._act_as_relay,
            SkillName.RETURN_HOME: self._return_home,
            SkillName.LAND: self._land,
            SkillName.EMERGENCY_HOLD: self._emergency_hold,
        }

    # ---------------------------------------------------------- interface

    def request_abort(self, via: VehicleAdapter | None = None) -> None:
        """Abort the skill in progress, from another thread.

        For AirSim pass `via`, an adapter on the calling thread's own
        connection: one connection per thread (Phase 1).
        """
        self._abort.set()
        (via or self.vehicle).cancel(self.vehicle_id)

    def run(self, command: SkillCommand) -> SkillResult:
        """Execute one skill to its end and report. Never raises for a flight."""
        if not isinstance(command, SkillCommand):
            raise TypeError(f"not a skill command: {command!r}")
        self._abort.clear()
        skill = command.skill
        details: dict[str, Any] = {}
        started = self.clock.now()
        status, code, message = SkillStatus.SUCCESS, None, ""
        try:
            self._handlers[skill](command, details)
        except _Aborted:
            status, code, message = SkillStatus.ABORTED, ErrorCode.ABORTED, "aborted by request"
            self._abort_behaviour(skill)
        except _Outcome as outcome:
            status, code, message = outcome.status, outcome.code, outcome.message
        except Exception as exc:            # a primitive raised: report it, word for word
            status, code = SkillStatus.FAILED, ErrorCode.SIMULATOR_ERROR
            message = f"{type(exc).__name__}: {exc}"
        return self._result(skill, status, started, code, message, details)

    # ------------------------------------------------------------ helpers

    def _result(self, skill: SkillName, status: SkillStatus, started: float,
                code: ErrorCode | None, message: str, details: dict[str, Any]) -> SkillResult:
        position = altitude = yaw = None
        try:
            position = self.vehicle.get_pose(self.vehicle_id)
            if self.ground_z is not None:
                altitude = round(nav.z_to_altitude(position.z, self.ground_z), 3)
            yaw = self.vehicle.get_state(self.vehicle_id).yaw_deg
        except Exception:
            pass
        return SkillResult(skill, self.vehicle_id, status, started, self.clock.now(),
                           position, altitude, yaw, code, message, details)

    def _check_abort(self) -> None:
        if self._abort.is_set():
            raise _Aborted()

    def _primitive(self, command: PrimitiveCommand) -> None:
        self._check_abort()
        self.vehicle.execute_primitive(self.vehicle_id, command)
        self._check_abort()

    def _pose(self) -> Position:
        return self.vehicle.get_pose(self.vehicle_id)

    def _altitude(self) -> float:
        return nav.z_to_altitude(self._pose().z, self._require_ground())

    def _require_ground(self) -> float:
        if self.ground_z is None:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           "no ground reference: TAKE_OFF first, or give ground_z")
        return self.ground_z

    def _require_airborne(self) -> None:
        self._require_ground()
        if not self.vehicle.has_control(self.vehicle_id):
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           "not under API control")
        altitude = self._altitude()
        if altitude <= AIRBORNE_ALTITUDE_M:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           f"not airborne: {altitude:.2f} m above the ground")

    def _deadline(self, timeout_s: float | None, distance_m: float, speed_mps: float) -> float:
        if timeout_s is None:
            timeout_s = TIMEOUT_FACTOR * nav.travel_time(distance_m, speed_mps) + TIMEOUT_MARGIN_S
        return self.clock.now() + timeout_s

    def _remaining(self, deadline: float) -> float:
        return max(0.001, deadline - self.clock.now())

    def _fly_to(self, target: Position, speed: float, tolerance: float, deadline: float) -> None:
        """Move to `target`; raise an _Outcome unless it arrived within tolerance."""
        self._primitive(PrimitiveCommand.move_to_position(
            target.x, target.y, target.z, speed, self._remaining(deadline)))
        here = self._pose()
        if nav.reached(here, target, tolerance):
            return
        missed = nav.distance(here, target)
        if self.clock.now() >= deadline:
            raise _Outcome(SkillStatus.TIMEOUT, ErrorCode.TIMEOUT,
                           f"out of time {missed:.2f} m from the target")
        raise _Outcome(SkillStatus.FAILED, ErrorCode.NOT_REACHED,
                       f"stopped {missed:.2f} m from the target (tolerance {tolerance} m)")

    def _face(self, heading_deg: float, deadline: float) -> None:
        self._primitive(PrimitiveCommand.rotate_to_yaw(
            nav.normalise_heading(heading_deg), self._remaining(deadline)))
        yaw = self.vehicle.get_state(self.vehicle_id).yaw_deg
        if yaw is None or abs(nav.heading_error(yaw, heading_deg)) > HEADING_TOLERANCE_DEG:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.HEADING_NOT_REACHED,
                           f"heading {yaw} after turning to {heading_deg}")

    def _hold(self, duration_s: float) -> None:
        self._primitive(PrimitiveCommand.hover())
        end = self.clock.now() + duration_s
        while True:
            self._check_abort()
            remaining = end - self.clock.now()
            if remaining <= 0:
                return
            self.clock.sleep(min(HOLD_SLICE_S, remaining))

    def _measure_ground(self) -> float:
        """The ground under an UNCONTROLLED drone at rest. See the module docstring."""
        previous = self.vehicle.get_state(self.vehicle_id).position.z
        deadline = self.clock.now() + GROUND_SETTLE_TIMEOUT_S
        while self.clock.now() < deadline:
            self.clock.sleep(GROUND_SETTLE_INTERVAL_S)
            current = self.vehicle.get_state(self.vehicle_id).position.z
            if abs(current - previous) < GROUND_SETTLE_TOLERANCE_M:
                return current
            previous = current
        raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                       f"the drone did not come to rest within {GROUND_SETTLE_TIMEOUT_S:g} s")

    def _abort_behaviour(self, skill: SkillName) -> None:
        # Every contract's abort is "hold where you are"; keep control.
        try:
            self.vehicle.execute_primitive(self.vehicle_id, PrimitiveCommand.hover())
        except Exception:
            pass

    def _leg_target(self, wp: Waypoint) -> Position:
        return wp.to_position(self._require_ground())

    def _fly_waypoints(self, waypoints: tuple[Waypoint, ...] | list[Waypoint], speed: float,
                       tolerance: float, timeout_s: float | None,
                       details: dict[str, Any]) -> None:
        targets = [self._leg_target(wp) for wp in waypoints]
        here = self._pose()
        total = sum(nav.distance(a, b) for a, b in zip([here] + targets[:-1], targets))
        deadline = self._deadline(timeout_s, total, speed)
        details["legs"] = legs = []
        details["legs_total"] = len(targets)
        for i, target in enumerate(targets):
            leg_started = self.clock.now()
            try:
                self._fly_to(target, speed, tolerance, deadline)
            except _Outcome as outcome:
                legs.append({"leg": i, "status": outcome.status.value,
                             "error_code": outcome.code.value, "message": outcome.message})
                raise
            legs.append({"leg": i, "status": SkillStatus.SUCCESS.value,
                         "seconds": round(self.clock.now() - leg_started, 3)})

    # ----------------------------------------------------------- the skills

    def _take_off(self, cmd: TakeOffCommand, details: dict[str, Any]) -> None:
        if self.ground_z is None:
            if self.vehicle.has_control(self.vehicle_id):
                raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                               "already under API control: the ground cannot be measured "
                               "(an armed drone is held wherever it is)")
            self.ground_z = self._measure_ground()
            details["ground_measured"] = True
        elif self._altitude() > AIRBORNE_ALTITUDE_M:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           f"already airborne: {self._altitude():.2f} m above the ground")
        details["ground_z"] = round(self.ground_z, 3)
        start = self._pose()
        self.home = Position(start.x, start.y, self.ground_z)
        deadline = self._deadline(cmd.timeout_s, cmd.altitude_m, cmd.speed_mps)
        self.vehicle.take_control(self.vehicle_id)
        self._primitive(PrimitiveCommand.take_off())
        target_z = nav.altitude_to_z(cmd.altitude_m, self.ground_z)
        self._primitive(PrimitiveCommand.move_to_z(target_z, cmd.speed_mps, self._remaining(deadline)))
        self._check_abort()
        self.clock.sleep(TAKEOFF_SETTLE_S)
        altitude = self._altitude()
        if abs(altitude - cmd.altitude_m) <= cmd.tolerance_m:
            return
        status = SkillStatus.TIMEOUT if self.clock.now() >= deadline else SkillStatus.FAILED
        code = ErrorCode.TIMEOUT if status is SkillStatus.TIMEOUT else ErrorCode.NOT_REACHED
        raise _Outcome(status, code, f"climbed to {altitude:.2f} m, asked {cmd.altitude_m} m")

    def _go_to_waypoint(self, cmd: GoToWaypointCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        target = self._leg_target(cmd.waypoint)
        deadline = self._deadline(cmd.timeout_s, nav.distance(self._pose(), target), cmd.speed_mps)
        self._fly_to(target, cmd.speed_mps, cmd.tolerance_m, deadline)
        if cmd.heading_deg is not None:
            self._face(cmd.heading_deg, deadline)

    def _follow_waypoints(self, cmd: FollowWaypointsCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        self._fly_waypoints(cmd.waypoints, cmd.speed_mps, cmd.tolerance_m, cmd.timeout_s, details)

    def _search_region(self, cmd: SearchRegionCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        path = nav.lawnmower(cmd.region, cmd.spacing_m, cmd.altitude_m)
        details["lanes"] = len(path) // 2
        try:
            self._fly_waypoints(path, cmd.speed_mps, cmd.tolerance_m, cmd.timeout_s, details)
        finally:
            done = sum(1 for leg in details.get("legs", []) if leg["status"] == "success")
            # A lane is complete when its far end is reached: the odd legs.
            details["lanes_completed"] = done // 2
            details["coverage"] = round(details["lanes_completed"] / details["lanes"], 3)

    def _inspect_point(self, cmd: InspectPointCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        ground = self._require_ground()
        target = cmd.target.to_position(ground)
        here = self._pose()
        origin = Position(here.x, here.y, nav.altitude_to_z(cmd.altitude_m, ground))
        stand = nav.standoff_point(target, origin, cmd.standoff_m)
        details["standoff"] = asdict(stand)
        deadline = self._deadline(cmd.timeout_s, nav.distance(here, stand), cmd.speed_mps)
        self._fly_to(stand, cmd.speed_mps, cmd.tolerance_m, deadline)
        if nav.horizontal_distance(stand, target) > 0:
            self._face(nav.heading_to(stand, target), deadline)
        self._hold(cmd.dwell_s)

    def _hold_position(self, cmd: HoldPositionCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        start = self._pose()
        self._hold(cmd.duration_s)
        details["drift_m"] = round(nav.distance(start, self._pose()), 3)

    def _rendezvous(self, cmd: RendezvousCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        target = self._leg_target(cmd.waypoint)
        deadline = self._deadline(cmd.timeout_s, nav.distance(self._pose(), target), cmd.speed_mps)
        self._fly_to(target, cmd.speed_mps, cmd.tolerance_m, deadline)
        arrived = self.clock.now()
        details["arrived_at"] = arrived
        if cmd.arrive_by is not None and arrived > cmd.arrive_by:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.LATE,
                           f"arrived {arrived - cmd.arrive_by:.2f} s after arrive_by")
        if cmd.hold_until is not None:
            self._hold(max(0.0, cmd.hold_until - self.clock.now()))

    def _act_as_relay(self, cmd: ActAsRelayCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        target = self._leg_target(cmd.waypoint)
        deadline = self._deadline(cmd.timeout_s, nav.distance(self._pose(), target), cmd.speed_mps)
        self._fly_to(target, cmd.speed_mps, cmd.tolerance_m, deadline)
        self._hold(cmd.duration_s)

    def _return_home(self, cmd: ReturnHomeCommand, details: dict[str, Any]) -> None:
        self._require_airborne()
        if self.home is None:
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           "no home: TAKE_OFF records it, or give home")
        altitude = cmd.altitude_m if cmd.altitude_m is not None else max(
            MIN_FLIGHT_ALTITUDE_M, self._altitude())
        target = Waypoint(self.home.x, self.home.y, altitude).to_position(self._require_ground())
        deadline = self._deadline(cmd.timeout_s, nav.distance(self._pose(), target), cmd.speed_mps)
        self._fly_to(target, cmd.speed_mps, cmd.tolerance_m, deadline)

    def _land(self, cmd: LandCommand, details: dict[str, Any]) -> None:
        ground = self._require_ground()
        if self._altitude() <= AIRBORNE_ALTITUDE_M and not self.vehicle.has_control(self.vehicle_id):
            details["already_on_ground"] = True
            return
        if not self.vehicle.has_control(self.vehicle_id):
            raise _Outcome(SkillStatus.FAILED, ErrorCode.PRECONDITION_FAILED,
                           "airborne but not under API control")
        deadline = self.clock.now() + cmd.timeout_s
        self._primitive(PrimitiveCommand.move_to_z(
            ground - LANDING_DESCENT_STOP_M, LANDING_DESCENT_SPEED_MPS, self._remaining(deadline)))
        self._primitive(PrimitiveCommand.land(self._remaining(deadline)))
        altitude = self._altitude()
        details["altitude_after_land_m"] = round(altitude, 3)
        if altitude > LANDED_ALTITUDE_M:
            # Never release in the air: disarming cuts the motors.
            status = SkillStatus.TIMEOUT if self.clock.now() >= deadline else SkillStatus.FAILED
            raise _Outcome(status, ErrorCode.TIMEOUT if status is SkillStatus.TIMEOUT
                           else ErrorCode.LANDING_FAILED,
                           f"{altitude:.2f} m above the ground after landing; control kept")
        self.vehicle.release(self.vehicle_id)

    def _emergency_hold(self, cmd: EmergencyHoldCommand, details: dict[str, Any]) -> None:
        # Not abortable: it is the abort. Cancel first, then brake.
        self.vehicle.cancel(self.vehicle_id)
        self.vehicle.execute_primitive(self.vehicle_id, PrimitiveCommand.hover())
