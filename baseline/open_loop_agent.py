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
import os
import sys
from typing import Any

# The research modules live beside `baseline/`. Run as a script, Python puts only
# this file's folder on the path, so add the repository root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# PHASE 2: execution lives in agentic_uav/control behind a VehicleAdapter,
# planning in agentic_uav/planners behind a MissionPlanner, the agent log and
# provenance in agentic_uav/experiments beside the mission runner, and the
# settings.json helpers in agentic_uav/simulator. These names are re-exported
# so every caller of this module -- the sandbox, the tools, the tests -- keeps
# working unchanged.
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
from agentic_uav.experiments.agent_log import LOG_PATH, log_execution, log_record  # noqa: E402,F401
from agentic_uav.experiments.provenance import (  # noqa: E402,F401
    file_digest,
    package_digest,
    provenance,
)
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
from agentic_uav.simulator.airsim_settings import (  # noqa: E402,F401
    CAMERA_TEMPLATE,
    build_settings,
    documents_dir,
    vehicle_names,
    write_settings,
)
from agentic_uav.simulator.scenario_manager import (  # noqa: E402,F401
    SPACING,
    ForeignVehicleError,
    foreign_vehicles,
)


AIRSIM_PORT = 41451


# ------------------------------------------------------------- AirSim settings

# ------------------------------------------------------------------ planning


def plan_for(instruction: str, drone: str, model: str = MODEL,
             endpoint: str = OLLAMA_ENDPOINT,
             options: dict[str, Any] | None = None) -> PlanRecord:
    """Ask the model for a plan and validate it. See ollama_planner.plan_for.

    `SYSTEM_PROMPT` is read from THIS module at call time, so replacing it
    here still takes effect. tools/fly_chat.py relied on that until Phase 2
    step 5; it now hands its own prompt to an OllamaPlanner instead, but the
    wrapper keeps the behaviour for any caller that still rewrites it.
    """
    return _ollama_planner.plan_for(instruction, drone, model, endpoint, options,
                                    system_prompt=SYSTEM_PROMPT)


# ----------------------------------------------------------------- execution


# ---------------------------------------------------------------- flying them

def reset_world(client, settle: float = 2.0) -> None:
    """Return every vehicle to its start pose. See scenario_manager.reset_world.

    Kept here, taking a raw AirSim client, so callers written before Phase 2
    work unchanged. (The runner and the sandbox, its first two, use the
    scenario manager directly since step 5.)
    """
    _scenario.reset_world(AirSimAdapter(client), settle)


def ensure_vehicles(client, names: list[str]) -> dict[str, Any]:
    """Spawn what is missing, refuse leftovers. See scenario_manager.ensure_vehicles."""
    return _scenario.ensure_vehicles(AirSimAdapter(client), names)


def fly_plans(client, records: list[PlanRecord], host: str = "127.0.0.1",
              port: int = AIRSIM_PORT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fly one plan per drone, concurrently. See executor.fly_plans.

    `DroneRunner` and `MOVE_SPEED` are read from THIS module at call time, so
    replacing either here still takes effect. tools/fly_chat.py relied on that
    until Phase 2 step 5; it now passes its runner and speed to
    executor.fly_plans as arguments, but the wrapper keeps the behaviour.
    """
    return _executor.fly_plans(
        AirSimAdapter(client), records,
        connect=lambda: AirSimAdapter.connect(host, port),
        runner_class=DroneRunner, speed=MOVE_SPEED)


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
