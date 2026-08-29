"""A fake `airsim` module, so the AirSim code path can be tested without AirSim.

Why this exists: the mock adapter tests the *agent logic*, but it bypasses
`AirSimVehicleAdapter` entirely. That left the whole `--airsim` path untested,
and two real bugs hid there - a missing `now()` clock (so battery never depleted
in the simulator) and scripts that never spawned their vehicles (so every Phase
4-7 run would have died with "Vehicle API for Drone1 not available").

Installing this fake into `sys.modules["airsim"]` lets the real
`AirSimVehicleAdapter`, the real scripts and the real threaded runner execute
end to end on any machine. It models AirSim's *contract*, not its physics:

  - vehicles must be registered (or spawned) before they can be commanded;
  - `moveToPositionAsync` may leave the drone slightly off target (`arrival_error_m`);
  - a move can fail to complete at all (`fail_first_move`), as a real one can;
  - API control must be enabled and the vehicle armed before it will move.

**This is not a substitute for flying it.** It cannot tell you whether a real
sweep exceeds its timeout, whether the drone lands cleanly, or how four real RPC
clients behave under load. It catches wiring, contract and concurrency bugs -
the class of failure that wastes a session before the sim even gets going.

    from agentic_uav.simulator import fake_airsim
    fake_airsim.install()                     # perfect behaviour
    fake_airsim.install(arrival_error_m=0.5)  # slightly sloppy arrivals
"""

import math
import sys
import threading
import types


class _Future:
    """Stands in for an AirSim async task."""

    def __init__(self, fn=None):
        self._fn = fn

    def join(self):
        if self._fn:
            self._fn()
        return None


class FakeWorld:
    """Shared state for every client, mirroring one running simulator."""

    def __init__(self, arrival_error_m=0.0, fail_first_move=False,
                 move_duration_s=0.0,
                 known_vehicles=("Drone1", "Drone2", "Drone3", "Drone4")):
        self.lock = threading.RLock()
        self.positions = {v: [0.0, 0.0, 0.0] for v in known_vehicles}
        self.registered = set(known_vehicles)
        self.api_enabled = set()
        self.armed = set()
        self.arrival_error_m = arrival_error_m
        self.fail_first_move = fail_first_move
        # Real moves take real time. Setting this makes the fake burn wall clock
        # per move, so battery depletion and information ageing are exercised
        # the way they will be in the simulator.
        self.move_duration_s = move_duration_s
        self._moves = 0
        self.calls = []          # every RPC, for assertions in tests

    def log(self, name, vehicle):
        self.calls.append((name, vehicle))

    def require(self, vehicle):
        if vehicle not in self.registered:
            raise RuntimeError(
                f"Vehicle API for '{vehicle}' not available. "
                "Make sure vehicle is spawned or declared in settings.json")


_world = None


class MultirotorClient:
    def __init__(self, *a, **k):
        self._w = _world

    # --- connection / setup ---

    def confirmConnection(self):
        return True

    def listVehicles(self):
        with self._w.lock:
            return sorted(self._w.registered)

    def simAddVehicle(self, vehicle_name=None, vehicle_type=None, pose=None, **k):
        with self._w.lock:
            self._w.registered.add(vehicle_name)
            self._w.positions.setdefault(vehicle_name, [0.0, 0.0, 0.0])
            self._w.log("simAddVehicle", vehicle_name)
        return True

    def enableApiControl(self, on, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        with self._w.lock:
            (self._w.api_enabled.add if on else self._w.api_enabled.discard)(vehicle_name)
            self._w.log("enableApiControl", vehicle_name)

    def armDisarm(self, on, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        with self._w.lock:
            (self._w.armed.add if on else self._w.armed.discard)(vehicle_name)
            self._w.log("armDisarm", vehicle_name)

    # --- state ---

    def getMultirotorState(self, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        with self._w.lock:
            p = list(self._w.positions.setdefault(vehicle_name, [0.0, 0.0, 0.0]))
        state = types.SimpleNamespace()
        state.kinematics_estimated = types.SimpleNamespace(
            position=types.SimpleNamespace(x_val=p[0], y_val=p[1], z_val=p[2]),
            orientation=None)
        return state

    # --- motion ---

    def _burn(self):
        if self._w.move_duration_s:
            import time as _t
            _t.sleep(self._w.move_duration_s)

    def takeoffAsync(self, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        self._w.log("takeoffAsync", vehicle_name)
        return _Future(self._burn)

    def moveToZAsync(self, z, velocity, vehicle_name=None, **k):
        self._w.require(vehicle_name)

        def apply():
            self._burn()
            with self._w.lock:
                self._w.positions.setdefault(vehicle_name, [0.0, 0.0, 0.0])[2] = z
                self._w.log("moveToZAsync", vehicle_name)
        return _Future(apply)

    def moveToPositionAsync(self, x, y, z, velocity, vehicle_name=None, **k):
        self._w.require(vehicle_name)

        def apply():
            self._burn()
            with self._w.lock:
                self._w._moves += 1
                if self._w.fail_first_move and self._w._moves == 1:
                    self._w.log("moveToPositionAsync:failed", vehicle_name)
                    return                      # drone simply doesn't get there
                e = self._w.arrival_error_m
                off = e / math.sqrt(2.0) if e else 0.0
                self._w.positions[vehicle_name] = [x + off, y + off, z]
                self._w.log("moveToPositionAsync", vehicle_name)
        return _Future(apply)

    def rotateToYawAsync(self, yaw, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        return _Future()

    def hoverAsync(self, vehicle_name=None, **k):
        self._w.require(vehicle_name)
        return _Future()

    def cancelLastTask(self, vehicle_name=None, **k):
        return None


DEFAULT_VEHICLES = ("Drone1", "Drone2", "Drone3", "Drone4")


def install(arrival_error_m=0.0, fail_first_move=False, move_duration_s=0.0,
            known_vehicles=None):
    """Put a fake `airsim` into sys.modules. Returns the FakeWorld.

    `known_vehicles=None` means "a normally configured sim" (Drone1-4 declared in
    settings.json). Pass an explicit empty tuple to simulate a sim where nothing
    is declared, which is what the spawn self-heal has to cope with.
    """
    global _world
    vehicles = DEFAULT_VEHICLES if known_vehicles is None else tuple(known_vehicles)
    _world = FakeWorld(arrival_error_m=arrival_error_m,
                       fail_first_move=fail_first_move,
                       move_duration_s=move_duration_s,
                       known_vehicles=vehicles)

    m = types.ModuleType("airsim")
    m.MultirotorClient = MultirotorClient
    m.Pose = lambda *a, **k: None
    m.Vector3r = lambda *a, **k: None
    m.Quaternionr = lambda *a, **k: None
    m.to_eularian_angles = lambda q: (0.0, 0.0, 0.0)
    sys.modules["airsim"] = m

    # drop any adapter module that imported the real airsim earlier
    sys.modules.pop("agentic_uav.simulator.airsim_adapter", None)
    return _world


def uninstall():
    global _world
    _world = None
    sys.modules.pop("airsim", None)
    sys.modules.pop("agentic_uav.simulator.airsim_adapter", None)


def world():
    return _world
