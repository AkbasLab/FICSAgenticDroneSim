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
import glob
import inspect
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
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
        self.yaw = 0.0             # degrees; Phase 3 reads it, the baseline never did

    def reset(self) -> None:
        self.x, self.y, self.z = self.spawn_x, 0.0, GROUND_Z
        self.landed_state = 0


class FakeWorld:
    """Shared state behind every FakeClient of one run."""

    def __init__(self, declared: list[str] | None = None,
                 stuck_land: set[str] | None = None,
                 intrude_on_reset: dict[int, str] | None = None) -> None:
        self.vehicles: dict[str, _Vehicle] = {}
        for i, name in enumerate(declared if declared is not None else ["Drone1"]):
            self.vehicles[name] = _Vehicle(i * SPACING)
        # Drones whose descent and landAsync move nothing -- the 2026-10-06 and
        # 2026-10-19 failure, where `land` returned with the aircraft still up.
        self.stuck_land = set(stuck_land or ())
        # {n: name}: on the n-th world reset a vehicle appears that nobody in
        # the run spawned -- "something else spawned a drone mid-series", the
        # case the runner's per-flight backstop exists for.
        self.intrude_on_reset = dict(intrude_on_reset or {})
        self.resets = 0
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
        # A handshake addresses no vehicle, so a per-drone stream -- the calls
        # one flight thread makes to ITS drone -- does not record it.
        if self.stream != "vehicle":
            self._rec("confirmConnection", (), {})

    def reset(self) -> None:
        self._rec("reset", (), {})
        for v in self.world.vehicles.values():
            v.reset()
        self.world.resets += 1
        intruder = self.world.intrude_on_reset.get(self.world.resets)
        if intruder:
            self.world.vehicles[intruder] = _Vehicle(0.0)

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
        half = math.radians(v.yaw) / 2.0          # a yaw-only quaternion, as AirSim builds it
        orientation = types.SimpleNamespace(w_val=math.cos(half), x_val=0.0, y_val=0.0,
                                            z_val=math.sin(half))
        return types.SimpleNamespace(
            kinematics_estimated=types.SimpleNamespace(position=position, orientation=orientation),
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

    def isApiControlEnabled(self, vehicle_name: str = "") -> bool:
        self._rec("isApiControlEnabled", (), {"vehicle_name": vehicle_name})
        return self._v(vehicle_name).api

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

    # -- Phase 3: never called by the baseline, so absent from its goldens
    def rotateToYawAsync(self, yaw: float, timeout_sec: float = 3e38, margin: float = 5,
                         vehicle_name: str = "") -> _Future:
        self._rec("rotateToYawAsync", (yaw,),
                  {"timeout_sec": timeout_sec, "margin": margin, "vehicle_name": vehicle_name})
        self._v(vehicle_name).yaw = (float(yaw) + 180.0) % 360.0 - 180.0
        return _Future()

    def cancelLastTask(self, vehicle_name: str = "") -> None:
        self._rec("cancelLastTask", (), {"vehicle_name": vehicle_name})


# ----------------------------------------------------------- running a case

def _clock_modules(agent: Any) -> list[Any]:
    """Every module of the agent that reads the clock through `time`.

    Since Phase 2 step 3 the flying code lives in `agentic_uav`, so the virtual
    clock has to replace `time` there as well as in the agent itself.
    """
    # Since step 5 the agent itself no longer reads the clock at all.
    found = [agent] if getattr(agent, "time", None) is _real_time else []
    for name, module in list(sys.modules.items()):
        if (name == "agentic_uav" or name.startswith("agentic_uav.")) \
                and getattr(module, "time", None) is _real_time:
            found.append(module)
    return found


@contextlib.contextmanager
def patched(agent: Any, world: FakeWorld):
    """Point the agent at the fake world and the virtual clock, then restore.

    Connections: every new simulator connection the agent opens is answered
    with a recording fake. Before Phase 2 step 3 those came from
    `agent.connect`; since then they come from `AirSimAdapter.connect`. Both
    are patched, so the same harness records either version of the code.
    """
    if getattr(agent, "SPACING", SPACING) != SPACING:
        raise AssertionError("airsim_fake.SPACING no longer matches the agent")
    main_thread = threading.main_thread()

    def stream_for_caller() -> str:
        # Flight threads connect from their own threads: record per drone. The
        # separation monitor connects from the main thread INSIDE fly_plans:
        # discard, since its poll count depends on the machine. Any other
        # main-thread connection is a runner's own scene connection: record as
        # "main". (Before step 5 the runner built its client directly, so only
        # the first two cases arose.)
        if threading.current_thread() is not main_thread:
            return "vehicle"
        if any(frame.function == "fly_plans" for frame in inspect.stack(0)):
            return "discard"
        return "main"

    def connect(host: str = "127.0.0.1", port: int = 41451) -> FakeClient:
        client = FakeClient(world, stream_for_caller())
        client.confirmConnection()            # as agent.connect does, via the adapter
        return client

    clock = VirtualTime()
    clocked = _clock_modules(agent)
    saved_time = [(m, m.time) for m in clocked]
    saved_connect = agent.connect
    agent.connect = connect
    for module in clocked:
        module.time = clock

    adapter_cls, saved_adapter_connect = None, None
    try:
        from agentic_uav.simulator.airsim_adapter import AirSimAdapter as adapter_cls
    except ImportError:
        pass
    def adapter_connect(cls: Any, host: str = "127.0.0.1", port: int = 41451) -> Any:
        client = FakeClient(world, stream_for_caller())
        client.confirmConnection()            # as AirSimAdapter.connect does
        return cls(client)

    if adapter_cls is not None:
        saved_adapter_connect = adapter_cls.__dict__["connect"]
        adapter_cls.connect = classmethod(adapter_connect)

    agent.forget_ground_reference()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield FakeClient(world, "main")
    finally:
        agent.connect = saved_connect
        for module, original in saved_time:
            module.time = original
        if adapter_cls is not None:
            adapter_cls.connect = saved_adapter_connect
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


# ------------------------------------------------------------ the whole runner

class RunnerOllama:
    """A stand-in `ollama` module for a whole runner invocation.

    `replies` maps an instruction to the raw reply the model gave it; an
    instruction mapped to the string "<unreachable>" raises ConnectionError
    instead. `models` is what `Client.list()` reports; `listing_fails` makes
    the endpoint check itself fail, as a dead tunnel does.
    """

    UNREACHABLE = "<unreachable>"

    def __init__(self, replies: dict[str, str], models: list[str],
                 listing_fails: bool = False) -> None:
        outer = self
        self.replies, self.models, self.listing_fails = replies, models, listing_fails
        # Asked something with no scripted reply. The planner catches every
        # exception as a failed plan, so a gap in the script would otherwise
        # pass for the model's own failure; run_runner raises on it instead.
        self.unscripted: list[str] = []
        self.requests: list[dict[str, Any]] = []     # every chat request, as sent

        class Client:
            def __init__(self, host: str | None = None, **kwargs: Any) -> None:
                self.host = host

            def list(self) -> dict[str, Any]:
                if outer.listing_fails:
                    raise ConnectionError("[WinError 10061] No connection could be made")
                return {"models": [{"model": m} for m in outer.models]}

            def chat(self, **kwargs: Any) -> dict[str, Any]:
                outer.requests.append(dict(kwargs, host=self.host))
                instruction = kwargs["messages"][-1]["content"]
                if instruction not in outer.replies:
                    outer.unscripted.append(instruction)
                    raise LookupError(f"no scripted reply for {instruction!r}")
                reply = outer.replies[instruction]
                if reply == RunnerOllama.UNREACHABLE:
                    raise ConnectionError("[WinError 10061] No connection could be made")
                return {"message": {"content": reply}}

        self.module = types.ModuleType("ollama")
        self.module.Client = Client


class _VersionResponse(io.BytesIO):
    def __enter__(self) -> "_VersionResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


_STAMP = re.compile(r"\d{8}-\d{6}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?")


def _clean_text(text: str, out_dir: str) -> str:
    """Remove what differs between two invocations of identical code."""
    text = text.replace(out_dir, "<OUT>").replace(out_dir.replace("\\", "/"), "<OUT>")
    text = _STAMP.sub("<STAMP>", text)
    lines = []
    for line in text.splitlines():
        if line.startswith("code    :"):          # commit, dirty flag, snapshot name
            line = "code    : <CODE>"
        if line.startswith("Generated "):          # summary header with the date
            line = _DATE.sub("<DATE>", line)
        line = _clean_monitor_line(line)
        lines.append(line)
    return "\n".join(lines)


_MEASURED = "<measured>"
_MONITOR_FIGURES = [
    # The runner's per-run line, and fly_plans' summary after each flight.
    (re.compile(r"min sep [\d.]+m"), "min sep <M>m"),
    (re.compile(r"closest approach: [\d.]+ m at t\+-?[\d.]+s \(\d+ samples\)"),
     "closest approach: <M> m at t+<M>s (<N> samples)"),
    (re.compile(r"monitored \d+ samples"), "monitored <N> samples"),
    # fly_chat's per-pair report.
    (re.compile(r"(Drone\d+-Drone\d+': )[\d.]+"), r"\g<1><M>"),
]


def _clean_monitor_line(line: str) -> str:
    """A console line minus the monitor's figures; see _clean_separation."""
    for pattern, replacement in _MONITOR_FIGURES:
        line = pattern.sub(replacement, line)
    return line


def _clean_separation(separation: Any) -> Any:
    """Keep the monitor's shape, drop its machine-dependent numbers.

    The monitor polls on a real 10 Hz timer while the drones move in virtual
    time, so how many samples it takes, and which positions it catches, depend
    on the machine. Which keys it reports, which pairs it watched, its errors
    and its collisions (none, in the fake) do not.
    """
    if not isinstance(separation, dict):
        return separation
    out = dict(separation)
    for key in ("samples", "min_separation_m", "min_separation_at_s"):
        if out.get(key) is not None:
            out[key] = _MEASURED
    for key in ("per_pair_min_m", "per_pair_min_at_s"):
        if isinstance(out.get(key), dict):
            out[key] = {pair: _MEASURED for pair in out[key]}
    return out


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    """A result row or agent-log record, minus what differs between runs."""
    row = json.loads(json.dumps(row))
    row.pop("t", None)
    protocol = row.get("protocol") or {}
    protocol.pop("code", None)                     # digests change with every refactor step, by design
    # Outcomes are appended as flight threads finish, so their order is the
    # scheduler's; sorted by drone, as run_flight does for the execution golden.
    if row.get("kind") == "execution":
        row.pop("code", None)                      # the same provenance, on the log record
        row["separation"] = _clean_separation(row.get("separation"))
        row["outcomes"] = sorted(row.get("outcomes") or [], key=lambda o: o["drone"])
    execution = row.get("execution")
    if isinstance(execution, dict) and "separation" in execution:
        execution["separation"] = _clean_separation(execution["separation"])
    if isinstance(execution, dict) and "outcomes" in execution:
        execution["outcomes"] = sorted(execution["outcomes"], key=lambda o: o["drone"])
    return _norm(row)


def _snapshot_shape(folder: str) -> dict[str, Any]:
    """What a code snapshot holds, minus what every code change alters.

    The digests and the commit change with every edit, by design. What must
    not change is the shape: the manifest's fields, the entry points and
    config archived by name, every file present on disk, and EVERY module of
    `agentic_uav/` archived -- the package is where the flying code lives, so
    a snapshot missing a module would not be the code that flew.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    files = sorted(manifest.get("files", {}))
    package = sorted(os.path.relpath(p, repo).replace(os.sep, "/") for p in
                     glob.glob(os.path.join(repo, "agentic_uav", "**", "*.py"), recursive=True))
    return {
        "manifest_keys": sorted(manifest),
        "entry_files": [f for f in files if not f.startswith("agentic_uav/")],
        "package_complete": [f for f in files if f.startswith("agentic_uav/")] == package,
        "all_files_present": all(os.path.isfile(os.path.join(folder, *f.split("/"))) for f in files),
    }


def _modules_with(agent: Any, attribute: str) -> list[Any]:
    """The agent and every agentic_uav module holding `attribute`.

    A name moved into the package and re-exported by the agent exists in both,
    and the code that uses it reads its OWN module's copy. Patching only the
    agent would leave the moved code reading the real one -- the real
    Documents folder, the real agent log.
    """
    found = [agent] if hasattr(agent, attribute) else []
    for name, module in list(sys.modules.items()):
        if (name == "agentic_uav" or name.startswith("agentic_uav.")) \
                and hasattr(module, attribute) and module is not agent:
            found.append(module)
    return found


def _file_state(path: str) -> tuple[int, float] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime


def _drone_blocks_sorted(lines: list[str]) -> list[str]:
    """Order each run of consecutive `[DroneN]` lines by drone, stably.

    Flight threads print concurrently, so how two drones' lines interleave is
    up to the scheduler. Each drone's own lines keep their order; only the
    interleaving -- which is not behaviour -- is removed.
    """
    out, block = [], []
    for line in lines + [None]:
        if line is not None and re.match(r"\s*\[Drone\d+\]", line):
            block.append(line)
            continue
        out += sorted(block, key=lambda l: re.match(r"\s*\[(Drone\d+)\]", l).group(1))
        block = []
        if line is not None:
            out.append(line)
    return out


def run_runner(agent: Any, runner: Any, argv: list[str], world: FakeWorld,
               ollama: RunnerOllama, server_version: str | None = "0.40.6",
               settings_vehicles: int = 1) -> dict[str, Any]:
    """Run `scripts/run_missions.py`'s main() end to end against the fakes.

    Everything the runner touches is stood in for: the Ollama client and its
    `/api/version`, AirSim (the runner's own connection, the flights, the
    monitor), the Documents folder `settings.json` is read from (declaring
    `settings_vehicles` drones), the clock, the output directory and the agent
    log. Returns what a reader of the results would see -- exit code, console,
    result rows, summary, agent-log records -- plus the simulator calls, with
    everything that legitimately differs between runs removed.

    The real `runs/agent-log.jsonl` is the record of every planning call ever
    made against a model. Scripted replies must never land in it, so the log
    is redirected, and a run that changed the real file anyway raises.
    """
    from unittest import mock
    import airsim

    out_dir = tempfile.mkdtemp(prefix="runner-golden-")
    docs = tempfile.mkdtemp(prefix="runner-docs-")
    os.makedirs(os.path.join(docs, "AirSim"))
    with open(os.path.join(docs, "AirSim", "settings.json"), "w", encoding="utf-8") as handle:
        json.dump(agent.build_settings(settings_vehicles), handle)
    log_path = os.path.join(out_dir, "agent-log.jsonl")
    log_modules = _modules_with(agent, "LOG_PATH")
    real_logs = {m.LOG_PATH: _file_state(m.LOG_PATH) for m in log_modules}

    def urlopen(url: Any, timeout: float = 0) -> _VersionResponse:
        if server_version is None:
            raise OSError("no version")
        return _VersionResponse(json.dumps({"version": server_version}).encode())

    saved_ollama = sys.modules.get("ollama")
    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = None
    calls_before = {k: len(v) for k, v in world.calls.items()}
    try:
        sys.modules["ollama"] = ollama.module
        with contextlib.ExitStack() as stack:
            stack.enter_context(patched(agent, world))
            stack.enter_context(mock.patch.object(
                airsim, "MultirotorClient",
                lambda ip="127.0.0.1", port=41451: FakeClient(world, "main")))
            stack.enter_context(mock.patch("urllib.request.urlopen", urlopen))
            for module in _modules_with(agent, "documents_dir"):
                stack.enter_context(mock.patch.object(module, "documents_dir", lambda: docs))
            for module in log_modules:
                stack.enter_context(mock.patch.object(module, "LOG_PATH", log_path))
            stack.enter_context(mock.patch.object(
                sys, "argv", ["run_missions.py"] + argv + ["--out", out_dir]))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            try:
                exit_code = runner.main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else str(exc.code)

        rows, summary, log, snapshot = [], None, [], None
        for name in sorted(os.listdir(out_dir)):
            path = os.path.join(out_dir, name)
            if name.endswith("-code") and os.path.isdir(path):
                snapshot = _snapshot_shape(path)
            elif name == "agent-log.jsonl":
                with open(path, encoding="utf-8") as handle:
                    log = [_clean_row(json.loads(l)) for l in handle if l.strip()]
            elif name.endswith(".jsonl"):
                with open(path, encoding="utf-8") as handle:
                    rows += [_clean_row(json.loads(l)) for l in handle if l.strip()]
            elif name.endswith(".md"):
                with open(path, encoding="utf-8") as handle:
                    summary = _clean_text(handle.read(), out_dir)
    finally:
        if saved_ollama is None:
            sys.modules.pop("ollama", None)
        else:
            sys.modules["ollama"] = saved_ollama
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(docs, ignore_errors=True)

    for path, before in real_logs.items():
        if _file_state(path) != before:
            raise AssertionError(f"the runner harness wrote to the real agent log {path}")
    if ollama.unscripted:
        raise AssertionError(f"no scripted reply for: {sorted(set(ollama.unscripted))}")

    new_calls = {k: v[calls_before.get(k, 0):] for k, v in world.calls.items()}
    return {
        "exit": exit_code,
        "stdout": _drone_blocks_sorted(_clean_text(stdout.getvalue(), out_dir).splitlines()),
        "stderr": _clean_text(stderr.getvalue(), out_dir).splitlines(),
        "rows": rows,
        "summary": summary.splitlines() if summary else None,
        "log": log,
        "snapshot": snapshot,
        "calls": {k: v for k, v in new_calls.items() if v},
    }


DEFAULT_MODELS = ["llama3.3:70b", "llama3.2:3b"]


def run_scenario(agent: Any, runner: Any, scenario: dict[str, Any],
                 replies: dict[str, str]) -> list[dict[str, Any]]:
    """One or more runner invocations against ONE simulator session.

    A scenario is what an operator does between two simulator restarts: the
    world persists across its invocations, so drones spawned by one are in the
    scene for the next -- which is the whole point of the protocol order. Every
    input is in the scenario itself, so a golden replays from what it stores.
    """
    spec = scenario.get("world", {})
    world = FakeWorld(
        declared=spec.get("declared"),
        stuck_land=set(spec.get("stuck_land", ())),
        intrude_on_reset={int(k): v for k, v in spec.get("intrude_on_reset", {}).items()})
    results = []
    for invocation in scenario["invocations"]:
        ollama = RunnerOllama(dict(replies, **invocation.get("reply_overrides", {})),
                              invocation.get("models", DEFAULT_MODELS),
                              invocation.get("listing_fails", False))
        results.append(run_runner(
            agent, runner, invocation["argv"], world, ollama,
            server_version=invocation.get("server_version", "0.40.6"),
            settings_vehicles=invocation.get("settings_vehicles", 1)))
    return results


# ------------------------------------------------------------- the sandbox



def run_fly_chat(agent: Any, fly_chat: Any, inputs: list[str], world: FakeWorld,
                 ollama: RunnerOllama) -> dict[str, Any]:
    """Drive `tools/fly_chat.py` through one scripted session against the fakes.

    `inputs` are the lines typed at its prompts, in order; when they run out
    the session sees end-of-input, as at Ctrl-Z. Returns the exit code, the
    console, every chat request the model received (the sandbox's prompt and
    speed live there) and the simulator calls.

    The sandbox rewrote the agent's globals before Phase 2 step 5, so they are
    restored afterwards: one session must not leak into the next test.
    """
    from unittest import mock

    typed = iter(inputs)

    def fake_input(prompt: str = "") -> str:
        print(prompt, end="")
        try:
            line = next(typed)
        except StopIteration:
            raise EOFError from None
        print(line)
        return line

    saved_globals = {name: getattr(agent, name)
                     for name in ("SYSTEM_PROMPT", "MOVE_SPEED", "DroneRunner")}
    saved_ollama = sys.modules.get("ollama")
    stdout = io.StringIO()
    exit_code = None
    calls_before = {k: len(v) for k, v in world.calls.items()}
    try:
        sys.modules["ollama"] = ollama.module
        with contextlib.ExitStack() as stack:
            stack.enter_context(patched(agent, world))
            stack.enter_context(mock.patch.object(fly_chat, "time", VirtualTime()))
            stack.enter_context(mock.patch("builtins.input", fake_input))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            try:
                exit_code = fly_chat.main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else str(exc.code)
            except Exception as exc:       # the session died: that is behaviour too
                exit_code = f"crashed: {type(exc).__name__}: {exc}"
    finally:
        for name, value in saved_globals.items():
            setattr(agent, name, value)
        if saved_ollama is None:
            sys.modules.pop("ollama", None)
        else:
            sys.modules["ollama"] = saved_ollama
    if ollama.unscripted:
        raise AssertionError(f"no scripted reply for: {sorted(set(ollama.unscripted))}")

    console = [_clean_monitor_line(line) for line in stdout.getvalue().splitlines()]
    new_calls = {k: v[calls_before.get(k, 0):] for k, v in world.calls.items()}
    return {
        "exit": exit_code,
        "stdout": _drone_blocks_sorted(console),
        "requests": _norm([{k: v for k, v in r.items() if k != "format"} for r in ollama.requests]),
        "calls": {k: v for k, v in new_calls.items() if v},
    }
