"""What a policy hands back, and the shape every policy has (AUV-06, 5.1).

    decision = policy.decide(belief, events)
    Decision.start(GoToWaypointCommand(...), objective="reach S1", reason="task assigned")

AUV-06: "the policy is swappable (rule, LLM, fallback)". Every policy, now
the rule-based one and from Phase 12 an LLM, answers the same question --
given what I believe and what just happened, what now? -- with one of four
decisions:

    START     fly this skill next (if one is still flying, the agent aborts
              it first: a decision to start replaces whatever was running)
    ABORT     stop the running skill and hold
    CONTINUE  nothing to change; let the running skill go on
    FINISH    the task is over (the drone has landed, or will do nothing more)

`objective` is the lifecycle's "Select objective", `command` its "Choose
skill"; `reason` is for the trace, in words a reader can audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from ..control.skills import SkillCommand
from ..core.events import Event
from .belief_state import BeliefState


class DecisionKind(Enum):
    START = "start"
    ABORT = "abort"
    CONTINUE = "continue"
    FINISH = "finish"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    objective: str | None = None
    command: SkillCommand | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.kind is DecisionKind.START) != (self.command is not None):
            raise ValueError("a START decision carries a command, and only a START decision does")

    @classmethod
    def start(cls, command: SkillCommand, objective: str, reason: str = "") -> "Decision":
        return cls(DecisionKind.START, objective, command, reason)

    @classmethod
    def abort(cls, objective: str | None = None, reason: str = "") -> "Decision":
        return cls(DecisionKind.ABORT, objective, None, reason)

    @classmethod
    def carry_on(cls, objective: str | None = None, reason: str = "") -> "Decision":
        return cls(DecisionKind.CONTINUE, objective, None, reason)

    @classmethod
    def finish(cls, objective: str | None = None, reason: str = "") -> "Decision":
        return cls(DecisionKind.FINISH, objective, None, reason)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value, "objective": self.objective, "reason": self.reason}
        if self.command is not None:
            from dataclasses import asdict
            out["skill"] = self.command.skill.value
            out["command"] = asdict(self.command)
        return out


class Policy(Protocol):
    def decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        """Given the belief and what just happened, what now."""
        ...
