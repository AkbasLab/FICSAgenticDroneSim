"""Functional roles and teammate health (Phase 9.1, 9.2).

Task allocation says *what* a drone is doing. A role says *what it is for* right
now, which is a different question: a drone with no search task is not idle, it
is a RESERVE, and a drone that stops searching to keep the team in contact has
become a RELAY. Roles are what let the team's shape change as conditions change,
rather than only its to-do list.

Health is deliberately graded rather than binary. A missed heartbeat means
"I have not heard from you", which is not the same as "you have crashed" - the
link may simply be down. Declaring failure on one missed message would make the
team thrash: tasks would be yanked from healthy drones that were merely quiet.
So a peer decays HEALTHY -> SUSPECTED -> UNREACHABLE -> FAILED as silence
lengthens, and can climb back to RECOVERED if it speaks again.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Role(str, Enum):
    SCOUT = "scout"        # searches or inspects
    RELAY = "relay"        # holds position to keep the team in contact
    RESERVE = "reserve"    # available for failed or high-priority work


class HealthState(str, Enum):
    HEALTHY = "healthy"          # heard from recently
    SUSPECTED = "suspected"      # one or two heartbeats missed
    UNREACHABLE = "unreachable"  # silent long enough that we cannot plan on it
    FAILED = "failed"            # silent past the failure threshold
    RECOVERED = "recovered"      # was suspected/unreachable, then spoke again


# Silence thresholds, expressed as multiples of the expected heartbeat interval.
# Generous on purpose: comms loss is common, vehicle loss is not.
SUSPECT_AFTER_MISSED = 2.0
UNREACHABLE_AFTER_MISSED = 4.0
FAILED_AFTER_MISSED = 8.0


@dataclass
class PeerHealth:
    """Health of one teammate, inferred only from when we last heard from it."""
    vehicle_id: str
    state: HealthState = HealthState.HEALTHY
    last_heard_s: Optional[float] = None
    missed_intervals: float = 0.0
    ever_degraded: bool = False       # so we can report RECOVERED meaningfully
    transitions: List[tuple] = field(default_factory=list)   # (t, from, to, why)

    def silence_s(self, now, since=0.0):
        """How long this peer has been quiet.

        Before we have ever heard from a peer we measure from when monitoring
        began, not from minus-infinity - at mission start nobody has spoken yet,
        and declaring the whole team failed at t=0 would be absurd.
        """
        reference = self.last_heard_s if self.last_heard_s is not None else since
        return max(0.0, now - reference)

    @property
    def usable(self):
        """Can the team still plan around this peer?"""
        return self.state in (HealthState.HEALTHY, HealthState.RECOVERED,
                              HealthState.SUSPECTED)

    @property
    def presumed_lost(self):
        return self.state in (HealthState.UNREACHABLE, HealthState.FAILED)


class HealthMonitor:
    """Tracks teammate liveness from heartbeat arrival times (9.2).

    Note what this deliberately does NOT do: conclude anything from a single
    missed message, or distinguish "crashed" from "out of range". It reports how
    long a peer has been silent and how much that silence should be trusted; the
    role policy decides what to do about it.
    """

    def __init__(self, vehicle_id, heartbeat_interval_s=20.0,
                 suspect_after=SUSPECT_AFTER_MISSED,
                 unreachable_after=UNREACHABLE_AFTER_MISSED,
                 failed_after=FAILED_AFTER_MISSED):
        self.vehicle_id = vehicle_id
        self.interval = heartbeat_interval_s
        self.suspect_after = suspect_after
        self.unreachable_after = unreachable_after
        self.failed_after = failed_after
        self.peers: Dict[str, PeerHealth] = {}
        self.events: List[str] = []
        self.started_at = 0.0        # monitoring baseline (see PeerHealth.silence_s)

    def note_heard(self, peer_id, now):
        """A message arrived from `peer_id` - it is alive as of `now`."""
        if peer_id == self.vehicle_id:
            return None
        h = self.peers.get(peer_id)
        if h is None:
            h = PeerHealth(vehicle_id=peer_id)
            self.peers[peer_id] = h
        previous = h.state
        h.last_heard_s = max(h.last_heard_s or 0.0, now)
        h.missed_intervals = 0.0
        # coming back from silence is worth naming, not just clearing
        h.state = (HealthState.RECOVERED if h.ever_degraded
                   else HealthState.HEALTHY)
        if h.state is not previous:
            self._transition(h, previous, h.state, now, "heard from")
        return h

    def tick(self, now, roster=None):
        """Re-evaluate every peer's health from how long it has been silent."""
        for vid in (roster or []):
            if vid != self.vehicle_id and vid not in self.peers:
                self.peers[vid] = PeerHealth(vehicle_id=vid)

        changed = []
        for h in self.peers.values():
            silence = h.silence_s(now, since=self.started_at)
            h.missed_intervals = (silence / self.interval
                                  if self.interval > 0 else 0.0)
            previous = h.state
            new = self._classify(h.missed_intervals, previous)
            if new is not previous:
                h.state = new
                if new in (HealthState.SUSPECTED, HealthState.UNREACHABLE,
                           HealthState.FAILED):
                    h.ever_degraded = True
                self._transition(h, previous, new, now,
                                 f"silent {silence:.0f}s "
                                 f"({h.missed_intervals:.1f} intervals)")
                changed.append(h)
        return changed

    def _classify(self, missed, previous):
        if missed >= self.failed_after:
            return HealthState.FAILED
        if missed >= self.unreachable_after:
            return HealthState.UNREACHABLE
        if missed >= self.suspect_after:
            return HealthState.SUSPECTED
        # heard from recently enough
        if previous in (HealthState.SUSPECTED, HealthState.UNREACHABLE,
                        HealthState.FAILED):
            return previous          # only note_heard() clears a degraded state
        return previous if previous is HealthState.RECOVERED else HealthState.HEALTHY

    def _transition(self, h, old, new, now, why):
        h.transitions.append((now, old.value, new.value, why))
        self.events.append(f"t={now:.0f} {h.vehicle_id}: {old.value} -> "
                           f"{new.value} ({why})")

    # --- queries the role policy uses ---

    def healthy_peers(self):
        return [v for v, h in self.peers.items() if h.usable]

    def failed_peers(self):
        return [v for v, h in self.peers.items() if h.presumed_lost]

    def state_of(self, peer_id):
        h = self.peers.get(peer_id)
        return h.state if h else HealthState.HEALTHY

    def active_count(self):
        """Us plus every peer we still believe is flying."""
        return 1 + len(self.healthy_peers())

    def summary(self, now):
        return {v: {"state": h.state.value,
                    "silent_s": round(h.silence_s(now, self.started_at), 1),
                    "missed_intervals": round(h.missed_intervals, 2)}
                for v, h in sorted(self.peers.items())}
