"""Faults injected in our own code, in front of any simulator (Phase 5, step 6).

    faults = PassingFaults({("Drone1", PrimitiveKind.MOVE_TO_POSITION): 1})
    adapter = FaultyAdapter(AirSimAdapter.connect(...), faults)

The mock can fail on demand (`MockFaults`); CarlaAir cannot, and must not be
tampered with. So for a live flight the fault sits between the skill layer
and the adapter: a primitive the skills send is refused here, with an
error, as a simulator would refuse it, a set number of times, and then
passed through untouched. Nothing reaches the simulator for a refused
primitive; everything else is the adapter's own.

`PassingFaults` is shared by every wrapper of one flight -- the executor
opens a new connection, and so a new wrapper, for each skill -- so a fault
that strikes once strikes once in the whole flight. It is thread-safe.
"""

from __future__ import annotations

import threading
from typing import Any

from ..core.models import PrimitiveCommand, PrimitiveKind, PrimitiveResult


class PassingFaults:
    """How many more times each (drone, primitive) is to fail, shared across connections."""

    def __init__(self, counts: dict[tuple[str, PrimitiveKind], int]) -> None:
        self._left = dict(counts)
        self._lock = threading.Lock()
        self.struck: list[tuple[str, str]] = []          # (drone, primitive), each time one struck

    def take(self, drone: str, kind: PrimitiveKind) -> bool:
        """True if this primitive is to fail now (and counts it)."""
        with self._lock:
            left = self._left.get((drone, kind), 0)
            if left <= 0:
                return False
            self._left[(drone, kind)] = left - 1
            self.struck.append((drone, kind.value))
            return True

    def left(self, drone: str, kind: PrimitiveKind) -> int:
        with self._lock:
            return self._left.get((drone, kind), 0)


class FaultyAdapter:
    """A VehicleAdapter that refuses chosen primitives a set number of times, then passes through."""

    def __init__(self, inner: Any, faults: PassingFaults) -> None:
        self._inner = inner
        self._faults = faults

    def execute_primitive(self, vehicle_id: str, command: PrimitiveCommand) -> PrimitiveResult:
        if self._faults.take(vehicle_id, command.kind):
            left = self._faults.left(vehicle_id, command.kind)
            raise RuntimeError(f"injected passing fault on {command.kind.value} ({left} more to come)")
        return self._inner.execute_primitive(vehicle_id, command)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
