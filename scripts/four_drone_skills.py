#!/usr/bin/env python3
"""Phase 3's exit script: four drones, eleven-skill layer, structured results.

    python scripts/four_drone_skills.py                    # the mock: seconds, no simulator
    python scripts/four_drone_skills.py --sim airsim       # CarlaAir, running, Town10HD

Four drones take off to 12, 16, 20 and 24 m, fly 20 m sideways to distinct
waypoints (alternating sides, so no tracks cross), turn to face the way they
went, hold 5 s, return home and land -- every
step a skill from `agentic_uav/control/skills.py`, every outcome a
`SkillResult`. The plan is fixed (`team_flight.exit_plan`): no model runs, so
no Vega job is needed.

Outputs, under phases/phase-03-flight-skill-layer/results/ by default:

    four-drone-skills-<sim>-<stamp>[-<block>].jsonl   one row per skill, plus a header row
    four-drone-skills-<sim>-<stamp>[-<block>].md      the summary and the exit verdict

Exit code 0 only if every skill of every drone succeeded.

FOR AIRSIM: the simulator must be up with ONE drone declared in
settings.json, as for the mission runner; Drone2-4 are spawned at runtime and
stay until a restart, so fly this on a fresh launch or after missions that
used four drones. The leftover-drone check refuses otherwise.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from agentic_uav.control.contacts import is_ground  # noqa: E402
from agentic_uav.control.monitor import SeparationMonitor  # noqa: E402
from agentic_uav.core.clock import RealClock  # noqa: E402
from agentic_uav.experiments.provenance import provenance  # noqa: E402
from agentic_uav.experiments.team_flight import (  # noqa: E402
    EXIT_DRONES,
    exit_plan,
    fly_team,
    verdict,
)
from agentic_uav.simulator.airsim_adapter import AIRSIM_PORT, AirSimAdapter  # noqa: E402
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter, MockWorld  # noqa: E402
from agentic_uav.simulator.scenario_manager import ensure_vehicles  # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "phases", "phase-03-flight-skill-layer", "results")
RESET_SETTLE_S = 2.0          # as scenario_manager.reset_world waits


def prepare(sim: str, host: str, port: int):
    """The scene, a connection factory, a clock and (mock only) the world, for
    `sim`. Reset and populated."""
    world = None
    if sim == "mock":
        world = MockWorld(declared=("Drone1",))
        scene = MockVehicleAdapter(world)
        clock = world.clock

        def connect():
            return MockVehicleAdapter(world)
    else:
        scene = AirSimAdapter.connect(host, port)
        clock = RealClock()

        def connect():
            return AirSimAdapter.connect(host, port)
    # The same steps as scenario_manager.reset_world, on this run's clock.
    scene.reset()
    clock.sleep(RESET_SETTLE_S)
    scene.confirm_connection()
    layout = ensure_vehicles(scene, list(EXIT_DRONES), settle=clock.sleep)
    return scene, connect, clock, layout, world


def separation_report(world, monitor_result) -> dict:
    """Closest approach per pair and drone-to-drone contacts.

    The mock measures them exactly, in simulated time. In AirSim the separation
    monitor Phase 1 built polls at 10 Hz while the team flies.
    """
    if world is not None:
        contacts = [c for c in world.contacts() if not is_ground(c["object"])]
        return {"source": "mock world, exact", "per_pair_min_m":
                {pair: v["min_m"] for pair, v in world.separation().items()},
                "drone_contacts": contacts}
    return {"source": "SeparationMonitor, 10 Hz",
            "per_pair_min_m": monitor_result.get("per_pair_min_m", {}),
            "drone_contacts": monitor_result.get("drone_collisions", []),
            "samples": monitor_result.get("samples")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sim", choices=("mock", "airsim"), default="mock")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--block", metavar="LABEL", help="short label appended to the file names")
    parser.add_argument("--host", default="127.0.0.1", help="AirSim host")
    parser.add_argument("--port", type=int, default=AIRSIM_PORT)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    started_wall = time.strftime("%Y-%m-%dT%H:%M:%S")
    scene, connect, clock, layout, world = prepare(args.sim, args.host, args.port)
    plan = exit_plan()
    print(f"sim     : {args.sim}")
    print(f"drones  : {', '.join(m.drone for m in plan)}  layout {layout['layout']}")
    print()

    monitor = None
    if world is None:
        monitor = SeparationMonitor(connect(), list(EXIT_DRONES))
        monitor.start()
    t0 = clock.now()
    try:
        records = fly_team(plan, connect, clock)
    finally:
        monitor_result = monitor.stop() if monitor is not None else {}
    separation = separation_report(world, monitor_result)
    ok, why = verdict(records)

    os.makedirs(args.out, exist_ok=True)
    stem = (f"four-drone-skills-{args.sim}-{time.strftime('%Y%m%d-%H%M%S')}"
            + (f"-{args.block}" if args.block else ""))
    header = {"kind": "header", "t": started_wall, "sim": args.sim, "clock": type(clock).__name__,
              "drones": list(EXIT_DRONES), "layout": layout["layout"], "added": layout["added"],
              "separation": separation, "code": provenance(),
              "exit_criterion_met": ok, "verdict": why}
    with io.open(os.path.join(args.out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(header) + "\n")
        for drone in sorted(records):
            for record in records[drone]:
                h.write(json.dumps(record.as_json()) + "\n")

    lines = [f"# Four-drone skill run — {args.sim}", "",
             f"Run {started_wall}, `scripts/four_drone_skills.py`, clock `{type(clock).__name__}`.", "",
             "| Drone | # | Skill | Status | Error | Start s | End s | Final altitude m | Heading ° |",
             "|---|---|---|---|---|---|---|---|---|"]
    for drone in sorted(records):
        for r in records[drone]:
            res = r.result
            name = r.command.skill.value + (" (safety)" if r.safety else "")
            if res is None:
                lines.append(f"| {drone} | {r.index} | {name} | skipped | | | | | |")
                continue
            lines.append(
                f"| {drone} | {r.index} | {name} | {res.status.value} | "
                f"{res.error_code.value if res.error_code else ''} | {res.started_at - t0:.1f} | "
                f"{res.ended_at - t0:.1f} | "
                f"{'' if res.final_altitude_m is None else f'{res.final_altitude_m:.2f}'} | "
                f"{'' if res.final_yaw_deg is None else f'{res.final_yaw_deg:.1f}'} |")
    pairs = separation["per_pair_min_m"]
    lines += ["", f"Closest approach per pair ({separation['source']}): "
              + (", ".join(f"{p} {d} m" for p, d in pairs.items()) or "not measured")
              + f". Drone-to-drone contacts: {len(separation['drone_contacts'])}.",
              "", f"**Exit criterion: {'MET' if ok else 'NOT MET'}** — {why}.", ""]
    summary = "\n".join(lines)
    with io.open(os.path.join(args.out, stem + ".md"), "w", encoding="utf-8", newline="\n") as h:
        h.write(summary)
    print(summary)
    print(f"raw     : {os.path.join(args.out, stem + '.jsonl')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
