"""Typed events for one experiment, written to events.jsonl.

Events are derived after a run from what the run already records (guardian log,
agent traces, telemetry samples), so the live code paths are not touched.
"""
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class EventType(str, Enum):
    RUN_START = "run_start"
    RUN_END = "run_end"
    GUARDIAN_DECISION = "guardian_decision"
    ZONE_INTERRUPT = "zone_interrupt"
    ZONE_ENTERED = "zone_entered"
    DRONE_KILLED = "drone_killed"


@dataclass
class Event:
    type: EventType
    repeat: int = 0
    t: Optional[float] = None
    vehicle: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["type"] = self.type.value
        return json.dumps(d, default=str)


class EventLog:
    def __init__(self):
        self.events: List[Event] = []

    def emit(self, type_: EventType, repeat: int = 0, t: Optional[float] = None,
             vehicle: Optional[str] = None, **data) -> Event:
        ev = Event(type_, repeat, t, vehicle, data)
        self.events.append(ev)
        return ev

    def extend(self, events: Iterable[Event]) -> None:
        self.events.extend(events)

    def counts(self) -> Dict[str, int]:
        return dict(Counter(e.type.value for e in self.events))

    def write(self, path: str) -> None:
        with open(path, "w") as f:
            for e in self.events:
                f.write(e.to_json() + "\n")

    def __len__(self) -> int:
        return len(self.events)


def read_events(path: str) -> List[Event]:
    out = []
    with open(path) as f:
        for line in f:
            d = json.loads(line)
            d["type"] = EventType(d["type"])
            out.append(Event(**d))
    return out


def _entry_time(entry) -> Optional[float]:
    for attr in ("t", "time_s", "timestamp"):
        v = getattr(entry, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def derive_events(agents, reports, scenario, telemetry, repeat: int) -> List[Event]:
    """Guardian decisions, zone interrupts and zone entries for one repeat."""
    out: List[Event] = []
    for name, agent in agents.items():
        for e in agent.guardian_log.entries:
            out.append(Event(EventType.GUARDIAN_DECISION, repeat, _entry_time(e), name, dict(
                outcome=e.outcome, failed_checks=list(e.failed_checks),
                fallback=e.fallback, move_m=e.move_m)))
    for name, rep in reports.items():
        for step in rep.trace:
            if step == "zone_interrupt":
                out.append(Event(EventType.ZONE_INTERRUPT, repeat, None, name, {}))
    for name, samples in telemetry.items():
        inside = False
        for smp in samples:
            now = any(z.contains(smp.position[0], smp.position[1], smp.t)
                      for z in scenario.no_fly_zones)
            if now and not inside:
                out.append(Event(EventType.ZONE_ENTERED, repeat, smp.t, name, {}))
            inside = now
    return sorted(out, key=lambda e: (e.t is None, e.t or 0.0))
