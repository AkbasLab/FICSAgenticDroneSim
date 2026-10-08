"""Shared prompt, schema, and validation for every planner backend.

validate_plan() is Phase 1's actual safety boundary: nothing past this
function ever sees an LLM's raw output. Everything downstream trusts a
SkillCommand list, never a dict straight from the model.
"""

from ..control.navigation import DEFAULT_HEIGHT
from ..core.enums import ActionType
from ..core.models import SkillCommand
from ..core.schema import ACTION_PARAMS


class PlanError(Exception):
    """Raised when a plan can't be trusted to fly. Caller must not execute it."""


SYSTEM_PROMPT = (
    "You are a drone flight planner in a simulator.\n"
    'Turn the user\'s instruction into a JSON object with a "plan" array, '
    "one step per thing the user asks for.\n\n"
    "The ONLY actions you may use:\n"
    "- fly_to        params: x, y, z\n"
    "- fly_forward   params: distance   (metres)\n"
    "- fly_backward  params: distance\n"
    "- fly_left      params: distance\n"
    "- fly_right     params: distance\n"
    "- hover         params: duration   (seconds)\n"
    "- set_height    params: z          (absolute height above ground, metres, always positive)\n"
    "- land          params: (empty)\n\n"
    "RULES:\n"
    f"- Normal cruise height is {DEFAULT_HEIGHT}. Height is always positive (never negative).\n"
    f"- 'go home' / 'return' means fly_to x=0.0, y=0.0, z={DEFAULT_HEIGHT}.\n"
    "- 'land' or 'touch down' means the land action, placed last.\n"
    "- Add ONE step for EVERY thing the user asks for. Never skip a part.\n"
    "- Add NOTHING the user did not ask for. Never add land, return-home, or "
    "extra moves unless the user says so. The drone stays in the air after the plan ends.\n"
    "- distance and duration must be greater than 0."
)

# Few-shot examples: these demonstrate the multi-step array shape to the model,
# not just describe it - schema enforcement alone wasn't reliable without this.
FEWSHOT = [
    ("fly forward 3 meters",
     '{"plan": [{"action": "fly_forward", "params": {"distance": 3.0}}]}'),
    ("go left 2 meters and hover for 4 seconds",
     '{"plan": [{"action": "fly_left", "params": {"distance": 2.0}}, '
     '{"action": "hover", "params": {"duration": 4.0}}]}'),
    ("hover for 2 seconds then land",
     '{"plan": [{"action": "hover", "params": {"duration": 2.0}}, '
     '{"action": "land", "params": {}}]}'),
    ("fly backward 3 meters, return home, then land",
     '{"plan": [{"action": "fly_backward", "params": {"distance": 3.0}}, '
     '{"action": "fly_to", "params": {"x": 0.0, "y": 0.0, "z": ' + str(DEFAULT_HEIGHT) + '}}, '
     '{"action": "land", "params": {}}]}'),
]


def validate_plan(raw_steps) -> list[SkillCommand]:
    """Check known action, then required params present, then numeric/positive.
    Action-first ordering: an unknown action makes any param check meaningless,
    and checking it first gives a precise error instead of a confusing one."""
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanError("empty or malformed plan")

    commands = []
    for i, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            raise PlanError(f"step {i} is not an object")

        action = step.get("action")
        if action not in ACTION_PARAMS:
            raise PlanError(f"step {i}: unknown action '{action}'")

        params = dict(step.get("params", {}))
        for key in ACTION_PARAMS[action]:
            if key not in params:
                raise PlanError(f"step {i} ({action}): missing '{key}'")
            try:
                params[key] = float(params[key])
            except (TypeError, ValueError):
                raise PlanError(f"step {i} ({action}): '{key}' is not a number")

        for key in ("duration", "distance"):
            if key in params and params[key] <= 0:
                raise PlanError(f"step {i} ({action}): {key} must be positive")

        commands.append(SkillCommand(action=action, params=params))

    return commands
