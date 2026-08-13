"""Adapter that lets any MissionPlanner be used as an agent 'policy'.

Placeholder / thin pass-through for now. In later phases a policy will combine a
planner with belief state and communication; for the baseline it just forwards
to whichever MissionPlanner it was given.
"""

from ..core.models import AgentContext, AgentDecision
from ..planners.base_planner import MissionPlanner


class LLMPolicy:
    def __init__(self, planner: MissionPlanner):
        self.planner = planner

    def decide(self, context: AgentContext) -> AgentDecision:
        return self.planner.decide(context)
