"""High-level, mission-oriented skills: their typed commands and formal contracts.

This is the agent's main interface (Phase 3.1). Each skill has:
  - a typed command dataclass (its required parameters, with sane defaults)
  - a formal SkillContract (preconditions, success/failure, timeout, abort
    behavior, expected state change)

The commands are executed by control/skill_executor.py, which enforces the
contract and returns a structured SkillResult.
"""

from dataclasses import dataclass, field
from typing import ClassVar, List

from ..core.enums import ActionType, SkillType
from ..core.models import Position3D


# --- Low-level action spec (Phase 1/2 LLM planner path, still used) ---
# action name -> required parameter names. Kept so the LLM planners can build
# their output schema and validate plans against the same source of truth.
ACTION_PARAMS = {
    ActionType.FLY_TO.value: ["x", "y", "z"],
    ActionType.FLY_STRAIGHT.value: ["duration"],
    ActionType.FLY_BACKWARD.value: ["duration"],
    ActionType.FLY_LEFT.value: ["duration"],
    ActionType.FLY_RIGHT.value: ["duration"],
    ActionType.HOVER.value: ["duration"],
    ActionType.SET_ALTITUDE.value: ["z"],
    ActionType.LAND.value: [],
}
PLANNER_ACTIONS = list(ACTION_PARAMS.keys())


def build_plan_schema():
    """JSON schema forcing an LLM planner to return {"plan": [ ...steps... ]}."""
    return {
        "type": "object",
        "properties": {
            "plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": PLANNER_ACTIONS},
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            }
        },
        "required": ["plan"],
    }

# default flight parameters (kept alongside navigation constants)
DEFAULT_ALTITUDE = -8.0     # NED: negative is up
DEFAULT_SPEED = 4.0         # m/s
DEFAULT_TOLERANCE = 1.5     # metres: how close counts as "reached"
HOME = Position3D(0.0, 0.0, DEFAULT_ALTITUDE)


@dataclass(frozen=True)
class SkillContract:
    """The formal contract a skill promises to honour (Phase 3.3)."""
    required_params: List[str]
    preconditions: str
    success_condition: str
    failure_condition: str
    timeout_s: float
    abort_behavior: str
    expected_state_change: str


# --- typed command classes, each carrying its contract ---


@dataclass
class TakeOffCommand:
    target_altitude: float = DEFAULT_ALTITUDE
    timeout_s: float = 30.0
    skill_type: ClassVar[SkillType] = SkillType.TAKE_OFF
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["target_altitude"],
        preconditions="vehicle is on the ground and idle",
        success_condition="altitude within tolerance of target_altitude",
        failure_condition="did not reach target altitude",
        timeout_s=30.0,
        abort_behavior="hold at current altitude",
        expected_state_change="airborne at cruise altitude",
    )


@dataclass
class GoToWaypointCommand:
    waypoint: Position3D
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 60.0
    skill_type: ClassVar[SkillType] = SkillType.GO_TO_WAYPOINT
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["waypoint", "speed_mps", "tolerance_m", "timeout_s"],
        preconditions="vehicle is airborne",
        success_condition="final position within tolerance_m of waypoint",
        failure_condition="not within tolerance when the move ends",
        timeout_s=60.0,
        abort_behavior="stop and hold at current position",
        expected_state_change="vehicle at the requested waypoint",
    )


@dataclass
class FollowWaypointsCommand:
    waypoints: List[Position3D] = field(default_factory=list)
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 120.0
    skill_type: ClassVar[SkillType] = SkillType.FOLLOW_WAYPOINTS
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["waypoints"],
        preconditions="vehicle is airborne; waypoints non-empty",
        success_condition="every waypoint reached within tolerance in order",
        failure_condition="any waypoint not reached; overall timeout",
        timeout_s=120.0,
        abort_behavior="stop and hold at current position",
        expected_state_change="vehicle at the final waypoint",
    )


