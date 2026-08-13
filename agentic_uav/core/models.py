"""Core data types and the adapter/planner-facing interfaces.

Plain data structures that flow between the agent, the planner, the skill layer,
and the simulator adapter. Nothing here talks to AirSim or an LLM directly.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .enums import SkillStatus


@dataclass
class Position3D:
    """A point in the NED frame (z negative is up)."""
    x: float
    y: float
    z: float

    def distance_to(self, other: "Position3D") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )

    def horizontal_distance_to(self, other: "Position3D") -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


@dataclass
class VehicleState:
    """A snapshot of one drone's state, returned by the adapter."""
    vehicle_id: str
    position: Position3D
    heading_deg: float = 0.0
    armed: bool = False


@dataclass
class NavOutcome:
    """Low-level result of a navigation primitive, returned by the adapter.

    The skill executor turns this (plus the skill's tolerance) into a SkillResult.
    """
    final_position: Position3D
    elapsed_s: float
    timed_out: bool = False


@dataclass
class SkillResult:
    """Structured result of executing a high-level skill (Phase 3 contract)."""
    status: SkillStatus
    skill: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    final_position: Optional[Position3D] = None
    error_code: Optional[str] = None
    detail: str = ""

    @property
    def duration_s(self) -> float:
        return self.ended_at - self.started_at


# --- low-level command (Phase 1/2 movement path) ---


@dataclass
class SkillCommand:
    """A single low-level action, e.g. fly_straight for 5 seconds."""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)


# --- planner-facing types (unchanged from Phase 1/2) ---


@dataclass
class AgentContext:
    vehicle_id: str
    instruction: str


@dataclass
class AgentDecision:
    plan: List[SkillCommand] = field(default_factory=list)
    source: str = ""


# --- the simulator interface ---


@runtime_checkable
class VehicleAdapter(Protocol):
    """The only way agent/skill code touches the simulator.

    Phase 3 adds navigation primitives (waypoint, heading, hold) alongside the
    Phase 1/2 low-level execute_skill path. Implemented by AirSimVehicleAdapter
    (real sim) and MockVehicleAdapter (kinematic, no sim).
    """

    # state
    def get_state(self, vehicle_id: str) -> VehicleState: ...
    def get_position(self, vehicle_id: str) -> Position3D: ...

    # navigation primitives (Phase 3.2)
    def takeoff(self, vehicle_id: str, target_altitude: float,
                timeout_s: float) -> NavOutcome: ...
    def go_to_waypoint(self, vehicle_id: str, waypoint: Position3D,
                       speed_mps: float, timeout_s: float) -> NavOutcome: ...
    def turn_to_heading(self, vehicle_id: str, heading_deg: float,
                        timeout_s: float) -> NavOutcome: ...
    def hold(self, vehicle_id: str, duration_s: float) -> NavOutcome: ...
    def land(self, vehicle_id: str, timeout_s: float) -> NavOutcome: ...
    def cancel(self, vehicle_id: str) -> None: ...

    # lifecycle
    def stop(self, vehicle_id: str) -> None: ...
