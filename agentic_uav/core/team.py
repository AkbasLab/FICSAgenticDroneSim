"""What one drone can be told about another: the received-messages half of the boundary.

    report = TeamReport("Drone2", at=41.0, source="message", position=(10.0, -4.0, 12.0),
                        task="search S2", status="searching")
    belief.receive(report, now=42.5)

AUV-06, 6.2: agent belief comes "from local sensing and received messages"
only. `core/sensing.py` is the first half; this is the second. A
`TeamReport` is one piece of news about a teammate, as it arrives. Phase 6
defines it and what the belief does with it; Phase 7's network is what will
deliver it. Until then only tests hand reports in, so the team block stays
"never heard" in every flight -- nothing is faked.

WHAT A REPORT SAYS, and why each field matters for staleness (6.3):

* `at`: when the news was TRUE at its source, not when it arrived. A report
  relayed through two drones arrives late; its age counts from `at`.
* `source`: how it came ("message" straight from the teammate, "relay"
  through another, ...). Kept on the record, so a reader can see where a
  belief came from.
* `confidence`: how far the source vouches for it, 0..1, when it was true.
  The belief lowers it as the news ages (`agents/belief_state.py`).
* `ttl_s`: how long after `at` the news may be treated as current; after
  that the record is kept, marked expired, and never used as current.
* `position`, `role`, `task`, `status`: the content. Any may be absent.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TTL_S = 10.0           # until Phase 7 sets heartbeat periods, a report is current for 10 s
SOURCES = ("message", "relay", "base")


@dataclass(frozen=True)
class TeamReport:
    drone: str
    at: float
    source: str
    position: tuple[float, float, float] | None = None     # x, y, altitude
    role: str | None = None
    task: str | None = None
    status: str | None = None
    confidence: float = 1.0
    ttl_s: float = DEFAULT_TTL_S

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.ttl_s <= 0:
            raise ValueError(f"ttl_s must be positive, got {self.ttl_s}")
