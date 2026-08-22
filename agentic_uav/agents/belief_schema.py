"""The structured belief-state schema (Phase 6.1).

Each drone's memory is an explicit, typed structure - deliberately NOT an LLM
conversation transcript. A transcript is unstructured, unbounded, and impossible
to query ("what did the agent know about Drone2 at t=140?"), which makes decisions
unauditable. These dataclasses give every belief a place, and every *learned*
belief a provenance: where it came from, when, and how much to trust it now.

Sections mirror the schema:
    self / mission / local_map / team / communication / assumptions
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..core.models import Position3D


class Source(str, Enum):
    """Where a belief came from. Never `ground_truth` for a real agent."""
    SELF_SENSING = "self_sensing"      # this drone's own sensors
    PEER_MESSAGE = "peer_message"      # a teammate told us
    BASE_MESSAGE = "base_message"      # the base station told us
    BRIEFING = "briefing"              # given before launch (mission spec)
    INFERENCE = "inference"            # derived from other beliefs


# how long different kinds of information stay useful, in seconds
DEFAULT_TTL = {
    Source.SELF_SENSING: 5.0,
    Source.PEER_MESSAGE: 30.0,
    Source.BASE_MESSAGE: 60.0,
    Source.BRIEFING: float("inf"),
    Source.INFERENCE: 15.0,
}


@dataclass
class Provenance:
    """When/where a belief came from, and when it stops being trustworthy."""
    timestamp: float
    source: Source
    confidence: float = 1.0
    expires_at: float = float("inf")

    def age(self, now: float) -> float:
        return max(0.0, now - self.timestamp)

    def expired(self, now: float) -> bool:
        return now >= self.expires_at

    def decayed_confidence(self, now: float, half_life_s: float = 20.0) -> float:
        """Confidence falls off as information ages (halves every half_life_s).

        This is what stops an agent from treating a two-minute-old position
        report as if it were a fresh observation.
        """
        if self.expired(now):
            return 0.0
        a = self.age(now)
        if a <= 0 or half_life_s <= 0:
            return self.confidence
        return self.confidence * (0.5 ** (a / half_life_s))


# --- self ---


@dataclass
class SelfBelief:
    vehicle_id: str
    position: Optional[Position3D] = None
    velocity: float = 0.0
    heading: float = 0.0
    battery_remaining_s: float = 0.0
    battery_total_s: float = 0.0
    health: str = "ok"                  # ok | degraded | failed
    current_skill: Optional[str] = None
    current_task: Optional[str] = None
    airborne: bool = False
    landed: bool = False

    @property
    def battery_frac(self) -> float:
        if self.battery_total_s <= 0:
            return 0.0
        return max(0.0, self.battery_remaining_s / self.battery_total_s)


# --- mission ---


@dataclass
class MissionBelief:
    mission_id: str = ""
    objective: str = ""
    constraints: Dict[str, Any] = field(default_factory=dict)
    deadline_s: float = float("inf")
    progress: Dict[str, Any] = field(default_factory=dict)


# --- local map ---


@dataclass
class ObservedTarget:
    target_id: str
    position: Position3D
    provenance: Provenance


@dataclass
class SearchedRegion:
    region_id: str
    footprint: Any                      # Rect
    searched_at: float
    by_vehicle: str
    coverage: float = 1.0


@dataclass
class LocalMap:
    """What this drone believes about the world - only what it has seen or been told."""
    searched_regions: List[SearchedRegion] = field(default_factory=list)
    observed_targets: List[ObservedTarget] = field(default_factory=list)
    known_hazards: List[Any] = field(default_factory=list)
    restricted_zones: List[Any] = field(default_factory=list)

    def mark_searched(self, region_id, footprint, at_time, by_vehicle, coverage=1.0):
        for r in self.searched_regions:
            if r.region_id == region_id:
                r.searched_at, r.by_vehicle, r.coverage = at_time, by_vehicle, coverage
                return
        self.searched_regions.append(
            SearchedRegion(region_id, footprint, at_time, by_vehicle, coverage))

    def note_target(self, target_id, position, provenance):
        for t in self.observed_targets:
            if t.target_id == target_id:
                return False
        self.observed_targets.append(ObservedTarget(target_id, position, provenance))
        return True

    @property
    def target_ids(self):
        return [t.target_id for t in self.observed_targets]

    @property
    def searched_ids(self):
        return [r.region_id for r in self.searched_regions]


# --- team ---


@dataclass
class TeammateRecord:
    """What we believe about one teammate, and how stale that belief is (6.3)."""
    vehicle_id: str
    last_position: Optional[Position3D] = None
    current_role: str = "unknown"
    current_task: Optional[str] = None
    status: str = "unknown"             # ok | degraded | failed | unknown
    provenance: Provenance = None

    def age(self, now):
        return self.provenance.age(now) if self.provenance else float("inf")

    def status_confidence(self, now):
        """How much to trust this record *now* - decays with age, 0 once expired."""
        return self.provenance.decayed_confidence(now) if self.provenance else 0.0

    def is_stale(self, now, threshold=0.5):
        return self.status_confidence(now) < threshold

    def is_expired(self, now):
        return self.provenance.expired(now) if self.provenance else True


@dataclass
class TeamBelief:
    teammates: Dict[str, TeammateRecord] = field(default_factory=dict)

    def update(self, vehicle_id, now, source, position=None, role=None,
               task=None, status=None, confidence=1.0, ttl=None):
        ttl = DEFAULT_TTL.get(source, 30.0) if ttl is None else ttl
        rec = self.teammates.get(vehicle_id) or TeammateRecord(vehicle_id=vehicle_id)
        if position is not None:
            rec.last_position = position
        if role is not None:
            rec.current_role = role
        if task is not None:
            rec.current_task = task
        if status is not None:
            rec.status = status
        rec.provenance = Provenance(timestamp=now, source=source,
                                    confidence=confidence,
                                    expires_at=now + ttl)
        self.teammates[vehicle_id] = rec
        return rec

    def fresh(self, now, threshold=0.5):
        return {v: r for v, r in self.teammates.items()
                if not r.is_stale(now, threshold)}

    def stale(self, now, threshold=0.5):
        return {v: r for v, r in self.teammates.items()
                if r.is_stale(now, threshold)}


# --- communication ---


@dataclass
class CommunicationBelief:
    estimated_latency_s: float = 0.0
    recent_loss_rate: float = 0.0
    connected_peers: List[str] = field(default_factory=list)
    base_reachable: bool = True
    last_base_contact_s: Optional[float] = None

    @property
    def degraded(self) -> bool:
        return self.recent_loss_rate > 0.2 or not self.base_reachable


# --- assumptions ---


@dataclass
class Assumption:
    """Something the agent is acting as if true, without having confirmed it.

    Recording these explicitly is what lets the log show not just what the agent
    knew, but what it was *guessing*.
    """
    statement: str
    evidence: str
    timestamp: float
    confidence: float = 0.5

    def to_dict(self):
        return {"statement": self.statement, "evidence": self.evidence,
                "timestamp": round(self.timestamp, 2),
                "confidence": round(self.confidence, 2)}
