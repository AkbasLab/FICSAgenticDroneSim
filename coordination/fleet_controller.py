"""Architecture A: one controller assigns all work (Phase 13).

The nominal-efficiency baseline. A single controller collects state reports from
every drone and hands out every task. With perfect communication this should be
the *best* architecture in the study: it sees the whole fleet at once and can
solve the assignment globally, where the decentralized agents only ever see
their own belief and whatever their neighbours managed to tell them.

The point of the comparison is what happens when that assumption breaks.

**It uses the same cost model as the decentralized agents.** Assignment calls
`compute_bid`, the identical function Architecture C bids with. That is
deliberate and load-bearing: if the controller optimised differently, a measured
difference between A and C would be a difference between two cost functions
rather than between centralized and decentralized control, and the experiment
would answer the wrong question. The only thing that differs is *whose state the
cost is computed from* - the controller's centrally-held (and possibly stale)
picture, versus each agent's own first-hand belief.

**Everything crosses the same degraded link.** State reports in and commands out
are ordinary messages on the ordinary `MessageBus`, so the Phase 10 network
model delays and drops them exactly as it does peer traffic. A controller that
received telemetry by magic would make this a study of planning quality, not of
communication.

**Disconnected drones fall back.** A drone that has not heard from the
controller within `fallback_after_s` stops waiting and assigns itself the
nearest unsearched sector. Without that rule Architecture A does not degrade
under partition - it simply stops, and the comparison becomes uninteresting for
the wrong reason. The fallback is deliberately the weakest sensible one: greedy,
local, and with no attempt to avoid duplicating a teammate's work, because
coordinating the fallback would smuggle decentralization into the centralized
baseline.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..agents.objectives import AgentEvent, Objective
from ..control import skills as sk
from ..core.models import Position3D
from .bidding import BidWeights, compute_bid
from .protocols import MessageType
from .tasks import MissionTask, TaskBoard, TaskStatus, TaskType

#: The controller's identity on the bus. It is a participant like any drone.
CONTROLLER_ID = "FleetController"

#: How long a drone waits without contact before assigning itself work.
DEFAULT_FALLBACK_AFTER_S = 45.0

#: How often the controller tells the fleet it is still there. Without this a
#: drone hears from the controller only when it is given work, so under perfect
#: communication it still concludes it is disconnected once the assignment
#: window passes - and self-assigns a sector it is already flying.
DEFAULT_CONTROLLER_HEARTBEAT_S = 15.0

#: How long a drone holds while awaiting orders. Waiting is not free: it burns
#: clock and battery, which is a genuine cost of centralized control and is one
#: of the things the A-vs-C comparison is meant to expose.
WAIT_TICK_S = 8.0

#: How long the controller waits before it treats a silent drone as lost and
#: reassigns its task.
#:
#: This obeys the same rule as Phase 9's task lease: it **must exceed the
#: longest skill**. A drone reports state between skills, so during a ~70 s
#: sweep it is legitimately silent. At 90 s the controller declared healthy
#: drones lost mid-sweep and handed their sectors to someone else, duplicating
#: the work even under perfect communication - which made Architecture A look
#: bad for a reason that had nothing to do with centralization. Set from the
#: same constant the decentralized lease uses, so A and C tolerate silence
#: equally and the comparison stays about architecture.
DEFAULT_ASSUME_LOST_AFTER_S = 150.0


@dataclass
class FleetRecord:
    """The controller's view of one drone. Every field may be stale."""
    vehicle_id: str
    last_heard_s: float = -1e9
    position: Optional[Position3D] = None
    battery_frac: float = 1.0
    current_task: Optional[str] = None
    searched: List[str] = field(default_factory=list)
    landed: bool = False

    def silence_s(self, now):
        return now - self.last_heard_s

    def known(self):
        return self.last_heard_s > -1e8


