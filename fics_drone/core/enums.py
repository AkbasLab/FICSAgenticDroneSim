"""The fixed action vocabulary the LLM planner is allowed to emit."""

from enum import Enum


class ActionType(str, Enum):
    """Low-level flight primitives. str+Enum so a value compares equal to its
    own string ("fly_to" == ActionType.FLY_TO) and serializes cleanly to JSON."""

    FLY_TO = "fly_to"
    FLY_FORWARD = "fly_forward"
    FLY_BACKWARD = "fly_backward"
    FLY_LEFT = "fly_left"
    FLY_RIGHT = "fly_right"
    HOVER = "hover"
    SET_HEIGHT = "set_height"
    LAND = "land"
