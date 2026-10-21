"""The scene: resetting it, and making sure exactly the right drones are in it.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 3. Only
calls to the AirSim client were changed, to calls on the adapter;
`tests/test_golden.py` proves the simulator sees the same calls as before.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..core.models import Position
from .adapter import SceneAdapter

SPACING = 4.0            # metres between drones at spawn, on X


def reset_world(scene: SceneAdapter, settle: float = 2.0) -> None:
    """Return every vehicle to its start pose.

    Without this, each run begins wherever the previous one ended -- M01 flies
    25 m forward and lands there, so the next mission arms from a different
    place, at a different ground height, over different terrain. Observed in
    practice: `ground z` moved from 29.25 to 27.27 between runs.

    For a one-off flight that hardly matters. For 1.3, where three repeats of a
    mission are meant to be the same mission, it is the difference between
    repeats and a drift.
    """
    scene.reset()
    time.sleep(settle)                 # physics needs a moment to settle
    scene.confirm_connection()


class ForeignVehicleError(RuntimeError):
    """The scene holds drones this flight does not use. See ensure_vehicles."""


def foreign_vehicles(present: list[str], names: list[str]) -> list[str]:
    """Vehicles in the scene that are not part of this flight, sorted.

    Pure, so the rule can be tested without a simulator.
    """
    wanted = set(names)
    return sorted(v for v in present if v not in wanted)


def ensure_vehicles(adapter: Any, names: list[str],
                    settle: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Make sure every named drone exists in the RUNNING simulator -- and no other.

    Drones declared in settings.json are created at process start, so changing
    that file means restarting. `simAddVehicle` adds one to a simulator that is
    already running: ask for four drones against a one-drone simulator and the
    other three appear. Going UP in drone count therefore needs no restart.

    Going DOWN does. Consequences of spawning this way:

    * **No cameras.** A runtime drone gets no camera configuration. This agent
      never reads an image -- it is blind by design -- so it costs nothing. A
      later phase that wants vision must declare those vehicles in
      settings.json instead.
    * **They outlive the mission.** A runtime drone stays in the scene until
      the simulator restarts. `client.reset()` does not remove it; it puts it
      back at its spawn pose, and AirSim 1.8.1's Python API has no call that
      removes a vehicle. The same holds for drones declared in settings.json.

    That second point is why this REFUSES when the scene holds a drone the
    flight does not use. Drones sit along +X at SPACING metres, which is the
    direction every forward mission flies, so a leftover Drone2 is parked 4 m
    in front of Drone1. Measured 2026-10-19, flying M01-M09 after M10 without a
    restart: 17 of 27 runs hit the leftover drones, flights stretched to
    61-201 s, and aircraft were left pinned or hanging up to 11 m above ground.
    Nothing warned, and the contacts were recorded as ordinary obstacles. The
    only fix is a simulator restart, so the error says so.

    Spawned along X at SPACING metres, matching the layout settings.json uses,
    because nothing in this stack avoids collisions.

    `settle` waits for the simulator (Phase 3): by default real time, as the
    baseline always has; the mock passes its simulated clock's `sleep`.
    """
    wait = time.sleep if settle is None else settle
    # `adapter` is both a SceneAdapter (spawn, place) and a VehicleAdapter
    # (read back where each drone landed). AirSimAdapter is both.
    existing = adapter.list_vehicles()
    extra = foreign_vehicles(existing, names)
    if extra:
        raise ForeignVehicleError(
            f"the scene holds {', '.join(extra)}, which this flight does not use "
            f"(it flies {', '.join(names)}). Leftover drones sit on the +X "
            f"flight path and are hit as obstacles, and nothing can remove them "
            f"short of a simulator restart. Restart the simulator, and fly "
            f"missions in increasing drone count.")
    added: list[str] = []

    for index, name in enumerate(names):
        if name in existing:
            continue
        if not adapter.add_vehicle(name, "SimpleFlight",
                                   Position(index * SPACING, 0.0, 0.0)):
            raise RuntimeError(f"simulator refused to add {name}")
        added.append(name)

    if added:
        wait(1.5)                            # let them register and settle
        now = adapter.list_vehicles()
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
        adapter.place_vehicle(name, Position(index * SPACING, 0.0, 0.0),
                              ignore_collision=True)
        placed.append(name)
    wait(1.5)                                # let them fall to the ground

    # Verify, because a silent failure here puts drones on top of each other.
    layout = {}
    for index, name in enumerate(names):
        position = adapter.get_state(name).position
        layout[name] = (round(position.x, 2), round(position.y, 2))
        if abs(position.x - index * SPACING) > 1.0:
            raise RuntimeError(
                f"{name} should be at x={index * SPACING} but is at "
                f"x={position.x:.2f}; refusing to fly drones that may be stacked"
            )

    if len(names) > 1:
        print("spawn layout: " + "  ".join(f"{n}{xy}" for n, xy in layout.items()))

    return {"present": existing, "added": added, "layout": layout}
