"""The deterministic policy: one drone, one search task, every next step decided as it goes (AUV-06, 5.3).

    agent = DroneAgent(brief, sensors, executor, RulePolicy())
    agent.assign("search S1")

AUV-06, 5.3: "Before any LLM, a rule-based agent that can: accept a search
task; navigate to the assigned sector; search it; report completion; return
home; react to low battery; and recover from a failed navigation skill."
It is also a research baseline in its own right: Architecture C in AUV-13.

UNLIKE PHASE 4's SCRIPTED CONTROLLER, nothing is planned before take-off.
The agent is told "search S1" and nothing else. Each skill is chosen when
the last one has ended -- or earlier, if something happens -- from the belief
as it stands then: where the drone is, what is left of its battery and its
time, whether the last skill worked.

THE STAGES it moves through, and what moves it on:

    READY ─task─> TAKING_OFF ─ok─> TO_SECTOR ─ok─> SEARCHING ─ok─> GOING_HOME ─ok─> LANDING ─ok─> DONE

TO_SECTOR is skipped when the sector's first lane is in a straight, clear
line. The geometry is Phase 4's: routes keep 2 m from zones
(`control.routing`), lanes are spaced by the detection rule and run on past
the sector's ends (`control.scripted`).

REPORT COMPLETION. The base stands by the pads, so the way home passes into
its radio range: whatever the drone saw is reported on the way back (the
belief marks it reported once the link is up). A drone that finishes the
search in range has reported already.

LOW BATTERY, AND THE DEADLINE. Before starting the outbound work, and then
at each battery level the agent crosses and each periodic check while that
work is still ahead: what remains (the rest of the transit, the rest of the
search measured from where the drone is on its lanes, the route home) is
costed with the brief's battery model, at the speed the drone is actually
making good on its search (never more than planned): time aloft is charged
by the second, so a slow drone pays more per metre. If it would leave less
than the reserve plus BATTERY_MARGIN, or the time left would not cover it,
the agent drops the search and goes home at once (a START replaces the
running skill).

A FAILED SKILL. Re-plan from where the drone is now and try the stage again,
up to MAX_RETRIES times. Then give up that stage: an unreachable sector or an
unfinishable search sends the drone home; a way home that keeps failing
ends in landing where it is; a take-off or landing that keeps failing ends
the task with the reason in the trace.

A REFUSED DECISION (the validation step said no). Outbound work refused --
it would not leave enough battery -- means going home. A way home refused
means landing where it is.

WHAT IT ASSUMES (Phase 6; AUV-06 6.1's `assumptions` block). Each decision
rests on things the policy takes to be true without checking them. It
records each in the belief -- statement, evidence, when, how confidently --
where it starts to rely on it, so a reader of the trace can audit it:

    battery_model   the brief's linear battery model holds             accepted task
    hazards         the brief's zones are all the hazards; 2 m clear   accepted task
    reporting       what it sees reaches the base on the way home      accepted task
    teammates       separation is not its concern                      every decision
    speed           the drone keeps the speed it is costed at          every estimate
    fits            the rest of the task fits the battery and time     every estimate; dropped when not
    retry           the failure was passing                            a retry; dropped on success or give-up

The confidences are the policy's own, fixed per kind of evidence (CONFIDENCE),
and not calibrated: they say how much the policy leans on each, for the
reader. An assumption whose statement and evidence have not changed keeps
its time, so its age says how long it has been held. None of this changes a
decision: the policy decides exactly as before, and says what it assumed.
"""

from __future__ import annotations

import math
from enum import Enum

from ..control import navigation as nav
from ..control.routing import NoRouteError, grown, length, route
from ..control.scripted import ZONE_CLEARANCE_M, lane_end_overrun, lane_spacing, searched_region
from ..control.skills import (
    DEFAULT_SPEED_MPS,
    FollowWaypointsCommand,
    LandCommand,
    ReturnHomeCommand,
    SearchRegionCommand,
    TakeOffCommand,
)
from ..core.events import Event, Trigger
from ..core.scenario import Sector
from .belief_state import BeliefState
from .decision import Decision

