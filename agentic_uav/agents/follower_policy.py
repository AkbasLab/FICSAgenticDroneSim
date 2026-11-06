"""Architecture A's drone: it does what the base controller assigns it (AUV-13).

    policy = FollowerPolicy(altitude_m=12.0)
    agent = DroneAgent(..., policy, comms=..., coordinator=policy); agent.assign_team()

The drone of a centralized fleet. Told the team mission, it takes off and
waits; the base controller (`coordination.central`) awards it a task, and it
flies it -- to the sector, the search -- with Phase 5's own primitives
(`RulePolicy`), then reports it done (TASK_COMPLETE) and waits for the next.
It never bids, claims or reassigns: every task it flies came from the base.

What it hears from the base: an award addressed to it; "complete" (the
mission is done: it goes home); and the base's heartbeat, by which it knows
the base is there (its own link record, `belief.links`).

THE DISCONNECTED FALLBACK (AUV-13: "disconnected drones use a fallback
policy"): a drone that has heard nothing from the base for `DISCONNECT_S`
finishes the task in hand, if any, and then goes home rather than waiting
for an award that may never come. Its own battery and failures are its own,
as in Phase 5: short of battery it gives the task up and goes home (its
status says so, and the base opens the task again).
"""

from __future__ import annotations

from typing import Any

from ..control.skills import DEFAULT_SPEED_MPS, HoldPositionCommand, TakeOffCommand
from ..coordination.contract_net import Out
from ..core.events import Event, Trigger
from ..core.messages import AgentMessage, MessageType
from .belief_state import BeliefState
from .decision import Decision
from .rule_policy import DEFAULT_ALTITUDE_M, RulePolicy, Stage

BASE_ID = "base"
DISCONNECT_S = 10.0          # Phase 9's "unreachable": this long without the base, a drone stops waiting for it
HOLD_S = 5.0


class FollowerPolicy(RulePolicy):
    def __init__(self, altitude_m: float = DEFAULT_ALTITUDE_M, speed_mps: float = DEFAULT_SPEED_MPS,
                 keep_out: Any = None) -> None:
        self._setup(altitude_m, speed_mps)
        self.keep_out = keep_out
        self.task_id: str | None = None
        self.version: int | None = None
        self.pending: tuple[str, int] | None = None
        self.complete = False
        self.waiting = False
        self.disconnected = False
        self.completed: list[str] = []
        self._outbox: list[Out] = []
        self._news: list[Event] = []
        self._joined_at: float | None = None

    # ------------------------------------------------------ as a coordinator

    def coordinate(self, belief: BeliefState, messages: list[AgentMessage], now: float) -> list[Out]:
        me = belief.self_.vehicle_id
        for m in messages:
            if m.sender_id != BASE_ID:
                continue
            p = m.payload
            if m.message_type is MessageType.TASK_AWARD and m.is_for(me):
                award = (p["task_id"], p["version"])
                if award != (self.task_id, self.version) and award != self.pending:
                    self.pending = award
                    self._news.append(Event(Trigger.MESSAGE, now, {"allocation": "assigned", "task": p["task_id"]}))
            elif m.message_type is MessageType.MISSION_UPDATE and p.get("status") == "complete" and not self.complete:
                self.complete = True
                self._news.append(Event(Trigger.MESSAGE, now, {"allocation": "complete"}))
        return []

    def drain(self) -> list[Out]:
        out, self._outbox = self._outbox, []
        return out

    def news(self) -> list[Event]:
        news, self._news = self._news, []
        return news

    # ---------------------------------------------------------------- decide

    def _decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        by = {e.trigger: e for e in events}
        if Trigger.TASK_ASSIGNED in by:
            self._joined_at = belief.self_.updated_at
            self.stage = Stage.TAKING_OFF
            return Decision.start(TakeOffCommand(altitude_m=self.altitude_m, speed_mps=self.speed_mps),
                                  "take off for the fleet", "the team mission: the base assigns the work")
        if Trigger.GUARD_REJECTED in by:
            return self._refused(belief, by[Trigger.GUARD_REJECTED])
        if Trigger.SKILL_FAILED in by:
            return self._failed(belief, by[Trigger.SKILL_FAILED])
        if Trigger.SKILL_ABORTED in by:
            return self._home(belief, "a skill was stopped: going home")
        if Trigger.SKILL_SUCCEEDED in by:
            self.retries = 0
            if self.waiting or self.stage is Stage.TAKING_OFF:
                return self._next(belief, "airborne" if self.stage is Stage.TAKING_OFF else "held")
            if self.stage is Stage.TO_SECTOR:
                return self._search(belief, f"at {self.sector.id}")
            if self.stage is Stage.SEARCHING:
                done = self.task_id
                belief.local_map.searched_regions.append(self.sector.region)
                self._outbox.append(Out(MessageType.TASK_COMPLETE, {"task_id": done, "version": self.version}))
                self.completed.append(done)
                self.task_id, self.version = None, None
                belief.self_.current_task = None
                return self._next(belief, f"{done} searched")
            return self._succeeded(belief)
        if by.keys() & {Trigger.BATTERY_THRESHOLD, Trigger.PERIODIC} and self.stage in (Stage.TO_SECTOR,
                                                                                          Stage.SEARCHING):
            short = self._shortfall(belief)
            if short:
                self.gave_up = short
                self.task_id, self.version = None, None
                belief.self_.current_task = None
                return self._home(belief, short)
        if self.waiting and (by.keys() & {Trigger.MESSAGE, Trigger.PERIODIC}):
            return self._next(belief, "news" if Trigger.MESSAGE in by else "still waiting")
        return Decision.carry_on(belief.mission.objective, "nothing calls for a change")

    def _base_silent_s(self, belief: BeliefState) -> float:
        link = belief.links.get(BASE_ID)
        heard = link["last_heard"] if link and link.get("last_heard") is not None else self._joined_at
        return belief.self_.updated_at - (heard if heard is not None else belief.self_.updated_at)

    def _next(self, belief: BeliefState, reason: str) -> Decision:
        """Airborne and free: the task the base awarded; or home if the mission is done or the base is gone; or wait."""
        if self.pending is not None:
            self.task_id, self.version = self.pending
            self.pending = None
            self.waiting = False
            belief.self_.current_task = self.task_id
            sectors = {s.id: s for s in belief.brief.sectors}
            self._prepare(belief, sectors[self.task_id.split()[1]])
            self.stage = Stage.TO_SECTOR
            return self._to_sector(belief, f"{reason}; the base assigned {self.task_id}")
        if self.complete:
            self.waiting = False
            return self._home(belief, f"{reason}; the base says the mission is complete")
        silent = self._base_silent_s(belief)
        if silent >= DISCONNECT_S:
            self.waiting = False
            self.disconnected = True
            return self._home(belief, f"{reason}; nothing from the base for {silent:.1f} s: the disconnected fallback")
        self.waiting = True
        return Decision.start(HoldPositionCommand(duration_s=HOLD_S), "wait for a task", f"{reason}; no task yet")

    def as_json(self) -> dict[str, Any]:
        return {"policy": "follower", "stage": self.stage.value, "task": self.task_id, "completed": list(self.completed),
                "disconnected": self.disconnected, "complete_heard": self.complete, "gave_up": self.gave_up}
