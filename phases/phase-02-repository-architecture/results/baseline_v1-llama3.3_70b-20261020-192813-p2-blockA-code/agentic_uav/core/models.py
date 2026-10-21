"""The data the agent and the simulator exchange.

Everything here is a plain value, so it can be built in a test, logged as JSON
and compared without a simulator running. It is what lets the agent depend on
a `VehicleAdapter` instead of on AirSim's own types (AUV-03, 2.2).

COORDINATES ARE NED, EXACTLY AS AIRSIM REPORTS THEM. North, East, Down: x
forward, y right, z DOWN, so more negative z is higher. Nothing here converts
to "height above ground", because the ground's NED z is a measured quantity
(29.25 on Town10HD, from Phase 1) and converting belongs with whoever measured
it. Hiding that sign in a helper is how every altitude in Phase 1 came out
29 m wrong.

Phase 2 is a pure refactor, so these types carry what the baseline already
uses and nothing more. Phase 3's flight-skill layer is where `SkillResult`
grows into a structured report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Position:
    """A point in AirSim's NED frame, metres."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class VehicleState:
    """What the simulator's state estimate says about one vehicle.

    `landed_state` is AirSim's own field (0 landed, 1 flying), kept as the raw
    value because Phase 1 found it unreliable: it reports "landed" for a
    motionless aircraft hovering 29 m up. The baseline treats height as
    authoritative and this only as a tie-breaker.
    """

    vehicle_id: str
    position: Position
    landed_state: int | None = None


@dataclass(frozen=True)
class CollisionInfo:
    """AirSim's MOST RECENT collision for one vehicle -- not a tally.

    It persists across flights and is overwritten by every new contact,
    including the landing. `time_stamp` is how a caller tells a new collision
    from a stale one.
    """

    has_collided: bool
    time_stamp: Any = None
    object_name: str = ""
    penetration_depth: float = 0.0
    impact_point: Position | None = None


class SkillKind(str, Enum):
    """The primitive things a vehicle can be told to do.

    Deliberately primitive. The agent's choices -- braking after a velocity
    leg, altitudes measured from the ground, checking that a landing landed --
    stay in the agent, so that moving code behind the adapter cannot move a
    decision with it.
    """

    TAKE_OFF = "take_off"
    MOVE_TO_Z = "move_to_z"                # absolute NED z
    VELOCITY = "velocity"                  # body-frame, z velocity zero
    HOVER = "hover"
    MOVE_TO_POSITION = "move_to_position"  # absolute NED x, y, z
    LAND = "land"


@dataclass(frozen=True)
class SkillCommand:
    """One skill for one vehicle, with its parameters.

    Build with the class methods rather than by hand: they fix the parameter
    names the adapters expect. A `timeout` of None means "the simulator's
    default", which for AirSim is effectively unbounded. That is what the
    baseline uses for takeoff, climbs and velocity legs.
    """

    kind: SkillKind
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SkillKind(self.kind))

    @classmethod
    def take_off(cls) -> "SkillCommand":
        return cls(SkillKind.TAKE_OFF)

    @classmethod
    def move_to_z(cls, z: float, speed: float, timeout: float | None = None) -> "SkillCommand":
        return cls(SkillKind.MOVE_TO_Z, {"z": z, "speed": speed, "timeout": timeout})

    @classmethod
    def velocity(cls, vx: float, vy: float, duration: float) -> "SkillCommand":
        return cls(SkillKind.VELOCITY, {"vx": vx, "vy": vy, "duration": duration})

    @classmethod
    def hover(cls) -> "SkillCommand":
        return cls(SkillKind.HOVER)

    @classmethod
    def move_to_position(cls, x: float, y: float, z: float, speed: float,
                         timeout: float | None = None) -> "SkillCommand":
        return cls(SkillKind.MOVE_TO_POSITION,
                   {"x": x, "y": y, "z": z, "speed": speed, "timeout": timeout})

    @classmethod
    def land(cls, timeout: float | None = None) -> "SkillCommand":
        return cls(SkillKind.LAND, {"timeout": timeout})


@dataclass(frozen=True)
class SkillResult:
    """What executing one skill reported.

    Minimal on purpose: the baseline learns nothing from a skill except that it
    returned, and anything more would be new behaviour. A skill that fails
    raises, exactly as the AirSim call underneath it does, so failure messages
    in the record stay word for word what they were. Phase 3 makes this a
    structured report.
    """

    vehicle_id: str
    kind: SkillKind
    completed: bool = True
