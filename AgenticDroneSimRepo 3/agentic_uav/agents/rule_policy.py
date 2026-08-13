"""Deterministic, no-LLM planner. Implements MissionPlanner.decide().

This is the rule-based policy Dr. Akbas asked for alongside the LLM planners. It
turns an instruction into a plan with simple keyword parsing - no model, no
network, fully deterministic. It is deliberately simple: it splits the
instruction on "then"/","/"and" and maps each clause to one action by keyword.
It won't understand everything an LLM does, but it always gives the same answer
for the same input, which makes it a clean control condition in experiments.
"""

import re

from ..control.navigation import ALTITUDE
from ..core.enums import ActionType
from ..core.models import AgentContext, AgentDecision, SkillCommand
from ..planners.base_planner import PlanError

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:second|sec|s)\b")
_ALT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:meter|metre|m)\b")


def _duration(text, default=3.0):
    m = _DURATION_RE.search(text)
    return float(m.group(1)) if m else default


class RulePolicy:
    """Keyword-based deterministic planner."""

    def decide(self, context: AgentContext) -> AgentDecision:
        text = context.instruction.lower()
        # Split into clauses on common separators.
        clauses = re.split(r"\bthen\b|,|\band\b", text)
        clauses = [c.strip() for c in clauses if c.strip()]

        commands = []
        for clause in clauses:
            cmd = self._clause_to_command(clause)
            if cmd is not None:
                commands.append(cmd)

        if not commands:
            raise PlanError("rule policy couldn't parse any action")
        return AgentDecision(plan=commands, source="rule")

    def _clause_to_command(self, clause):
        dur = _duration(clause)

        if "land" in clause or "touch down" in clause:
            return SkillCommand(ActionType.LAND.value, {})
        if "home" in clause or "back to start" in clause or "return" in clause \
                or "come back" in clause:
            return SkillCommand(ActionType.FLY_TO.value,
                                {"x": 0.0, "y": 0.0, "z": ALTITUDE})
        if "hover" in clause or "wait" in clause:
            return SkillCommand(ActionType.HOVER.value, {"duration": dur})
        if "backward" in clause or "back" in clause or "reverse" in clause:
            return SkillCommand(ActionType.FLY_BACKWARD.value, {"duration": dur})
        if "left" in clause:
            return SkillCommand(ActionType.FLY_LEFT.value, {"duration": dur})
        if "right" in clause:
            return SkillCommand(ActionType.FLY_RIGHT.value, {"duration": dur})
        if "up" in clause or "climb" in clause or "ascend" in clause or "rise" in clause:
            m = _ALT_RE.search(clause)
            height = -float(m.group(1)) if m else -15.0   # negative is up
            return SkillCommand(ActionType.SET_ALTITUDE.value, {"z": height})
        if "down" in clause or "descend" in clause or "lower" in clause:
            m = _ALT_RE.search(clause)
            height = -float(m.group(1)) if m else -3.0
            return SkillCommand(ActionType.SET_ALTITUDE.value, {"z": height})
        if "forward" in clause or "straight" in clause or "ahead" in clause \
                or "fly" in clause:
            return SkillCommand(ActionType.FLY_STRAIGHT.value, {"duration": dur})
        return None
