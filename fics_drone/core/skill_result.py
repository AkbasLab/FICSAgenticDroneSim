"""What a skill hands back: a verdict the skill itself decided, not raw
numbers the caller has to re-interpret against a target it may not even know."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class SkillStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"
    PARTIAL = "partial"  # FOLLOW_WAYPOINTS only: some legs succeeded, some didn't


@dataclass
class SkillResult:
    status: SkillStatus
    final_position: Optional[Tuple[float, float, float]] = None
    elapsed_s: float = 0.0
    error: Optional[str] = None


@dataclass
class FollowWaypointsResult:
    status: SkillStatus  # SUCCESS only if every leg succeeded, else PARTIAL
    leg_results: List[SkillResult] = field(default_factory=list)
    elapsed_s: float = 0.0
