#!/usr/bin/env python3
"""Open-loop natural-language drone agent — the project baseline.

This is the system the study sets out to improve on, and it is deliberately
limited. One instruction per drone becomes one complete action list, generated
before takeoff, validated, and then executed to the end. Nothing observes.
Nothing adapts. There is no replanning after launch.

Removing that last property is the point of Phase 5 onward; until then this
agent is the constant every later architecture is measured against, so its
behaviour must stay fixed once the mission set has been run against it.

Usage
-----
    python baseline/open_loop_agent.py                      # interactive
    python baseline/open_loop_agent.py --drones 2           # skip the count prompt
    python baseline/open_loop_agent.py --plan-only \\
        --instruction "fly forward for 5 seconds then land"

    --plan-only plans and validates without connecting to the simulator, which
    is how the planner is tested without occupying a GPU.

Every planning call is written to runs/agent-log.jsonl. Logging is not optional:
planning latency and raw model output cannot be reconstructed after the fact.

Coordinate system
-----------------
AirSim is North-East-Down. **Negative Z is up.** In a plan, 15 metres above the
ground is z = -15, and a positive Z would mean down -- the most common error
against this platform -- so `set_altitude` normalises a positive value and says
so rather than obeying it.

NED fixes which direction is up; it does not say where zero is. `moveToZAsync`
takes an ABSOLUTE z in the map's frame, and Town10HD's terrain at the player
start sits at z = +29.25, so the origin is 29.25 m in the air. A plan z is
therefore translated to `ground_z + z` before it is flown, and the resulting
target is legitimately positive for anything below 29 m: M10's 12 m leg flies to
+17.25. Sending a plan z straight to `moveToZAsync` flew every altitude in this
project 29.25 m too high until 2026-10-06.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------- constants

MODEL = "llama3.2:3b"

# Where planning calls are sent. Ollama's own default is http://127.0.0.1:11434,
# and the library reads OLLAMA_HOST from the environment -- which is a trap when
# the model is meant to be running somewhere else, because a plan can come from
# a completely different machine than the data implies. So the endpoint is
# resolved once, here, and recorded with every planning call.
#
# For a remote model, point this at the local end of an SSH tunnel:
#
#     ssh -N -L 11435:gpu01:11434 user@vega.erau.edu
#     --ollama-host http://127.0.0.1:11435
#
# Deliberately NOT port 11434 for a tunnel: that is where a local Ollama
# listens, so if the tunnel dies the agent would silently fall back to whatever
# small model is installed locally and the results would be mislabelled.
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"


def is_transport_error(exc: BaseException) -> bool:
    """True if the endpoint was unreachable, rather than the model misbehaving.

    THE DISTINCTION IS NOT COSMETIC. plan_for() records any failure as an
    invalid plan, so without this a dropped network link lands in the
    `all_valid` column as the model having produced something unflyable. Over a
    VPN to a cluster that will happen, and it would quietly understate the
    model -- scoring our own connectivity as its failure.

    Classified by type rather than by message: ollama talks over httpx, so a
    dead endpoint surfaces as an httpx or httpcore exception, a socket error,
    or a plain ConnectionError depending on how it died. Matching on module and
    on the usual words in the class name covers those without importing httpx
    here, which matters because --plan-only has to work on a machine with a
    minimal install.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    module = type(exc).__module__.split(".")[0]
    if module in ("httpx", "httpcore", "socket", "ssl", "urllib3", "requests"):
        return True
    name = type(exc).__name__
    if any(word in name for word in
           ("Connect", "Timeout", "Transport", "Unreachable", "Protocol")):
        return True
    # OSError last: ConnectionError is a subclass, but so are unrelated file
    # errors, so this is a fallback rather than a first test.
    return isinstance(exc, OSError)


def normalise_endpoint(endpoint: str) -> str:
    """Accept `host:port` as well as a full URL, since both get typed."""
    endpoint = (endpoint or "").strip()
    if endpoint and "://" not in endpoint:
        endpoint = "http://" + endpoint
    return endpoint or "http://127.0.0.1:11434"

# DEFAULT inference options for running the agent directly. The authoritative
# values for a scored series live in configs/missions/*.toml under
# [protocol.options] and are passed in -- see plan_for(). These are part of the
# measurement protocol, not preferences.
#
# num_gpu is the number of layers offloaded to the GPU, and it is PER REQUEST.
# Zero is correct on this laptop, where the simulator already owns 4 GB of
# VRAM -- but sending zero to a remote GPU server makes that server reload the
# model onto CPU cores. Measured 2026-10-06: a 70B sitting entirely on an H100
# would be thrown off it by this one value.
#
# num_ctx matters more than it looks. Left unset, Ollama uses the model's own
# maximum, which for llama3.3 is 131072 -- and the KV cache for a 70B at that
# length is about 43 GB on top of 42 GB of weights, so the model does not fit
# in an 80 GB card and gets split 67%/33% CPU/GPU. Pinning it small puts the
# whole model on the GPU and makes the number comparable between machines
# instead of depending on each Ollama version's default.
OLLAMA_OPTIONS = {
    "num_gpu": 0,
    "num_ctx": 4096,
    "temperature": 0,
    "num_predict": 512,
    "num_thread": 12,
}

CRUISE_ALTITUDE = -8.0   # metres, NED: negative is up
SPACING = 4.0            # metres between drones at spawn, on X
MOVE_SPEED = 5.0         # m/s for every directional move
TAKEOFF_SETTLE = 3.0     # seconds to let takeoff stabilise before the plan runs
GROUND_SETTLE_TIMEOUT = 15.0   # seconds to wait for the drone to stop falling
GROUND_SETTLE_TOLERANCE = 0.05 # metres of movement per sample that counts as still

AIRSIM_PORT = 41451
MAX_DURATION = 60.0      # seconds; a single leg longer than this is rejected
MAX_ALTITUDE = -120.0    # metres NED; roughly the legal ceiling for small UAS
MIN_ALTITUDE = -2.0      # metres NED; below this is effectively ground level

# How far above its arming height the vehicle must be for teardown to treat it
# as airborne and land it first. Disarming while airborne cuts the motors.
AIRBORNE_MARGIN = 1.0    # metres

# How far a run's measured ground may differ from the first run's before the run
# is refused. reset_world() returns every vehicle to the same pose, so the ground
# under a given drone is a constant for the session; a disagreement means the
# measurement is wrong, not that the ground moved.
GROUND_REFERENCE_TOLERANCE = 2.0   # metres

# Per-vehicle ground height, first measured wins. Guarded because DroneRunner
# threads arm concurrently.
_GROUND_REFERENCE: dict[str, float] = {}
_GROUND_LOCK = threading.Lock()


class GroundReferenceError(RuntimeError):
    """Raised when a run's measured ground disagrees with the session's.

    This exists because the failure it catches is silent. `arm()` infers the
    ground from the aircraft standing still, and an aircraft held motionless in
    mid air stands just as still as one on the ground -- observed reporting
    "armed, ground z = -0.18" against a true 29.25, with ground_settled true.
    Every altitude in the run is then offset by the error, and nothing in the
    record contradicts it. Refusing the run is the point: the plan is already
    recorded, and a flight measured against a wrong ground is worse than no
    flight.
    """


def forget_ground_reference(name: str | None = None) -> None:
    """Drop the cached ground, for one vehicle or all. For tests and restarts."""
    with _GROUND_LOCK:
        if name is None:
            _GROUND_REFERENCE.clear()
        else:
            _GROUND_REFERENCE.pop(name, None)


