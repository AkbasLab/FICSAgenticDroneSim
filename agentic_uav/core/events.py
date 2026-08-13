"""Event records for logging/metrics. Placeholder for the next phase, where
agents emit structured events (message sent, task claimed, drone lost, ...)."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Event:
    kind: str
    vehicle_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
