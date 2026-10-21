"""What a collision was with, and whether it proves a landing.

Pure classification of the object names AirSim reports. No simulator.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 3. Only
calls to the AirSim client were changed, to calls on the adapter;
`tests/test_golden.py` proves the simulator sees the same calls as before.
"""

from __future__ import annotations

from typing import Iterable

# How close to the end of a flight a polled ground contact must be to count as
# evidence of landing. Generous enough to cover the teardown descent and the
# offset between the monitor's clock and one drone's flight, far enough from the
# start to exclude the reset drop, which also touches the ground.
LANDING_CONTACT_WINDOW = 8.0   # seconds


# Object names AirSim reports for ground contact. Touching these on landing is
# the mission working, not a fault, so they are classified separately.
GROUND_OBJECTS = ("terrain", "ground", "landscape", "road", "sidewalk",
                  # Town10HD's player start rests on this mesh. The aircraft was
                  # measured sitting on it at 0.00 m AGL with contact reported,
                  # so it is the floor however it is named.
                  "sm_seam")


def is_ground(object_name: str) -> bool:
    """True if a collision object is the ground rather than an obstacle."""
    lowered = (object_name or "").lower()
    return any(marker in lowered for marker in GROUND_OBJECTS)


# The free camera. It is an actor in the level and the drones collide with it,
# which says nothing about the flight -- measured 2026-10-06, Drone3 reporting
# 0.14 m of penetration against it mid-mission. A simulator artifact, counted
# separately so it cannot inflate an obstacle count.
CAMERA_OBJECTS = ("spectatorpawn", "cameraactor", "defaultpawn")


def landing_contact(drone: str, flight_seconds: float,
                    polled: Iterable[dict]) -> dict | None:
    """The polled ground contact that shows `drone` finished on the ground.

    Returns the contact, or None if there isn't one. Pure: no simulator, no
    clock, so it can be tested.

    A flight touches the ground twice. Once near the START, when `reset_world`
    drops the aircraft at the map origin and it falls -- that proves nothing
    about how the flight ended. And once at the END, on landing. Only the
    second counts, which is what the window is for.
    """
    cutoff = flight_seconds - LANDING_CONTACT_WINDOW
    late = [c for c in polled
            if c.get("drone") == drone
            and c.get("is_ground")
            and c.get("last_at_s", -1) >= cutoff]
    return late[-1] if late else None


def classify_contact(object_name: str, drones: Iterable[str] = ()) -> str:
    """One of "ground", "drone", "camera" or "obstacle".

    Four categories rather than two, because "not ground" turned out to mean
    four different things and only one of them is a flight defect:

    - **ground** — the surface. `SM_seaM` is included by name: it is what the
      aircraft rests on at Town10HD's player start, measured sitting on it at
      0.00 m AGL with the physics engine reporting contact. Naming a map mesh in
      a general predicate is unlovely, but calling the floor an obstacle is a
      worse answer, and the alternative is a claim that every landing is a crash.
    - **drone** — another aircraft. The thing M09 and M10 exist to measure, and
      not an "obstacle" in the sense section 1.3 means.
    - **camera** — the spectator pawn. An artifact of someone watching.
    - **obstacle** — anything else: a building, a vehicle, a tree. The only
      category that counts against a flight.
    """
    lowered = (object_name or "").lower()
    if not lowered:
        return "obstacle"
    if any(d.lower() in lowered for d in drones):
        return "drone"
    if any(marker in lowered for marker in CAMERA_OBJECTS):
        return "camera"
    if is_ground(object_name):
        return "ground"
    return "obstacle"
