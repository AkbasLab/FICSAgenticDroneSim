"""Deterministic persistent policy (Phase 5.3).

Given the current belief, decide the next objective and the single skill to run
for it - no LLM, no preflight plan. Building this first gives us a debugging tool
and a research baseline: the LLM policy (later) has to match or beat it.

The policy is a small state machine over progress flags in the belief:

    (on ground) -> TAKE_OFF -> GO_TO_SECTOR -> SEARCH_SECTOR -> REPORT
                -> RETURN_HOME -> LAND -> DONE

with two deterministic reactions layered on top:
  - low battery: skip remaining search and return/land (safety first);
  - a failed navigation skill: retry it a bounded number of times, then give up
    the task safely by returning home.
"""

from ..control import skills as sk
from ..core.models import Position3D
from .objectives import Objective

DEFAULT_SPEED = 4.0
DEFAULT_TOLERANCE = 1.5
LANE_SPACING = 8.0
LEG_TIMEOUT = 600.0


class SearchAgentPolicy:
    def __init__(self, max_nav_retries=2):
        self.max_nav_retries = max_nav_retries

    def next_objective(self, belief) -> Objective:
        if belief.landed:
            return Objective.DONE

        # safety reaction: too many nav failures -> abandon task, come home.
        if belief.nav_failures > self.max_nav_retries and not belief.rtb_forced:
            belief.rtb_forced = True

        # safety reaction: low/critical battery -> return and land, skip search.
        if (belief.low_battery or belief.critical_battery) and not belief.reported:
            belief.rtb_forced = True

        if not belief.airborne:
            return Objective.TAKE_OFF

        if belief.rtb_forced:
            return Objective.LAND if belief.near_home else Objective.RETURN_HOME

        if not belief.at_sector and not belief.sector_searched:
            return Objective.GO_TO_SECTOR
        if not belief.sector_searched:
            return Objective.SEARCH_SECTOR
        if not belief.reported:
            return Objective.REPORT
        if not belief.near_home:
            return Objective.RETURN_HOME
        return Objective.LAND

    def choose_skill(self, belief, objective):
        """Return the single command for this objective (or None for REPORT/DONE)."""
        task = belief.task
        alt = belief.cruise_altitude

        if objective is Objective.TAKE_OFF:
            return sk.TakeOffCommand(target_altitude=alt, timeout_s=LEG_TIMEOUT)

        if objective is Objective.GO_TO_SECTOR:
            r = task.sector.footprint
            entry = Position3D(r.min_x, r.min_y, task.sector.altitude)
            return sk.GoToWaypointCommand(waypoint=entry, speed_mps=DEFAULT_SPEED,
                                          tolerance_m=DEFAULT_TOLERANCE,
                                          timeout_s=LEG_TIMEOUT)

        if objective is Objective.SEARCH_SECTOR:
            r = task.sector.footprint
            return sk.SearchRegionCommand(
                min_x=r.min_x, min_y=r.min_y, max_x=r.max_x, max_y=r.max_y,
                altitude=task.sector.altitude, lane_spacing_m=LANE_SPACING,
                speed_mps=DEFAULT_SPEED, tolerance_m=DEFAULT_TOLERANCE,
                timeout_s=LEG_TIMEOUT)

        if objective is Objective.RETURN_HOME:
            return sk.ReturnHomeCommand(home=belief.home, speed_mps=DEFAULT_SPEED,
                                        tolerance_m=DEFAULT_TOLERANCE,
                                        timeout_s=LEG_TIMEOUT)

        if objective is Objective.LAND:
            return sk.LandCommand(timeout_s=LEG_TIMEOUT)

        # REPORT and DONE have no flight skill
        return None
