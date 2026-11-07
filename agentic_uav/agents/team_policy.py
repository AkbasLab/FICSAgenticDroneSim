"""The team policy: the rule policy, taking its work from the contract-net instead of being told it (Phase 8).

    net = ContractNet("Drone2", tasks_from_brief(brief), config)
    policy = TeamPolicy(net, altitude_m=16.0)
    agent = DroneAgent(brief, sensors, executor, policy, comms=comms, coordinator=policy)
    agent.assign_team()                      # the team mission; no sector

WHAT IT IS TOLD: the team mission, and nothing more. Which sector it flies is
decided by the bids and claims it exchanges (`coordination/contract_net.py`).
It is told nothing by anyone else, and reads nobody's book but its own.

HOW IT FLIES is Phase 5's rule policy, unchanged: once it holds a task -- "search
S2" -- it routes there, searches the lanes it bid on, and comes home, with the
same battery and deadline checks, the same retries and the same give-ups. What
is new is only where the sector comes from, and what happens around it:

    the team mission   take off at once: every sector is a flight away, and the
                       claims settle in the first second or two of the climb
    airborne           go to the task it holds; with none yet, hold and wait;
                       with nothing left for it, go home
    a task claimed     after take-off, go to it
    a task lost        (another claim beat its own) drop it; take the next, or wait
    searched           complete the task, so all hear it; with nothing left, go
                       home; otherwise wait to bid for what is left
    a shortfall, or    give the task back (release), so a teammate may take it,
    a give-up          and go home -- Phase 5's reaction, now with a team to tell

The flight decisions are made from the protocol's STATE -- what the drone holds
now -- not from the order its news arrived in, so a tick that brings both "lost
S2" and "claimed S1" is one decision, to S1.

AS A COORDINATOR (for `DroneAgent`): `coordinate` takes the tick's task
messages to the contract-net and ticks it, bidding from the drone's own
belief; `drain` gives what the policy itself said while deciding (a
completion, a release); `news` gives the net's news as MESSAGE events.
"""

from __future__ import annotations

from typing import Any

from ..control.routing import length
from ..control.skills import DEFAULT_SPEED_MPS, HoldPositionCommand, TakeOffCommand
from ..coordination.keepout import KeepOutConfig
from ..coordination.bids import Bid, Bidder, bid_for
from ..coordination.contract_net import ContractNet, Out
from ..coordination.tasks import MissionTask
from ..core.events import Event, Trigger
from ..core.messages import AgentMessage
from .belief_state import BeliefState
from .decision import Decision
from .rule_policy import DEFAULT_ALTITUDE_M, RulePolicy, Stage, remaining_along

HOLD_S = 5.0                 # a wait for a task is held in slices this long


