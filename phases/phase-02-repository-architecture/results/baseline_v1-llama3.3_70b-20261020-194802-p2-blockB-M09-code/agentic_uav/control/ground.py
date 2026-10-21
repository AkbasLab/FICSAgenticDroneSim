"""The session's ground reference: where each drone's ground is, and whether a
new reading can be believed.

Every altitude the executor flies is measured from this number, and for most of
Phase 1 it was wrong. Pure bookkeeping: no simulator, so it is unit-tested in
`tests/test_ground.py`.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 3. Only
calls to the AirSim client were changed, to calls on the adapter;
`tests/test_golden.py` proves the simulator sees the same calls as before.
"""

from __future__ import annotations

import threading

# How far a run's measured ground may differ from the first run's before the run
# is refused. reset_world() returns every vehicle to the same pose, so the ground
# under a given drone is a constant for the session; a disagreement means the
# measurement is wrong, not that the ground moved.
GROUND_REFERENCE_TOLERANCE = 2.0   # metres

# How far two DIFFERENT drones' grounds may differ. They spawn SPACING metres
# apart on one patch of terrain, so this is relief, not frame error. Wider than
# the per-drone tolerance because the terrain genuinely varies: 29.25, 29.28 and
# 27.29 were measured across the four M10 spawn points, a 1.99 m spread.
GROUND_SPREAD_TOLERANCE = 5.0      # metres

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


# Raw readings for this run, before any of them is trusted. The barrier below
# exists because a reading can only be judged against the others, and the others
# are not known until every drone has armed.
_GROUND_RAW: dict[str, float] = {}
GROUND_BARRIER_TIMEOUT = 30.0   # seconds to wait for the other drones to arm


def register_ground(name: str, ground_z: float) -> None:
    """Record what `name` measured, without judging it yet."""
    with _GROUND_LOCK:
        _GROUND_RAW[name] = ground_z


def validate_grounds(name: str) -> None:
    """Refuse this run if `name`'s reading cannot be right.

    Called after every drone in the run has registered, so the comparison is
    against a complete set. An aircraft can only be AT or ABOVE the ground, and
    in NED a larger z is lower, so the deepest reading in the scene is the best
    evidence of where the ground is. A reading sitting well above it was taken in
    mid air.

    This refuses rather than substituting. The deepest reading belongs to another
    drone over its own terrain, so it is not this drone's ground either -- it is
    only proof that this drone's number is wrong. Flying a mission against a
    guess would produce data that looks valid, which is the failure mode this
    whole area of the code exists to prevent.
    """
    with _GROUND_LOCK:
        readings = dict(_GROUND_RAW)
    mine = readings.get(name)
    if mine is None or len(readings) < 2:
        return
    deepest_name, deepest = max(readings.items(), key=lambda kv: kv[1])
    if deepest - mine > GROUND_SPREAD_TOLERANCE:
        raise GroundReferenceError(
            f"{name}: measured ground z = {mine:.2f}, which is "
            f"{deepest - mine:.2f} m above the ground {deepest_name} found in "
            f"the same scene ({deepest:.2f}, tolerance "
            f"{GROUND_SPREAD_TOLERANCE}). An aircraft cannot be below the "
            f"ground, so this was measured in mid air. Refusing to fly: all "
            f"readings this run were "
            + ", ".join(f"{k}={v:.2f}" for k, v in sorted(readings.items()))
        )


def forget_ground_reference(name: str | None = None) -> None:
    """Drop the cached ground, for one vehicle or all. For tests and restarts."""
    with _GROUND_LOCK:
        if name is None:
            _GROUND_REFERENCE.clear()
            _GROUND_RAW.clear()
        else:
            _GROUND_REFERENCE.pop(name, None)
            _GROUND_RAW.pop(name, None)


def check_ground_reference(name: str, ground_z: float) -> float:
    """Record or verify the ground for `name`. Returns the session reference.

    Checks against this drone's own history AND against the other drones in the
    scene. The per-drone check alone has a hole: a drone's FIRST reading becomes
    the reference and is never questioned. Measured 2026-10-06, two drones armed
    seconds apart in the same world -- `Drone1 ground z = 29.25` and
    `Drone3 ground z = -0.28`. Drone3's was its first, so it was accepted, and
    Drone3 then flew its 18 m leg at about 50 m.

    Drones spawn SPACING metres apart on one patch of ground, so their ground
    heights differ by terrain relief, not by 29 m. The disagreement is the signal.
    """
    with _GROUND_LOCK:
        reference = _GROUND_REFERENCE.get(name)
        if reference is None:
            others = {k: v for k, v in _GROUND_REFERENCE.items() if k != name}
            # WHICH reading is wrong, not merely which arrived second. In NED a
            # larger z is lower, and an aircraft can only ever be AT or ABOVE the
            # ground -- so of two disagreeing readings the LARGER is nearer the
            # true ground, and a too-small one belongs to an aircraft that never
            # came down. Refusing the later arrival instead got this backwards in
            # flight on 2026-10-06: Drone3 armed first with -0.23, became the
            # reference, and Drone1's correct 29.25 was the one refused.
            deepest = max(others.items(), key=lambda kv: kv[1], default=None)
            if deepest is not None and deepest[1] - ground_z > GROUND_SPREAD_TOLERANCE:
                raise GroundReferenceError(
                    f"{name}: measured ground z = {ground_z:.2f}, which is "
                    f"{deepest[1] - ground_z:.2f} m ABOVE the ground "
                    f"{deepest[0]} found in the same scene ({deepest[1]:.2f}, "
                    f"tolerance {GROUND_SPREAD_TOLERANCE}). An aircraft cannot "
                    f"be below the ground, so this reading was taken in mid "
                    f"air. Refusing to fly."
                )
            lowest = min(others.values(), default=None)
            if lowest is not None and ground_z - lowest > GROUND_SPREAD_TOLERANCE:
                # This reading is the lower one, so it is the credible one and the
                # drones already registered are the suspects. Adopt it and correct
                # them, loudly: a run already refused is better than one flown
                # against a ground 29 m in the air.
                stale = {k: v for k, v in _GROUND_REFERENCE.items()
                         if ground_z - v > GROUND_SPREAD_TOLERANCE}
                for k in stale:
                    _GROUND_REFERENCE.pop(k, None)
                print(f"  [ground] {name} found ground at {ground_z:.2f}; "
                      f"discarding higher readings from "
                      f"{', '.join(f'{k}={v:.2f}' for k, v in stale.items())}",
                      flush=True)
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
