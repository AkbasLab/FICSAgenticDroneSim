"""Roles and health grading. A team that can only say 'alive' or 'dead' about
a teammate will mistake an ordinary comms gap for a lost drone - a missed
heartbeat means 'I have not heard from you', which is not the same claim as
'you have crashed'. Declaring failure on one missed message would be worse
than no detection at all, since sectors would get pulled off healthy drones
that were just briefly quiet. Grading the signal (HEALTHY -> SUSPECTED ->
UNREACHABLE -> FAILED, with RECOVERED if a peer speaks again) is what makes
that restraint possible instead of assumed.
"""

from enum import Enum
from typing import Optional

from ..agents.belief_schema import Provenance, TeammateRecord


class Role(str, Enum):
    SCOUT = "scout"      # searches a sector - every agent in this scenario, by default
    RELAY = "relay"      # holds station to keep the team connected - not exercised this
    # phase (no comms-degradation model yet, that's Phase 10's job); the vocabulary exists
    # so Phase 10 doesn't need to redesign this enum.
    RESERVE = "reserve"   # spare capacity, no task yet


class HealthState(str, Enum):
    HEALTHY = "healthy"
    SUSPECTED = "suspected"
    UNREACHABLE = "unreachable"
    FAILED = "failed"
    RECOVERED = "recovered"


SUSPECT_AFTER_MISSED = 2.0
UNREACHABLE_AFTER_MISSED = 4.0
FAILED_AFTER_MISSED = 8.0


class HealthMonitor:
    """Classifies a teammate's health from local belief alone - the last time
    THIS agent actually heard from them, never a peek at the teammate's real
    state. A peer never heard from at all is simply unknown, not 'failed' -
    failure is something you conclude from silence AFTER contact, not from
    the absence of a first message, which could just mean it hasn't sent one
    yet (e.g. hasn't taken its first search leg)."""

    def __init__(self, heartbeat_interval_s: float):
        self.heartbeat_interval_s = heartbeat_interval_s

    def classify(self, record: Optional[TeammateRecord], now: float) -> HealthState:
        if record is None:
            return HealthState.HEALTHY  # never heard from - not evidence of failure, just unknown
        age = now - record.provenance.timestamp
        missed = age / self.heartbeat_interval_s
        if missed >= FAILED_AFTER_MISSED:
            return HealthState.FAILED
        if missed >= UNREACHABLE_AFTER_MISSED:
            return HealthState.UNREACHABLE
        if missed >= SUSPECT_AFTER_MISSED:
            return HealthState.SUSPECTED
        return HealthState.HEALTHY
