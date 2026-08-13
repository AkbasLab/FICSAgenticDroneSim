"""Per-agent local belief state. Placeholder for the multi-agent phase.

Will hold what a drone believes about itself, its task, and its teammates -
updated from observations and peer messages, and used by policies to decide and
replan under uncertainty. The open-loop baseline has no belief state.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class BeliefState:
    vehicle_id: str
    self_state: Dict[str, Any] = field(default_factory=dict)
    teammates: Dict[str, Any] = field(default_factory=dict)
    mission: Dict[str, Any] = field(default_factory=dict)
