"""The recovery policy: Phase 8's team policy with roles, a failure detector, and recovery (Phase 9).

    net = ContractNet("Drone2", tasks_from_brief(brief), allocation)
    policy = RecoveryPolicy(net, HealthConfig(), altitude_m=16.0)
    agent = DroneAgent(brief, sensors, executor, policy, comms=comms, coordinator=policy)
    agent.assign_team()

WHAT IT ADDS TO THE TEAM POLICY (AUV-09, 9.1-9.3), each from its own belief:

    a failure detector   every teammate's rung -- healthy, suspected, unreachable, failed,
                         recovered -- from how long since it last heard it (`coordination/health.py`),
                         shown in its belief; a teammate that reported its part done is not watched
    a role               SCOUT, RELAY or RESERVE (`coordination/roles.py`), announced (ROLE_CHANGE)
    RESERVE              with nothing open but teammates still at work, it holds where it is instead
                         of going home -- as long as it could still do one of their tasks -- and bids
                         for anything that comes back (Phase 8 went home)
    RELAY                free, with a teammate unreachable but not failed: it holds half way from the
                         base to where that teammate was last heard, until it is heard or declared failed
    REPRIORITIZING       an open task no drone could still finish before the deadline -- not it, not a
                         teammate that is not FAILED, from where each was last known -- is ABANDONED in
                         its book, and the team's objective is what is left: the drones go home with the
                         partial result rather than burn the time chasing it (9.3, step 6)

THE RECOVERY ITSELF is Phase 8's: a stopped drone's lease runs out, its task
returns to the pool one version on, and a free drone -- a reserve -- bids for
it, claims it, and becomes a scout again. Nothing is told to anyone; no
command is given after the team mission.

WHAT A TEAMMATE COULD DO is reckoned from what this drone knows: its last
reported position and the brief's pads (its home); its battery is not on the
record, so for teammates only the deadline counts -- an optimistic estimate,
so a task is abandoned only when even that says no.
"""

from __future__ import annotations

import math
from typing import Any

from ..control import navigation as nav
from ..control.routing import NoRouteError, route
from ..control.scripted import ZONE_CLEARANCE_M
from ..control.skills import DEFAULT_SPEED_MPS, FollowWaypointsCommand, HoldPositionCommand
from ..coordination.bids import Bidder, bid_for
from ..coordination.contract_net import ContractNet, Out
from ..coordination.health import FailureDetector, Health, HealthConfig
from ..coordination.roles import Role, RoleKeeper, relay_point
from ..coordination.tasks import MissionTask, TaskStatus
from ..core.events import Event, Trigger
from ..core.messages import AgentMessage, MessageType
from .belief_state import BeliefState
from .decision import Decision
from .rule_policy import DEFAULT_ALTITUDE_M
from .team_policy import HOLD_S, TeamPolicy

RELAY_ARRIVED_M = 2.0


