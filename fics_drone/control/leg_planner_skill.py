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

CLIMB_GAIN = 0.7          # 1/s: vertical speed per metre of height error (1.0 overshot a roof target's height by 1.6 m)
FINAL_APPROACH_M = 4.0    # a leg that stops at its target walks the last stretch straight at it, at ...
FINAL_GAIN = 0.8          # ... this times the distance (1/s), no slower than FINAL_MIN_MPS and no faster than FINAL_MAX_MPS
FINAL_MIN_MPS = 0.3
FINAL_MAX_MPS = 1.3
MAX_CLIMB_MPS = 2.0


VERTICAL_STALL_S = 6.0      # over its goal but not getting any nearer its height (resting on something the map does not have): the leg has failed
STALL_S = 20.0              # a leg that has not got this much nearer its goal (stall_progress_m) for this long has stalled
STALL_PROGRESS_M = 1.5
LEAD_S = 0.7                # a pass-through waypoint is done this many seconds of flight before it (so 2.5 m at 3.5 m/s), to round the corner ...
LEAD_MAX_M = 4.0            # ... but never earlier than this
PASS_BY_M = 3.0             # a pass-through leg that came within this (level) of its waypoint and is now moving away from it has passed it
PASS_THROUGH_M = 1.5        # a leg that another follows is done this near its waypoint, without stopping there
APPROACH_GAIN = 0.6         # 1/s: a leg that stops at its target flies no faster than this times its distance to it ...
APPROACH_MIN_MPS = 0.4      # ... but never slower than this. The aircraft coasts about 0.7 m for every m/s when told to hover, so at 2 m/s it went 1.5-2.5 m past
#                             the target (seen in every live run) and had to come back


