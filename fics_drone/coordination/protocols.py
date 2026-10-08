"""One common envelope for every message, so ordering, expiry, addressing and
logging are implemented once, not per message type.

Scope note: FICS's own Phase 7 builds 13 message types. This build scopes
down to the two this mission's exit criterion actually needs -
TARGET_FOUND (the thing that has to propagate between agents) and HEARTBEAT
(exercises the TeamBelief/Provenance scaffolding Phase 6 built but left
dormant, since there was no second agent to have beliefs about yet). Task
bidding, role reassignment, and failure-recovery messages are real Phase 8-9
concerns, not invented early here.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(str, Enum):
    HEARTBEAT = "heartbeat"       # periodic self-report: position, battery
    TARGET_FOUND = "target_found"  # broadcast once a sighting is confirmed
    TASK_BID = "task_bid"         # Phase 8: this agent's bid on a sector task
    TASK_CLAIM = "task_claim"     # Phase 8: this agent believes it won a task
    HELP_REQUEST = "help_request"  # Phase 12.3: the ONLY type a model may author. Informational and
    # low-privilege on purpose - receivers merely record it, so a model can never forge a protocol
    # message (a fake TARGET_FOUND, a stolen TASK_CLAIM) by writing one.
    TASK_ANNOUNCE = "task_announce"  # Phase 12 (15-tool set): "a task I hold is up for bids" - built by
    # code from the sender's own board, never authored by a model
    TASK_RELEASE = "task_release"  # Phase 12: a holder gives a task up (awarded_to = the lowest bidder, if any)
    TASK_COMPLETE = "task_complete"  # Phase 9: this agent finished its own task - explicit,
    # because silence alone can't distinguish "finished and landed" from "died": both look
    # identical to a teammate as "stopped sending heartbeats"


# Must exceed the longest skill this message's sender might be mid-skill
# during - FICS's own Phase 7 doc flags this exact mistake (a TTL shorter
# than a ~70s sweep aged out messages before anyone next checked their
# inbox, showing up as false "drops"). Our own live Phase 5 run took up to
# ~218s end to end, so these are set generously rather than guessed.
TTL_BY_TYPE = {
    MessageType.HEARTBEAT: 60.0,
    MessageType.TARGET_FOUND: 300.0,
    MessageType.TASK_BID: 30.0,
    MessageType.TASK_CLAIM: 300.0,
    MessageType.TASK_COMPLETE: 300.0,
    MessageType.HELP_REQUEST: 120.0,
    MessageType.TASK_ANNOUNCE: 120.0,
    MessageType.TASK_RELEASE: 300.0,
}

BROADCAST = None  # Message.recipients=None means "every other registered agent"


@dataclass
class Message:
    id: int
    type: MessageType
    sender: str
    recipients: Optional[List[str]]  # None = BROADCAST
    created_t: float
    ttl_s: float
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    seq: int = 0  # Phase 10: per-sender monotonic counter, assigned by MessageBus -
    # the only way a receiver can notice a gap (a message that never arrived at all,
    # distinct from one that arrived late) without being told the drop rate directly

    def expires_at(self) -> float:
        return self.created_t + self.ttl_s