class RecoveryPolicy(TeamPolicy):
    def __init__(self, net: ContractNet, health: HealthConfig, altitude_m: float = DEFAULT_ALTITUDE_M,
                 speed_mps: float = DEFAULT_SPEED_MPS) -> None:
        self._team_setup(net, altitude_m, speed_mps)
        self.health_config = health
        self.detector: FailureDetector | None = None
        self.roles: RoleKeeper | None = None
        self.heard_roles: list[dict[str, Any]] = []

    # ------------------------------------------------------ as a coordinator

    def coordinate(self, belief: BeliefState, messages: list[AgentMessage], now: float) -> list[Out]:
        me = belief.self_.vehicle_id
        if self.detector is None:
            self.detector = FailureDetector(me, [v.id for v in belief.brief.vehicles], self.health_config, now)
            self.roles = RoleKeeper(me, now)
        for m in messages:
            if m.message_type is MessageType.ROLE_CHANGE:
                self.heard_roles.append({"at": round(now, 3), "from": m.sender_id, **m.payload})
        done = [m for m, r in belief.team.members.items() if r is not None and r.report.status == "done"]
        self.detector.update(belief.links, now, finished=done)
        belief.teammate_health = self.detector.states()
        out = super().coordinate(belief, messages, now)
        for t in self.net.book.open():
            why = self._nobody_can(belief, t)
            if why:
                self.net.abandon(t.task_id, now, why)
        for n in self.net.take_news():
            self._news.append(Event(Trigger.MESSAGE, now, {"allocation": n["what"],
                                                           **{k: v for k, v in n.items() if k != "what"}}))
        change = self.roles.update(now, self.net.holding, self.detector.in_state(Health.UNREACHABLE))
        if change is not None:
            out.append(Out(MessageType.ROLE_CHANGE, {"role": change.after.value, "previous": change.before.value,
                                                     "why": change.why}))
            self._news.append(Event(Trigger.MESSAGE, now, {"allocation": "role", "task": change.after.value}))
        return out

    def _nobody_can(self, belief: BeliefState, task: MissionTask) -> str | None:
        """Why no drone could still finish `task` before the deadline; None if one could."""
        me = belief.self_
        pads = {v.id: (v.start_x, v.start_y) for v in belief.brief.vehicles}
        mine = bid_for(task, Bidder(me.vehicle_id, me.x, me.y, me.battery, me.home, belief.time_left,
                                    self.altitude_m, self.speed_mps), belief.brief, self.net.config.weights)
        if mine.eligible:
            return None
        for mate, record in belief.team.members.items():
            if (self.detector.state(mate) is Health.FAILED or mate in self.detector.finished or record is None
                    or record.report.position is None):
                continue
            x, y = record.report.position[0], record.report.position[1]
            # Its battery is not on the record: only the deadline counts for a teammate.
            theirs = bid_for(task, Bidder(mate, x, y, 100.0, pads[mate], belief.time_left, self.altitude_m,
                                          self.speed_mps), belief.brief, self.net.config.weights)
            if theirs.eligible:
                return None
        return f"no drone could still do it: it ({mine.why_not}), nor any teammate not failed, by the deadline"

    # ------------------------------------------------------------ decide

    def _go(self, belief: BeliefState, reason: str) -> Decision:
        if self.net.holding is None and self.roles is not None and self.roles.role is Role.RELAY:
            return self._relay(belief, reason)
        return super()._go(belief, reason)

    def _nothing_open(self, belief: BeliefState, reason: str) -> Decision:
        """Nothing open for it. A reserve stays while teammates still work and it could still help them."""
        why = self._still_useful(belief)
        if why is None:
            return super()._nothing_open(belief, reason)
        self.waiting = True
        return Decision.start(HoldPositionCommand(duration_s=HOLD_S), "stand by as a reserve", f"{reason}; {why}")

    def _still_useful(self, belief: BeliefState) -> str | None:
        """Why it should stay aloft as a reserve; None if it should go home."""
        me = belief.self_
        held = [t for t in self.net.book.tasks() if t.status is TaskStatus.CLAIMED and t.assigned_agent != me.vehicle_id]
        able = [t.task_id for t in held
                if bid_for(t, Bidder(me.vehicle_id, me.x, me.y, me.battery, me.home, belief.time_left,
                                     self.altitude_m, self.speed_mps), belief.brief,
                           self.net.config.weights).eligible]
        if not able:
            return None
        return f"teammates still at {', '.join(sorted(t.task_id for t in held))}: a reserve for any that comes back"

    def _relay(self, belief: BeliefState, reason: str) -> Decision:
        mates = self.detector.in_state(Health.UNREACHABLE)
        self.waiting = True
        record = belief.team.members.get(mates[0]) if mates else None
        if record is None or record.report.position is None:
            return Decision.start(HoldPositionCommand(duration_s=HOLD_S), "relay", f"{reason}; nowhere known to bridge to")
        brief = belief.brief
        point = relay_point((brief.base.x, brief.base.y), (record.report.position[0], record.report.position[1]))
        here = (belief.self_.x, belief.self_.y)
        if math.dist(here, point) <= RELAY_ARRIVED_M:
            return Decision.start(HoldPositionCommand(duration_s=HOLD_S), f"relay toward {mates[0]}",
                                  f"{reason}; holding at the relay point")
        try:
            leg = route(here, point, [z.polygon for z in brief.restricted_zones], ZONE_CLEARANCE_M)
        except NoRouteError:
            return Decision.start(HoldPositionCommand(duration_s=HOLD_S), f"relay toward {mates[0]}",
                                  f"{reason}; no route to the relay point")
        return Decision.start(FollowWaypointsCommand(tuple(nav.Waypoint(x, y, self.altitude_m) for x, y in leg[1:]),
                                                     speed_mps=self.speed_mps),
                              f"relay toward {mates[0]}", f"{reason}; to the relay point {point[0]:.1f}, {point[1]:.1f}")

    def as_json(self) -> dict[str, Any]:
        row = super().as_json()
        row.update(health=None if self.detector is None else self.detector.as_json(),
                   roles=None if self.roles is None else self.roles.as_json(), heard_roles=list(self.heard_roles))
        return row
