"""Architecture B: independent persistent agents -- a task each at the start, never negotiated (AUV-13).

    division = initial_division(brief, config, heights)    # who searches what, once, before take-off
    policy = IndependentPolicy(division[drone], altitude_m=12.0)
    agent = DroneAgent(..., policy, comms=..., coordinator=policy); agent.assign_team()

AUV-13: "Each drone gets a task initially but never negotiates or reassigns.
Agents replan locally but do not coordinate. Isolates the value of
communication and coordination."

THE START IS C's OWN. The division is made once, from the brief and the pads,
by the same bid function (`coordination.bids.bid_for`) and the same rule
the contract-net uses to give each task to its best free bidder
(`ContractNet._choice`): every drone at its pad, battery full, the whole
deadline left. So B begins exactly where C's first round of bidding ends,
and differs from C only by never coordinating after it.

THEN EACH FLIES ALONE. Each drone is Phase 5's persistent agent with its one
task (`RulePolicy`): take off, reach the sector, search it, go home, land --
replanning locally on its own failures, its own battery. It still talks
(heartbeats and status updates, so the guardian and the keep-out know where
teammates are), but no task message is ever sent: a stopped drone's sector
stays unsearched.

ITS TASK IS ITS OWN. The share of the division is the policy's, given before
take-off like Phase 4's preflight plan; told the team mission, the drone
takes it up itself. So the flight code gives B, like C and A, the team
mission and never a task (Phase 9's "no central controller", which
`test_recovery_exit` holds the harness to). In the agent the policy sits in
the coordinator's place, where it only ever answers with that task: it
reads no task message, sends none and has no news.
"""

from __future__ import annotations

from typing import Any

from ..coordination.bids import AllocationConfig, Bidder, bid_for
from ..coordination.contract_net import _key
from ..coordination.tasks import tasks_from_brief
from ..coordination.contract_net import Out
from ..core.events import Event, Trigger
from ..core.messages import AgentMessage
from ..core.scenario import MissionBrief
from .belief_state import BeliefState
from .decision import Decision
from .rule_policy import DEFAULT_ALTITUDE_M, RulePolicy, Stage
from ..control.skills import DEFAULT_SPEED_MPS


def initial_division(brief: MissionBrief, config: AllocationConfig, heights: dict[str, float],
                     speed_mps: float = DEFAULT_SPEED_MPS) -> dict[str, str]:
    """Each drone's task: every task to its best free bidder, best bid first, from the pads (C's first round)."""
    entries = []
    for v in brief.vehicles:
        bidder = Bidder(v.id, v.start_x, v.start_y, brief.battery.capacity, (v.start_x, v.start_y),
                        brief.mission.deadline_s, heights[v.id], speed_mps)
        for t in tasks_from_brief(brief):
            bid = bid_for(t, bidder, brief, config.weights)
            if bid.eligible:
                entries.append((_key(bid.value, v.id), t.task_id))
    given_tasks: set[str] = set()
    out: dict[str, str] = {}
    for (value, who), task_id in sorted(entries):
        if task_id in given_tasks or who in out:
            continue
        given_tasks.add(task_id)
        out[who] = task_id
    return out


class IndependentPolicy(RulePolicy):
    """Phase 5's rule policy, with a record of what it searched -- architecture B's agent."""

    def __init__(self, task: str | None, altitude_m: float = DEFAULT_ALTITUDE_M,
                 speed_mps: float = DEFAULT_SPEED_MPS, keep_out: Any = None) -> None:
        self._setup(altitude_m, speed_mps)
        self.task = task
        self.keep_out = keep_out
        self.completed: list[str] = []

    # in the coordinator's place: no task message read, none sent, no news
    def coordinate(self, belief: BeliefState, messages: list[AgentMessage], now: float) -> list[Out]:
        return []

    def drain(self) -> list[Out]:
        return []

    def news(self) -> list[Event]:
        return []

    def _decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        assigned = next((e for e in events if e.trigger is Trigger.TASK_ASSIGNED), None)
        if assigned is not None and assigned.detail.get("team"):
            belief.self_.current_task = self.task
            if self.task is None:
                self.stage = Stage.DONE
                return Decision.finish(reason="no task in the initial division")
            return self._accept(belief, self.task)
        return super()._decide(belief, events)

    def _succeeded(self, belief: BeliefState) -> Decision:
        if self.stage is Stage.SEARCHING and self.sector is not None:
            self.completed.append(f"search {self.sector.id}")
        return super()._succeeded(belief)

    def as_json(self) -> dict[str, Any]:
        return {"policy": "independent", "stage": self.stage.value,
                "task": None if self.sector is None else f"search {self.sector.id}", "completed": list(self.completed),
                "gave_up": self.gave_up, "retries": self.retries}
