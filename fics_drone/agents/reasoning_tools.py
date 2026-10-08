"""Phase 12.5: deterministic calculators, so the model never does arithmetic.
Plan.docx 12.5: "Do not expect the LLM to perform precise spatial optimization
from textual coordinates." The model chooses WHAT to do and WHY; this code
computes WHETHER IT IS POSSIBLE.

Everything is in the WORLD frame (the frame the model, the teammates' reported
positions and the SafetyGuardian all use). Two design rules:

* "Legal" is never reimplemented here. route_feasible() asks the guardian's own
  checks (through SafetyGuardian.preview, which touches no state), so this tool
  and the guardian cannot disagree - tests assert they agree on random points.
* The tools use their OWN guardian instance, never the agent's, so asking "is
  this point legal?" cannot move the real guardian's escalation counters.

battery_sufficient always counts the RETURN leg: the question is never "can I
get there" but "can I get there and still get back".
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from ..control.navigation import DEFAULT_HEIGHT, MOVE_SPEED, SKILL_TIMEOUT_S
from ..coordination.bidding import compute_bid, sector_center
from ..core.scenario import Scenario
from .safety_guardian import Command, SafetyGuardian, SafetyLimits

BATTERY_SAFETY_MARGIN = 1.25   # applied to every battery answer, on top of the travel-time estimate
DEFAULT_REPAIR_RADIUS_M = 60.0
REPAIR_STEP_M = 1.0
REPAIR_ANGLES = 24

Point = Tuple[float, float]


@dataclass
class RouteCheck:
    legal: bool
    failed_checks: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)   # the guardian's own words, "name: reason"


@dataclass
class ReasoningTools:
    scenario: Scenario
    spawn_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)   # THIS agent's local->world offset
    speed_mps: float = MOVE_SPEED
    cruise_height: float = DEFAULT_HEIGHT
    guardian: SafetyGuardian = None

    def __post_init__(self):
        if self.guardian is None:
            self.guardian = SafetyGuardian(limits=SafetyLimits.from_scenario(self.scenario))

    # --- pure geometry ---
    @staticmethod
    def distance(a: Point, b: Point) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def travel_time_s(self, a: Point, b: Point) -> float:
        return self.distance(a, b) / self.speed_mps

    def own_world(self, belief) -> Point:
        return (belief.position[0] + self.spawn_offset[0], belief.position[1] + self.spawn_offset[1])

    def home_world(self) -> Point:
        return (self.spawn_offset[0], self.spawn_offset[1])

    # --- feasibility ---
    def battery_sufficient(self, belief, point: Point) -> Tuple[bool, float]:
        """(ok, seconds_needed): fly to `point` AND still get home, with a margin."""
        needed = (self.travel_time_s(self.own_world(belief), point)
                  + self.travel_time_s(point, self.home_world())) * BATTERY_SAFETY_MARGIN
        remaining = belief.battery_s - belief.elapsed_s
        return needed <= remaining, needed

    def comms_reachable(self, belief, point: Point) -> bool:
        """Within radio range of the base station, or of any teammate we last heard from."""
        rng = self.scenario.comms_range_m
        base = self.scenario.base_station
        if self.distance(point, (base[0], base[1])) <= rng:
            return True
        return any(t.last_known_position is not None
                   and self.distance(point, (t.last_known_position[0], t.last_known_position[1])) <= rng
                   for t in belief.team.teammates.values())

    def separation_risk(self, belief, point: Point) -> Tuple[Optional[str], Optional[float]]:
        """(nearest teammate, distance to it) among teammates whose position we know."""
        best: Tuple[Optional[str], Optional[float]] = (None, None)
        for name, t in belief.team.teammates.items():
            if t.last_known_position is None:
                continue
            d = self.distance(point, (t.last_known_position[0], t.last_known_position[1]))
            if best[1] is None or d < best[1]:
                best = (name, d)
        return best

    def task_cost(self, belief, sector_id: str) -> float:
        """The deterministic bid. A model may decide WHETHER to bid, never what to bid."""
        return compute_bid((*self.own_world(belief), 0.0), belief.battery_frac_remaining, workload=0,
                           sector=self.scenario.sector(sector_id))

    def route_feasible(self, belief, point: Point) -> RouteCheck:
        """Would the SafetyGuardian accept flying to `point` as new mission work?"""
        failed = self.guardian.preview(self._command(point), belief)
        return RouteCheck(legal=not failed, failed_checks=[c.name for c in failed],
                          reasons=[f"{c.name}: {c.reason}" for c in failed])

    def nearest_legal_point(self, belief, point: Point,
                            max_radius_m: float = DEFAULT_REPAIR_RADIUS_M) -> Optional[Point]:
        """Closest point to `point` the guardian would accept, or None if nothing within
        `max_radius_m` qualifies. Deterministic: expanding rings, fixed angular order."""
        if not all(math.isfinite(v) for v in point):
            return None                      # a non-finite point has no "nearby" - nothing to search around
        if self.route_feasible(belief, point).legal:
            return point
        steps = int(max_radius_m / REPAIR_STEP_M)
        for i in range(1, steps + 1):
            r = i * REPAIR_STEP_M
            for k in range(REPAIR_ANGLES):
                a = 2 * math.pi * k / REPAIR_ANGLES
                candidate = (point[0] + r * math.cos(a), point[1] + r * math.sin(a))
                if self.route_feasible(belief, candidate).legal:
                    return candidate
        return None

    # --- what the prompt shows ---
    def checked_points(self, belief) -> List[str]:
        """Pre-computed facts about the obvious places to go, so the model can choose among
        them without computing anything. One line per sector centre."""
        lines = []
        for s in self.scenario.sectors:
            c = sector_center(s)
            route = self.route_feasible(belief, c)
            battery_ok, needed = self.battery_sufficient(belief, c)
            name, dist = self.separation_risk(belief, c)
            near = f"nearest teammate {name} {dist:.0f}m away" if name else "no teammate position known"
            verdict = "LEGAL" if route.legal else f"NOT LEGAL ({', '.join(route.failed_checks)})"
            lines.append(f"- sector {s.id} centre ({c[0]:.0f}, {c[1]:.0f}): {verdict}; "
                         f"round trip needs {needed:.0f}s, battery {'ok' if battery_ok else 'INSUFFICIENT'}; "
                         f"{'in' if self.comms_reachable(belief, c) else 'OUT of'} radio range; {near}")
        return lines

    def _command(self, point: Point) -> Command:
        return Command(kind="fly", target=(point[0], point[1], self.cruise_height + self.spawn_offset[2]),
                       purpose="mission", speed_mps=self.speed_mps, timeout_s=SKILL_TIMEOUT_S)