class _ControllerBelief:
    """Just enough of the belief interface for `compute_bid` to run.

    `compute_bid` reads position, battery, workload and communication state. The
    controller holds those for *other* drones, so this adapts its fleet record
    into the shape the shared cost function expects. Writing a second cost
    function for the controller would have been easier and would have quietly
    invalidated the A-versus-C comparison.
    """

    def __init__(self, record: FleetRecord, now: float, home: Position3D):
        self.vehicle_id = record.vehicle_id
        self.position = record.position or home
        self.home = home
        self.now = now
        self.battery_frac = record.battery_frac
        self.held_task_ids = [record.current_task] if record.current_task else []

        class _Comms:
            base_reachable = True
            recent_loss_rate = 0.0
        self.communication = _Comms()


class FleetController:
    """The central assigner. One per mission, not one per drone."""

    def __init__(self, link, scenario, tasks=None, weights=None,
                 assume_lost_after_s=DEFAULT_ASSUME_LOST_AFTER_S,
                 capabilities=None, log=None,
                 heartbeat_s=DEFAULT_CONTROLLER_HEARTBEAT_S):
        self.link = link
        self.scenario = scenario
        self.board = TaskBoard(list(tasks or []))
        self.weights = weights or BidWeights()
        self.assume_lost_after_s = assume_lost_after_s
        self.heartbeat_s = heartbeat_s
        self._last_heartbeat_s = -1e9
        self._announced_complete = False
        self.capabilities = set(capabilities or {"search", "relay", "inspect"})
        self.fleet: Dict[str, FleetRecord] = {
            v.vehicle_id: FleetRecord(v.vehicle_id) for v in scenario.vehicles}
        self.home = scenario.base.position
        # MissionSpec carries no id; agents stamp messages with whatever their
        # belief was briefed with, which is "" for this scenario format.
        self.mission_id = getattr(scenario.mission, "mission_id", "")
        self.log: List[str] = [] if log is None else log
        self.assignments_sent = 0
        self.reassignments = 0
        self.steps = 0
        self._released = set()

    # --- the controller's own loop ---

    def tick(self, now: float):
        """Receive whatever arrived, then reassign and command. Returns True if
        the controller changed anything."""
        self.steps += 1
        self._receive(now)
        self._heartbeat(now)
        changed = self._reclaim_from_lost(now)
        changed = self._assign(now) or changed
        return self._announce_completion(now) or changed

    def _heartbeat(self, now):
        """Periodic "still here". Subject to loss like every other message, so a
        partitioned drone still stops hearing it and still falls back."""
        if now - self._last_heartbeat_s < self.heartbeat_s:
            return
        self._last_heartbeat_s = now
        self.link.send(MessageType.HEARTBEAT, payload={"status": "ok"},
                       now=now, mission_id=self.mission_id)

    def _announce_completion(self, now):
        """Tell the fleet when there is nothing left, so drones come home
        instead of waiting out the fallback timer and self-assigning."""
        if self._announced_complete:
            return False
        if any(t.status is not TaskStatus.COMPLETE for t in self.board.all()):
            return False
        self._announced_complete = True
        self._log(now, "all tasks complete; releasing the fleet")
        self.link.send(MessageType.MISSION_UPDATE,
                       payload={"status": "complete"}, now=now,
                       mission_id=self.mission_id)
        return True

    def _receive(self, now):
        for m in self.link.receive_available(now=now):
            rec = self.fleet.get(m.sender_id)
            if rec is None:
                continue
            rec.last_heard_s = max(rec.last_heard_s, m.timestamp)
            p = m.payload or {}
            pos = p.get("position")
            if pos:
                rec.position = Position3D(float(pos[0]), float(pos[1]),
                                          float(pos[2]) if len(pos) > 2 else 0.0)
            if "battery_frac" in p:
                rec.battery_frac = float(p["battery_frac"])
            if p.get("searched"):
                rec.searched = list(p["searched"])
            if m.message_type is MessageType.TASK_COMPLETE:
                tid = p.get("task_id")
                t = self.board.get(tid) if tid else None
                if t is not None and t.status is not TaskStatus.COMPLETE:
                    t.status = TaskStatus.COMPLETE
                    t.assigned_agent = m.sender_id
                    self._log(now, f"{m.sender_id} reported {tid} complete")
                rec.current_task = None
            elif m.message_type is MessageType.TASK_ACCEPT:
                rec.current_task = p.get("task_id") or rec.current_task

    def _reclaim_from_lost(self, now):
        """Take work back from drones we have not heard from in too long.

        The controller cannot distinguish a crashed drone from one whose reports
        are being dropped - which is the whole difficulty of centralized control
        under degradation. It has to guess, and it is sometimes wrong: a drone
        that is still flying its sector will keep flying it, and the sector gets
        assigned twice. That duplication is a real cost of this architecture and
        is left in rather than papered over.
        """
        changed = False
        for rec in self.fleet.values():
            if not rec.known() or rec.silence_s(now) <= self.assume_lost_after_s:
                continue
            for t in self.board.all():
                if t.assigned_agent == rec.vehicle_id and t.status not in (
                        TaskStatus.COMPLETE, TaskStatus.FAILED):
                    t.status = TaskStatus.UNASSIGNED
                    t.assigned_agent = None
                    self.reassignments += 1
                    changed = True
                    self._log(now, f"reclaimed {t.task_id}: no contact with "
                                   f"{rec.vehicle_id} for "
                                   f"{rec.silence_s(now):.0f}s")
        return changed

    def _assign(self, now):
        """Greedy global assignment over the shared cost model."""
        open_tasks = [t for t in self.board.all()
                      if t.status is TaskStatus.UNASSIGNED
                      and t.required_capabilities <= self.capabilities]
        if not open_tasks:
            return False

        busy = {t.assigned_agent for t in self.board.all()
                if t.assigned_agent and t.status not in (TaskStatus.COMPLETE,
                                                         TaskStatus.FAILED)}
        free = [r for r in self.fleet.values()
                if r.vehicle_id not in busy and not r.landed]
        if not free:
            return False

        # Cost for every (free drone, open task) pair, cheapest first. Greedy
        # rather than Hungarian: with four drones the difference is nil, and a
        # greedy pass over the same costs is easier to state in a paper.
        pairs = []
        for t in sorted(open_tasks, key=lambda t: (-t.priority, t.task_id)):
            for rec in free:
                belief = _ControllerBelief(rec, now, self.home)
                bid = compute_bid(t, belief, self.weights, self.capabilities, now)
                if bid.eligible:
                    pairs.append((bid.value, t.task_id, rec.vehicle_id))
        pairs.sort()

        taken_t, taken_v, changed = set(), set(), False

        for value, task_id, vehicle_id in pairs:
            if task_id in taken_t or vehicle_id in taken_v:
                continue
            t = self.board.get(task_id)
            t.status = TaskStatus.CLAIMED
            t.assigned_agent = vehicle_id
            t.winning_bid = value
            t.version += 1
            self.fleet[vehicle_id].current_task = task_id
            taken_t.add(task_id)
            taken_v.add(vehicle_id)
            self.assignments_sent += 1
            changed = True
            self._log(now, f"assigned {task_id} -> {vehicle_id} "
                           f"(cost {value:.3f})")
            # The command crosses the same degraded link as everything else.
            self.link.send(MessageType.TASK_AWARD,
                           payload={"task": t.to_payload(), "bid": value},
                           recipients=[vehicle_id], now=now,
                           mission_id=self.mission_id)

        # A drone the controller has nothing for should be told so, not left
        # holding until its fallback timer expires. Leaving it to guess made A
        # both slow and prone to self-assigning work it had already done.
        self._release_idle(now, taken_v)
        return changed

    def _release_idle(self, now, just_assigned):
        unassigned = [t for t in self.board.all()
                      if t.status is TaskStatus.UNASSIGNED]
        if unassigned:
            return
        busy = {t.assigned_agent for t in self.board.all()
                if t.assigned_agent and t.status not in (TaskStatus.COMPLETE,
                                                         TaskStatus.FAILED)}
        for rec in self.fleet.values():
            vid = rec.vehicle_id
            if vid in busy or vid in just_assigned or vid in self._released:
                continue
            self._released.add(vid)
            self._log(now, f"no work for {vid}; released")
            self.link.send(MessageType.MISSION_UPDATE,
                           payload={"status": "no_work"}, recipients=[vid],
                           now=now, mission_id=self.mission_id)

    # --- reporting ---

    def _log(self, now, text):
        self.log.append(f"t={now:6.1f}s  {text}")

    def stats(self):
        done = sum(1 for t in self.board.all() if t.status is TaskStatus.COMPLETE)
        return {"controller_steps": self.steps,
                "assignments_sent": self.assignments_sent,
                "reassignments": self.reassignments,
                "tasks_complete": done,
                "tasks_total": len(self.board.all()),
                "drones_heard_from": sum(1 for r in self.fleet.values()
                                         if r.known())}


