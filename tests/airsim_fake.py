"""A recording stand-in for AirSim, a virtual clock, and a scripted Ollama.

Not a test module: the characterisation harness that `tools/record_golden.py`
and `tests/test_golden.py` share. It exists for Phase 2, which moves every
AirSim call behind a `VehicleAdapter` and every planning call behind a
`MissionPlanner`, and must not change behaviour while doing it (AUV-03, 2.3).
"Behaviour" is made concrete here as the exact sequence of simulator calls each
drone makes and the exact request each plan is made from, captured from the
code tagged `v0.1-open-loop-baseline` before anything moves.

The fake is deliberately simple physics: commands set positions, nothing
drifts, every drone rests on the same ground. It is not a simulator -- that is
the Phase 3 mock adapter's job. It only has to drive the agent down the same
code paths a real flight does, deterministically, so that two versions of the
code can be compared call for call.

Three things make that deterministic:

* **One stream per drone.** Each flight thread opens its own connection and
  only ever addresses its own vehicle, so its calls are recorded in order under
  that vehicle's name. Thread interleaving cannot change a per-drone sequence.
* **A per-thread virtual clock.** `time.sleep` advances the calling thread's
  clock instead of sleeping, so a 30 s mission runs in milliseconds and every
  timeout, settle loop and `flight_seconds` comes out the same every time.
* **The separation monitor is not recorded.** It polls on a real 10 Hz timer
  through its own connection; how many polls fit into a run depends on the
  machine. Its calls go to a stream that is discarded.
"""

from __future__ import annotations

import contextlib
import io
import sys
import threading
import time as _real_time
import types
from typing import Any

GROUND_Z = 29.25        # Town10HD's ground in NED, as measured on every valid run
SPACING = 4.0           # matches open_loop_agent.SPACING; checked at use


# --------------------------------------------------------------- virtual time

class VirtualTime:
    """Stands in for the `time` module inside the agent, per thread.

    Every thread starts at t = 1000.0 and moves only when it sleeps. Anything
    not overridden falls through to the real module (strftime, monotonic, ...).
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def _now(self) -> float:
        if not hasattr(self._local, "t"):
            self._local.t = 1000.0
        return self._local.t

    def time(self) -> float:
        return self._now()

    def sleep(self, seconds: float) -> None:
        self._local.t = self._now() + max(0.0, float(seconds))
        _real_time.sleep(0)          # still yield, so other threads progress

    def __getattr__(self, name: str) -> Any:
        return getattr(_real_time, name)


# ---------------------------------------------------------------- the world

def _norm(value: Any) -> Any:
    """Make an argument comparable and JSON-safe: floats rounded, AirSim
    geometry flattened, everything else by value."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    if hasattr(value, "position") and hasattr(value, "orientation"):      # Pose
        return {"pose": _norm(value.position), "orientation": _norm(value.orientation)}
    if all(hasattr(value, a) for a in ("x_val", "y_val", "z_val", "w_val")):  # Quaternionr
        return [_norm(value.w_val), _norm(value.x_val), _norm(value.y_val), _norm(value.z_val)]
    if all(hasattr(value, a) for a in ("x_val", "y_val", "z_val")):          # Vector3r
        return [_norm(value.x_val), _norm(value.y_val), _norm(value.z_val)]
    return repr(value)


class _Vehicle:
    def __init__(self, spawn_x: float) -> None:
        self.spawn_x = spawn_x
        self.x, self.y, self.z = spawn_x, 0.0, GROUND_Z
        self.landed_state = 0      # 0 Landed, 1 Flying
        self.api = False
        self.armed = False

    def reset(self) -> None:
        self.x, self.y, self.z = self.spawn_x, 0.0, GROUND_Z
        self.landed_state = 0


class FakeWorld:
    """Shared state behind every FakeClient of one run."""

    def __init__(self, declared: list[str] | None = None,
                 stuck_land: set[str] | None = None) -> None:
        self.vehicles: dict[str, _Vehicle] = {}
        for i, name in enumerate(declared if declared is not None else ["Drone1"]):
            self.vehicles[name] = _Vehicle(i * SPACING)
        # Drones whose descent and landAsync move nothing -- the 2026-10-06 and
        # 2026-10-19 failure, where `land` returned with the aircraft still up.
        self.stuck_land = set(stuck_land or ())
        self.lock = threading.Lock()
        self.calls: dict[str, list[list[Any]]] = {}

    def record(self, stream: str, method: str, args: tuple, kwargs: dict) -> None:
        if stream == "discard":
            return
        with self.lock:
            self.calls.setdefault(stream, []).append(
                [method, _norm(list(args)), _norm(dict(kwargs))])


class _Future:
    def join(self) -> None:
        return None


