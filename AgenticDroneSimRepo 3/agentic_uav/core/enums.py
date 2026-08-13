"""Enumerations shared across the system."""

from enum import Enum


class ActionType(str, Enum):
    """Low-level movement primitives (Phase 1/2 open-loop baseline).

    These remain available underneath the high-level skills, but the main agent
    interface from Phase 3 on is SkillType below.
    """
    ARM_TAKEOFF = "arm_takeoff"
    FLY_TO = "fly_to"
    FLY_STRAIGHT = "fly_straight"
    FLY_BACKWARD = "fly_backward"
    FLY_LEFT = "fly_left"
    FLY_RIGHT = "fly_right"
    HOVER = "hover"
    SET_ALTITUDE = "set_altitude"
    LAND = "land"


class SkillType(str, Enum):
    """High-level, mission-oriented skills - the agent's main interface.

    First implementations are composed from the navigation primitives; the
    mission-level ones (search, inspect, rendezvous, relay) build on waypoints.
    """
    TAKE_OFF = "take_off"
    GO_TO_WAYPOINT = "go_to_waypoint"
    FOLLOW_WAYPOINTS = "follow_waypoints"
    SEARCH_REGION = "search_region"
    INSPECT_POINT = "inspect_point"
    HOLD_POSITION = "hold_position"
    RENDEZVOUS = "rendezvous"
    ACT_AS_RELAY = "act_as_relay"
    RETURN_HOME = "return_home"
    LAND = "land"
    EMERGENCY_HOLD = "emergency_hold"


class SkillStatus(str, Enum):
    """Outcome of executing a skill."""
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"
    TIMEOUT = "timeout"


class PlannerType(str, Enum):
    GEMINI = "gemini"
    LLAMA = "llama"
    MISTRAL = "mistral"
    RULE = "rule"
