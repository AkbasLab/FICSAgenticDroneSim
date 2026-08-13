"""Local Mistral planner (via Ollama). Implements MissionPlanner.decide().

Identical to the Llama planner except for the model name - it reuses the same
Ollama call so the comparison between them is apples to apples.
"""

from .llama_planner import LlamaPlanner

MODEL = "mistral-nemo"


class MistralPlanner(LlamaPlanner):
    def __init__(self, model: str = MODEL):
        super().__init__(model=model)