@dataclass
class HoldPositionCommand:
    duration_s: float = 5.0
    skill_type: ClassVar[SkillType] = SkillType.HOLD_POSITION
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["duration_s"],
        preconditions="vehicle is airborne",
        success_condition="held position for duration_s",
        failure_condition="lost control during hold",
        timeout_s=0.0,   # duration is the timeout
        abort_behavior="remain in hold",
        expected_state_change="position unchanged",
    )


@dataclass
class SearchRegionCommand:
    """First implementation: a boustrophedon (lawnmower) sweep of a rectangle."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    altitude: float = DEFAULT_ALTITUDE
    lane_spacing_m: float = 10.0
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 300.0
    skill_type: ClassVar[SkillType] = SkillType.SEARCH_REGION
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["min_x", "min_y", "max_x", "max_y"],
        preconditions="vehicle is airborne; region is valid",
        success_condition="all sweep waypoints covered",
        failure_condition="sweep incomplete; timeout",
        timeout_s=300.0,
        abort_behavior="stop and hold",
        expected_state_change="region covered; vehicle at last lane end",
    )


@dataclass
class InspectPointCommand:
    point: Position3D
    dwell_s: float = 5.0
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 90.0
    skill_type: ClassVar[SkillType] = SkillType.INSPECT_POINT
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["point"],
        preconditions="vehicle is airborne",
        success_condition="reached point and dwelled for dwell_s",
        failure_condition="did not reach point",
        timeout_s=90.0,
        abort_behavior="stop and hold",
        expected_state_change="inspected the point; hovering over it",
    )


@dataclass
class RendezvousCommand:
    """First implementation: fly to a shared meeting point."""
    point: Position3D
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 90.0
    skill_type: ClassVar[SkillType] = SkillType.RENDEZVOUS
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["point"],
        preconditions="vehicle is airborne",
        success_condition="reached the shared rendezvous point",
        failure_condition="did not reach the point",
        timeout_s=90.0,
        abort_behavior="stop and hold",
        expected_state_change="vehicle at the rendezvous point",
    )


@dataclass
class ActAsRelayCommand:
    """First implementation: station-keep at a relay position for a duration."""
    position: Position3D
    duration_s: float = 30.0
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 120.0
    skill_type: ClassVar[SkillType] = SkillType.ACT_AS_RELAY
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=["position", "duration_s"],
        preconditions="vehicle is airborne",
        success_condition="held the relay position for duration_s",
        failure_condition="could not reach or hold the position",
        timeout_s=120.0,
        abort_behavior="stop and hold",
        expected_state_change="vehicle holding the relay station",
    )


@dataclass
class ReturnHomeCommand:
    home: Position3D = field(default_factory=lambda: HOME)
    speed_mps: float = DEFAULT_SPEED
    tolerance_m: float = DEFAULT_TOLERANCE
    timeout_s: float = 90.0
    skill_type: ClassVar[SkillType] = SkillType.RETURN_HOME
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=[],
        preconditions="vehicle is airborne",
        success_condition="reached the home position within tolerance",
        failure_condition="did not reach home",
        timeout_s=90.0,
        abort_behavior="stop and hold",
        expected_state_change="vehicle at home position",
    )


@dataclass
class LandCommand:
    timeout_s: float = 45.0
    skill_type: ClassVar[SkillType] = SkillType.LAND
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=[],
        preconditions="vehicle is airborne",
        success_condition="vehicle settled on the ground and disarmed",
        failure_condition="did not reach the ground",
        timeout_s=45.0,
        abort_behavior="hold above the ground",
        expected_state_change="vehicle on the ground, motors off",
    )


@dataclass
class EmergencyHoldCommand:
    skill_type: ClassVar[SkillType] = SkillType.EMERGENCY_HOLD
    contract: ClassVar[SkillContract] = SkillContract(
        required_params=[],
        preconditions="none - always allowed",
        success_condition="vehicle immediately holding position",
        failure_condition="could not command a hold",
        timeout_s=5.0,
        abort_behavior="n/a (this is the abort)",
        expected_state_change="all motion cancelled; hovering in place",
    )
