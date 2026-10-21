"""CarlaAir's AirSim behind `VehicleAdapter` and `SceneAdapter`.

Every method makes EXACTLY the AirSim call, or pair of calls, that
`v0.1-open-loop-baseline` made for the same purpose: same method, same
arguments, same order, same blocking `.join()`. That is not tidiness. It is
what lets Phase 2 move the agent onto this class with `tests/test_golden.py`
proving nothing changed. Anything this class "improves" would show up there
as a behaviour change.

So: no retries, no error translation, no defaults filled in. Where the
baseline relied on AirSim's own default (takeoff's timeout, a climb's
timeout), the call here leaves the argument out too.

`airsim` is imported lazily, so code that only plans, or only tests against a
fake client, never needs the package or a simulator.

PHASE 3 ADDITIONS, which the baseline never calls: the heading in `get_state`
(read from the same `getMultirotorState` call, so no new call), the
`ROTATE_TO_YAW` primitive (`rotateToYawAsync`) and `cancel`
(`cancelLastTask`). Having no baseline to copy, their call shapes follow
AirSim's own API, and their behaviour in CarlaAir is checked in a live
flight before Phase 3 closes.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.models import (
    CollisionInfo,
    Position,
    PrimitiveCommand,
    PrimitiveKind,
    PrimitiveResult,
    VehicleState,
)

AIRSIM_PORT = 41451


class AirSimAdapter:
    """One AirSim connection, as a VehicleAdapter and a SceneAdapter.

    Give each flight thread its own (see `connect`). A client shared between
    threads fails; separate connections work. Measured in Phase 1.
    """

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def connect(cls, host: str = "127.0.0.1", port: int = AIRSIM_PORT) -> "AirSimAdapter":
        """Open a NEW connection and wait for the simulator to answer."""
        import airsim

        client = airsim.MultirotorClient(ip=host, port=port)
        client.confirmConnection()
        return cls(client)

    # ------------------------------------------------------- VehicleAdapter

    def get_state(self, vehicle_id: str) -> VehicleState:
        state = self.client.getMultirotorState(vehicle_name=vehicle_id)
        p = state.kinematics_estimated.position
        q = getattr(state.kinematics_estimated, "orientation", None)
        return VehicleState(vehicle_id, Position(p.x_val, p.y_val, p.z_val),
                            getattr(state, "landed_state", None),
                            None if q is None else yaw_degrees(q.w_val, q.x_val, q.y_val, q.z_val))

    def get_pose(self, vehicle_id: str) -> Position:
        # Positional, as the baseline called it.
        p = self.client.simGetVehiclePose(vehicle_id).position
        return Position(p.x_val, p.y_val, p.z_val)

    def get_collision(self, vehicle_id: str) -> CollisionInfo:
        info = self.client.simGetCollisionInfo(vehicle_name=vehicle_id)
        point = getattr(info, "impact_point", None)
        return CollisionInfo(
            has_collided=bool(getattr(info, "has_collided", False)),
            time_stamp=getattr(info, "time_stamp", None),
            object_name=getattr(info, "object_name", "") or "",
            penetration_depth=float(getattr(info, "penetration_depth", 0.0)),
            impact_point=None if point is None else Position(point.x_val, point.y_val, point.z_val),
        )

    def has_control(self, vehicle_id: str) -> bool:
        # Added in Phase 2 step 5 for the sandbox's :status, which reads it.
        return self.client.isApiControlEnabled(vehicle_name=vehicle_id)

    def take_control(self, vehicle_id: str) -> None:
        self.client.enableApiControl(True, vehicle_name=vehicle_id)
        self.client.armDisarm(True, vehicle_name=vehicle_id)

    def release(self, vehicle_id: str) -> None:
        # Disarm first, then hand back. If disarming raises, control is not
        # handed back either -- the order and the coupling are the baseline's.
        self.client.armDisarm(False, vehicle_name=vehicle_id)
        self.client.enableApiControl(False, vehicle_name=vehicle_id)

    def execute_primitive(self, vehicle_id: str, command: PrimitiveCommand) -> PrimitiveResult:
        kind, p = command.kind, command.params
        c = self.client
        if kind is PrimitiveKind.TAKE_OFF:
            c.takeoffAsync(vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.MOVE_TO_Z:
            extra = {} if p.get("timeout") is None else {"timeout_sec": p["timeout"]}
            c.moveToZAsync(p["z"], p["speed"], **extra, vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.VELOCITY:
            c.moveByVelocityBodyFrameAsync(
                p["vx"], p["vy"], 0.0, p["duration"], vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.HOVER:
            c.hoverAsync(vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.MOVE_TO_POSITION:
            extra = {} if p.get("timeout") is None else {"timeout_sec": p["timeout"]}
            c.moveToPositionAsync(p["x"], p["y"], p["z"], p["speed"],
                                  **extra, vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.LAND:
            extra = {} if p.get("timeout") is None else {"timeout_sec": p["timeout"]}
            c.landAsync(**extra, vehicle_name=vehicle_id).join()
        elif kind is PrimitiveKind.ROTATE_TO_YAW:
            extra = {} if p.get("timeout") is None else {"timeout_sec": p["timeout"]}
            if p.get("margin") is not None:
                extra["margin"] = p["margin"]
            c.rotateToYawAsync(p["yaw"], **extra, vehicle_name=vehicle_id).join()
        else:  # unreachable: PrimitiveCommand rejects unknown kinds
            raise ValueError(f"unhandled primitive {kind!r}")
        return PrimitiveResult(vehicle_id, kind)

    def stop(self, vehicle_id: str) -> None:
        self.execute_primitive(vehicle_id, PrimitiveCommand.hover())

    def cancel(self, vehicle_id: str) -> None:
        self.client.cancelLastTask(vehicle_name=vehicle_id)

    # --------------------------------------------------------- SceneAdapter

    def confirm_connection(self) -> None:
        self.client.confirmConnection()

    def reset(self) -> None:
        self.client.reset()

    def list_vehicles(self) -> list[str]:
        return list(self.client.listVehicles())

    def add_vehicle(self, vehicle_id: str, vehicle_type: str, position: Position) -> bool:
        return self.client.simAddVehicle(vehicle_id, vehicle_type, _pose(position))

    def place_vehicle(self, vehicle_id: str, position: Position,
                      ignore_collision: bool = True) -> None:
        self.client.simSetVehiclePose(_pose(position), ignore_collision=ignore_collision,
                                      vehicle_name=vehicle_id)


def yaw_degrees(w: float, x: float, y: float, z: float) -> float:
    """Heading, in degrees, of an orientation quaternion (w, x, y, z).

    The yaw term of AirSim's own `to_eularian_angles`, so the number matches
    what AirSim reports; in degrees, within -180..180. Pure, so it is tested
    without a simulator.
    """
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _pose(position: Position) -> Any:
    """A level AirSim pose at `position` -- the only pose the baseline builds."""
    import airsim

    return airsim.Pose(airsim.Vector3r(position.x, position.y, position.z),
                       airsim.to_quaternion(0.0, 0.0, 0.0))
