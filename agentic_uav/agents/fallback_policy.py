"""Fallback policy for when the primary planner is unavailable.

Placeholder. In the degraded-communication experiments, an agent that can't
reach its LLM (or its teammates) should fall back to a safe deterministic
behavior (e.g. hold position, or hand off to the rule policy). Wired in later.
"""

from ..agents.rule_policy import RulePolicy
from ..core.models import AgentContext, AgentDecision


class FallbackPolicy:
    """For now, delegates to the deterministic rule policy."""

    def __init__(self):
        self._rule = RulePolicy()

    def decide(self, context: AgentContext) -> AgentDecision:
        return self._rule.decide(context)
