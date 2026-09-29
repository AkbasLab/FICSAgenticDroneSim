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
AirSim is North-East-Down. **Negative Z is up.** 15 metres above ground is
z = -15. A positive Z flies into the ground, which is the most common error
against this platform, so `set_altitude` normalises a positive value and says so
rather than obeying it.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------- constants

MODEL = "llama3.2:3b"

# Frozen inference options. These are part of the measurement protocol in
# docs/BASELINE_MISSIONS.md, not preferences: num_gpu 0 because 4 GB of VRAM is
# already spoken for by the simulator, temperature 0 so runs are comparable.
OLLAMA_OPTIONS = {
    "num_gpu": 0,
    "temperature": 0,
    "num_predict": 512,
    "num_thread": 12,
}

CRUISE_ALTITUDE = -8.0   # metres, NED: negative is up
SPACING = 4.0            # metres between drones at spawn, on X
MOVE_SPEED = 5.0         # m/s for every directional move
TAKEOFF_SETTLE = 3.0     # seconds to let takeoff stabilise before the plan runs

AIRSIM_PORT = 41451
MAX_DURATION = 60.0      # seconds; a single leg longer than this is rejected
MAX_ALTITUDE = -120.0    # metres NED; roughly the legal ceiling for small UAS
MIN_ALTITUDE = -2.0      # metres NED; below this is effectively ground level

# How far above its arming height the vehicle must be for teardown to treat it
# as airborne and land it first. Disarming while airborne cuts the motors.
AIRBORNE_MARGIN = 1.0    # metres

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

    def as_json(self) -> dict[str, Any]:
        return {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "drone": self.drone,
            "model": self.model,
            "instruction": self.instruction,
            "raw_output": self.raw_output,
            "plan": self.plan,
            "plan_seconds": round(self.plan_seconds, 2),
            "valid": self.valid,
            "error": self.error,
            "normalised": self.normalised,
        }


def log_execution(outcomes: list[dict[str, Any]]) -> None:
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
        "drones": len(outcomes),
        "completed": all(o["completed"] for o in outcomes),
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


def write_settings(count: int) -> tuple[str, bool]:
    """Write settings.json for `count` drones. Returns (path, changed).

    The whole file is rewritten, so every drone must be emitted -- including
    Drone1. AirSim reads this only at process start, so a change means the
    simulator has to be restarted before it takes effect.
    """
    settings = build_settings(count)

    directory = os.path.join(documents_dir(), "AirSim")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "settings.json")

    new_text = json.dumps(settings, indent=2)
    old_text = ""
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as handle:
                old_text = handle.read()
        except OSError:
            old_text = ""

    changed = json.loads(old_text) != settings if old_text.strip() else True
    if changed:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new_text)
    return path, changed


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


