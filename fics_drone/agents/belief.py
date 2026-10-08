"""Belief is now composed of the six typed sections in belief_schema.py,
instead of a flat bag of fields - but exposes the same flat properties
Phase 5's policy and agent loop already use (position, elapsed_s, phase,
search_queue, ...), so neither of those files had to change shape, only what
they're reading from. Same idea FICS's own Phase 6 doc describes: "the
Phase 5 interface was preserved as properties over the new structure."
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .belief_schema import (
    Assumptions, CommunicationBelief, LocalMap, MissionBelief, SelfState,
    TargetSighting, TeamBelief, VisitedPoint,
)


@dataclass
class SearchLeg:
    point: Tuple[float, float, float]  # local frame, already offset-adjusted


@dataclass
class Belief:
    self_state: SelfState
    mission: MissionBelief
    local_map: LocalMap = field(default_factory=LocalMap)
    team: TeamBelief = field(default_factory=TeamBelief)
    communication: CommunicationBelief = field(default_factory=CommunicationBelief)
    assumptions: Assumptions = field(default_factory=Assumptions)

    # --- Phase 5 compatibility surface: search_policy.py and
    # persistent_agent.py read/write these exact names ---
    @property
    def position(self):
        return self.self_state.position

    @position.setter
    def position(self, value):
        self.self_state.position = value

    @property
    def elapsed_s(self):
        return self.self_state.elapsed_s

    @elapsed_s.setter
    def elapsed_s(self, value):
        self.self_state.elapsed_s = value

    @property
    def battery_s(self):
        return self.self_state.battery_s

    @property
    def phase(self):
        return self.self_state.phase

    @phase.setter
    def phase(self, value):
        self.self_state.phase = value

    @property
    def nav_retries(self):
        return self.self_state.nav_retries

    @nav_retries.setter
    def nav_retries(self, value):
        self.self_state.nav_retries = value

    @property
    def listen_rounds(self):
        return self.self_state.listen_rounds

    @listen_rounds.setter
    def listen_rounds(self, value):
        self.self_state.listen_rounds = value

    @property
    def battery_frac_remaining(self) -> float:
        return self.self_state.battery_frac_remaining

    @property
    def search_queue(self) -> List[SearchLeg]:
        return self.mission.search_queue

    @property
    def target_found(self) -> Optional[str]:
        for sighting in self.mission.targets_known.values():
            if sighting.confirmed:
                return sighting.target_id
        return None
