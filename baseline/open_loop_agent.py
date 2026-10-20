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
from typing import Any, Iterable

# The research modules live beside `baseline/`. Run as a script, Python puts only
# this file's folder on the path, so add the repository root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# PHASE 2: execution now lives in agentic_uav/, behind a VehicleAdapter. These
# names are re-exported so every caller of this module -- the runner, the
# sandbox, the tests -- keeps working unchanged.
from agentic_uav.control import executor as _executor  # noqa: E402
from agentic_uav.control.contacts import (  # noqa: E402,F401
    CAMERA_OBJECTS,
    GROUND_OBJECTS,
    LANDING_CONTACT_WINDOW,
    classify_contact,
    is_ground,
    landing_contact,
)
from agentic_uav.control.executor import (  # noqa: E402,F401
    AIRBORNE_MARGIN,
    CRUISE_ALTITUDE,
    FLY_TO_TIMEOUT,
    GROUND_SETTLE_TIMEOUT,
    GROUND_SETTLE_TOLERANCE,
    LAND_DESCENT_TIMEOUT,
    LAND_TIMEOUT,
    LANDED_AGL_MAX,
    MOVE_SPEED,
    TAKEOFF_SETTLE,
    DroneRunner,
)
from agentic_uav.control.ground import (  # noqa: E402,F401
    _GROUND_REFERENCE,
    GROUND_BARRIER_TIMEOUT,
    GROUND_REFERENCE_TOLERANCE,
    GROUND_SPREAD_TOLERANCE,
    GroundReferenceError,
    check_ground_reference,
    forget_ground_reference,
    register_ground,
    validate_grounds,
)
from agentic_uav.control.monitor import SeparationMonitor  # noqa: E402,F401
from agentic_uav.core.errors import PlanError  # noqa: E402,F401
from agentic_uav.simulator import scenario_manager as _scenario  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402
from agentic_uav.simulator.scenario_manager import (  # noqa: E402,F401
    SPACING,
    ForeignVehicleError,
    foreign_vehicles,
)

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
    # The LAPTOP's defaults, not the study's. The runner always sends the
    # protocol block from the mission config, which since 2026-10-19 asks for
    # the model's full 131072 context on two H100s. These values are what a
    # bare import gets on a machine whose VRAM belongs to the simulator.
    "num_gpu": 0,
    "num_ctx": 4096,
    "temperature": 0,
    "num_predict": 512,
    "num_thread": 12,
}


AIRSIM_PORT = 41451
MAX_DURATION = 60.0      # seconds; a single leg longer than this is rejected
MAX_ALTITUDE = -120.0    # metres NED; roughly the legal ceiling for small UAS
MIN_ALTITUDE = -2.0      # metres NED; below this is effectively ground level


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
    False.

    That does NOT mean a simulator booted with four drones can fly a one-drone
    mission. The unused drones sit where they spawned, SPACING metres apart
    along +X -- directly on a forward mission's flight path -- and a flight
    into them is recorded as an obstacle collision. `ensure_vehicles` refuses
    that case. The protocol therefore keeps the declared roster at ONE and
    spawns extra drones at runtime, flying missions in increasing drone count
    and restarting the simulator before going back down.

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
            # NOT bounds-checked, unlike set_altitude. The asymmetry is real
            # and the behaviour is DELIBERATE as of 2026-10-19: left alone, so
            # "return home" means the origin at ground level and M04 scores as
            # the model wrote it. set_altitude refuses z = 0 as "at or below
            # ground level"; fly_to accepts it, and since altitudes are anchored
            # to the measured ground, z = 0 means the terrain. Measured
            # 2026-10-09: two drones told to "return home and land" from 70 m and
            # 55 m both arrived at 0.04 m AGL after fly_to, where its default
            # implies 8 m. It explains M04 finishing at 0.27 m where every other
            # mission finishes near 1.17 m.
            #
            # Applying the bounds here was tried and REVERTED on 2026-10-09:
            # the model emits {"x":0,"y":0,"z":0} for M04 in all three attempts,
            # so the bounds turn a 3/3 mission into 0/3. Decided 2026-10-19 to
            # leave it: nothing in the prompt tells the model fly_to's z has a
            # floor, so rejecting the plan would score it against a rule it was
            # never given. The consequence is recorded instead -- a fly_to with
            # z = 0 arrives at ground level, which is why M04 finishes at 0.27 m
            # where other missions finish near 1.17 m. See the phase log.
            step = dict(step, z=float(z))

        checked.append(step)

    return checked, notes


