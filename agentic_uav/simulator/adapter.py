"""What the agent may ask of a simulator -- and nothing else.

AUV-03 calls `VehicleAdapter` "the highest-leverage interface in the project":
the agent never calls arbitrary AirSim methods, so it can be tested without
CarlaAir, and every simulator becomes a constructor argument.

AUV-03 sketches three methods (`get_state`, `execute_skill`, `stop`); here the
middle one is `execute_primitive`, since Phase 3, because what an adapter runs
are primitives and the mission-level skills are built on top of them. The
baseline needs four more, and this protocol states them openly rather than
leaving the agent to reach around it:

* `get_pose` -- the simulator's ground-truth pose, distinct from the state
  ESTIMATE in `get_state`. The baseline records where a flight ended from the
  pose, and its altitudes from the estimate. Phase 2 keeps both.
* `get_collision` -- the most recent collision, polled during flight.
* `take_control` and `release` -- the hand-over around a flight. Releasing
  disarms, which cuts the motors, so it is never folded into a skill.

Phase 3 adds what heading and waypoint navigation need (AUV-04, 3.2): a
heading in the state, a turn-to-heading primitive, and `cancel`, to abort a
movement in progress. The baseline never uses them.

Scene management -- resetting the world, adding and placing vehicles -- is a
separate protocol, because it is the scenario's business and not a drone's.
CarlaAir's AirSim implements both on one connection.

ONE ADAPTER PER CONNECTION, ONE CONNECTION PER THREAD. AUV-03 assumed one
adapter should own the only connection, because AirSim is "hostile to
concurrent clients". Phase 1 measured the opposite: a client SHARED between
threads fails (`IOLoop is already running`, `BufferError`), and separate
connections, one per flight thread, have worked on every flight since.

Errors propagate. A simulator call that raises makes the adapter raise the same
exception, so the flight record's failure text stays what it was.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.models import CollisionInfo, Position, PrimitiveCommand, PrimitiveResult, VehicleState


@runtime_checkable
class VehicleAdapter(Protocol):
    """Everything a flight may do to, or learn about, one vehicle."""

    def get_state(self, vehicle_id: str) -> VehicleState:
        """The state ESTIMATE: position in NED, AirSim's landed flag, heading."""
        ...

    def get_pose(self, vehicle_id: str) -> Position:
        """The simulator's ground-truth position, in NED."""
        ...

    def get_collision(self, vehicle_id: str) -> CollisionInfo:
        """The most recent collision. Stale until its time_stamp changes."""
        ...

    def has_control(self, vehicle_id: str) -> bool:
        """Whether the API holds control of the vehicle."""
        ...

    def take_control(self, vehicle_id: str) -> None:
        """Enable API control, then arm. The vehicle should be at rest."""
        ...

    def release(self, vehicle_id: str) -> None:
        """Disarm, then hand control back. Disarming cuts the motors: land first."""
        ...

    def execute_primitive(self, vehicle_id: str, command: PrimitiveCommand) -> PrimitiveResult:
        """Run one primitive to completion. Raises if the simulator call raises."""
        ...

    def stop(self, vehicle_id: str) -> None:
        """Halt in place: hold position and altitude."""
        ...

    def cancel(self, vehicle_id: str) -> None:
        """Abort the vehicle's movement in progress. Does not brake: follow
        with `stop`. Meant to be called from another thread, on that thread's
        own adapter, while the movement blocks its flight thread."""
        ...


@runtime_checkable
class SceneAdapter(Protocol):
    """The world the vehicles live in: resetting it, and who is in it."""

    def confirm_connection(self) -> None:
        """Block until the simulator answers."""
        ...

    def reset(self) -> None:
        """Return every vehicle to its spawn pose. Does NOT remove any."""
        ...

    def list_vehicles(self) -> list[str]:
        """Every vehicle in the scene, declared or spawned at runtime."""
        ...

    def add_vehicle(self, vehicle_id: str, vehicle_type: str, position: Position) -> bool:
        """Spawn a vehicle into the running simulator. AirSim ignores the pose."""
        ...

    def place_vehicle(self, vehicle_id: str, position: Position,
                      ignore_collision: bool = True) -> None:
        """Teleport a vehicle, level, to a position. It then falls to rest."""
        ...
