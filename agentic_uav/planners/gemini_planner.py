"""Gemini (cloud) planner. Implements MissionPlanner.decide()."""

import json
import os

from ..core.models import AgentContext, AgentDecision
from .base_planner import (
    FEWSHOT, SYSTEM_PROMPT, PlanError, extract_actions, validate_and_build,
)

MODEL = "gemini-flash-latest"


class GeminiPlanner:
    """Plans with Google's Gemini API. Needs GEMINI_API_KEY in the environment."""

    def __init__(self, model: str = MODEL):
        from google import genai  # imported lazily so non-Gemini runs don't need it
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY not set (put it in a .env file).")
        self.model = model
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def decide(self, context: AgentContext) -> AgentDecision:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self.model,
            contents=context.instruction,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            raise PlanError(f"Gemini returned invalid JSON: {e}")

        steps = extract_actions(data)
        if steps is None:
            raise PlanError("no action list in Gemini's reply")
        return validate_and_build(steps, source="gemini")
