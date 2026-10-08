"""The one place this codebase talks to AirSim, and the one place NED
(negative-up) gets converted to/from plain positive-up altitude.

ground_z is recorded once, at connect_and_takeoff() time, from wherever the
drone happens to be - so it must only ever be called once per real physical
takeoff. The caller (main.py) is responsible for that: connect_and_takeoff()
once per session, then execute() as many plans as needed without re-taking
off, landing only when the user actually says stop. Calling
connect_and_takeoff() again while still airborne would treat the current
altitude as ground level, and a later land() would disarm mid-air.
"""

import queue
import threading

from ..control.navigation import (
    DEFAULT_HEIGHT, LAND_FAST_ABOVE, LAND_FAST_SPEED, LAND_SETTLE_SECS,
    LAND_SLOW_SPEED, MOVE_SPEED,
)
from ..core.enums import ActionType
from ..core.interfaces import VehicleAdapter

# AirSim's Python client (msgpack-rpc over Tornado) has a known concurrency bug:
# concurrent RPC calls against the SAME client instance from more than one
# thread can corrupt Tornado's own write buffer ("BufferError: Existing
# exports of data: object cannot be re-sized", or the same fault surfacing
# inside Tornado's own IOLoop callback thread). This repo already gives each
# vehicle its own client instance, but two separate threads still touch any
# one drone's client concurrently: that drone's own flight thread (moving it,
# polling its own arrival) AND the telemetry recorder thread (polling every
# drone's position on its own timer). That overlap is the actual race.
#
# First attempt used ONE lock shared across all 4 drones - that stopped the
# crash but wrecked responsiveness: every drone's poll loop now queued behind
# the other three's RPC round-trips on every single check, so a drone could
# sit well within its arrival tolerance for the full 30s skill timeout without
# ever getting a fast-enough speed reading to confirm it had settled. The
# actual conflict was never cross-drone - each drone's own client is only
# ever touched by ITS OWN flight thread plus the recorder thread, never by
# another drone's thread. A lock PER ADAPTER (see __init__) protects exactly
# that real overlap, with zero unrelated contention between drones.

# moveToPositionAsync()'s own timeout_sec parameter defaults to 3e38 - effectively
# unbounded - unless passed explicitly, which nothing here did. A live multi-drone
# run hung for over an hour: 3 of 4 drones landed fine, the 4th never returned,
# because all 4 land at the same tight spawn cluster and the last one back can find
# the landing zone already occupied by a parked drone. If noclip wasn't active, that
# collision means the move server-side NEVER reports completion, so an unbounded
# .join() blocks forever - no code-level logic can recover from that, only a real
# server-side timeout can. takeoffAsync/landAsync already default to sane timeouts
# (20s/60s); every moveToPositionAsync call below now gets one too.
MOVE_TIMEOUT_S = 30.0  # matches the skill-level timeout in control/navigation.py

# Even with the above fix, a live run still hung the same way - 3 drones landed, the 4th
# never returned. That proves the freeze isn't inside a move/land command at all: it's in
# getMultirotorState(), a PLAIN synchronous call AirSim's own API gives no timeout_sec
# parameter for at all. If that call itself never returns - the connection silently
# stalling, not the flight controller - the 30s skill-level timeout in control/skills.py
# never gets a chance to fire, because the polling loop is stuck INSIDE the call it's
# supposed to be timing, not at the point where it checks the clock.
RPC_READ_TIMEOUT_S = 10.0


def _with_timeout(fn, timeout_s: float):
    """Runs fn() in a background thread and gives up after timeout_s. Python
    cannot cancel an arbitrary blocking call, so a genuinely stuck call leaks
    its thread (daemon=True, so it won't block process exit) - but the
    caller gets control back instead of hanging forever, which is what
    actually matters here. Known residual risk: if that orphaned call ever
    does complete later, it touches self.client without the lock a NEW call
    would be holding by then - accepted as better than the alternative
    (hanging forever, every time, with no way out) for what should be a
    rare failure path, not normal operation."""
    result_q = queue.Queue(maxsize=1)

    def run():
        try:
            result_q.put(("ok", fn()))
        except Exception as e:
            result_q.put(("error", e))

    threading.Thread(target=run, daemon=True).start()
    try:
        status, value = result_q.get(timeout=timeout_s)
    except queue.Empty:
        raise TimeoutError(f"AirSim RPC call did not return within {timeout_s}s")
    if status == "error":
        raise value
    return value

# world-frame (x, y) unit direction per strafe action - heading is held fixed,
# the drone strafes rather than turning to face its travel direction.
_DIRECTIONS = {
    ActionType.FLY_FORWARD.value: (1.0, 0.0),
    ActionType.FLY_BACKWARD.value: (-1.0, 0.0),
    ActionType.FLY_LEFT.value: (0.0, -1.0),
    ActionType.FLY_RIGHT.value: (0.0, 1.0),
}