class FakeClient:
    """The subset of `airsim.MultirotorClient` the agent uses, recorded.

    `stream` decides where calls are written: "main" for the setup client,
    "vehicle" to file each call under the drone it addresses, "discard" for
    the separation monitor.
    """

    def __init__(self, world: FakeWorld, stream: str) -> None:
        self.world = world
        self.stream = stream

    # -- bookkeeping
    def _rec(self, method: str, args: tuple, kwargs: dict, vehicle: str | None = None) -> None:
        stream = self.stream
        if stream == "vehicle":
            stream = vehicle or kwargs.get("vehicle_name") or "unaddressed"
        self.world.record(stream, method, args, kwargs)

    def _v(self, name: str) -> _Vehicle:
        return self.world.vehicles[name]

    # -- connection and scene
    def confirmConnection(self) -> None:
        self._rec("confirmConnection", (), {})

    def reset(self) -> None:
        self._rec("reset", (), {})
        for v in self.world.vehicles.values():
            v.reset()

    def listVehicles(self) -> list[str]:
        self._rec("listVehicles", (), {})
        return list(self.world.vehicles)

    def simAddVehicle(self, name: str, vehicle_type: str, pose: Any, *args: Any, **kwargs: Any) -> bool:
        self._rec("simAddVehicle", (name, vehicle_type, pose) + args, kwargs)
        # Real AirSim ignores the pose and spawns at the player start.
        self.world.vehicles[name] = _Vehicle(0.0)
        return True

    def simSetVehiclePose(self, pose: Any, ignore_collision: bool, vehicle_name: str = "") -> None:
        self._rec("simSetVehiclePose", (pose, ignore_collision), {"vehicle_name": vehicle_name})
        v = self._v(vehicle_name)
        v.x, v.y = pose.position.x_val, pose.position.y_val
        v.spawn_x = v.x
        v.z = GROUND_Z            # it falls and comes to rest

    # -- state
    def getMultirotorState(self, vehicle_name: str = "") -> Any:
        self._rec("getMultirotorState", (), {"vehicle_name": vehicle_name})
        v = self._v(vehicle_name)
        position = types.SimpleNamespace(x_val=v.x, y_val=v.y, z_val=v.z)
        return types.SimpleNamespace(
            kinematics_estimated=types.SimpleNamespace(position=position),
            landed_state=v.landed_state)

    def simGetVehiclePose(self, vehicle_name: str = "") -> Any:
        # The agent passes the name positionally, so file it explicitly.
        self._rec("simGetVehiclePose", (vehicle_name,), {}, vehicle=vehicle_name)
        v = self._v(vehicle_name)
        return types.SimpleNamespace(
            position=types.SimpleNamespace(x_val=v.x, y_val=v.y, z_val=v.z))

    def simGetCollisionInfo(self, vehicle_name: str = "") -> Any:
        self._rec("simGetCollisionInfo", (), {"vehicle_name": vehicle_name})
        return types.SimpleNamespace(
            has_collided=False, time_stamp=0, object_name="", penetration_depth=0.0,
            impact_point=types.SimpleNamespace(x_val=0.0, y_val=0.0, z_val=0.0))

    # -- control
    def enableApiControl(self, on: bool, vehicle_name: str = "") -> bool:
        self._rec("enableApiControl", (on,), {"vehicle_name": vehicle_name})
        self._v(vehicle_name).api = on
        return True

    def armDisarm(self, arm: bool, vehicle_name: str = "") -> bool:
        self._rec("armDisarm", (arm,), {"vehicle_name": vehicle_name})
        self._v(vehicle_name).armed = arm
        return True

    def takeoffAsync(self, timeout_sec: float = 20, vehicle_name: str = "") -> _Future:
        self._rec("takeoffAsync", (), {"timeout_sec": timeout_sec, "vehicle_name": vehicle_name})
        v = self._v(vehicle_name)
        v.z, v.landed_state = GROUND_Z - 3.0, 1
        return _Future()

    def moveToZAsync(self, z: float, velocity: float, timeout_sec: float = 3e38,
                     *args: Any, vehicle_name: str = "", **kwargs: Any) -> _Future:
        self._rec("moveToZAsync", (z, velocity) + args,
                  dict(kwargs, timeout_sec=timeout_sec, vehicle_name=vehicle_name))
        v = self._v(vehicle_name)
        descending_to_land = z > GROUND_Z - 2.0
        if not (descending_to_land and vehicle_name in self.world.stuck_land):
            v.z = z
            v.landed_state = 1
        return _Future()

    def moveToPositionAsync(self, x: float, y: float, z: float, velocity: float,
                            timeout_sec: float = 3e38, *args: Any,
                            vehicle_name: str = "", **kwargs: Any) -> _Future:
        self._rec("moveToPositionAsync", (x, y, z, velocity) + args,
                  dict(kwargs, timeout_sec=timeout_sec, vehicle_name=vehicle_name))
        v = self._v(vehicle_name)
        v.x, v.y, v.z, v.landed_state = x, y, z, 1
        return _Future()

    def moveByVelocityBodyFrameAsync(self, vx: float, vy: float, vz: float, duration: float,
                                     *args: Any, vehicle_name: str = "", **kwargs: Any) -> _Future:
        self._rec("moveByVelocityBodyFrameAsync", (vx, vy, vz, duration) + args,
                  dict(kwargs, vehicle_name=vehicle_name))
        v = self._v(vehicle_name)
        v.x += vx * duration
        v.y += vy * duration
        return _Future()

    def hoverAsync(self, vehicle_name: str = "") -> _Future:
        self._rec("hoverAsync", (), {"vehicle_name": vehicle_name})
        return _Future()

    def landAsync(self, timeout_sec: float = 60, vehicle_name: str = "") -> _Future:
        self._rec("landAsync", (), {"timeout_sec": timeout_sec, "vehicle_name": vehicle_name})
        v = self._v(vehicle_name)
        if vehicle_name not in self.world.stuck_land:
            v.z, v.landed_state = GROUND_Z, 0
        return _Future()