class CentralAssignmentClient:
    """The drone side of Architecture A.

    Implements the same interface `PersistentAgent` already uses for the
    contract-net allocator, so the agent, the guardian, the skills and the
    executor are byte-for-byte the same code in A as in C. Only the object in
    this slot differs, which is what keeps the comparison honest: A and C differ
    in who decides, not in how anything flies.

    The agent never bids here. It waits to be told, and if nobody tells it for
    long enough, it falls back to the simplest possible local rule.
    """

    def __init__(self, vehicle_id, link, scenario, capabilities=None,
                 fallback_after_s=DEFAULT_FALLBACK_AFTER_S, lease_s=None):
        self.vehicle_id = vehicle_id
        self.link = link
        self.scenario = scenario
        self.capabilities = set(capabilities or {"search", "relay", "inspect"})
        self.fallback_after_s = fallback_after_s
        self.board = TaskBoard([])
        self.last_contact_s = -1e9
        self.started_at = None
        self.self_assigned = 0
        self.awards_received = 0
        self._reported_complete = set()
        self._belief = None
        self.mission_complete = False

    # --- the allocator interface the agent expects ---

    def on_message(self, msg, belief):
        if msg.sender_id != CONTROLLER_ID:
            return False
        self.last_contact_s = max(self.last_contact_s, msg.timestamp)
        if msg.message_type is MessageType.MISSION_UPDATE:
            if (msg.payload or {}).get("status") in ("complete", "no_work"):
                self.mission_complete = True
            return True
        if msg.message_type is not MessageType.TASK_AWARD:
            return False
        payload = (msg.payload or {}).get("task") or {}
        if not payload.get("task_id"):
            return False
        tid = payload["task_id"]
        existing = self.board.get(tid)
        if existing is None:
            existing = MissionTask.from_payload(payload)
            self.board.tasks[tid] = existing
        existing.assigned_agent = self.vehicle_id
        existing.status = TaskStatus.CLAIMED
        existing.lease_expires_at = None      # the controller owns the lifetime
        self.awards_received += 1
        return True

    def tick(self, belief):
        """Report state upward; take work only if the controller has gone quiet."""
        now = belief.now
        self._belief = belief
        if self.started_at is None:
            self.started_at = now

        self.link.send(MessageType.STATUS_UPDATE,
                       payload={"position": [belief.position.x, belief.position.y,
                                             belief.position.z],
                                "battery_frac": round(belief.battery_frac, 3),
                                "task": belief.self_.current_task,
                                "searched": list(belief.local_map.searched_ids)},
                       recipients=[CONTROLLER_ID], now=now,
                       mission_id=belief.mission.mission_id)

        if self.my_tasks(now):
            return False

        # Keep the agent's loop alive while an assignment may still arrive. The
        # agent stops when a step produces no events, so without this a drone
        # sitting on the pad waiting for orders would quit before the first
        # award could cross the link.
        if self.open_for_me(now):
            belief.push(AgentEvent.COMMS_CHANGED, "awaiting assignment")

        # Being told there is no work outranks the disconnection fallback. Without
        # this a drone that had already been released kept self-assigning sectors
        # it had just finished, because the fallback timer only looks at silence.
        if self.mission_complete or not self._out_of_contact(now):
            return False
        return self._self_assign(belief)

    def _out_of_contact(self, now):
        baseline = self.started_at if self.last_contact_s < -1e8 \
            else self.last_contact_s
        return (now - baseline) > self.fallback_after_s

    def _self_assign(self, belief):
        """The disconnected fallback: nearest sector nobody is known to have done.

        Deliberately unilateral. It does not ask, does not announce, and does not
        check whether a teammate is already there - a drone out of contact with
        the controller in this architecture has no coordination mechanism at all,
        and pretending otherwise would import Architecture C's benefits into the
        baseline.
        """
        searched = set(belief.local_map.searched_ids)
        mine = {t.task_id for t in self.board.all()}
        best, best_d = None, None
        for s in self.scenario.sectors:
            tid = f"SEARCH_SECTOR_{s.sector_id}"
            if s.sector_id in searched or tid in mine:
                continue
            r = s.footprint
            cx, cy = (r.min_x + r.max_x) / 2, (r.min_y + r.max_y) / 2
            d = belief.position.horizontal_distance_to(Position3D(cx, cy,
                                                                  belief.position.z))
            if best_d is None or d < best_d:
                best, best_d = s, d
        if best is None:
            return False
        tid = f"SEARCH_SECTOR_{best.sector_id}"
        t = MissionTask(task_id=tid, task_type=TaskType.SEARCH_SECTOR,
                        region=best.footprint, priority=2,
                        required_capabilities={"search"})
        t.assigned_agent = self.vehicle_id
        t.status = TaskStatus.CLAIMED
        self.board.tasks[tid] = t
        self.self_assigned += 1
        return True

    def my_tasks(self, now):
        return [t for t in self.board.all()
                if t.assigned_agent == self.vehicle_id
                and t.status in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS)]

    def open_for_me(self, now):
        """Work this drone might still *be given* - not work it may take.

        The agent treats an empty result as "the mission is over, go home", so
        returning [] unconditionally sent every drone home the moment it was
        between assignments, before the controller had said anything. This
        instead reports the sectors the drone does not believe are searched yet:
        there is still work out there, so keep waiting. The drone still never
        *chooses* any of it - only `tick`'s disconnected fallback can do that.
        """
        if self.mission_complete:
            return []
        b = self._belief
        if b is None:
            return list(self.scenario.sectors)
        searched = set(b.local_map.searched_ids)
        return [s for s in self.scenario.sectors if s.sector_id not in searched]

    def has_capacity(self, now):
        return not self.my_tasks(now)

    def complete_task(self, task_id, belief):
        t = self.board.get(task_id)
        if t is not None:
            t.status = TaskStatus.COMPLETE
        if task_id not in self._reported_complete:
            self._reported_complete.add(task_id)
            self.link.send(MessageType.TASK_COMPLETE,
                           payload={"task_id": task_id,
                                    "searched": list(belief.local_map.searched_ids)},
                           recipients=[CONTROLLER_ID], now=belief.now,
                           mission_id=belief.mission.mission_id)
        return True

    def release_task(self, task_id, belief, reason="released"):
        t = self.board.get(task_id)
        if t is not None:
            t.status = TaskStatus.UNASSIGNED
            t.assigned_agent = None
        return True

    def stats(self):
        return {"awards_received": self.awards_received,
                "self_assigned_while_disconnected": self.self_assigned}