def check_ground_reference(name: str, ground_z: float) -> float:
    """Record or verify the ground for `name`. Returns the session reference."""
    with _GROUND_LOCK:
        reference = _GROUND_REFERENCE.get(name)
        if reference is None:
            _GROUND_REFERENCE[name] = ground_z
            return ground_z
    if abs(ground_z - reference) > GROUND_REFERENCE_TOLERANCE:
        raise GroundReferenceError(
            f"{name}: measured ground z = {ground_z:.2f}, but this session "
            f"established {reference:.2f} ({abs(ground_z - reference):.2f} m "
            f"apart, tolerance {GROUND_REFERENCE_TOLERANCE}). The aircraft was "
            f"probably held in mid air while the ground was measured. Refusing "
            f"to fly rather than record altitudes against a wrong ground."
        )
    return reference

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(REPO_ROOT, "runs", "agent-log.jsonl")

ACTIONS = (
    "fly_to", "fly_straight", "fly_backward", "fly_left", "fly_right",
    "hover", "set_altitude", "land",
)

# The schema is the single most important part of this agent. Small local models
# collapse multi-step requests into one action when left unconstrained -- asked
# to hover then land, they return only the hover. Requiring an array, and
# restricting the action name to an enum, fixes that and also stops the model
# inventing actions that do not exist.
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "duration": {"type": "number"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["action"],
            },
        }
    },
    "required": ["plan"],
}

SYSTEM_PROMPT = f"""You convert a plain-English drone instruction into a flight plan.

Reply with JSON only: {{"plan": [ ... ]}} -- an array of steps, in execution order.

Available actions, and their parameters:
  fly_to        x, y, z    fly to an absolute coordinate
  fly_straight  duration   forward, relative to the drone's heading
  fly_backward  duration   backward
  fly_left      duration   strafe left
  fly_right     duration   strafe right
  hover         duration   hold position
  set_altitude  z          climb or descend
  land                     controlled descent and landing

Rules:
- duration is in seconds. Speed is fixed at {MOVE_SPEED} m/s and cannot be changed.
- z is altitude in NED: NEGATIVE IS UP. 20 metres above ground is z = -20.
- Emit one step per requested manoeuvre, in the order they must be executed,
  which is not always the order they are mentioned.
- "return home" is fly_to with x = 0, y = 0.
- Do not invent actions. Do not add steps that were not asked for.
"""

# Worked examples, chosen so that none of them is a mission from
# docs/BASELINE_MISSIONS.md or a close paraphrase of one. A demonstration that
# mirrors a benchmark item makes that item score correct because it is in the
# prompt, not because the model solved it.
EXAMPLES = [
    (
        "fly left for 2 seconds, then climb to 30 meters",
        {"plan": [
            {"action": "fly_left", "duration": 2},
            {"action": "set_altitude", "z": -30},
        ]},
    ),
    (
        "after hovering for 4 seconds, fly backward for 6 seconds",
        {"plan": [
            {"action": "hover", "duration": 4},
            {"action": "fly_backward", "duration": 6},
        ]},
    ),
]


# ------------------------------------------------------------------- results

class PlanError(Exception):
    """A plan that cannot be flown safely or at all."""


@dataclass
class PlanRecord:
    """One planning call, as it is logged."""

    drone: str
    instruction: str
    raw_output: str
    plan: list[dict[str, Any]] | None
    plan_seconds: float
    valid: bool
    error: str | None = None
    normalised: list[str] = field(default_factory=list)
    model: str = MODEL
    # Which endpoint answered. A model name alone does not say where it ran,
    # and "llama3.3:70b" served from a laptop and from an H100 are not the
    # same measurement.
    endpoint: str = OLLAMA_ENDPOINT
    # True when the endpoint could not be reached at all. Such a row is NOT a
    # measurement of the model and must not be scored as one.
    transport_error: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "drone": self.drone,
            "model": self.model,
            "endpoint": self.endpoint,
            "instruction": self.instruction,
            "raw_output": self.raw_output,
            "plan": self.plan,
            "plan_seconds": round(self.plan_seconds, 2),
            "valid": self.valid,
            "transport_error": self.transport_error,
            "error": self.error,
            "normalised": self.normalised,
        }


# Object names AirSim reports for ground contact. Touching these on landing is
# the mission working, not a fault, so they are classified separately.
GROUND_OBJECTS = ("terrain", "ground", "landscape", "road", "sidewalk")


def is_ground(object_name: str) -> bool:
    """True if a collision object is the ground rather than an obstacle."""
    lowered = (object_name or "").lower()
    return any(marker in lowered for marker in GROUND_OBJECTS)


class SeparationMonitor:
    """Samples inter-drone distance AND collisions while a mission flies.

    Section 1.3 asks for "collision or proximity events". NEITHER is visible from
    the start and end states: the closest approach happens in between, and
    AirSim keeps only the most recent collision, which the landing overwrites.
    Both have to be watched while the flight is happening.

    Runs in its own thread at a fixed interval and keeps only the minimum
    separation seen and when it happened -- enough to answer "did they come
    dangerously close", without writing a position trace per sample.

    There is no collision avoidance anywhere in this stack. Vertical staggering
    and spawn spacing are the only separation M09 and M10 have, so this is the
    measurement that says whether that was enough.
    """

    def __init__(self, client, names: list[str], interval: float = 0.1) -> None:
        self.client = client
        self.names = names
        self.interval = interval
        self.min_distance: float | None = None
        self.min_at: float | None = None
        # Per pair as well as overall. M10 reported a single 4.0 m minimum for a
        # flight in which two drones interpenetrated by 0.115 m, because one
        # overall figure cannot say WHICH pair was close, and the pair that
        # collided was not the pair that set the minimum. Six pairs at four
        # drones, and only one of them mattered.
        self.pair_min: dict[str, float] = {}
        self.pair_min_at: dict[str, float] = {}
        # Collisions have to be polled for the same reason proximity does: the
        # end state does not contain them. `simGetCollisionInfo` returns only the
        # MOST RECENT collision, and every flight that lands ends touching the
        # ground, so a single read after teardown can never see a mid-flight
        # collision -- it has already been overwritten. Measured 2026-10-06: a
        # 10 Hz trace caught Drone1 and Drone3 in contact in two of three M10
        # runs, penetration to 0.152 m, while all three records said
        # `collision: false`. The pre-fix M10 recorded that same contact only
        # because the flight never landed.
        self.collisions: list[dict[str, Any]] = []
        self._seen: set[tuple[str, Any]] = set()
        self.samples = 0
        self.errors = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def _positions(self) -> dict[str, tuple[float, float, float]]:
        found = {}
        for name in self.names:
            state = self.client.getMultirotorState(vehicle_name=name)
            p = state.kinematics_estimated.position
            found[name] = (p.x_val, p.y_val, p.z_val)
        return found

    def _collisions(self) -> None:
        """Record every distinct collision, once each, as it happens."""
        for name in self.names:
            info = self.client.simGetCollisionInfo(vehicle_name=name)
            if not getattr(info, "has_collided", False):
                continue
            key = (name, getattr(info, "time_stamp", None))
            if key in self._seen:
                continue
            self._seen.add(key)
            obj = getattr(info, "object_name", "") or ""
            self.collisions.append({
                "drone": name,
                "object": obj,
                "is_ground": is_ground(obj),
                "penetration_depth": round(
                    float(getattr(info, "penetration_depth", 0.0)), 3),
                "at_s": round(time.time() - self._started, 2),
            })

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._collisions()
                positions = self._positions()
                self.samples += 1
                names = list(positions)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        a, b = positions[names[i]], positions[names[j]]
                        distance = math.dist(a, b)
                        at = round(time.time() - self._started, 1)
                        pair = f"{names[i]}-{names[j]}"
                        if distance < self.pair_min.get(pair, float("inf")):
                            self.pair_min[pair] = distance
                            self.pair_min_at[pair] = at
                        if self.min_distance is None or distance < self.min_distance:
                            self.min_distance = distance
                            self.min_at = at
            except Exception:
                # A sampling failure must never disturb a flight; count it so a
                # monitor that silently failed cannot look like a clean run.
                self.errors += 1
            self._stop.wait(self.interval)

    def start(self) -> None:
        # Runs for a single drone too. Separation needs two, but collisions need
        # only one, and a single-drone mission was previously unpolled -- so the
        # 24 single-drone runs flown on 2026-10-06 cannot support a collision
        # claim either.
        if not self.names:
            return
        self._started = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        return {
            "measured": self._thread is not None,
            "samples": self.samples,
            "sample_errors": self.errors,
            "min_separation_m": None if self.min_distance is None else round(self.min_distance, 2),
            "min_separation_at_s": self.min_at,
            "interval_s": self.interval,
            "per_pair_min_m": {k: round(v, 2) for k, v in sorted(self.pair_min.items())},
            "per_pair_min_at_s": dict(sorted(self.pair_min_at.items())),
            "collisions_polled": self.collisions,
            "obstacle_collisions": [c for c in self.collisions if not c["is_ground"]],
        }