def fly_leg_with_planner(adapter: VehicleAdapter, x: float, y: float, z: float, planner,
                         zone_rects_fn: Callable[[], list], offset_xy: Tuple[float, float] = (0.0, 0.0),
                         tolerance: float = SKILL_TOLERANCE_M, timeout_s: float = SKILL_TIMEOUT_S,
                         max_speed: float = SKILL_STOP_SPEED_MPS, interrupt: Optional[Callable] = None,
                         stall_s: float = STALL_S, stall_progress_m: float = STALL_PROGRESS_M,
                         pass_through_m: float = 0.0, evade_fn: Optional[Callable] = None,
                         lead_s: float = LEAD_S, dz_tol_m: float = 2.0) -> SkillResult:
    """pass_through_m > 0: the leg is one of a run (the next starts at once), so it ends, still moving, as soon as the aircraft is
    that near the waypoint. Stopping at every waypoint costs a braking and a climb back to cruise speed each time: at 3 m between
    waypoints a live aircraft averaged about 1.1 m/s of the 1.9 commanded."""
    target = (x, y, z)
    start = time.monotonic()
    best_distance, last_progress = float("inf"), start
    try:
        ox, oy = offset_xy
        goal_world = (x + ox, y + oy)
        pos = adapter.get_position()
        start_world = (pos[0] + ox, pos[1] + oy)
        # a planner that reads a sensor on the aircraft (NavRL's lidar) is handed the adapter, so one shared planner
        # can serve several drones, each leg using its own aircraft's sensor
        leg = (planner.begin_leg(start_world, goal_world, adapter) if getattr(planner, "wants_adapter", False)
               else planner.begin_leg(start_world, goal_world))
        holding = False
        best_dz, dz_progress = float("inf"), start
        nearest_h = float("inf")
        while True:
            pos = adapter.get_position()
            elapsed = time.monotonic() - start
            if interrupt is not None and interrupt(pos):
                adapter.start_hover()
                return SkillResult(SkillStatus.INTERRUPTED, pos, elapsed, error="interrupted by monitor")
            if evade_fn is not None:
                # a body about to run into the aircraft (while it creeps the last metres or waits on its target) is stepped away from first
                step = evade_fn((pos[0] + offset_xy[0], pos[1] + offset_xy[1], pos[2]))
                if step is not None:
                    adapter.start_velocity(float(step[0]), float(step[1]), 0.0)
                    holding = False
                    last_progress = time.monotonic()
                    time.sleep(SKILL_POLL_INTERVAL_S)
                    continue
            if pass_through_m > 0.0:
                h = math.hypot(x - pos[0], y - pos[1])
                nearest_h = min(nearest_h, h)
                # a waypoint that is one of a run is done when level with it (the height is flown on the way), or once the aircraft has gone by:
                # at 3.5 m/s it passed a waypoint 1.3 m to one side, was not "within 1.5 m" in 3D, turned back and crawled to it (seen live)
                # the next run starts early enough to turn in one smooth curve instead of a corner: the faster the aircraft, the earlier
                lead = max(pass_through_m, min(LEAD_MAX_M, lead_s * adapter.get_speed()))
                if (math.dist(pos, target) <= max(pass_through_m, tolerance)
                        or (h <= lead and abs(z - pos[2]) <= dz_tol_m)
                        or (nearest_h <= PASS_BY_M and h > nearest_h + 0.3 and abs(z - pos[2]) <= dz_tol_m)):
                    return SkillResult(SkillStatus.SUCCESS, pos, elapsed)
            close = math.dist(pos, target) <= tolerance
            if close and not holding:
                adapter.start_hover()
                holding = True
            if close and adapter.get_speed() <= max_speed:
                return SkillResult(SkillStatus.SUCCESS, pos, elapsed)
            distance = math.hypot(x - pos[0], y - pos[1])
            if distance < best_distance - stall_progress_m:
                best_distance, last_progress = distance, time.monotonic()
            elif not close and distance > tolerance and time.monotonic() - last_progress > stall_s:
                # a reactive planner can be held in a pocket (a keep-out between it and its goal) and would otherwise fly in
                # place until the leg timeout; the agent is told the leg failed and carries on with the mission
                adapter.start_hover()
                return SkillResult(SkillStatus.TIMEOUT, pos, elapsed, error=f"no progress toward {target} for {stall_s}s")
            dz = abs(z - pos[2])
            if dz < best_dz - 0.3 or distance > tolerance:
                best_dz, dz_progress = dz, time.monotonic()
            elif not close and time.monotonic() - dz_progress > VERTICAL_STALL_S:
                adapter.start_hover()
                return SkillResult(SkillStatus.TIMEOUT, pos, elapsed, error=f"stuck {dz:.1f} m off the height of {target} for {VERTICAL_STALL_S}s")
            if elapsed > timeout_s:
                adapter.start_hover()
                return SkillResult(SkillStatus.TIMEOUT, pos, elapsed, error=f"didn't reach {target} within {timeout_s}s")
            if not close:
                vx, vy = 0.0, 0.0
                # A leg with no horizontal distance (the climb to cruise height) has no direction for a planner to
                # head in (NavRL turns it into NaN), so only the height is flown. A planner that still returns a
                # non-finite velocity holds position rather than sending the aircraft off.
                distance_to_goal = math.hypot(x - pos[0], y - pos[1])
                if distance_to_goal > tolerance:
                    vx, vy = leg.velocity((pos[0] + ox, pos[1] + oy), goal_world, zone_rects_fn())
                    if not (math.isfinite(vx) and math.isfinite(vy)):
                        vx, vy = 0.0, 0.0
                    if pass_through_m <= 0.0 and math.isfinite(vx) and math.isfinite(vy):
                        cap = max(APPROACH_MIN_MPS, APPROACH_GAIN * distance_to_goal)
                        speed = math.hypot(vx, vy)
                        if speed > cap:
                            vx, vy = vx * cap / speed, vy * cap / speed
                        if distance_to_goal < FINAL_APPROACH_M:
                            # the planner's own output dies away a metre or so short of its goal, so the aircraft sat there; the last
                            # metres are a plain, slow walk straight at the target (the target is already clear of keep-outs)
                            creep = min(FINAL_MAX_MPS, max(FINAL_MIN_MPS, FINAL_GAIN * distance_to_goal))
                            vx = creep * (x - pos[0]) / distance_to_goal
                            vy = creep * (y - pos[1]) / distance_to_goal
                vz = max(-MAX_CLIMB_MPS, min(MAX_CLIMB_MPS, (z - pos[2]) * CLIMB_GAIN))
                if (z - pos[2]) < 0.0 and distance_to_goal > FINAL_APPROACH_M and math.hypot(vx, vy) < 0.3:
                    vz = 0.0     # not held in place to sink straight down while the planner has not started moving on (it descended, stopped, then went)
                adapter.start_velocity(float(vx), float(vy), vz)
            time.sleep(SKILL_POLL_INTERVAL_S)
    except Exception as e:
        final = None
        try:
            adapter.start_hover()      # a failed leg must not leave the aircraft flying on its last command
            final = adapter.get_position()
        except Exception:
            pass
        return SkillResult(SkillStatus.FAILED, final, time.monotonic() - start, error=str(e))
