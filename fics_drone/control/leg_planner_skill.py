"""Flying one leg with a planner that chooses a velocity every control tick, instead of one straight move command.

Same shape as skills.go_to_waypoint (same polling, tolerance, timeout, interrupt and result), so the agent can use
either for an approved leg. The guardian still approves the leg's target before this runs, and the per-tick zone
monitor (`interrupt`) still stops the leg the moment the aircraft is inside a zone that has become active.

The planner is any object with begin_leg(start_xy, goal_xy), called once per leg in world coordinates, that returns
an object (the leg) with
    velocity(pos_xy, goal_xy, zone_rects)     returns (vx, vy) in m/s, world coordinates
One planner can be shared by several drone threads, so anything that belongs to a leg lives in the returned object.
where zone_rects is a list of (x_min, x_max, y_min, y_max) for the zones active right now (world coordinates).
`offset_xy` is the aircraft's spawn offset, added to local positions to get world ones.
"""

import math
import time
from typing import Callable, Optional, Tuple

from ..core.interfaces import VehicleAdapter
from ..core.skill_result import SkillResult, SkillStatus
from .navigation import SKILL_POLL_INTERVAL_S, SKILL_STOP_SPEED_MPS, SKILL_TIMEOUT_S, SKILL_TOLERANCE_M

CLIMB_GAIN = 1.0          # 1/s: vertical speed per metre of height error
MAX_CLIMB_MPS = 1.0


def fly_leg_with_planner(adapter: VehicleAdapter, x: float, y: float, z: float, planner,
                         zone_rects_fn: Callable[[], list], offset_xy: Tuple[float, float] = (0.0, 0.0),
                         tolerance: float = SKILL_TOLERANCE_M, timeout_s: float = SKILL_TIMEOUT_S,
                         max_speed: float = SKILL_STOP_SPEED_MPS, interrupt: Optional[Callable] = None) -> SkillResult:
    target = (x, y, z)
    start = time.monotonic()
    try:
        ox, oy = offset_xy
        goal_world = (x + ox, y + oy)
        pos = adapter.get_position()
        leg = planner.begin_leg((pos[0] + ox, pos[1] + oy), goal_world)
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
                adapter.start_hover()
                return SkillResult(SkillStatus.TIMEOUT, pos, elapsed, error=f"didn't reach {target} within {timeout_s}s")
            if not close:
                vx, vy = 0.0, 0.0
                # A leg with no horizontal distance (the climb to cruise height) has no direction for a planner to
                # head in (NavRL turns it into NaN), so only the height is flown. A planner that still returns a
                # non-finite velocity holds position rather than sending the aircraft off.
                if math.hypot(x - pos[0], y - pos[1]) > tolerance:
                    vx, vy = leg.velocity((pos[0] + ox, pos[1] + oy), goal_world, zone_rects_fn())
                    if not (math.isfinite(vx) and math.isfinite(vy)):
                        vx, vy = 0.0, 0.0
                vz = max(-MAX_CLIMB_MPS, min(MAX_CLIMB_MPS, (z - pos[2]) * CLIMB_GAIN))
                adapter.start_velocity(float(vx), float(vy), vz)
            time.sleep(SKILL_POLL_INTERVAL_S)
    except Exception as e:
        return SkillResult(SkillStatus.FAILED, None, time.monotonic() - start, error=str(e))