DEFAULT_ALTITUDE_M = 12.0     # Phase 3's lowest live height
MAX_RETRIES = 2               # per stage, before giving it up
BATTERY_MARGIN = 2.0          # percent above the reserve the agent wants to keep
LANDING_ALLOWANCE_S = 30.0    # time kept for the descent and landing, against the deadline
MIN_SPEED_SAMPLE_S = 10.0     # a search this long before its speed made good is trusted
MIN_SPEED_MPS = 0.5           # a floor, so a drone barely moving costs finite, not infinite
CONFIDENCE = {
    "brief": 0.8,             # what the public brief says, uncalibrated (Phase 4's models)
    "planned": 0.5,           # the plan's own number, not yet measured
    "measured": 0.9,          # measured in this flight
    "alone": 1.0,             # the roster has no one else on it
    "unheard": 0.5,           # teammates exist, none heard: they could be anywhere
    "retry": 0.5,             # a skill failed once; the next try may fail too
}


def remaining_along(path: list[tuple[float, float]], here: tuple[float, float]) -> float:
    """How much of `path` is still ahead of a drone at `here`, measured along it.

    The drone is placed at its closest point on the path; where two legs are
    equally close (a corner) the later one counts, so a drone at the end of a
    lane has that lane behind it.
    """
    best, best_i, best_f = math.inf, 0, 0.0
    for i, (a, b) in enumerate(zip(path, path[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = dx * dx + dy * dy
        f = 0.0 if span == 0 else max(0.0, min(1.0, ((here[0] - a[0]) * dx + (here[1] - a[1]) * dy) / span))
        d = math.hypot(here[0] - a[0] - f * dx, here[1] - a[1] - f * dy)
        if d <= best + 1e-9:
            best, best_i, best_f = d, i, f
    legs = list(zip(path, path[1:]))
    if not legs:
        return 0.0
    a, b = legs[best_i]
    return (1.0 - best_f) * math.dist(a, b) + sum(math.dist(p, q) for p, q in legs[best_i + 1:])


class Stage(Enum):
    READY = "ready"
    TAKING_OFF = "taking_off"
    TO_SECTOR = "to_sector"
    SEARCHING = "searching"
    GOING_HOME = "going_home"
    LANDING = "landing"
    DONE = "done"


class RulePolicy:
    def __init__(self, altitude_m: float = DEFAULT_ALTITUDE_M, speed_mps: float = DEFAULT_SPEED_MPS) -> None:
        self.altitude_m = altitude_m
        self.speed_mps = speed_mps
        self.stage = Stage.READY
        self.sector: Sector | None = None
        self.region = None
        self.spacing = 0.0
        self.lanes: list[tuple[float, float]] = []
        self.search_path: list[tuple[float, float]] = []     # where the search began, then its lanes
        self.search_started_at: float | None = None
        self.retries = 0
        self.gave_up: str | None = None

    # ------------------------------------------------------------ decide

    def decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        decision = self._decide(belief, events)
        if self.sector is not None and self.stage is not Stage.DONE:
            self._assume_teammates(belief)
        progress = belief.mission.progress
        progress.update(stage=self.stage.value, sector=None if self.sector is None else self.sector.id,
                        retries=self.retries)
        if self.gave_up:
            progress["gave_up"] = self.gave_up
        return decision

    def _decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        by = {e.trigger: e for e in events}
        if Trigger.TASK_ASSIGNED in by:
            return self._accept(belief, by[Trigger.TASK_ASSIGNED].detail.get("task", ""))
        if Trigger.GUARD_REJECTED in by:
            return self._refused(belief, by[Trigger.GUARD_REJECTED])
        if Trigger.SKILL_SUCCEEDED in by:
            return self._succeeded(belief)
        if Trigger.SKILL_FAILED in by:
            return self._failed(belief, by[Trigger.SKILL_FAILED])
        if Trigger.SKILL_ABORTED in by:
            return self._home(belief, "a skill was stopped: going home")
        if by.keys() & {Trigger.BATTERY_THRESHOLD, Trigger.PERIODIC} and self.stage in (Stage.TO_SECTOR, Stage.SEARCHING):
            short = self._shortfall(belief)
            if short:
                self.gave_up = short
                return self._home(belief, short)
        return Decision.carry_on(belief.mission.objective, "nothing calls for a change")

    # ------------------------------------------------------------ stages

    def _accept(self, belief: BeliefState, task: str) -> Decision:
        words = task.split()
        sectors = {s.id: s for s in belief.brief.sectors}
        if len(words) != 2 or words[0] != "search" or words[1] not in sectors:
            self.stage = Stage.DONE
            return Decision.finish(reason=f"not a task this policy knows: {task!r}")
        self.sector = sectors[words[1]]
        obstacles = [grown(z.polygon, ZONE_CLEARANCE_M) for z in belief.brief.restricted_zones]
        r = self.sector.region
        self.spacing = lane_spacing(r.y_max - r.y_min, belief.brief.detection, self.speed_mps)
        self.region = searched_region(r, self.spacing, self.altitude_m,
                                      lane_end_overrun(belief.brief.detection, self.speed_mps), obstacles)
        self.lanes = [(w.x, w.y) for w in nav.lawnmower(self.region, self.spacing, self.altitude_m)]
        self._assume_from_brief(belief)
        if belief.self_.airborne:
            return self._to_sector(belief, f"task {task!r}, already airborne")
        self.stage = Stage.TAKING_OFF
        return Decision.start(TakeOffCommand(altitude_m=self.altitude_m, speed_mps=self.speed_mps),
                              f"take off for {self.sector.id}", f"task {task!r}")

    def _succeeded(self, belief: BeliefState) -> Decision:
        self.retries = 0
        belief.drop_assumption("retry")
        if self.stage in (Stage.TAKING_OFF, Stage.TO_SECTOR):
            # Before starting outbound work, not only during it: never begin
            # a search the battery or the time cannot finish.
            short = self._shortfall(belief)
            if short:
                self.gave_up = short
                return self._home(belief, short)
        if self.stage is Stage.TAKING_OFF:
            return self._to_sector(belief, "airborne")
        if self.stage is Stage.TO_SECTOR:
            return self._search(belief, f"at {self.sector.id}")
        if self.stage is Stage.SEARCHING:
            belief.local_map.searched_regions.append(self.sector.region)
            return self._home(belief, f"{self.sector.id} searched")
        if self.stage is Stage.GOING_HOME:
            return self._land("home")
        if self.stage is Stage.LANDING:
            self.stage = Stage.DONE
            return Decision.finish(reason="landed: task over" + (f" ({self.gave_up})" if self.gave_up else ""))
        return Decision.carry_on(belief.mission.objective, f"a skill ended in stage {self.stage.value}")

    def _failed(self, belief: BeliefState, event: Event) -> Decision:
        why = f"{event.detail.get('skill')} {event.detail.get('status')}: {event.detail.get('message', '')}"
        retry = self.retries < MAX_RETRIES
        if retry:
            self.retries += 1
            self._assume(belief, "retry", f"the {self.stage.value} failure was passing: trying again from here",
                         f"{why}; retry {self.retries} of {MAX_RETRIES}", CONFIDENCE["retry"])
        else:
            belief.drop_assumption("retry")
        stage = self.stage
        if stage is Stage.TAKING_OFF:
            if retry:
                return Decision.start(TakeOffCommand(altitude_m=self.altitude_m, speed_mps=self.speed_mps),
                                      f"take off for {self.sector.id}", f"retry {self.retries}: {why}")
            self.gave_up = f"could not take off: {why}"
            self.stage = Stage.DONE
            return Decision.finish(reason=self.gave_up)
        if stage in (Stage.TO_SECTOR, Stage.SEARCHING):
            if retry:
                if stage is Stage.TO_SECTOR:
                    return self._to_sector(belief, f"retry {self.retries}: {why}")
                return self._search(belief, f"retry {self.retries}: {why}")
            self.gave_up = f"gave up {stage.value} after {MAX_RETRIES} retries: {why}"
            self.retries = 0
            return self._home(belief, self.gave_up)
        if stage is Stage.GOING_HOME:
            if retry:
                return self._home(belief, f"retry {self.retries}: {why}")
            self.gave_up = f"could not get home: {why}"
            return self._land("land where it is")
        if stage is Stage.LANDING:
            if retry:
                return Decision.start(LandCommand(), "land", f"retry {self.retries}: {why}")
            self.gave_up = f"could not land: {why}"
            self.stage = Stage.DONE
            return Decision.finish(reason=self.gave_up)
        return Decision.carry_on(belief.mission.objective, f"a skill failed in stage {stage.value}")

    def _refused(self, belief: BeliefState, event: Event) -> Decision:
        reasons = "; ".join(event.detail.get("reasons", []))
        if self.stage is Stage.GOING_HOME:
            self.gave_up = f"the way home was refused ({reasons})"
            return self._land("land where it is")
        self.gave_up = f"refused: {reasons}"
        return self._home(belief, self.gave_up)

    # ----------------------------------------------------------- actions

    def _to_sector(self, belief: BeliefState, reason: str) -> Decision:
        here = (belief.self_.x, belief.self_.y)
        try:
            leg = route(here, self.lanes[0], [z.polygon for z in belief.brief.restricted_zones], ZONE_CLEARANCE_M)
        except NoRouteError as exc:
            self.gave_up = f"no route to {self.sector.id}: {exc}"
            return self._home(belief, self.gave_up)
        if len(leg) <= 2:                          # straight and clear: the search flies there itself
            return self._search(belief, reason)
        self.stage = Stage.TO_SECTOR
        return Decision.start(FollowWaypointsCommand(tuple(nav.Waypoint(x, y, self.altitude_m) for x, y in leg[1:-1]),
                                                     speed_mps=self.speed_mps),
                              f"reach {self.sector.id}", reason)

    def _search(self, belief: BeliefState, reason: str) -> Decision:
        self.stage = Stage.SEARCHING
        self.search_started_at = belief.self_.updated_at
        self.search_path = [(belief.self_.x, belief.self_.y)] + self.lanes
        return Decision.start(SearchRegionCommand(region=self.region, altitude_m=self.altitude_m,
                                                  spacing_m=self.spacing, speed_mps=self.speed_mps),
                              f"search {self.sector.id}", reason)

    def _home(self, belief: BeliefState, reason: str) -> Decision:
        here, home = (belief.self_.x, belief.self_.y), belief.self_.home
        if math.dist(here, home) <= 1.0:
            return self._land(reason)
        self.stage = Stage.GOING_HOME
        try:
            leg = route(here, home, [z.polygon for z in belief.brief.restricted_zones], ZONE_CLEARANCE_M)
        except NoRouteError:
            # Too close to a zone to keep the clearance: straight home, which
            # the validation step still checks against the zone itself.
            return Decision.start(ReturnHomeCommand(speed_mps=self.speed_mps), "return home and report", reason)
        return Decision.start(FollowWaypointsCommand(tuple(nav.Waypoint(x, y, self.altitude_m) for x, y in leg[1:]),
                                                     speed_mps=self.speed_mps),
                              "return home and report", reason)

    def _land(self, reason: str) -> Decision:
        self.stage = Stage.LANDING
        return Decision.start(LandCommand(), "land", reason)

    # ------------------------------------------------------ the estimate

    def _shortfall(self, belief: BeliefState) -> str | None:
        """Why the work ahead no longer fits the battery or the time; None if it does."""
        me = belief.self_
        here = (me.x, me.y)
        zones = [z.polygon for z in belief.brief.restricted_zones]
        if self.stage in (Stage.TAKING_OFF, Stage.TO_SECTOR):
            ahead = math.dist(here, self.lanes[0]) + length(self.lanes)
        else:
            # Measured from where the drone IS on its lanes, not from the time
            # spent: a drone slower than planned -- exactly when the battery
            # runs short -- would otherwise look further along than it is.
            ahead = remaining_along(self.lanes, here)
        try:
            home = length(route(self.lanes[-1], me.home, zones, ZONE_CLEARANCE_M))
        except NoRouteError:
            home = math.dist(self.lanes[-1], me.home)
        metres = ahead + home
        speed = self._speed_made_good(belief)
        self._assume_speed(belief, speed)
        seconds = metres / speed
        battery = belief.brief.battery
        cost = battery.hover_drain_per_s * seconds + battery.move_drain_per_m * metres
        if me.battery - cost < battery.reserve + BATTERY_MARGIN:
            belief.drop_assumption("fits")
            return (f"low battery: {me.battery:.1f} % left, about {cost:.1f} % to finish and get home, "
                    f"under the {battery.reserve:g} % reserve plus {BATTERY_MARGIN:g}")
        if belief.time_left < seconds + LANDING_ALLOWANCE_S:
            belief.drop_assumption("fits")
            return (f"short of time: {belief.time_left:.0f} s left, about {seconds + LANDING_ALLOWANCE_S:.0f} s "
                    f"to finish and get home")
        self._assume(belief, "fits", "the battery and the time cover the rest of the task",
                     f"about {cost:.1f} % and {seconds + LANDING_ALLOWANCE_S:.0f} s needed for {metres:.0f} m; "
                     f"{me.battery:.1f} % (reserve {battery.reserve:g} + {BATTERY_MARGIN:g}) and "
                     f"{belief.time_left:.0f} s left", min(CONFIDENCE["brief"], self._speed_confidence(belief)))
        return None

    # -------------------------------------------------- what it assumes

    @staticmethod
    def _assume(belief: BeliefState, key: str, statement: str, evidence: str, confidence: float) -> None:
        """Record an assumption; one unchanged in statement and evidence keeps its time."""
        held = belief.assumptions.get(key)
        if held is not None and (held.statement, held.evidence) == (statement, evidence):
            return
        belief.assume(key, statement, evidence, at=belief.self_.updated_at, confidence=confidence)

    def _assume_from_brief(self, belief: BeliefState) -> None:
        brief = belief.brief
        b = brief.battery
        self._assume(belief, "battery_model", "the brief's battery model holds",
                     f"linear: {b.hover_drain_per_s:g} %/s aloft and {b.move_drain_per_m:g} %/m moving, "
                     f"from the brief, uncalibrated", CONFIDENCE["brief"])
        zones = ", ".join(z.id for z in brief.restricted_zones) or "none"
        self._assume(belief, "hazards", f"the brief's zones are all the hazards, and {ZONE_CLEARANCE_M:g} m clear of them is safe",
                     f"zones in the brief: {zones}; no hazard sensed", CONFIDENCE["brief"])
        home, base = belief.self_.home, (brief.base.x, brief.base.y)
        reach, range_m = math.dist(home, base), brief.network.communication_range_m
        if reach <= range_m:
            self._assume(belief, "reporting", "what it sees reaches the base on the way home",
                         f"home is {reach:.1f} m from the base, inside its {range_m:g} m radio", CONFIDENCE["brief"])
        else:
            self._assume(belief, "reporting", "what it sees may never reach the base",
                         f"home is {reach:.1f} m from the base, beyond its {range_m:g} m radio", CONFIDENCE["brief"])

    def _assume_teammates(self, belief: BeliefState) -> None:
        roster = sorted(belief.team.members)
        if not roster:
            self._assume(belief, "teammates", "separation is not its concern: it flies alone",
                         "no other drone on the brief's roster", CONFIDENCE["alone"])
            return
        current = sorted(belief.current_teammates())
        if current:
            self._assume(belief, "teammates", "separation is not its concern: its teammates keep clear",
                         f"current reports from {', '.join(current)}; this policy does not plan around them",
                         CONFIDENCE["unheard"])
        else:
            self._assume(belief, "teammates", "separation is not its concern: its teammates keep clear",
                         f"{', '.join(roster)} on the roster, none heard", CONFIDENCE["unheard"])

    def _assume_speed(self, belief: BeliefState, speed: float) -> None:
        me = belief.self_
        if self.stage is not Stage.SEARCHING or self.search_started_at is None:
            evidence = "the planned speed; not measured until the search is under way"
        elif me.updated_at - self.search_started_at < MIN_SPEED_SAMPLE_S:
            evidence = (f"the planned speed; the search is {me.updated_at - self.search_started_at:.0f} s old, "
                        f"under the {MIN_SPEED_SAMPLE_S:g} s needed to measure it")
        else:
            elapsed = me.updated_at - self.search_started_at
            made = length(self.search_path) - remaining_along(self.search_path, (me.x, me.y))
            evidence = (f"made good {made / elapsed:.2f} m/s over {elapsed:.0f} s of search"
                        + (f", capped at the planned {self.speed_mps:g}" if made / elapsed > self.speed_mps else "")
                        + (f", floored at {MIN_SPEED_MPS:g}" if made / elapsed < MIN_SPEED_MPS else ""))
        self._assume(belief, "speed", f"the drone keeps making {speed:.2f} m/s for the rest", evidence,
                     self._speed_confidence(belief))

    def _speed_confidence(self, belief: BeliefState) -> float:
        measured = (self.stage is Stage.SEARCHING and self.search_started_at is not None
                    and belief.self_.updated_at - self.search_started_at >= MIN_SPEED_SAMPLE_S)
        return CONFIDENCE["measured"] if measured else CONFIDENCE["planned"]

    def _speed_made_good(self, belief: BeliefState) -> float:
        """The speed to cost the rest at: the planned speed, or less if the drone is making less.

        Measured along the search's path (from where the search began,
        through the lanes) by position, over the search so far. Time in the
        air is charged by the second, so a drone at half speed spends twice
        the hover drain per metre: costing the way home at the planned speed
        would bring it in under the reserve. Not yet measurable (under
        MIN_SPEED_SAMPLE_S into a search, or before one), the planned speed.
        """
        me = belief.self_
        if self.stage is not Stage.SEARCHING or self.search_started_at is None:
            return self.speed_mps
        elapsed = me.updated_at - self.search_started_at
        if elapsed < MIN_SPEED_SAMPLE_S:
            return self.speed_mps
        made = length(self.search_path) - remaining_along(self.search_path, (me.x, me.y))
        return max(MIN_SPEED_MPS, min(self.speed_mps, made / elapsed))
