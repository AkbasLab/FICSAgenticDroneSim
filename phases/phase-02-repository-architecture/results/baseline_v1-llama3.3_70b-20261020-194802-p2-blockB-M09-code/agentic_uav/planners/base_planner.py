"""The planner protocol, and the record every planner returns.

AUV-03 (2.1) asks for one interface implemented by every way of producing a
plan -- language models and deterministic policies alike -- so that comparing
architectures is configuration rather than separate code.

The baseline plans ONCE, before takeoff, from an instruction. So the protocol
is `plan(instruction, drone)`. AUV-03's `decide(context)` belongs to the
persistent agent of Phase 5, which consults the world as it flies; forcing the
open loop into that shape now would add behaviour, which 2.3 forbids.

`PlanRecord` moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 4.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .endpoint import MODEL, OLLAMA_ENDPOINT


@runtime_checkable
class MissionPlanner(Protocol):
    """Anything that turns one drone's instruction into a validated plan.

    Never raises for a bad plan or an unreachable model: it returns a
    `PlanRecord` that says so, because "the model produced nonsense" and "the
    network was down" are both results and must be recorded, not lost.
    """

    def plan(self, instruction: str, drone: str) -> "PlanRecord":
        ...


@dataclass
class PlanRecord:
    """One planning call, as it is logged."""

    drone: str
    instruction: str
    raw_output: str
    plan: list[dict[str, Any]] | None
    plan_seconds: float
    valid: bool
    error: str | None = None
    normalised: list[str] = field(default_factory=list)
    model: str = MODEL
    # Which endpoint answered. A model name alone does not say where it ran,
    # and "llama3.3:70b" served from a laptop and from an H100 are not the
    # same measurement.
    endpoint: str = OLLAMA_ENDPOINT
    # True when the endpoint could not be reached at all. Such a row is NOT a
    # measurement of the model and must not be scored as one.
    transport_error: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "drone": self.drone,
            "model": self.model,
            "endpoint": self.endpoint,
            "instruction": self.instruction,
            "raw_output": self.raw_output,
            "plan": self.plan,
            "plan_seconds": round(self.plan_seconds, 2),
            "valid": self.valid,
            "transport_error": self.transport_error,
            "error": self.error,
            "normalised": self.normalised,
        }
