"""Objectives, tasks and events for the persistent agent (Phase 5).

An *objective* is a short-lived goal the agent is currently pursuing (take off,
go to the sector, search it, ...). A *task* is what the agent was assigned (in
Phase 5, a single search task). An *event* is something that happened and may
justify re-deciding - the agent replans on events, not on a fixed clock.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..core.mission_models import Sector
from ..core.models import Position3D


class Objective(str, Enum):
    """The next thing the agent is trying to accomplish."""
    TAKE_OFF = "take_off"
    GO_TO_SECTOR = "go_to_sector"
    SEARCH_SECTOR = "search_sector"
    REPORT = "report"
    RETURN_HOME = "return_home"
    LAND = "land"
    DONE = "done"


class AgentEvent(str, Enum):
    """Triggers that justify a replan (Phase 5.2).

    The single-drone phase can raise the first six; the message/comms/teammate
    events are defined here so the multi-agent phase plugs in without changing
    the loop.
    """
    TASK_ASSIGNED = "task_assigned"
    SKILL_SUCCEEDED = "skill_succeeded"
    SKILL_FAILED = "skill_failed"
    SKILL_TIMEOUT = "skill_timeout"
    TARGET_DETECTED = "target_detected"
    BATTERY_LOW = "battery_low"
    BATTERY_CRITICAL = "battery_critical"
    SAFETY_REJECTED = "safety_rejected"
    REPORT_SENT = "report_sent"
    # multi-agent (not raised yet, reserved for later phases)
    MESSAGE_RECEIVED = "message_received"
    COMMS_CHANGED = "comms_changed"
    TEAMMATE_FAILED = "teammate_failed"


@dataclass
class SearchTask:
    """A search assignment handed to one agent - not a plan, just the goal."""
    task_id: str
    sector: Sector
    report_to: Position3D             # base station position to report back to
    targets_of_interest: Optional[list] = field(default=None)