def log_execution(outcomes: list[dict[str, Any]], separation: dict[str, Any] | None = None) -> None:
    """Append one execution record for a flown mission.

    Written to the same JSONL as the planning records, tagged `"kind":
    "execution"`, so a reader can reconstruct a whole mission from one file:
    what was asked, what was planned, and what the aircraft actually did.

    These two are deliberately separate records rather than one. A plan is
    produced even when nothing flies (`--plan-only`), and a plan can be correct
    while the flight fails -- which is precisely the distinction 1.3 has to
    report.
    """
    record = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "execution",
        # Which agent flew this. Cheap to record, impossible to reconstruct.
        "code": provenance(),
        "drones": len(outcomes),
        "completed": all(o["completed"] for o in outcomes),
        "any_collision": any(
            o.get("collision", {}).get("has_collided") for o in outcomes
        ),
        "separation": separation,
        "outcomes": outcomes,
    }
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"  [log write failed: {exc}]")


def log_record(record: PlanRecord) -> None:
    """Append one planning call to the JSONL log.

    A failure to log is reported but never stops a flight; a failure to log
    silently would be worse, because the run would look measured when it is not.
    """
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_json()) + "\n")
    except OSError as exc:
        print(f"  [log write failed: {exc}]")


# ------------------------------------------------------------- AirSim settings

def documents_dir() -> str:
    """The Documents folder Windows actually uses.

    OneDrive's Known Folder Move redirects Documents out of the user profile.
    AirSim asks Windows for the real location, so assuming ~/Documents writes
    settings.json somewhere AirSim never reads, and the drone count silently
    fails to apply.
    """
    if os.name == "nt":
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        CSIDL_PERSONAL, SHGFP_TYPE_CURRENT = 5, 0
        rc = ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf
        )
        if rc == 0 and buf.value:
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


def vehicle_names(count: int) -> list[str]:
    return [f"Drone{i}" for i in range(1, count + 1)]


# Camera block copied from the package's own AirSimConfig/settings.json. The
# offsets, orientations and FOV are the shipped values; do not simplify them.
# A settings file that AirSim dislikes does not produce an error -- the
# simulator exits during startup, silently, with no log and no crash dump.
CAMERA_TEMPLATE = {
    "0": {
        "CaptureSettings": [{"ImageType": 0, "Width": 1280, "Height": 960}],
        "X": 0.5, "Y": 0.0, "Z": 0.1,
        "Pitch": 0.0, "Roll": 0.0, "Yaw": 0.0,
    },
    "front_center": {
        "CaptureSettings": [
            {"ImageType": 0, "Width": 1280, "Height": 960, "FOV_Degrees": 90}
        ],
        "X": 0.2, "Y": 0.0, "Z": -0.1,
        "Pitch": 0.0, "Roll": 0.0, "Yaw": 0.0,
    },
}


def build_settings(count: int) -> dict[str, Any]:
    """Build the settings.json contents for `count` drones.

    Mirrors the package's shipped template, because deviating from it killed
    the simulator: an earlier version wrote vehicle-level "X"/"Y"/"Z" keys, and
    with "Z": 0.0 the process exited ten seconds into startup every time. Zero
    in NED is world origin height, not ground level, so the vehicle was being
    placed into the terrain. There was no error message, no log and no crash
    dump -- it simply stopped.

    Consequences for anyone editing this:

    * NO vehicle-level Z. Let AirSim place the drone at the PlayerStart.
    * X is emitted only for the second drone onwards, purely as lateral spacing
      so that four drones do not spawn inside each other. There is no collision
      avoidance anywhere in this stack.
    * The camera block is the shipped one, verbatim.

    Pure, so it can be tested without touching the Documents folder.
    """
    vehicles = {}
    for index, name in enumerate(vehicle_names(count)):
        vehicle: dict[str, Any] = {
            "VehicleType": "SimpleFlight",
            "AutoCreate": True,
            "Cameras": CAMERA_TEMPLATE,
        }
        if index:
            vehicle["X"] = index * SPACING
        vehicles[name] = vehicle

    return {
        "SettingsVersion": 1.2,
        "SimMode": "Multirotor",   # suppresses the car-or-drone dialog at launch
        "Vehicles": vehicles,
    }


def write_settings(count: int, exact: bool = False) -> tuple[str, bool]:
    """Ensure settings.json can host `count` drones. Returns (path, changed).

    `exact=True` writes exactly `count` drones, shrinking the fleet if it is
    currently larger. The default grows but never shrinks, which is what a
    flight wants -- and which means the roster tool must ask for `exact`, or a
    four-drone fleet could never be reduced again.

    **A larger roster is left alone.** If the file already declares at least
    `count` drones in the expected shape, nothing is written and `changed` is
    False -- so a simulator booted with four drones flies one-, two- and
    four-drone missions without a restart between them.

    That matters because changing the roster is expensive: AirSim reads this
    file only at process start, so every change costs a simulator restart. With
    a fixed fleet declared once, mission scripts stop touching it at all.

    The unused drones sit on the ground where they spawned. They are extra
    actors in the world -- a real condition change, not a free lunch -- so a
    series should be flown at one fleet size throughout, and the fleet size is
    recorded per run.

    The file is only rewritten when it cannot serve the request: too few
    vehicles, or a shape that does not match what build_settings produces.
    """
    directory = os.path.join(documents_dir(), "AirSim")
    path = os.path.join(directory, "settings.json")

    existing = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as handle:
                existing = json.load(handle)
        except (OSError, ValueError):
            existing = None

    if isinstance(existing, dict):
        have = list(existing.get("Vehicles", {}))
        if exact:
            # Nothing to do only if it already matches exactly.
            if existing == build_settings(count):
                return path, False
        elif len(have) >= count and existing == build_settings(len(have)):
            # Already big enough, and written by this code rather than by hand.
            return path, False

    settings = build_settings(count)
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(settings, indent=2))
    return path, True


# ------------------------------------------------------------------ planning

