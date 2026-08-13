"""The MissionPlanner interface plus the planning logic shared by all planners.

Gemini, Llama, Mistral and the deterministic rule policy all implement the same
`decide(context) -> AgentDecision` method, so the agent doesn't care which one it
holds. The prompt, schema, validation and parsing that the LLM planners share
live here so they stay identical to the open-loop baseline.
"""

from typing import Protocol, runtime_checkable

from ..control.navigation import ALTITUDE
from ..control.skills import ACTION_PARAMS, build_plan_schema
from ..core.models import AgentContext, AgentDecision, SkillCommand


@runtime_checkable
class MissionPlanner(Protocol):
    """Turns an AgentContext into a plan. Every planner implements this."""

    def decide(self, context: AgentContext) -> AgentDecision:
        ...


class PlanError(Exception):
    """Raised when a produced plan can't be safely executed."""


# --- shared LLM prompt / schema (identical to the baseline) ---

PLAN_SCHEMA = build_plan_schema()

SYSTEM_PROMPT = (
    "You are a drone flight planner in a simulator.\n"
    'Turn the user\'s instruction into a plan: a JSON object with a "plan"\n'
    "array, one step per thing the user asks for.\n\n"
    "The ONLY actions you may use:\n"
    "- fly_to        params: x, y, z\n"
    "- fly_straight  params: duration   (forward)\n"
    "- fly_backward  params: duration\n"
    "- fly_left      params: duration\n"
    "- fly_right     params: duration\n"
    "- hover         params: duration\n"
    "- set_altitude  params: z          (go higher/lower)\n"
    "- land          params: (empty)\n\n"
    "RULES:\n"
    f"- Z is altitude and NEGATIVE means up. Normal height is {ALTITUDE}.\n"
    "- Higher = MORE negative z (e.g. -15); lower = less negative (e.g. -3).\n"
    f"- 'go home' / 'return' / 'come back' means fly_to x=0.0, y=0.0, z={ALTITUDE}.\n"
    "- 'land' or 'touch down' means the land action, placed last.\n"
    "- Add ONE step for EVERY thing the user asks for. Never skip a part.\n"
    "- Durations are seconds and must be greater than 0."
)

# Few-shot examples given to the LLM planners as prior turns.
FEWSHOT = [
    ("hover for 2 seconds then land",
     '{"plan": [{"action": "hover", "params": {"duration": 2.0}}, '
     '{"action": "land", "params": {}}]}'),
    ("fly backward for 3 seconds, return home, then land",
     '{"plan": [{"action": "fly_backward", "params": {"duration": 3.0}}, '
     '{"action": "fly_to", "params": {"x": 0.0, "y": 0.0, "z": -8.0}}, '
     '{"action": "land", "params": {}}]}'),
]


def extract_actions(data):
    """Pull the list of action dicts out of whatever shape the model returned."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "action" in data:
            return [data]
        for value in data.values():
            if isinstance(value, list):
                return value
        for value in data.values():
            if isinstance(value, dict):
                found = extract_actions(value)
                if found is not None:
                    return found
    return None


def validate_and_build(raw_steps, source) -> AgentDecision:
    """Validate a list of action dicts and turn it into an AgentDecision.

    Same checks the baseline ran before any drone took off: known action,
    required params present, params numeric, durations positive.
    """
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
        if "duration" in params and params["duration"] <= 0:
            raise PlanError(f"step {i} ({action}): duration must be positive")
        commands.append(SkillCommand(action=action, params=params))

    return AgentDecision(plan=commands, source=source)