# ----------------------------------------------------------- running a case

@contextlib.contextmanager
def patched(agent: Any, world: FakeWorld):
    """Point the agent at the fake world and the virtual clock, then restore."""
    if getattr(agent, "SPACING", SPACING) != SPACING:
        raise AssertionError("airsim_fake.SPACING no longer matches the agent")
    saved = (agent.connect, agent.time)
    main_thread = threading.main_thread()

    def connect(host: str = "127.0.0.1", port: int = 41451) -> FakeClient:
        # The separation monitor connects from the main thread; flight threads
        # connect from their own. Only the flights are recorded.
        stream = "discard" if threading.current_thread() is main_thread else "vehicle"
        return FakeClient(world, stream)

    agent.connect = connect
    agent.time = VirtualTime()
    agent.forget_ground_reference()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield FakeClient(world, "main")
    finally:
        agent.connect, agent.time = saved
        agent.forget_ground_reference()


def run_flight(agent: Any, plans: dict[str, list[dict[str, Any]]],
               declared: list[str] | None = None,
               stuck_land: set[str] | None = None) -> dict[str, Any]:
    """Fly `plans` ({drone: steps}) the way `run_missions.fly_one` does:
    reset the world, then `fly_plans`. Returns what the goldens compare."""
    world = FakeWorld(declared=declared, stuck_land=stuck_land)
    records = [agent.PlanRecord(drone=d, instruction="", raw_output="", plan=steps,
                                plan_seconds=0.0, valid=True)
               for d, steps in plans.items()]
    error = None
    outcomes: list[dict[str, Any]] = []
    with patched(agent, world) as main:
        try:
            agent.reset_world(main)
            outcomes, _separation = agent.fly_plans(main, records)
        except Exception as exc:              # e.g. ForeignVehicleError
            error = f"{type(exc).__name__}: {exc}"
    return {
        "error": error,
        "calls": world.calls,
        "outcomes": sorted((_norm(o) for o in outcomes), key=lambda o: o["drone"]),
    }


# --------------------------------------------------------- scripted planning

class ScriptedOllama:
    """A stand-in `ollama` module: records the chat request, returns a reply."""

    def __init__(self, reply: str | None = None, raise_exc: BaseException | None = None) -> None:
        self.reply, self.raise_exc = reply, raise_exc
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Client:
            def __init__(self, host: str | None = None, **kwargs: Any) -> None:
                outer.requests.append({"host": host})

            def chat(self, **kwargs: Any) -> dict[str, Any]:
                outer.requests[-1]["chat"] = kwargs
                if outer.raise_exc is not None:
                    raise outer.raise_exc
                return {"message": {"content": outer.reply}}

        self.module = types.ModuleType("ollama")
        self.module.Client = Client


def run_planning(agent: Any, instruction: str, drone: str, model: str,
                 endpoint: str, options: dict[str, Any], reply: str | None = None,
                 raise_exc: BaseException | None = None) -> dict[str, Any]:
    """Call the real `plan_for` with a scripted model. Returns the request it
    sent and the record it produced, minus timing."""
    fake = ScriptedOllama(reply, raise_exc)
    saved = sys.modules.get("ollama")
    sys.modules["ollama"] = fake.module
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            record = agent.plan_for(instruction, drone, model, endpoint, options)
    finally:
        if saved is None:
            sys.modules.pop("ollama", None)
        else:
            sys.modules["ollama"] = saved
    out = record.as_json()
    out.pop("t", None)
    out.pop("plan_seconds", None)
    return {"request": _norm(fake.requests), "record": _norm(out)}
