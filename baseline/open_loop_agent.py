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

# PHASE 2: execution lives in agentic_uav/control behind a VehicleAdapter, and
# planning in agentic_uav/planners behind a MissionPlanner. These names are
# re-exported so every caller of this module -- the runner, the sandbox, the
# tests -- keeps working unchanged.
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
from agentic_uav.planners import ollama_planner as _ollama_planner  # noqa: E402
from agentic_uav.planners.base_planner import MissionPlanner, PlanRecord  # noqa: E402,F401
from agentic_uav.planners.endpoint import (  # noqa: E402,F401
    MODEL,
    OLLAMA_ENDPOINT,
    EndpointError,
    check_endpoint,
    is_transport_error,
    normalise_endpoint,
    server_version,
)
from agentic_uav.planners.ollama_planner import OLLAMA_OPTIONS  # noqa: E402,F401
from agentic_uav.planners.plan_schema import (  # noqa: E402,F401
    ACTIONS,
    MAX_ALTITUDE,
    MAX_DURATION,
    MIN_ALTITUDE,
    PLAN_SCHEMA,
    validate,
)
from agentic_uav.planners.prompt import EXAMPLES, SYSTEM_PROMPT, build_messages  # noqa: E402,F401
from agentic_uav.simulator import scenario_manager as _scenario  # noqa: E402
from agentic_uav.simulator.airsim_adapter import AirSimAdapter  # noqa: E402
from agentic_uav.simulator.scenario_manager import (  # noqa: E402,F401
    SPACING,
    ForeignVehicleError,
    foreign_vehicles,
)


AIRSIM_PORT = 41451


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(REPO_ROOT, "runs", "agent-log.jsonl")


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


def plan_for(instruction: str, drone: str, model: str = MODEL,
             endpoint: str = OLLAMA_ENDPOINT,
             options: dict[str, Any] | None = None) -> PlanRecord:
    """Ask the model for a plan and validate it. See ollama_planner.plan_for.

    `SYSTEM_PROMPT` is read from THIS module at call time, so replacing it
    here still takes effect -- tools/fly_chat.py rewrites it for its speed
    setting and its sandbox addendum.
    """
    return _ollama_planner.plan_for(instruction, drone, model, endpoint, options,
                                    system_prompt=SYSTEM_PROMPT)


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
