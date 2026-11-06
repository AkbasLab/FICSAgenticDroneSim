"""Architecture A: one controller at the base assigns every task (AUV-13).

    controller = CentralController(brief, roster, config, health, heights)
    controller.receive(message, now)          # what reached the base: heartbeats, status updates, completions
    outs = controller.tick(now)               # what it sends: awards, its heartbeat, "complete"

AUV-13: "One controller sees all DELIVERED vehicle states and assigns all
tasks. Under degradation: state reports can be delayed or lost; commands can
be delayed or lost; disconnected drones use a fallback policy. This is the
nominal-efficiency baseline."

THE CONTROLLER IS A PARTICIPANT ON THE BUS, at the base (the network model
already names the base). It knows each drone only by what reached it: the
latest heartbeat or status update (position, battery, task, stage) and when
it arrived. It never reads a drone's belief, nor the truth.

EACH TICK:

* a drone holding a task that has been silent `health.unreachable_s` (10 s,
  Phase 9's lease) loses it: the task is open again, one version on --
  unless reassignment is switched off (the leases ablation);
* every open task goes to the best FREE drone -- heard within
  `health.suspected_s`, holding nothing, not on its way home or down -- by
  the same bid function and the same ranking the contract-net uses
  (`bid_for`, best bid first, each task once, each drone once);
* an award stands until the drone's own report says it has the task, and is
  sent again every second until then; a task is done when its drone says so
  (TASK_COMPLETE);
* when every task is done, it says so (MISSION_UPDATE "complete"), every
  second; and it sends its own heartbeat every second, so a drone can tell
  the controller is there.

Deterministic: drones and tasks in a fixed order, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.messages import BROADCAST, AgentMessage, MessageType
from ..core.scenario import MissionBrief
from .bids import AllocationConfig, Bidder, bid_for
from .contract_net import _key
from .health import HealthConfig
from .tasks import tasks_from_brief

BASE_ID = "base"
RESEND_S = 1.0
GONE_STAGES = ("going_home", "landing", "done")


@dataclass
class _Heard:
    at: float
    position: tuple[float, float, float]
    battery: float
    task: str | None
    stage: str | None


@dataclass
class _Task:
    task_id: str
    version: int = 1
    holder: str | None = None
    done: bool = False
    awarded_at: float | None = None
    sent_at: float | None = None
    value: float = 0.0


@dataclass
class Send:
    kind: MessageType
    to: tuple[str, ...]
    payload: dict[str, Any]
    ttl_s: float | None = None


@dataclass
class CentralController:
    brief: MissionBrief
    roster: tuple[str, ...]
    config: AllocationConfig
    health: HealthConfig
    heights: dict[str, float]
    start: float = 0.0
    reassign: bool = True                    # off: the leases ablation -- a silent holder keeps its task
    speed_mps: float = 5.0
    heard: dict[str, _Heard] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tasks = {t.task_id: _Task(t.task_id) for t in tasks_from_brief(self.brief)}
        self._specs = {t.task_id: t for t in tasks_from_brief(self.brief)}
        self.pads = {v.id: (v.start_x, v.start_y) for v in self.brief.vehicles}
        self._last_beat: float | None = None
        self._last_complete: float | None = None

    # ------------------------------------------------------------ hearing

    def receive(self, m: AgentMessage, now: float) -> None:
        p = m.payload
        if m.sender_id not in self.roster:
            return
        if m.message_type in (MessageType.HEARTBEAT, MessageType.STATUS_UPDATE):
            self.heard[m.sender_id] = _Heard(now, tuple(p["position"]), float(p["battery"]), p.get("task"),
                                            p.get("stage"))
        elif m.message_type is MessageType.TASK_COMPLETE:
            t = self.tasks.get(p["task_id"])
            if t is not None and t.holder == m.sender_id and not t.done:
                t.done = True
                self.log.append({"at": round(now - self.start, 3), "what": "done", "task": t.task_id,
                                 "by": m.sender_id})

    # -------------------------------------------------------------- deciding

    def _free(self, now: float) -> list[str]:
        held = {t.holder for t in self.tasks.values() if t.holder is not None and not t.done}
        return [d for d in self.roster if d in self.heard and d not in held
                and now - self.heard[d].at <= self.health.suspected_s
                and self.heard[d].stage not in GONE_STAGES]

    def tick(self, now: float) -> list[Send]:
        out: list[Send] = []
        for t in self.tasks.values():           # a silent holder loses its task, as a lease runs out
            if t.done or t.holder is None:
                continue
            h = self.heard.get(t.holder)
            if h is not None and h.stage in GONE_STAGES and h.at > (t.awarded_at or 0.0):
                # It gave the task up and is going home (its battery, its failures): open again, as a release.
                self.log.append({"at": round(now - self.start, 3), "what": "given back", "task": t.task_id,
                                 "by": t.holder})
                t.holder, t.version, t.awarded_at, t.sent_at = None, t.version + 1, None, None
                continue
            if not self.reassign:
                continue
            silent = now - (h.at if h else t.awarded_at)
            if silent >= self.health.unreachable_s:
                self.log.append({"at": round(now - self.start, 3), "what": "reassigned", "task": t.task_id,
                                 "from": t.holder, "silent_s": round(silent, 3)})
                t.holder, t.version, t.awarded_at, t.sent_at = None, t.version + 1, None, None
        entries = []
        time_left = self.brief.mission.deadline_s - (now - self.start)
        for d in self._free(now):
            h = self.heard[d]
            bidder = Bidder(d, h.position[0], h.position[1], h.battery, self.pads[d], time_left, self.heights[d],
                            self.speed_mps)
            for t in self.tasks.values():
                if t.done or t.holder is not None:
                    continue
                bid = bid_for(self._specs[t.task_id], bidder, self.brief, self.config.weights)
                if bid.eligible:
                    entries.append((_key(bid.value, d), t.task_id))
        given: set[str] = set()
        for (value, d), task_id in sorted(entries):
            t = self.tasks[task_id]
            if t.holder is not None or d in given:
                continue
            given.add(d)
            t.holder, t.awarded_at, t.sent_at = d, now, None
            t.value = value
            self.log.append({"at": round(now - self.start, 3), "what": "assigned", "task": task_id, "to": d,
                             "version": t.version, "value": value})
        for t in self.tasks.values():            # an award stands until the drone says it has it
            if t.done or t.holder is None:
                continue
            h = self.heard.get(t.holder)
            if h is not None and h.task == t.task_id:
                continue
            if t.sent_at is None or now - t.sent_at >= RESEND_S - 1e-9:
                t.sent_at = now
                out.append(Send(MessageType.TASK_AWARD, (t.holder,),
                                {"task_id": t.task_id, "version": t.version, "value": t.value}))
        if all(t.done for t in self.tasks.values()) and \
                (self._last_complete is None or now - self._last_complete >= RESEND_S - 1e-9):
            self._last_complete = now
            out.append(Send(MessageType.MISSION_UPDATE, BROADCAST, {"status": "complete"}))
        if self._last_beat is None or now - self._last_beat >= RESEND_S - 1e-9:
            self._last_beat = now
            b = self.brief.base
            out.append(Send(MessageType.HEARTBEAT, BROADCAST, {"position": [b.x, b.y, 0.0], "airborne": False,
                                                               "battery": 100.0, "task": None, "stage": "base"}))
        return out

    def as_json(self) -> dict[str, Any]:
        return {"controller": "central", "reassign": self.reassign,
                "tasks": {k: {"version": t.version, "holder": t.holder, "done": t.done} for k, t in self.tasks.items()},
                "log": self.log}
