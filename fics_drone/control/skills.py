"""Mission-level primitives on top of raw movement. Each wraps a non-blocking
adapter call in a polling loop with its own timeout, so a skill always
returns within a bounded time and always reports a real SkillResult, unlike
the raw actions in airsim_adapter.py which block on .join() with no limit.

Each function takes a VehicleAdapter, so these run against AirSimVehicleAdapter
or MockVehicleAdapter identically - nothing here imports airsim.
"""

import math
import time
from typing import List, Tuple

from ..core.interfaces import VehicleAdapter
from ..core.skill_result import FollowWaypointsResult, SkillResult, SkillStatus
from .navigation import (
    DEFAULT_HEIGHT, SKILL_POLL_INTERVAL_S, SKILL_SETTLE_SECS, SKILL_STOP_SPEED_MPS,
    SKILL_TIMEOUT_S, SKILL_TOLERANCE_M,
)


def go_to_waypoint(adapter: VehicleAdapter, x: float, y: float, z: float,
                    tolerance: float = SKILL_TOLERANCE_M,
                    timeout_s: float = SKILL_TIMEOUT_S,
                    max_speed: float = SKILL_STOP_SPEED_MPS, interrupt=None) -> SkillResult:
    """`interrupt`, if given, is called with the current local position on every poll; if it
    returns True the leg stops (hover) and reports INTERRUPTED. Default None = unchanged.

    Moves toward the target, then - once within tolerance - actively holds
    there (start_hover()) and waits for speed to actually drop, instead of
    just hoping the move command leaves the drone stationary on its own.
    Passively waiting without holding lets the drone drift uncontrolled for
    the rest of the timeout, since AirSim stops resisting drift once its own
    move command's internal state finishes."""
    target = (x, y, z)
    start = time.monotonic()
    try:
        adapter.start_move_to(x, y, z)
        holding = False

        while True:
            pos = adapter.get_position()
            elapsed = time.monotonic() - start
            if interrupt is not None and interrupt(pos):
                adapter.start_hover()
                return SkillResult(SkillStatus.INTERRUPTED, pos, elapsed, error="interrupted by monitor")
            close = math.dist(pos, target) <= tolerance
            if close and not holding:
                adapter.start_hover()
                holding = True
            if close and adapter.get_speed() <= max_speed:
                return SkillResult(SkillStatus.SUCCESS, pos, elapsed)
            if elapsed > timeout_s:
                return SkillResult(SkillStatus.TIMEOUT, pos, elapsed,
                                    error=f"didn't reach {target} within {timeout_s}s")
            time.sleep(SKILL_POLL_INTERVAL_S)
    except Exception as e:
        # A real adapter call can now raise (e.g. the AirSim adapter's RPC watchdog
        # giving up on a stalled connection) instead of hanging forever - report it
        # as a normal FAILED skill result like everywhere else, don't let it crash
        # this drone's whole thread silently.
        return SkillResult(SkillStatus.FAILED, None, time.monotonic() - start, error=str(e))


def hold_position(adapter: VehicleAdapter, duration_s: float,
                   drift_tolerance: float = SKILL_TOLERANCE_M) -> SkillResult:
    start = time.monotonic()
    try:
        adapter.start_hover()
        time.sleep(SKILL_SETTLE_SECS)  # let arrival momentum die down before measuring drift
        anchor = adapter.get_position()

        while True:
            pos = adapter.get_position()
            elapsed = time.monotonic() - start
            if math.dist(pos, anchor) > drift_tolerance:
                return SkillResult(SkillStatus.FAILED, pos, elapsed,
                                    error=f"drifted more than {drift_tolerance}m while holding")
            if elapsed >= duration_s:
                return SkillResult(SkillStatus.SUCCESS, pos, elapsed)
            time.sleep(SKILL_POLL_INTERVAL_S)
    except Exception as e:
        return SkillResult(SkillStatus.FAILED, None, time.monotonic() - start, error=str(e))


def take_off(adapter: VehicleAdapter) -> SkillResult:
    start = time.monotonic()
    try:
        adapter.connect_and_takeoff()
        return SkillResult(SkillStatus.SUCCESS, adapter.get_position(), time.monotonic() - start)
    except Exception as e:
        return SkillResult(SkillStatus.FAILED, None, time.monotonic() - start, error=str(e))


def land(adapter: VehicleAdapter) -> SkillResult:
    start = time.monotonic()
    try:
        adapter.land()
        return SkillResult(SkillStatus.SUCCESS, adapter.get_position(), time.monotonic() - start)
    except Exception as e:
        return SkillResult(SkillStatus.FAILED, None, time.monotonic() - start, error=str(e))


def return_home(adapter: VehicleAdapter, tolerance: float = SKILL_TOLERANCE_M,
                 timeout_s: float = SKILL_TIMEOUT_S) -> SkillResult:
    """fly_to(0, 0, DEFAULT_HEIGHT) then land - skip landing if home was never
    reached, so a failed return doesn't also disarm mid-air somewhere unknown."""
    to_home = go_to_waypoint(adapter, 0.0, 0.0, DEFAULT_HEIGHT, tolerance, timeout_s)
    if to_home.status != SkillStatus.SUCCESS:
        return to_home
    return land(adapter)


def follow_waypoints(adapter: VehicleAdapter, waypoints: List[Tuple[float, float, float]],
                      tolerance: float = SKILL_TOLERANCE_M,
                      timeout_s: float = SKILL_TIMEOUT_S) -> FollowWaypointsResult:
    """Runs every waypoint even if one times out or fails - one bad leg
    shouldn't abort the whole route. Reports each leg's own SkillResult so
    the caller knows exactly which one, and where it was."""
    start = time.monotonic()
    legs = []
    for x, y, z in waypoints:
        leg = go_to_waypoint(adapter, x, y, z, tolerance, timeout_s)
        legs.append(leg)
        if leg.status != SkillStatus.SUCCESS:
            print(f"follow_waypoints: leg ({x}, {y}, {z}) {leg.status.value} "
                  f"at {leg.final_position} after {leg.elapsed_s:.1f}s - {leg.error}")

    overall = (SkillStatus.SUCCESS if all(l.status == SkillStatus.SUCCESS for l in legs)
               else SkillStatus.PARTIAL)
    return FollowWaypointsResult(overall, legs, time.monotonic() - start)
