"""What makes an agent think again: AUV-06's replanning triggers (5.2).

    Event(Trigger.SKILL_FAILED, at=t, detail={"skill": "GO_TO_WAYPOINT", ...})

AUV-06: "Do not call the LLM continuously. Replan when:" -- and nine
triggers follow. An agent observes every tick, which is cheap, but decides
only when one of these fires, which is what makes an expensive policy
affordable and keeps motion independent of how long a decision takes.

WHICH FIRE IN PHASE 5. A single drone with no team and no messages can see:

    TASK_ASSIGNED       a task is given to it
    SKILL_SUCCEEDED     the current skill ended in success
    SKILL_FAILED        the current skill failed or timed out
    TARGET_DETECTED     a new sighting
    COMMS_CHANGED       its link to the base came or went -- for a lone
                        drone, the one change in communication there is
    BATTERY_THRESHOLD   its battery fell through one of the agent's levels
    GUARD_REJECTED      the validation step refused a decision

and two that are not in AUV-06's nine but complete the picture:

    SKILL_ABORTED       a skill the agent itself aborted has stopped
    PERIODIC            AUV-06's "slow periodic check every few seconds"

The rest are defined so later phases raise them without changing this
module: MESSAGE (Phase 7: a message changes mission state) and
TEAMMATE_FAILED (Phase 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Trigger(Enum):
    TASK_ASSIGNED = "task_assigned"
    SKILL_SUCCEEDED = "skill_succeeded"
    SKILL_FAILED = "skill_failed"
    SKILL_ABORTED = "skill_aborted"
    TARGET_DETECTED = "target_detected"
    MESSAGE = "message"                       # Phase 7
    COMMS_CHANGED = "comms_changed"
    TEAMMATE_FAILED = "teammate_failed"       # Phase 9
    BATTERY_THRESHOLD = "battery_threshold"
    GUARD_REJECTED = "guard_rejected"
    PERIODIC = "periodic"


RAISED_IN_PHASE_5 = frozenset(Trigger) - {Trigger.MESSAGE, Trigger.TEAMMATE_FAILED}


@dataclass(frozen=True)
class Event:
    trigger: Trigger
    at: float
    detail: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"trigger": self.trigger.value, "at": self.at, "detail": self.detail}
