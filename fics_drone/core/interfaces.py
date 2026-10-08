"""The two contracts the rest of the codebase depends on. Orchestration code
imports these, never LlamaPlanner or AirSimVehicleAdapter directly, so a
mock or a different backend can be swapped in without touching it."""

from abc import ABC, abstractmethod
from typing import List, Tuple

from .models import SkillCommand


class MissionPlanner(ABC):
    @abstractmethod
    def plan(self, instruction: str) -> List[SkillCommand]:
        """instruction -> validated commands, or raises PlanError."""


class VehicleAdapter(ABC):
    @abstractmethod
    def connect_and_takeoff(self) -> None:
        """Call exactly once per real takeoff (records ground level)."""

    @abstractmethod
    def execute(self, commands: List[SkillCommand]) -> None:
        """Run one validated plan, blocking until done. Does not take off."""

    @abstractmethod
    def land(self) -> None:
        """Land and disarm."""

    # --- non-blocking primitives, for skills that poll with their own timeout
    # (execute()'s per-action .join() calls have no time limit; a skill needs
    # to be able to give up on its own clock instead of waiting forever) ---

    @abstractmethod
    def get_position(self) -> Tuple[float, float, float]:
        """Current (x, y, z), height above the recorded ground."""

    @abstractmethod
    def get_speed(self) -> float:
        """Current speed (m/s), magnitude of linear velocity. Lets a skill tell
        'passed through the target while still moving fast' apart from 'arrived'."""

    @abstractmethod
    def start_move_to(self, x: float, y: float, z: float) -> None:
        """Begin moving toward (x, y, z). Returns immediately."""

    @abstractmethod
    def start_hover(self) -> None:
        """Begin holding the current position. Returns immediately."""
