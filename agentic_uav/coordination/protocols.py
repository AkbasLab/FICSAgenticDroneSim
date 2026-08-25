"""Inter-agent message types and the common envelope (Phase 7.1 / 7.2).

Every message an agent sends uses the same envelope, whatever its type. That
matters for the experiments: the envelope carries the fields the logger and the
network model need (timestamp, sequence number, TTL, recipients), so message
handling, latency, loss and staleness are all implemented once rather than per
message type.

Phase 7 runs this protocol under *perfect* communication. Degradation gets added
only once the protocol itself is known to work.
"""

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(str, Enum):
    # --- liveness and state sharing ---
    HEARTBEAT = "heartbeat"                    # "I am alive", cheap and frequent
    STATUS_UPDATE = "status_update"            # position, battery, current skill
    INTENT_UPDATE = "intent_update"            # what I am about to do next

    # --- task allocation (contract-net style) ---
    TASK_ANNOUNCEMENT = "task_announcement"    # a task is available
    TASK_BID = "task_bid"                      # my cost/utility for that task
    TASK_AWARD = "task_award"                  # you have the task
    TASK_ACCEPT = "task_accept"                # I take it
    TASK_RELEASE = "task_release"              # I am giving it up
    TASK_COMPLETE = "task_complete"            # it is done

    # --- mission events ---
    TARGET_FOUND = "target_found"
    HELP_REQUEST = "help_request"
    ROLE_CHANGE = "role_change"
    MISSION_UPDATE = "mission_update"


BROADCAST = "*"          # recipient id meaning "everyone but me"

_ids = itertools.count(1)


@dataclass
class AgentMessage:
    """The common envelope. All inter-agent traffic is one of these."""
    message_type: MessageType
    sender_id: str
    recipient_ids: List[str] = field(default_factory=lambda: [BROADCAST])
    mission_id: str = ""
    timestamp: float = 0.0                 # sim time the sender created it
    sequence_number: int = 0               # per-sender counter, for ordering
    time_to_live_s: float = 30.0
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
    message_id: str = ""

    def __post_init__(self):
        if not self.message_id:
            self.message_id = f"m{next(_ids):05d}"

    # --- helpers used by the bus and the logger ---

    @property
    def expires_at(self) -> float:
        return self.timestamp + self.time_to_live_s

    def expired(self, now: float) -> bool:
        return now >= self.expires_at

    def is_broadcast(self) -> bool:
        return BROADCAST in self.recipient_ids

    def addressed_to(self, vehicle_id: str) -> bool:
        if vehicle_id == self.sender_id:
            return False                   # never deliver a message to its sender
        return self.is_broadcast() or vehicle_id in self.recipient_ids

    def size_bytes(self) -> int:
        """Approximate wire size - used for bandwidth accounting later."""
        import json
        try:
            payload = json.dumps(self.payload, default=str)
        except (TypeError, ValueError):
            payload = str(self.payload)
        return len(payload) + len(self.sender_id) + len(self.message_type) + 64

    def summary(self) -> str:
        to = "all" if self.is_broadcast() else ",".join(self.recipient_ids)
        return (f"{self.message_id} {self.message_type.value} "
                f"{self.sender_id}->{to} t={self.timestamp:.1f}")