class TeamPolicy(RulePolicy):
    def __init__(self, net: ContractNet, altitude_m: float = DEFAULT_ALTITUDE_M,
                 speed_mps: float = DEFAULT_SPEED_MPS, keep_out: KeepOutConfig | None = None) -> None:
        self._team_setup(net, altitude_m, speed_mps)
        self.keep_out = keep_out

    def _team_setup(self, net: ContractNet, altitude_m: float, speed_mps: float) -> None:
        # Its own method, so a policy built on this one (Phase 9's) sets up the same
        # state without `super().__init__`, a dunder the agents' boundary refuses.
        self._setup(altitude_m, speed_mps)
        self.net = net
        self.task_id: str | None = None              # the task it is flying, as the policy knows it
        self.waiting = False
        self.completed: list[str] = []
        self._outbox: list[Out] = []
        self._news: list[Event] = []
        self._idle_said = False
        # Phase 12: tasks its agent (an LLM's `decline_task`) will not bid for. Empty: exactly as before.
        self.declined: set[str] = set()

    # ------------------------------------------------------ as a coordinator

    def coordinate(self, belief: BeliefState, messages: list[AgentMessage], now: float) -> list[Out]:
        out: list[Out] = []
        for m in messages:
            out += self.net.receive(m, now)
        me = belief.self_
        bidder = Bidder(me.vehicle_id, me.x, me.y, me.battery, me.home, belief.time_left, self.altitude_m,
                        self.speed_mps)
        out += self.net.tick(now, lambda task: self._bid(task, bidder, belief), self._progress(belief))
        for n in self.net.take_news():
            self._news.append(Event(Trigger.MESSAGE, now, {"allocation": n["what"],
                                                           **{k: v for k, v in n.items() if k != "what"}}))
            if n["what"] == "claimed":
                self._idle_said = False
        if self.net.idle and not self._idle_said:
            self._idle_said = True
            self._news.append(Event(Trigger.MESSAGE, now, {"allocation": "nothing left"}))
        return out

    def _bid(self, task: MissionTask, bidder: Bidder, belief: BeliefState) -> Bid:
        if task.task_id in self.declined:
            return Bid(task.task_id, task.version, bidder.drone, None, {}, {}, "declined by its agent")
        return bid_for(task, bidder, belief.brief, self.net.config.weights)

    def drain(self) -> list[Out]:
        out, self._outbox = self._outbox, []
        return out

    def news(self) -> list[Event]:
        news, self._news = self._news, []
        return news

    def _progress(self, belief: BeliefState) -> float:
        if self.stage is not Stage.SEARCHING or not self.lanes:
            return 0.0
        total = length(self.lanes)
        return 0.0 if total <= 0 else max(0.0, min(1.0, 1.0 - remaining_along(self.lanes, (belief.self_.x,
                                                                                          belief.self_.y)) / total))

    # ------------------------------------------------------------ decide

    def decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        decision = super().decide(belief, events)
        if self.waiting:
            belief.mission.progress["stage"] = "waiting"
        belief.mission.progress["task"] = self.task_id
        return decision

    def _decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        by = {e.trigger: e for e in events}
        assigned = by.get(Trigger.TASK_ASSIGNED)
        if assigned is not None and not assigned.detail.get("team"):
            return super()._decide(belief, events)              # a plain task, as in Phase 5
        if assigned is not None:
            return self._join(belief)
        if Trigger.GUARD_REJECTED in by:
            return self._giving_back(belief, lambda: self._refused(belief, by[Trigger.GUARD_REJECTED]))
        if Trigger.SKILL_SUCCEEDED in by:
            return self._done_skill(belief)
        if Trigger.SKILL_FAILED in by:
            return self._giving_back(belief, lambda: self._failed(belief, by[Trigger.SKILL_FAILED]))
        if Trigger.SKILL_ABORTED in by:
            return self._giving_back(belief, lambda: self._home(belief, "a skill was stopped: going home"))
        if by.keys() & {Trigger.BATTERY_THRESHOLD, Trigger.PERIODIC} and self.stage in (Stage.TO_SECTOR, Stage.SEARCHING) \
                and not self.waiting and self.task_id is not None:
            short = self._shortfall(belief)
            if short:
                self.gave_up = short
                return self._giving_back(belief, lambda: self._home(belief, short))
        if Trigger.MESSAGE in by:
            return self._follow(belief, [e for e in events if e.trigger is Trigger.MESSAGE])
        return Decision.carry_on(belief.mission.objective, "nothing calls for a change")

    def _join(self, belief: BeliefState) -> Decision:
        if self.net.idle:
            self.net.stop()
            self.stage = Stage.DONE
            return Decision.finish(reason="the team mission has nothing for it")
        self._take(belief)
        self.stage = Stage.TAKING_OFF
        return Decision.start(TakeOffCommand(altitude_m=self.altitude_m, speed_mps=self.speed_mps),
                              "take off for the team mission", "team mission: the work is divided by bids")

    def _take(self, belief: BeliefState) -> bool:
        """Make the task the net says it holds its work. True if that changed it."""
        holding = self.net.holding
        if holding == self.task_id:
            return False
        self.task_id = holding
        belief.self_.current_task = holding
        if holding is None:
            self.sector = None
            self.lanes = []
            return True
        sectors = {s.id: s for s in belief.brief.sectors}
        self._prepare(belief, sectors[holding.split()[1]])
        return True

    def _go(self, belief: BeliefState, reason: str) -> Decision:
        """Airborne: to its task; or hold for one; or home with nothing left."""
        self._take(belief)
        if self.task_id is not None:
            self.waiting = False
            self.stage = Stage.TO_SECTOR              # costed from here to its lanes, as before any search
            short = self._shortfall(belief)
            if short:
                self.gave_up = short
                return self._giving_back(belief, lambda: self._home(belief, short))
            return self._to_sector(belief, reason)
        if self.net.idle:
            return self._nothing_open(belief, f"{reason}; nothing left for it")
        self.waiting = True
        return Decision.start(HoldPositionCommand(duration_s=HOLD_S), "wait for a task", f"{reason}; no task yet")

    def _done_skill(self, belief: BeliefState) -> Decision:
        self.retries = 0
        belief.drop_assumption("retry")
        if self.waiting:
            return self._go(belief, "held")
        if self.stage is Stage.TAKING_OFF:
            return self._go(belief, "airborne")
        if self.stage is Stage.TO_SECTOR:
            return self._search(belief, f"at {self.sector.id}")
        if self.stage is Stage.SEARCHING:
            belief.local_map.searched_regions.append(self.sector.region)
            done = self.task_id
            self._outbox += self.net.complete(belief.self_.updated_at)
            self.completed.append(done)
            self.task_id = None
            belief.self_.current_task = None
            if not self.net.book.open():
                return self._nothing_open(belief, f"{self.sector.id} searched; nothing left")
            self.waiting = True
            return Decision.start(HoldPositionCommand(duration_s=HOLD_S), "wait for a task",
                                  f"{self.sector.id} searched; bidding for what is left")
        return super()._succeeded(belief)

    def _nothing_open(self, belief: BeliefState, reason: str) -> Decision:
        """Nothing open for it: Phase 8 goes home. (Phase 9's reserve may stay.)"""
        self.net.stop()
        self.waiting = False
        return self._home(belief, reason)

    def _follow(self, belief: BeliefState, news: list[Event]) -> Decision:
        """Act on the net's state after its news: one decision, whatever order the news came in."""
        said = "; ".join(f"{e.detail['allocation']} {e.detail.get('task', '')}".strip() for e in news)
        if self.waiting:
            return self._go(belief, said)
        if self.stage is Stage.TAKING_OFF or not belief.self_.airborne:
            self._take(belief)
            return Decision.carry_on(belief.mission.objective, f"{said}; still taking off")
        if self.stage in (Stage.GOING_HOME, Stage.LANDING, Stage.DONE):
            return Decision.carry_on(belief.mission.objective, f"{said}; already going home")
        if self.net.holding != self.task_id:
            return self._go(belief, said)
        return Decision.carry_on(belief.mission.objective, said)

    def _giving_back(self, belief: BeliefState, react) -> Decision:
        """Phase 5's reaction; and if that sends it home with a task in hand, give the task back."""
        decision = react()
        if self.stage in (Stage.GOING_HOME, Stage.LANDING, Stage.DONE):
            # Going home is not waiting for a task: left set (a "stand by" before), the landing's success took it
            # back to "wait for a task", a hold on the ground that fails, a landing retried -- every half second
            # to the deadline (Phase 17 pilot run 0027, 2026-11-06).
            self.waiting = False
        if self.stage in (Stage.GOING_HOME, Stage.LANDING, Stage.DONE) and self.net.holding is not None:
            self._outbox += self.net.release(belief.self_.updated_at, self.gave_up or "going home")
            self.task_id = None
        elif self.stage in (Stage.GOING_HOME, Stage.LANDING, Stage.DONE):
            self.net.stop()
        return decision

    def as_json(self) -> dict[str, Any]:
        return {"task": self.task_id, "completed": list(self.completed), "net": self.net.as_json()}