class CentralizedPolicy:
    """The flight policy for Architecture A: wait for orders, then fly them.

    Wraps the deterministic Phase 5 policy and changes exactly one thing - what
    to do when holding no task. The decentralized agents bid; these drones have
    nothing to bid into, so they hold position until the controller tells them
    something. Modelling that as a real hold rather than as a free no-op matters
    twice over: it advances the clock, so commands can actually arrive, and it
    charges the battery for waiting, which is the cost centralized control pays
    when the link is slow.
    """

    def __init__(self, inner=None, wait_s=WAIT_TICK_S):
        from ..agents.search_policy import SearchAgentPolicy
        self.inner = inner or SearchAgentPolicy()
        self.wait_s = wait_s
        self.waits = 0

    def next_objective(self, belief) -> Objective:
        if belief.landed:
            return Objective.DONE
        if belief.task is None:
            if getattr(belief, "no_work_remaining", False):
                return Objective.LAND if belief.near_home else Objective.RETURN_HOME
            self.waits += 1
            return Objective.HOLD
        return self.inner.next_objective(belief)

    def choose_skill(self, belief, objective):
        if objective is Objective.HOLD:
            return sk.HoldPositionCommand(duration_s=self.wait_s)
        return self.inner.choose_skill(belief, objective)

    def stats(self):
        return {"waits_for_orders": self.waits}

    def __getattr__(self, item):
        return getattr(self.__dict__.get("inner"), item)