def server_version(endpoint: str = OLLAMA_ENDPOINT) -> str | None:
    """The Ollama server's own version string, or None if it cannot be read.

    Recorded with every series because the server is part of the apparatus and
    was previously invisible: the provenance named the ENDPOINT but not what was
    running there, so two blocks produced by different Ollama versions looked
    identical in the record. Found 2026-10-19, while upgrading 0.35.1 to 0.40.6
    between two sets of runs that are meant to be compared.

    Never fatal. A version that cannot be read is recorded as None, which is
    still better than a number nobody checked.
    """
    import json
    import urllib.request

    try:
        url = normalise_endpoint(endpoint).rstrip("/") + "/api/version"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8")).get("version")
    except Exception:
        return None


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


# ---------------------------------------------------------------- flying them

def reset_world(client, settle: float = 2.0) -> None:
    """Return every vehicle to its start pose. See scenario_manager.reset_world.

    Kept here, taking a raw AirSim client, so callers written before Phase 2 --
    the runner and the sandbox -- work unchanged.
    """
    _scenario.reset_world(AirSimAdapter(client), settle)


def ensure_vehicles(client, names: list[str]) -> dict[str, Any]:
    """Spawn what is missing, refuse leftovers. See scenario_manager.ensure_vehicles."""
    return _scenario.ensure_vehicles(AirSimAdapter(client), names)


def fly_plans(client, records: list[PlanRecord], host: str = "127.0.0.1",
              port: int = AIRSIM_PORT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fly one plan per drone, concurrently. See executor.fly_plans.

    `DroneRunner` and `MOVE_SPEED` are read from THIS module at call time, so
    replacing either here still takes effect -- tools/fly_chat.py swaps in its
    own runner and changes the speed that way.
    """
    return _executor.fly_plans(
        AirSimAdapter(client), records,
        connect=lambda: AirSimAdapter.connect(host, port),
        runner_class=DroneRunner, speed=MOVE_SPEED)


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
        # Since Phase 2 the flying code is in agentic_uav/, so the entry point's
        # digest alone no longer identifies what flew. One digest over the
        # whole package, file names included, does.
        "agentic_uav_sha256": package_digest(),
        "python": sys.version.split()[0],
        "ollama_endpoint": OLLAMA_ENDPOINT,
    }


def package_digest() -> str | None:
    """SHA-256 over every agentic_uav module, names and contents, short form."""
    import glob
    import hashlib

    root = os.path.join(_REPO_ROOT, "agentic_uav")
    paths = sorted(glob.glob(os.path.join(root, "**", "*.py"), recursive=True))
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in paths:
        digest.update(os.path.relpath(path, _REPO_ROOT).replace(os.sep, "/").encode())
        digest.update(b"\0")
        with open(path, "rb") as handle:
            digest.update(handle.read())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def connect(host: str = "127.0.0.1", port: int = AIRSIM_PORT):
    """Open a NEW AirSim connection.

    One per thread, always. `msgpack-rpc` multiplexes a single socket over a
    tornado IOLoop that is not thread-safe, and sharing a client across threads
    does not fail cleanly -- the first two-drone flight produced
    `RuntimeError: IOLoop is already running` on one drone and
    `BufferError: Existing exports of data: object cannot be re-sized` on the
    other, and neither flew.

    Connections are cheap. Threads are not worth sharing them for.

    Returns the raw AirSim client, for callers written before Phase 2 (the
    sandbox). The connection itself is opened by the adapter.
    """
    return AirSimAdapter.connect(host, port).client


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

    # AirSim is imported only on the flight path (inside the adapter), so
    # --plan-only works in an environment where airsim is not installed at all.
    client = connect(args.host, args.port)

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