def plan_for(instruction: str, drone: str, model: str = MODEL) -> PlanRecord:
    """Ask the model for a plan and validate it. Never raises; records instead."""
    import ollama  # imported here so --plan-only works without AirSim installed

    started = time.time()
    raw = ""
    try:
        response = ollama.chat(
            model=model,
            messages=build_messages(instruction),
            format=PLAN_SCHEMA,
            options=OLLAMA_OPTIONS,
        )
        raw = response["message"]["content"]
        elapsed = time.time() - started
        steps, notes = validate(json.loads(raw))
        return PlanRecord(drone, instruction, raw, steps, elapsed, True, None, notes, model)
    except (PlanError, json.JSONDecodeError) as exc:
        return PlanRecord(drone, instruction, raw, None, time.time() - started,
                          False, str(exc), [], model)
    except Exception as exc:  # model unreachable, transport error, and friends
        return PlanRecord(
            drone, instruction, raw, None, time.time() - started, False,
            f"{type(exc).__name__}: {exc}", [], model,
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

    def _say(self, message: str) -> None:
        # flush=True because several threads print concurrently; without it the
        # interleaving is buffered into nonsense.
        print(f"[{self.name}] {message}", flush=True)

    def arm(self) -> None:
        """Take control of the vehicle and record where the ground is."""
        import airsim  # noqa: F401  (kept local so --plan-only needs no install)

        self.client.enableApiControl(True, vehicle_name=self.name)
        self.client.armDisarm(True, vehicle_name=self.name)
        state = self.client.getMultirotorState(vehicle_name=self.name)
        # Recorded before takeoff because this build has NO TERRAIN COLLISION:
        # the drone passes through the ground, so landing cannot wait for a
        # physical touchdown and must descend to a remembered height instead.
        #
        # This is also the only simulator state the agent reads, and it never
        # reaches the model. The agent is blind by design.
        self.ground_z = state.kinematics_estimated.position.z_val
        self._say(f"armed, ground z = {self.ground_z:.2f}")

    def take_off(self) -> None:
        """Lift off and settle at cruise height before the plan begins."""
        self.client.takeoffAsync(vehicle_name=self.name).join()
        self.client.moveToZAsync(CRUISE_ALTITUDE, MOVE_SPEED, vehicle_name=self.name).join()
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
            self.client.moveToZAsync(step["z"], MOVE_SPEED, vehicle_name=self.name).join()
        elif action == "fly_to":
            self.client.moveToPositionAsync(
                float(step["x"]), float(step["y"]), float(step.get("z", CRUISE_ALTITUDE)),
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
        failure: str | None = None
        try:
            self.arm()
            self.take_off()
            for position, step in enumerate(steps, start=1):
                self._say(f"{position}/{len(steps)} {step['action']}")
                self.step(step)
                executed.append(step["action"])
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

        return {
            "drone": self.name,
            "planned": [s["action"] for s in steps],
            "executed": executed,
            # Completed means every step ran, not that the outcome was correct.
            "completed": len(executed) == len(steps) and failure is None,
            "failure": failure,
            "flight_seconds": round(time.time() - started, 1),
            "ground_z": round(self.ground_z, 2),
        }

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

        # LandedState: 0 = Landed, 1 = Flying. Authoritative when available.
        landed_state = getattr(state, "landed_state", None)
        if landed_state is not None:
            return landed_state != 0

        # Fall back to height if the field is missing. NED: more negative is
        # higher.
        return state.kinematics_estimated.position.z_val < self.ground_z - AIRBORNE_MARGIN

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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=AIRSIM_PORT)
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive gates; for scripted runs "
                             "against an already-loaded map")
    args = parser.parse_args()

    count = args.drones or int(input("How many drones?  ").strip() or "1")
    if count < 1:
        sys.exit("need at least one drone")
    drones = vehicle_names(count)

    # settings.json declares the vehicle roster, and AirSim reads it ONLY at
    # process start. Writing it is therefore useless without a restart, and
    # flying on with a stale roster produces "vehicle not found" errors that
    # look like a connection problem. Hence the explicit confirmation.
    if not args.plan_only:
        path, changed = write_settings(count)
        print(f"settings.json -> {path}")
        if changed:
            print("  settings changed: RESTART the simulator before flying, "
                  "AirSim reads this file only at startup")
            # --yes does NOT skip this one. The roster on disk no longer matches
            # the running simulator, so flying on would address vehicles that do
            # not exist. A scripted run must stop here and let its caller
            # restart the simulator.
            if args.yes:
                print("  refusing to continue: --yes cannot substitute for a restart")
                return 1
            if input("  restart done? [y/N]  ").strip().lower() not in ("y", "yes"):
                return 1

    instructions = collect_instructions(args, drones)

    # Plan for every drone first. Nothing arms until every plan is valid --
    # a half-flown mission is harder to interpret than one that never started.
    records: list[PlanRecord] = []
    for name, instruction in zip(drones, instructions):
        print(f"\n[{name}] planning: {instruction}")
        record = plan_for(instruction, name, args.model)
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

    # One thread per drone, all sharing the one client. Threads rather than
    # AirSim's own async futures because each drone runs a SEQUENCE: within a
    # plan the steps are ordered, and only the drones are concurrent.
    #
    # Note every runner gets the same `client` -- see the thread-safety caveat
    # on DroneRunner. Changing to one client per thread is a two-line edit here
    # if multi-drone runs prove unreliable.
    outcomes: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run(record: PlanRecord) -> None:
        outcome = DroneRunner(client, record.drone).fly(record.plan)
        with lock:                     # list.append is atomic, but be explicit
            outcomes.append(outcome)

    threads = [threading.Thread(target=run, args=(r,)) for r in records]
    for thread in threads:
        thread.start()
    # Join every thread before returning: exiting with drones still flying
    # leaves them armed and under API control.
    for thread in threads:
        thread.join()

    # Execution record, one line per run, beside the planning records. Written
    # here rather than in the thread so a multi-drone mission is one entry.
    log_execution(outcomes)

    print("\nAll drones finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