def build_messages(instruction: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example_instruction, example_plan in EXAMPLES:
        messages.append({"role": "user", "content": example_instruction})
        messages.append({"role": "assistant", "content": json.dumps(example_plan)})
    messages.append({"role": "user", "content": instruction})
    return messages


def validate(plan: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Check a plan is flyable. Returns (steps, notes) or raises PlanError.

    The schema already guarantees shape and action names. This checks the things
    a schema cannot: that parameters are present for the action that needs them,
    that durations are sane, and that altitudes are the right sign.
    """
    if not isinstance(plan, dict) or "plan" not in plan:
        raise PlanError("no 'plan' key in model output")
    steps = plan["plan"]
    if not isinstance(steps, list) or not steps:
        raise PlanError("'plan' is not a non-empty array")

    notes: list[str] = []
    checked: list[dict[str, Any]] = []

    for position, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise PlanError(f"step {position} is not an object")
        action = step.get("action")
        if action not in ACTIONS:
            raise PlanError(f"step {position}: unknown action {action!r}")

        if action in ("fly_straight", "fly_backward", "fly_left", "fly_right", "hover"):
            duration = step.get("duration")
            if not isinstance(duration, (int, float)):
                raise PlanError(f"step {position}: {action} needs a duration")
            if duration <= 0:
                raise PlanError(f"step {position}: duration must be positive")
            if duration > MAX_DURATION:
                raise PlanError(
                    f"step {position}: duration {duration}s exceeds the {MAX_DURATION}s limit"
                )

        if action == "set_altitude":
            z = step.get("z")
            if not isinstance(z, (int, float)):
                raise PlanError(f"step {position}: set_altitude needs z")
            if z > 0:
                # The model meant "up". Obeying the sign would fly into the
                # ground, so normalise and record that it happened -- silently
                # correcting a model error would hide a real failure mode.
                notes.append(f"step {position}: z={z} treated as {-z} (NED, negative is up)")
                z = -float(z)
            if z > MIN_ALTITUDE:
                raise PlanError(f"step {position}: z={z} is at or below ground level")
            if z < MAX_ALTITUDE:
                raise PlanError(f"step {position}: z={z} exceeds the {MAX_ALTITUDE}m ceiling")
            step = dict(step, z=float(z))

        if action == "fly_to":
            for axis in ("x", "y"):
                if not isinstance(step.get(axis), (int, float)):
                    raise PlanError(f"step {position}: fly_to needs {axis}")
            z = step.get("z", CRUISE_ALTITUDE)
            if not isinstance(z, (int, float)):
                raise PlanError(f"step {position}: fly_to z must be a number")
            if z > 0:
                notes.append(f"step {position}: z={z} treated as {-z} (NED, negative is up)")
                z = -float(z)
            step = dict(step, z=float(z))

        checked.append(step)

    return checked, notes


class EndpointError(Exception):
    """The model endpoint is not usable. Raised before anything flies."""


def check_endpoint(model: str = MODEL,
                   endpoint: str = OLLAMA_ENDPOINT) -> dict[str, Any]:
    """Confirm the endpoint answers AND is serving the model we asked for.

    WHY THIS RUNS BEFORE EVERY SERIES
    ---------------------------------
    The failure it prevents is specific and silent. This laptop runs Ollama on
    port 11434 with a 3B model. A remote model is reached through an SSH tunnel
    on a different port. If that tunnel is not up -- or quietly died -- and the
    endpoint falls back to the default, planning calls are answered by the
    LOCAL 3B while every record still carries the model name that was
    requested. The plans would look plausible, the scores would compute, and
    the results would be wrong in a way nothing in the data could reveal.

    Checking that the model is PRESENT at the endpoint, rather than merely that
    something answered, is the whole point. "Something answered on 11434" is
    exactly what a dead tunnel looks like.

    Returns what it found, so the series can record it. Raises EndpointError
    rather than returning a flag, because flying a scored series against the
    wrong model is not a degraded run -- it is a worthless one, and it should
    stop before the first takeoff rather than after twenty-four of them.
    """
    import ollama

    endpoint = normalise_endpoint(endpoint)
    try:
        listing = ollama.Client(host=endpoint).list()
    except Exception as exc:
        raise EndpointError(
            "no model endpoint at {}: {}: {}".format(
                endpoint, type(exc).__name__, exc)
            + "\n  If this should be a remote model, is the SSH tunnel up?"
            + "\n    ssh -N -L 11435:<gpu-node>:11434 <user>@<cluster>"
        ) from exc

    # The ollama client returns objects in newer versions and plain dicts in
    # older ones, and this has to work on whatever is installed on the machine
    # flying the missions. So read both shapes rather than pinning a version.
    available = []
    entries = (listing.get("models", []) if isinstance(listing, dict)
               else getattr(listing, "models", []))
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("model") or entry.get("name")
        else:
            name = getattr(entry, "model", None) or getattr(entry, "name", None)
        if name:
            available.append(name)

    # Ollama reports a fully qualified tag such as "llama3.3:70b", while a
    # config may name the family only. A bare family name is accepted as a
    # prefix, but NEVER the reverse: asking for llama3.3:70b must not be
    # satisfied by llama3.2:3b happening to be installed.
    if not any(name == model or name.startswith(model + ":") for name in available):
        raise EndpointError(
            "endpoint {} is answering, but does NOT serve {!r}.".format(endpoint, model)
            + "\n  available there: " + (", ".join(sorted(available)) or "(none)")
            + "\n  Refusing to fly: a different model would be recorded under"
            + "\n  the requested name. If this is a tunnel it may point at the"
            + "\n  wrong host, or have died leaving a local Ollama answering."
        )

    found = {"endpoint": endpoint, "model": model,
             "models_available": sorted(available)}
    print("endpoint: {} serving {}  ({} model(s) available)".format(
        endpoint, model, len(available)))
    return found


def plan_for(instruction: str, drone: str, model: str = MODEL,
             endpoint: str = OLLAMA_ENDPOINT,
             options: dict[str, Any] | None = None) -> PlanRecord:
    """Ask the model for a plan and validate it. Never raises; records instead.

    An explicit `ollama.Client(host=...)` rather than the module-level
    `ollama.chat`, because the module-level call silently honours OLLAMA_HOST
    from the environment. That is convenient and dangerous in equal measure: a
    stale environment variable would send planning calls somewhere other than
    where the record claims, and nothing would look wrong.
    """
    import ollama  # imported here so --plan-only works without AirSim installed

    endpoint = normalise_endpoint(endpoint)
    # The options that actually ran, not the ones a config happens to declare.
    options = dict(OLLAMA_OPTIONS if options is None else options)
    client = ollama.Client(host=endpoint)
    started = time.time()
    raw = ""
    try:
        response = client.chat(
            model=model,
            messages=build_messages(instruction),
            format=PLAN_SCHEMA,
            options=options,
        )
        raw = response["message"]["content"]
        elapsed = time.time() - started
        steps, notes = validate(json.loads(raw))
        return PlanRecord(drone, instruction, raw, steps, elapsed, True, None,
                          notes, model, endpoint)
    except (PlanError, json.JSONDecodeError) as exc:
        return PlanRecord(drone, instruction, raw, None, time.time() - started,
                          False, str(exc), [], model, endpoint)
    except Exception as exc:
        # Separated deliberately: "the endpoint was unreachable" and "the model
        # produced nonsense" are different findings, and only the second is
        # about the model. See is_transport_error().
        transport = is_transport_error(exc)
        if transport:
            print(f"[{drone}] ENDPOINT UNREACHABLE at {endpoint}: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        return PlanRecord(
            drone, instruction, raw, None, time.time() - started, False,
            f"{type(exc).__name__}: {exc}", [], model, endpoint, transport,
        )


# ----------------------------------------------------------------- execution

class DroneRunner:
    """Flies one validated plan to completion. No decisions are taken here.

    THIS CLASS IS THE OPEN LOOP. It receives a finished plan and executes it
    step by step, never consulting the model, never re-examining the world, and
    never abandoning a step because circumstances changed. Adding any of that
    would make it a different architecture -- which is what Phase 5 onward is
    for, in a different directory.

    One instance per drone, one thread per instance. The AirSim client is
    SHARED across instances, which is the open question recorded in
    phases/phase-01-baseline-freeze/: msgpack-rpc multiplexes one socket and is
    not documented as thread-safe. If multi-drone runs misbehave, give each
    runner its own client before suspecting anything else.
    """

    def __init__(self, client, name: str) -> None:
        self.client = client
        self.name = name          # must match a vehicle in settings.json
        self.ground_z = 0.0       # filled in by arm(), used by land()
        self.ground_settled = False   # did the drone stop falling before
                                      # arm() read the ground? see arm()
        # AirSim keeps the last collision across flights, so the timestamp seen
        # at arm time is the baseline for "did anything hit during THIS run".
        self._collision_at_arm: Any = None

    def _say(self, message: str) -> None:
        # flush=True because several threads print concurrently; without it the
        # interleaving is buffered into nonsense.
        print(f"[{self.name}] {message}", flush=True)

    def collisions(self) -> dict[str, Any]:
        """Collision state for this vehicle, as AirSim reports it.

        Required by the plan: section 1.3 asks for "collision or proximity
        events" per run, and nothing recorded them until now.

        AirSim keeps only the MOST RECENT collision, not a tally, and it
        persists across flights -- so the raw flag alone says nothing about
        *this* run. `time_stamp` is compared against the value read at arm time
        to decide whether the collision is new.

        Ground contact is separated from obstacle contact, because **every
        landing registers a terrain collision**: the first live capture returned
        `Town10HD_Terrain_Ground_64` with zero penetration depth, which is a
        drone sitting on the ground having landed correctly. Counting that as a
        collision would make the metric meaningless.
        """
        try:
            info = self.client.simGetCollisionInfo(vehicle_name=self.name)
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

        collided = bool(getattr(info, "has_collided", False))
        stamp = getattr(info, "time_stamp", None)
        name = getattr(info, "object_name", "") if collided else ""

        record: dict[str, Any] = {
            "available": True,
            "has_collided": collided,
            # Did this happen during this flight, or is it left over from the
            # previous one? AirSim does not clear it between runs.
            "new_this_flight": bool(collided and stamp != self._collision_at_arm),
            "object": name,
            "is_ground": is_ground(name),
        }
        if collided:
            position = getattr(info, "impact_point", None)
            record.update({
                "penetration_depth": round(float(getattr(info, "penetration_depth", 0.0)), 3),
                "time_stamp": stamp,
                "impact_point": None if position is None else {
                    "x": round(position.x_val, 2),
                    "y": round(position.y_val, 2),
                    "z": round(position.z_val, 2),
                },
            })
        return record

    def arm(self) -> None:
        """Take control of the vehicle and record where the ground is."""
        import airsim  # noqa: F401  (kept local so --plan-only needs no install)

        # WAIT FOR THE DRONE TO STOP FALLING BEFORE BELIEVING THE GROUND.
        #
        # THIS MUST HAPPEN BEFORE enableApiControl. An unpowered drone falls to
        # the ground and stops there, which is the number we want. An ARMED one
        # does not: SimpleFlight catches it and holds it wherever it was. So
        # waiting after arming measures a hover, not the ground -- it reports
        # "settled" with complete confidence and is 17 m wrong. Measured
        # 2026-09-29: armed mid-fall at z=12.17, the controller arrested the
        # fall and held 12.20 indefinitely, 17.0 m above a ground at 29.25.
        #
        # Recorded before takeoff because this build has NO TERRAIN COLLISION:
        # the drone passes through the ground, so landing cannot wait for a
        # physical touchdown and must descend to a remembered height instead.
        # That makes this one number decide where every landing ends, and for
        # most of this project it has been wrong.
        #
        # client.reset() drops the drone at the player start, which sits about
        # 25 m above the terrain, and it falls. reset_world() waited a fixed
        # 2.0 s, which is not enough, so this line read a position taken in mid
        # air. Measured 2026-09-29 over three M01 runs: ground_z of 12.07,
        # 12.17 and 12.12 against a true ground of 29.25 -- an 18 m error,
        # consistent every run because the fall is deterministic. Landing then
        # descended to ground_z - 1.0 and stopped 18 m above the ground, which
        # is the drone "hovering in the air" seen throughout this project.
        # Block A recorded 10.87-11.02, the same error, so its 24 flights
        # ended in mid air too.
        #
        # So sample until the drone stops moving rather than trusting a delay.
        # The timeout means this can never hang; if it expires the value is
        # used anyway but flagged, because a silently wrong number is what
        # caused the problem in the first place.
        #
        # This is also the only simulator state the agent reads, and it never
        # reaches the model. The agent is blind by design.
        self.ground_settled = False
        previous = self.client.getMultirotorState(
            vehicle_name=self.name).kinematics_estimated.position.z_val
        deadline = time.time() + GROUND_SETTLE_TIMEOUT
        while time.time() < deadline:
            time.sleep(0.3)
            current = self.client.getMultirotorState(
                vehicle_name=self.name).kinematics_estimated.position.z_val
            if abs(current - previous) < GROUND_SETTLE_TOLERANCE:
                previous = current
                self.ground_settled = True
                break
            previous = current
        self.ground_z = previous

        # Cross-check against the session. The settle loop cannot tell an
        # aircraft resting on the ground from one held motionless above it, so
        # this is the only thing standing between a bad reading and a whole run
        # of altitudes measured against it.
        check_ground_reference(self.name, self.ground_z)

        # Only now take control, with the drone at rest on the ground.
        self.client.enableApiControl(True, vehicle_name=self.name)
        self.client.armDisarm(True, vehicle_name=self.name)
        try:
            self._collision_at_arm = self.client.simGetCollisionInfo(
                vehicle_name=self.name
            ).time_stamp
        except Exception:
            self._collision_at_arm = None
        self._say(f"armed, ground z = {self.ground_z:.2f}"
                  + ("" if self.ground_settled else "  [DID NOT SETTLE]"))

    def take_off(self) -> None:
        """Lift off and settle at cruise height before the plan begins."""
        self.client.takeoffAsync(vehicle_name=self.name).join()
        # Every altitude is relative to the GROUND, not to z=0. Town10HD's
        # ground sits at NED z = +29.25, so a bare moveToZAsync(-8) climbs to
        # 37.5 m rather than 8 m. Measured 2026-10-06; see the phase log.
        self.client.moveToZAsync(
            self.ground_z + CRUISE_ALTITUDE, MOVE_SPEED, vehicle_name=self.name).join()
        # Settle before executing: a velocity command issued mid-climb produces
        # a curve rather than the straight leg the plan describes.
        time.sleep(TAKEOFF_SETTLE)

    def _velocity(self, vx: float, vy: float, duration: float) -> None:
        """Fly a body-frame velocity leg, then stop.

        Body frame means vx is forward RELATIVE TO THE DRONE'S HEADING, not
        north. Since nothing in this agent ever yaws, the two coincide here --
        but a future change that adds turning will make them diverge.
        """
        self.client.moveByVelocityBodyFrameAsync(
            vx, vy, 0.0, duration, vehicle_name=self.name
        ).join()
        # Velocity commands do not brake -- they expire and the aircraft coasts.
        # Without this hover, every leg overshoots by however far momentum
        # carries it, and the overshoot compounds across a multi-step plan.
        self.client.hoverAsync(vehicle_name=self.name).join()

    def step(self, step: dict[str, Any]) -> None:
        """Execute one validated plan step.

        One branch per action. Adding an action means adding a branch HERE as
        well as to ACTIONS, PLAN_SCHEMA, SYSTEM_PROMPT and validate() -- five
        places, or the model will emit something this method cannot fly.

        Every call is synchronous (`.join()`): within one drone the plan is a
        sequence, and concurrency happens between drones, not inside one.
        """
        action = step["action"]
        if action == "fly_straight":
            self._velocity(MOVE_SPEED, 0.0, step["duration"])
        elif action == "fly_backward":
            self._velocity(-MOVE_SPEED, 0.0, step["duration"])
        elif action == "fly_right":
            self._velocity(0.0, MOVE_SPEED, step["duration"])
        elif action == "fly_left":
            self._velocity(0.0, -MOVE_SPEED, step["duration"])
        elif action == "hover":
            self.client.hoverAsync(vehicle_name=self.name).join()
            time.sleep(step["duration"])
        elif action == "set_altitude":
            # ground_z-relative: the plan says "30 m up", which means 30 m above
            # the ground the drone armed on, not 30 m above the map origin.
            self.client.moveToZAsync(
                self.ground_z + step["z"], MOVE_SPEED, vehicle_name=self.name).join()
        elif action == "fly_to":
            self.client.moveToPositionAsync(
                float(step["x"]), float(step["y"]),
                self.ground_z + float(step.get("z", CRUISE_ALTITUDE)),
                MOVE_SPEED, vehicle_name=self.name,
            ).join()
        elif action == "land":
            # Descend to just above the remembered ground height first, slowly
            # (2 m/s rather than MOVE_SPEED), then hand over to landAsync. Going
            # straight to landAsync from cruise means a fast descent onto a
            # surface the physics does not model.
            self.client.moveToZAsync(
                self.ground_z - 1.0, 2.0, vehicle_name=self.name
            ).join()
            self.client.landAsync(vehicle_name=self.name).join()
        else:  # unreachable: validate() rejects unknown actions
            raise PlanError(f"unhandled action {action!r}")

    def fly(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Arm, take off, execute the whole plan, then land and release control.

        Returns an execution record: which steps ran, which failed, and how long
        it took. The plan record says what the model produced; this says what the
        aircraft did, and 1.3 needs both -- a correct plan that fails in flight
        is not a successful mission.

        This is the thread body. It never raises: an exception here would die
        inside a worker thread where nobody sees it, leaving the vehicle armed
        and under API control with no way to fly it manually. So failures are
        caught, reported, and teardown runs in `finally` regardless.

        Teardown lands the aircraft if it is still airborne -- see
        `_land_and_release`. That landing is NOT a plan step and is not scored.

        The plan is executed to the end. A step that fails does NOT cancel the
        rest -- open loop means exactly that, and pretending otherwise would
        quietly make this a different architecture.
        """
        started = time.time()
        executed: list[str] = []
        altitudes: list[dict[str, Any]] = []
        failure: str | None = None
        try:
            self.arm()
            self.take_off()
            altitudes.append({"after": "take_off", "agl": self._agl()})
            for position, step in enumerate(steps, start=1):
                self._say(f"{position}/{len(steps)} {step['action']}")
                self.step(step)
                executed.append(step["action"])
                # Read immediately: moveToZAsync has joined, so this is the
                # height the step actually achieved, against the height asked
                # for. A set_altitude step records both and they must agree.
                altitudes.append({
                    "after": step["action"],
                    "agl": self._agl(),
                    "asked_agl": (round(-float(step["z"]), 2)
                                  if step["action"] == "set_altitude" else None),
                })
            # A plan without a final land leaves the drone airborne. Hover to
            # stop it drifting on whatever velocity the last step left behind;
            # teardown then brings it down.
            if steps[-1]["action"] != "land":
                self._say("plan ended without land; holding")
                self.client.hoverAsync(vehicle_name=self.name).join()
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            self._say(f"FAILED: {failure}")
        finally:
            # If the plan's last step was a successful `land`, the aircraft is
            # already coming down and teardown must not land it again. Trusting
            # the plan beats polling the vehicle: `landAsync` returns before
            # AirSim updates `landed_state`, so a state check right here reports
            # "flying" for an aircraft that is metres off the ground and
            # descending.
            ended_landed = bool(executed) and executed[-1] == "land" and failure is None
            self._land_and_release(skip_landing=ended_landed)

        # Read once, after teardown, and used twice: to decide whether the
        # aircraft is on the ground, and in the record. Calling it twice would
        # risk the two disagreeing.
        collision = self.collisions()

        # Where the aircraft actually finished. Recorded because for most of
        # this project every flight ended roughly 17 m above the ground and
        # nothing in the data showed it -- the run said "completed", the plan
        # was correct, and the only witness was somebody watching the screen.
        # A record that cannot show a drone hovering in mid air is not evidence.
        try:
            final = self.client.simGetVehiclePose(self.name).position
            final_position = {"x": round(final.x_val, 2),
                              "y": round(final.y_val, 2),
                              "z": round(final.z_val, 2)}
            # TWO WAYS TO BE ON THE GROUND, because one of them is not enough.
            #
            # The height test compares against ground_z, which was read where
            # the drone ARMED. That is only the right reference if the terrain
            # is flat between there and wherever it came down, and Town10HD is
            # not. Measured 2026-10-06: a landed drone rests about 1.2 m above
            # its arming ground_z, so a 1.5 m window leaves only 0.3 m of
            # margin -- and M05, which flies 25 m out, landed on terrain 0.8 m
            # higher and read 1.99 m. Three perfectly good flights were flagged
            # as not having landed.
            #
            # So the simulator's own terrain contact is accepted as proof. If
            # the physics engine says the aircraft is touching ground, it has
            # landed, whatever a height taken 25 m away suggests. is_ground()
            # already separates terrain from obstacles, which is what makes
            # this safe: hitting a building would not satisfy it.
            touching_ground = bool(collision.get("has_collided")
                                   and collision.get("is_ground"))
            landed_on_ground = abs(final.z_val - self.ground_z) < 1.5 or touching_ground
        except Exception:
            final_position, landed_on_ground = None, None

        return {
            "drone": self.name,
            "planned": [s["action"] for s in steps],
            "executed": executed,
            # Completed means every step ran, not that the outcome was correct.
            "completed": len(executed) == len(steps) and failure is None,
            "failure": failure,
            "flight_seconds": round(time.time() - started, 1),
            "ground_z": round(self.ground_z, 2),
            "step_altitudes_agl": altitudes,
            "final_position": final_position,
            # True if the aircraft ended near its own ground height OR the
            # simulator reports it touching terrain. See the note above.
            "landed_on_ground": landed_on_ground,
            # False means the drone was still moving when the ground was
            # read, so every altitude in this run is suspect.
            "ground_settled": self.ground_settled,
            # Read after teardown so a collision during the landing is caught.
            "collision": collision,
        }

    def _agl(self) -> float | None:
        """Height above the arming ground, in metres. None if unreadable.

        Recorded after every step because the record could previously show where
        a flight ENDED but never how high it went, which is exactly how an
        altitude error of 29.25 m survived 30 runs and four sessions: every plan
        was correct, every flight completed, and no field disagreed.
        """
        try:
            z = self.client.getMultirotorState(
                vehicle_name=self.name).kinematics_estimated.position.z_val
            return round(self.ground_z - z, 2)
        except Exception:
            return None

    def _is_airborne(self) -> bool:
        """True if the vehicle still needs landing before control is released.

        Asks AirSim for its landed state first. A height comparison alone is
        unreliable here: `landAsync` returns before the aircraft has fully
        settled, so a plan ending in `land` looked airborne to a z-check and got
        landed a second time -- harmless, but it added a redundant descent to
        every mission that lands, and would have appeared in every 1.3 run and
        every recording.
        """
        try:
            state = self.client.getMultirotorState(vehicle_name=self.name)
        except Exception:
            # If the state cannot be read, assume airborne: attempting a landing
            # that was not needed is harmless, skipping one that was is not.
            return True

        # HEIGHT IS AUTHORITATIVE, not LandedState. AirSim reports
        # LandedState = Landed for a motionless vehicle regardless of height:
        # measured 2026-10-06 with the aircraft hovering at 29.43 m above the
        # terrain and reporting Landed, and again on an M01 run that released
        # control at 9.32 m and dropped the aircraft. That is the same failure
        # `_land_and_release` was written to prevent, reintroduced by trusting
        # the field.
        #
        # The redundant-descent problem that motivated LandedState is already
        # handled by `skip_landing`, which the caller passes when the plan's own
        # last step was a successful `land` -- so height can be trusted here
        # without bringing it back. NED: more negative is higher.
        if state.kinematics_estimated.position.z_val < self.ground_z - AIRBORNE_MARGIN:
            return True

        # Low enough to be down. Defer to LandedState if it disagrees, since a
        # needless landing is harmless and a skipped one is not.
        landed_state = getattr(state, "landed_state", None)
        return landed_state is not None and landed_state != 0

    def _land_and_release(self, skip_landing: bool = False) -> None:
        """Bring the aircraft down, then hand control back.

        `skip_landing` is passed when the plan itself ended with a successful
        `land`, so the descent is already under way.

        THIS IS TEARDOWN, NOT PART OF THE PLAN. It runs after the plan has
        finished, or after it failed, and it is not scored: the plan is what the
        model produced, and landing safely afterwards is the harness's job.

        It exists because disarming cuts the motors. Doing that while the
        aircraft is hovering -- which is exactly how a plan without a final
        `land` ends -- drops it out of the sky. Found on the first real flight:
        M01 took off, flew its leg, held position, and then fell when control
        was released.
        """
        try:
            if not skip_landing and self._is_airborne():
                self._say("teardown: landing before releasing control")
                self.step({"action": "land"})
        except Exception as exc:
            # Report and continue to the release: leaving the vehicle armed and
            # under API control is worse than an ungraceful landing.
            self._say(f"teardown landing failed: {type(exc).__name__}: {exc}")

        # Best effort, and silent if it fails: if the connection is already gone
        # there is nothing useful to do, and raising here would mask whatever
        # failure was reported above.
        try:
            self.client.armDisarm(False, vehicle_name=self.name)
            self.client.enableApiControl(False, vehicle_name=self.name)
            self._say("control released")
        except Exception:
            pass


# ---------------------------------------------------------------- flying them

def reset_world(client, settle: float = 2.0) -> None:
    """Return every vehicle to its start pose.

    Without this, each run begins wherever the previous one ended -- M01 flies
    25 m forward and lands there, so the next mission arms from a different
    place, at a different ground height, over different terrain. Observed in
    practice: `ground z` moved from 29.25 to 27.27 between runs.

    For a one-off flight that hardly matters. For 1.3, where three repeats of a
    mission are meant to be the same mission, it is the difference between
    repeats and a drift.
    """
    client.reset()
    time.sleep(settle)                 # physics needs a moment to settle
    client.confirmConnection()


def file_digest(path: str) -> str | None:
    """SHA-256 of a file, short form. None if it cannot be read."""
    import hashlib

    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16]
    except OSError:
        return None


def provenance() -> dict[str, Any]:
    """Which code produced this run.

    Required by the plan (`AUV-14` §14.2: git SHA, versions, config) and by
    anyone reading a result months later who needs the exact agent that flew it.

    A commit SHA alone is not enough. Development happens with a dirty working
    tree, and most runs in this project were flown from uncommitted code -- so
    the digest of the agent file is recorded too, and `dirty` says whether the
    tree had uncommitted changes at the time. A run whose digest matches no
    commit can still be identified by the snapshot the runner archives beside
    the data.
    """
    import subprocess

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    commit, dirty = None, None
    try:
        commit = subprocess.run(
            ["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
        status = subprocess.run(
            ["git", "-c", "safe.directory=*", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        ).stdout
        dirty = bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "commit": commit,
        "dirty": dirty,
        "agent": os.path.basename(__file__),
        "agent_sha256": file_digest(os.path.abspath(__file__)),
        "python": sys.version.split()[0],
        "ollama_endpoint": OLLAMA_ENDPOINT,
    }


def connect(host: str = "127.0.0.1", port: int = AIRSIM_PORT):
    """Open a NEW AirSim connection.

    One per thread, always. `msgpack-rpc` multiplexes a single socket over a
    tornado IOLoop that is not thread-safe, and sharing a client across threads
    does not fail cleanly -- the first two-drone flight produced
    `RuntimeError: IOLoop is already running` on one drone and
    `BufferError: Existing exports of data: object cannot be re-sized` on the
    other, and neither flew.

    Connections are cheap. Threads are not worth sharing them for.
    """
    import airsim

    client = airsim.MultirotorClient(ip=host, port=port)
    client.confirmConnection()
    return client


def ensure_vehicles(client, names: list[str]) -> dict[str, Any]:
    """Make sure every named drone exists in the RUNNING simulator.

    Drones declared in settings.json are created at process start, so changing
    that file means restarting. `simAddVehicle` adds one to a simulator that is
    already running, which removes the restart entirely: ask for four drones
    against a one-drone simulator and the other three appear.

    Two consequences of spawning this way, both acceptable here:

    * **No cameras.** A runtime drone gets no camera configuration. This agent
      never reads an image -- it is blind by design -- so it costs nothing. A
      later phase that wants vision must declare those vehicles in
      settings.json instead.
    * **Not persistent.** They vanish when the simulator restarts, and are
      simply re-added on the next run.

    Spawned along X at SPACING metres, matching the layout settings.json uses,
    because nothing in this stack avoids collisions.
    """
    import airsim

    existing = list(client.listVehicles())
    added: list[str] = []

    for index, name in enumerate(names):
        if name in existing:
            continue
        pose = airsim.Pose(
            airsim.Vector3r(index * SPACING, 0.0, 0.0),
            airsim.to_quaternion(0.0, 0.0, 0.0),
        )
        if not client.simAddVehicle(name, "SimpleFlight", pose):
            raise RuntimeError(f"simulator refused to add {name}")
        added.append(name)

    if added:
        time.sleep(1.5)                      # let them register and settle
        now = list(client.listVehicles())
        missing = [n for n in names if n not in now]
        if missing:
            raise RuntimeError(f"added {added} but {missing} are still absent")
        print(f"spawned at runtime: {', '.join(added)}")

    # simAddVehicle IGNORES the pose it is given: every runtime drone appears at
    # the player start, stacked on top of whatever is already there. Measured
    # directly -- asked for x=12, got x=0. Two drones spawned this way came
    # within 0.08 m of each other in flight, and nothing in this stack avoids
    # collisions.
    #
    # So place them explicitly afterwards. Every drone is positioned, not only
    # the new ones, because a drone that exists may have been left wherever a
    # previous flight ended.
    placed = []
    for index, name in enumerate(names):
        want = airsim.Pose(
            airsim.Vector3r(index * SPACING, 0.0, 0.0),
            airsim.to_quaternion(0.0, 0.0, 0.0),
        )
        client.simSetVehiclePose(want, ignore_collision=True, vehicle_name=name)
        placed.append(name)
    time.sleep(1.5)                          # let them fall to the ground

    # Verify, because a silent failure here puts drones on top of each other.
    layout = {}
    for index, name in enumerate(names):
        position = client.getMultirotorState(vehicle_name=name).kinematics_estimated.position
        layout[name] = (round(position.x_val, 2), round(position.y_val, 2))
        if abs(position.x_val - index * SPACING) > 1.0:
            raise RuntimeError(
                f"{name} should be at x={index * SPACING} but is at "
                f"x={position.x_val:.2f}; refusing to fly drones that may be stacked"
            )

    if len(names) > 1:
        print("spawn layout: " + "  ".join(f"{n}{xy}" for n, xy in layout.items()))

    return {"present": existing, "added": added, "layout": layout}


def fly_plans(client, records: list[PlanRecord], host: str = "127.0.0.1",
              port: int = AIRSIM_PORT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fly one validated plan per drone, concurrently. Returns (outcomes, separation).

    Shared by the interactive agent and the mission runner ON PURPOSE. If the
    two flew missions differently -- a different thread model, a different
    monitor, a different teardown -- then scored runs and hand-flown runs would
    not be the same experiment, and nobody would notice until the numbers
    disagreed.
    """
    # Create any drone this mission needs that the simulator does not have.
    # Runs here, after any reset, because a reset can drop runtime vehicles.
    ensure_vehicles(client, [r.drone for r in records])

    outcomes: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run(record: PlanRecord) -> None:
        # ITS OWN CONNECTION. See connect(): a shared client fails with
        # IOLoop and BufferError exceptions under concurrent use, and both
        # drones stay on the ground.
        own = connect(host, port)
        outcome = DroneRunner(own, record.drone).fly(record.plan)
        with lock:                     # list.append is atomic, but be explicit
            outcomes.append(outcome)

    # Runs for every mission, not just multi-drone ones: proximity needs two
    # drones but collisions need one, and collisions are only visible while they
    # are happening. Started before the threads so the climb is covered.
    #
    # ALWAYS its own connection, even for a single drone. It polls at 10 Hz while
    # the flight threads issue commands, and sharing one msgpack-rpc socket
    # across threads is the open question this file has carried since 2026-09-24.
    # Not something to find out about through a rare, unreproducible failure.
    monitor = SeparationMonitor(connect(host, port), [r.drone for r in records])
    monitor.start()

    threads = [threading.Thread(target=run, args=(r,)) for r in records]
    for thread in threads:
        thread.start()
    # Join every thread before returning: exiting with drones still flying
    # leaves them armed and under API control.
    for thread in threads:
        thread.join()

    separation = monitor.stop()
    if separation["measured"]:
        print(f"\nclosest approach: {separation['min_separation_m']} m "
              f"at t+{separation['min_separation_at_s']}s "
              f"({separation['samples']} samples)")
    return outcomes, separation


# ---------------------------------------------------------------------- main

def collect_instructions(args, drones: list[str]) -> list[str]:
    """Get one instruction per drone, from flags or by prompting.

    `--instruction` may be given once for several drones, which repeats it --
    convenient for "all four do the same thing" without typing it four times.
    Any other count mismatch is an error rather than a guess: silently flying
    three of four drones is worse than refusing.
    """
    if args.instruction:
        if len(args.instruction) == 1 and len(drones) > 1:
            return args.instruction * len(drones)
        if len(args.instruction) != len(drones):
            sys.exit(
                f"got {len(args.instruction)} instructions for {len(drones)} drones"
            )
        return list(args.instruction)
    return [input(f"What should {name} do?  ").strip() for name in drones]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--drones", type=int, help="number of drones (skips the prompt)")
    parser.add_argument("--instruction", action="append",
                        help="instruction for one drone; repeat per drone")
    parser.add_argument("--plan-only", action="store_true",
                        help="plan and validate without flying")
    parser.add_argument("--model", default=MODEL, help=f"Ollama model (default {MODEL})")
    # --host/--port are the SIMULATOR. --ollama-host is the MODEL. Two
    # different machines once the model runs on a cluster, so two flags.
    parser.add_argument("--ollama-host", default=OLLAMA_ENDPOINT,
                        help=f"model endpoint (default {OLLAMA_ENDPOINT})")
    parser.add_argument("--host", default="127.0.0.1",
                        help="simulator host (AirSim RPC)")
    parser.add_argument("--port", type=int, default=AIRSIM_PORT)
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive gates; for scripted runs "
                             "against an already-loaded map")
    args = parser.parse_args()

    count = args.drones or int(input("How many drones?  ").strip() or "1")
    if count < 1:
        sys.exit("need at least one drone")
    drones = vehicle_names(count)

    # No settings.json edit, and no restart. Vehicles the simulator does not
    # have are spawned into it at runtime by fly_plans -> ensure_vehicles, so
    # the number asked for here is simply created. settings.json is still the
    # way to declare a PERSISTENT fleet with cameras (tools/write_roster.py),
    # but nothing requires it for flying.

    instructions = collect_instructions(args, drones)

    # Plan for every drone first. Nothing arms until every plan is valid --
    # a half-flown mission is harder to interpret than one that never started.
    records: list[PlanRecord] = []
    for name, instruction in zip(drones, instructions):
        print(f"\n[{name}] planning: {instruction}")
        record = plan_for(instruction, name, args.model, args.ollama_host)
        log_record(record)
        for note in record.normalised:
            print(f"  normalised: {note}")
        if record.valid:
            print(f"  {len(record.plan)} steps in {record.plan_seconds:.1f}s: "
                  f"{', '.join(s['action'] for s in record.plan)}")
        else:
            print(f"  REJECTED after {record.plan_seconds:.1f}s: {record.error}")
            print(f"  raw output: {record.raw_output[:200]}")
        records.append(record)

    # All-or-nothing. One rejected plan stops the whole mission, because a
    # partially flown multi-drone run is neither a result nor a clean failure.
    if any(not record.valid for record in records):
        print("\nNo drone armed: at least one plan was rejected.")
        return 1
    if args.plan_only:
        print("\n--plan-only: not flying.")
        return 0

    # AirSim is imported only on the flight path, so --plan-only works in an
    # environment where airsim is not installed at all.
    import airsim

    client = airsim.MultirotorClient(ip=args.host, port=args.port)
    client.confirmConnection()

    # Manual gate: the RPC port opens well before the map finishes loading, and
    # arming into a half-loaded world produces failures that look like bugs.
    # --yes skips it for scripted runs, where the caller has already waited.
    if not args.yes:
        input("\nPress Enter once the map has loaded to launch all drones.  ")

    # fly_plans owns the thread model, the separation monitor and teardown, and
    # is shared with scripts/run_missions.py so both fly the same way.
    outcomes, separation = fly_plans(client, records, args.host, args.port)
    log_execution(outcomes, separation)

    print("\nAll drones finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
