"""Build a planner or adapter by name, so scripts don't import every backend."""

from ..core.enums import PlannerType


def make_planner(name: str):
    """Return a zero-arg callable that builds a fresh MissionPlanner."""
    name = name.lower()
    if name == PlannerType.GEMINI.value:
        from .gemini_planner import GeminiPlanner
        return GeminiPlanner
    if name == PlannerType.LLAMA.value:
        from .llama_planner import LlamaPlanner
        return LlamaPlanner
    if name == PlannerType.MISTRAL.value:
        from .mistral_planner import MistralPlanner
        return MistralPlanner
    if name == PlannerType.RULE.value:
        from ..agents.rule_policy import RulePolicy
        return RulePolicy
    raise ValueError(f"unknown planner '{name}'. Options: "
                     f"{[p.value for p in PlannerType]}")


def make_adapter(name: str):
    """Return a VehicleAdapter instance. 'airsim' or 'mock'."""
    name = name.lower()
    if name == "airsim":
        from ..simulator.airsim_adapter import AirSimVehicleAdapter
        return AirSimVehicleAdapter()
    if name == "mock":
        from ..simulator.mock_adapter import MockVehicleAdapter
        return MockVehicleAdapter()
    raise ValueError(f"unknown adapter '{name}'. Options: airsim, mock")
