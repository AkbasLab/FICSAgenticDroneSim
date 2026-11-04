"""What one drone believes of each teammate's health, from what it has heard (AUV-09, 9.2).

    detector = FailureDetector("Drone2", ["Drone1", "Drone3", "Drone4"], HealthConfig(), start=0.0)
    detector.update(belief.links, now)           # when each teammate was last heard: the belief's own record
    detector.state("Drone3"), detector.log

THE LADDER, per teammate:

    HEALTHY ──silence──> SUSPECTED ──silence──> UNREACHABLE ──silence──> FAILED
        ^                    │                       │                     │
        └──── a while ── RECOVERED <──── heard again ┴─────────────────────┘

Built only from SILENCE -- how long since the drone last heard anything at all
from that teammate (`BeliefState.links`, its record of every arrival). Never
from the teammate's true state: a drone cannot see a teammate stop, only stop
hearing it.

DO NOT DECLARE FAILURE AFTER ONE MISSED MESSAGE (AUV-09). Heartbeats come
every second; the thresholds, in `configs/recovery/default.toml`, are:

    SUSPECTED     3 s of silence   the heartbeat's lifetime: three missed
    UNREACHABLE  10 s              a lease: the moment its task returns to the pool
    FAILED       30 s

Communication loss and vehicle failure are different conditions, and the
ladder keeps UNREACHABLE and FAILED apart so a later phase can act on the
difference. Under Phase 9's network every message is delivered, so silence
can only mean a stopped drone; telling a partition from a failure needs a
network that partitions -- Phase 10's.

RECOVERED: a teammate heard again after SUSPECTED or worse -- reintegrated, not
treated as a stranger -- and HEALTHY again once it has been heard steadily for
the SUSPECTED interval. Silence from the start of the flight counts too: a
teammate never heard at all climbs the same ladder.

Every transition is logged, with when and how long the silence had been,
crossing each rung in order even if a tick skipped one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class Health(str, Enum):
    HEALTHY = "healthy"
    SUSPECTED = "suspected"
    UNREACHABLE = "unreachable"
    FAILED = "failed"
    RECOVERED = "recovered"


LADDER = (Health.HEALTHY, Health.SUSPECTED, Health.UNREACHABLE, Health.FAILED)


@dataclass(frozen=True)
class HealthConfig:
    suspected_s: float = 3.0
    unreachable_s: float = 10.0
    failed_s: float = 30.0

    def __post_init__(self) -> None:
        values = (self.suspected_s, self.unreachable_s, self.failed_s)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values) \
                or not 0 < self.suspected_s < self.unreachable_s < self.failed_s:
            raise ValueError(f"thresholds must rise from above 0: {values}")

    def as_json(self) -> dict[str, float]:
        return {"suspected_s": self.suspected_s, "unreachable_s": self.unreachable_s, "failed_s": self.failed_s}

    def rung(self, silence: float) -> Health:
        """Where `silence` seconds put a teammate on the ladder."""
        if silence >= self.failed_s:
            return Health.FAILED
        if silence >= self.unreachable_s:
            return Health.UNREACHABLE
        if silence >= self.suspected_s:
            return Health.SUSPECTED
        return Health.HEALTHY


@dataclass(frozen=True)
class Transition:
    at: float
    teammate: str
    before: Health
    after: Health
    silence_s: float

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "teammate": self.teammate, "before": self.before.value,
                "after": self.after.value, "silence_s": round(self.silence_s, 3)}


class FailureDetector:
    def __init__(self, owner: str, teammates: Iterable[str], config: HealthConfig, start: float) -> None:
        self.owner = owner
        self.config = config
        self.start = start
        self._state = {m: Health.HEALTHY for m in sorted(teammates) if m != owner}
        self._last: dict[str, float] = {m: start for m in self._state}
        self._recovered_at: dict[str, float] = {}
        self.log: list[Transition] = []

    def state(self, teammate: str) -> Health:
        return self._state[teammate]

    def states(self) -> dict[str, str]:
        return {m: s.value for m, s in self._state.items()}

    def in_state(self, *states: Health) -> tuple[str, ...]:
        return tuple(m for m, s in self._state.items() if s in states)

    def update(self, links: dict[str, dict[str, Any]], now: float) -> list[Transition]:
        """Bring every teammate's rung up to date from when it was last heard. Returns the transitions."""
        out: list[Transition] = []
        for m in self._state:
            heard = links.get(m, {}).get("last_heard")
            if heard is not None and heard > self._last[m]:
                self._last[m] = heard
                if self._state[m] in (Health.SUSPECTED, Health.UNREACHABLE, Health.FAILED):
                    out.append(self._move(m, Health.RECOVERED, heard, 0.0))
                    self._recovered_at[m] = heard
            silence = now - self._last[m]
            rung = self.config.rung(silence)
            current = self._state[m]
            if current is Health.RECOVERED:
                if rung is Health.HEALTHY:
                    if now - self._recovered_at[m] >= self.config.suspected_s:
                        out.append(self._move(m, Health.HEALTHY, now, silence))
                    continue
                current = Health.HEALTHY                      # silent again: climb from the bottom
            if LADDER.index(rung) > LADDER.index(current):
                for step in LADDER[LADDER.index(current) + 1:LADDER.index(rung) + 1]:
                    out.append(self._move(m, step, now, silence))
        return out

    def _move(self, teammate: str, to: Health, at: float, silence: float) -> Transition:
        t = Transition(at, teammate, self._state[teammate], to, silence)
        self._state[teammate] = to
        self.log.append(t)
        return t

    def as_json(self) -> dict[str, Any]:
        return {"owner": self.owner, "config": self.config.as_json(), "states": self.states(),
                "log": [t.as_json() for t in self.log]}