class AirSimVehicleAdapter(VehicleAdapter):
    def __init__(self, vehicle_name="Drone1"):
        import airsim  # lazy import, only needed when actually flying
        self._airsim = airsim
        self.vehicle_name = vehicle_name
        self.client = airsim.MultirotorClient()
        self.client.confirmConnection()
        self.client.enableApiControl(True, vehicle_name)
        self.client.armDisarm(True, vehicle_name)
        self._ground_ned = None  # set on connect_and_takeoff()
        self._lock = threading.Lock()  # protects THIS drone's client from its own
        # flight thread racing the telemetry recorder thread - see module docstring

    # --- the one NED boundary ---

    def _to_ned(self, height_above_ground: float) -> float:
        return self._ground_ned - height_above_ground

    def _from_ned(self, z_ned: float) -> float:
        return self._ground_ned - z_ned

    def _get_position_ned(self):
        """The one place getMultirotorState() is called for a raw position -
        locked, and shared by every caller below, so get_position() no longer
        makes two separate RPC round-trips (get_xy() + get_height()) for what
        is one state read. Watchdog-timed - see RPC_READ_TIMEOUT_S above."""
        with self._lock:
            return _with_timeout(
                lambda: self.client.getMultirotorState(self.vehicle_name).kinematics_estimated.position,
                RPC_READ_TIMEOUT_S)

    def get_height(self) -> float:
        return self._from_ned(self._get_position_ned().z_val)

    def get_xy(self):
        pos = self._get_position_ned()
        return pos.x_val, pos.y_val

    # --- lifecycle ---

    def connect_and_takeoff(self):
        self._ground_ned = self._get_position_ned().z_val  # recorded here - see the module docstring
        with self._lock:
            self.client.takeoffAsync(vehicle_name=self.vehicle_name, timeout_sec=20).join()
        self.set_height(DEFAULT_HEIGHT)  # locks internally

    # --- non-blocking primitives, for skills.py's polling loops ---

    def get_position(self):
        pos = self._get_position_ned()
        return (pos.x_val, pos.y_val, self._from_ned(pos.z_val))

    def get_speed(self):
        with self._lock:
            v = _with_timeout(
                lambda: self.client.getMultirotorState(self.vehicle_name).kinematics_estimated.linear_velocity,
                RPC_READ_TIMEOUT_S)
        return (v.x_val ** 2 + v.y_val ** 2 + v.z_val ** 2) ** 0.5

    def start_move_to(self, x, y, z):
        with self._lock:
            self.client.moveToPositionAsync(
                x, y, self._to_ned(z), MOVE_SPEED, vehicle_name=self.vehicle_name,
            )

    def start_hover(self):
        with self._lock:
            self.client.hoverAsync(vehicle_name=self.vehicle_name)

    # --- action executors, one per ActionType ---
    # Every one of these holds self._lock across its .join() too, not just the
    # dispatch - .join() itself polls via more RPC calls, so releasing early would
    # still let it race the recorder thread's read mid-wait. See the module-level
    # comment for why this is needed at all.

    def fly_to(self, x, y, z):
        with self._lock:
            self.client.moveToPositionAsync(
                x, y, self._to_ned(z), MOVE_SPEED, vehicle_name=self.vehicle_name,
                timeout_sec=MOVE_TIMEOUT_S,
            ).join()

    def set_height(self, z):
        x, y = self.get_xy()
        with self._lock:
            self.client.moveToPositionAsync(
                x, y, self._to_ned(z), MOVE_SPEED, vehicle_name=self.vehicle_name,
                timeout_sec=MOVE_TIMEOUT_S,
            ).join()

    def _strafe(self, action, distance):
        dx, dy = _DIRECTIONS[action]
        x, y = self.get_xy()
        target_z = self._get_position_ned().z_val
        with self._lock:
            self.client.moveToPositionAsync(
                x + dx * distance, y + dy * distance, target_z, MOVE_SPEED,
                vehicle_name=self.vehicle_name, timeout_sec=MOVE_TIMEOUT_S,
            ).join()

    def hover(self, duration):
        with self._lock:
            _with_timeout(lambda: self.client.hoverAsync(vehicle_name=self.vehicle_name).join(),
                           MOVE_TIMEOUT_S)
        import time
        time.sleep(duration)  # no RPC happening during the wait itself - don't hold the lock for it

    def land(self):
        """Fast descent to LAND_FAST_ABOVE, settle, slow final approach, disarm.
        Most of the drop doesn't need precision; only the final few metres,
        where impact speed matters, get the slow speed."""
        x, y = self.get_xy()
        fast_target_ned = self._to_ned(LAND_FAST_ABOVE)
        with self._lock:
            self.client.moveToPositionAsync(
                x, y, fast_target_ned, LAND_FAST_SPEED, vehicle_name=self.vehicle_name,
                timeout_sec=MOVE_TIMEOUT_S,
            ).join()
            # hoverAsync has NO timeout_sec parameter at all (checked directly against the
            # installed airsim client) - unlike every move/land/takeoff command, there is no
            # native way to bound this one. Watchdog it like the raw state reads above.
            _with_timeout(lambda: self.client.hoverAsync(vehicle_name=self.vehicle_name).join(),
                           MOVE_TIMEOUT_S)
        import time
        time.sleep(LAND_SETTLE_SECS)

        with self._lock:
            self.client.moveToPositionAsync(
                x, y, self._ground_ned, LAND_SLOW_SPEED, vehicle_name=self.vehicle_name,
                timeout_sec=MOVE_TIMEOUT_S,
            ).join()
            self.client.landAsync(vehicle_name=self.vehicle_name, timeout_sec=60).join()
            # armDisarm is also a plain synchronous call with no timeout concept at all.
            _with_timeout(lambda: self.client.armDisarm(False, self.vehicle_name), RPC_READ_TIMEOUT_S)

    # --- run a validated plan ---

    def execute(self, commands):
        """Run one validated plan. Does NOT take off first - call
        connect_and_takeoff() once per session before the first execute()."""
        for cmd in commands:
            if cmd.action == ActionType.FLY_TO.value:
                self.fly_to(cmd.params["x"], cmd.params["y"], cmd.params["z"])
            elif cmd.action == ActionType.SET_HEIGHT.value:
                self.set_height(cmd.params["z"])
            elif cmd.action in _DIRECTIONS:
                self._strafe(cmd.action, cmd.params["distance"])
            elif cmd.action == ActionType.HOVER.value:
                self.hover(cmd.params["duration"])
            elif cmd.action == ActionType.LAND.value:
                self.land()
