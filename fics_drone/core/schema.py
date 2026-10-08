"""Required parameters per action, and the JSON schema built from them.

Single source of truth: ACTION_PARAMS drives both validate_plan()'s required-key
check and the schema handed to the LLM, so the two can never drift apart.
"""

from .enums import ActionType

ACTION_PARAMS = {
    ActionType.FLY_TO: ["x", "y", "z"],
    ActionType.FLY_FORWARD: ["distance"],
    ActionType.FLY_BACKWARD: ["distance"],
    ActionType.FLY_LEFT: ["distance"],
    ActionType.FLY_RIGHT: ["distance"],
    ActionType.HOVER: ["duration"],
    ActionType.SET_HEIGHT: ["z"],
    ActionType.LAND: [],
}


def build_plan_schema():
    """JSON schema forcing the {"plan": [...]} array shape (Phase 1's fix for
    the local model collapsing multi-step instructions into one action)."""
    return {
        "type": "object",
        "properties": {
            "plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [a.value for a in ActionType],
                        },
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            }
        },
        "required": ["plan"],
    }
