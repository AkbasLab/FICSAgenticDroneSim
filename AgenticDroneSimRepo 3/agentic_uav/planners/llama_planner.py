"""Local Llama planner (via Ollama). Implements MissionPlanner.decide()."""

import json

from ..core.models import AgentContext, AgentDecision
from .base_planner import (
    FEWSHOT, PLAN_SCHEMA, SYSTEM_PROMPT, PlanError,
    extract_actions, validate_and_build,
)

MODEL = "llama3.1:8b"


def _build_messages(instruction):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_in, ex_out in FEWSHOT:
        messages.append({"role": "user", "content": ex_in})
        messages.append({"role": "assistant", "content": ex_out})
    messages.append({"role": "user", "content": instruction})
    return messages


class LlamaPlanner:
    """Plans with a local Llama model. Runs on CPU so the GPU stays free for
    the simulator (num_gpu=0). Uses the JSON schema to force a full plan."""

    def __init__(self, model: str = MODEL):
        import ollama  # lazy import
        self._ollama = ollama
        self.model = model

    def decide(self, context: AgentContext) -> AgentDecision:
        response = self._ollama.chat(
            model=self.model,
            messages=_build_messages(context.instruction),
            format=PLAN_SCHEMA,
            options={"num_gpu": 0, "temperature": 0},
        )
        raw = response["message"]["content"]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise PlanError(f"model returned invalid JSON: {e}")

        steps = extract_actions(data)
        if steps is None:
            raise PlanError(f"no action list in the model's reply: {raw}")
        return validate_and_build(steps, source=self.model)
