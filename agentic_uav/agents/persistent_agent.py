"""Persistent, closed-loop single-drone agent (Phase 5).

This replaces one-shot planning. The agent is handed a *task*, not a plan, and
runs the lifecycle until the task is done or it has to abort:

    observe -> update belief -> select objective -> choose skill
            -> validate -> execute -> verify

Replanning is event-driven (Phase 5.2): the agent only re-decides when something
happened - a skill finished, a target was seen, the battery crossed a threshold,
a safety guard fired. Between decisions it does not think; low-level motion is the
skill executor's job, not the policy's. Deciding one skill at a time (rather than
emitting a full action list up front) is what makes this a closed loop: the agent
recognizes success or failure and chooses what to do next.
"""

from dataclasses import dataclass, field
from typing import List

from ..control import skills as sk
from ..control.skill_executor import SkillExecutor, _lawnmower
from ..coordination.protocols import MessageType
from ..coordination.role_manager import RoleManager
from ..coordination.roles import HealthState, Role
from ..core.enums import SkillStatus
from ..core.models import Position3D
from ..experiments.decision_log import DecisionLog
from ..experiments.mission_runner import _timed_path
from .belief_schema import Source
from .belief_state import BeliefState
from .comms_estimator import CommsEstimator
from .guardian import Guardian
from .objectives import AgentEvent, Objective
from .search_policy import SearchAgentPolicy

# how many decision rounds an idle-but-airborne agent waits for work to appear
# before giving up and returning home
MAX_IDLE_ROUNDS = 3


def _to_list(p):
    return None if p is None else [round(p.x, 2), round(p.y, 2), round(p.z, 2)]


def _position_from(seq):
    if not seq:
        return None
    return Position3D(float(seq[0]), float(seq[1]),
                      float(seq[2]) if len(seq) > 2 else 0.0)


@dataclass
class AgentRunReport:
    vehicle_id: str
    task_id: str
    completed: bool                 # searched, reported, returned, landed
    aborted_safely: bool            # gave up the task but landed safely
    sector_searched: bool
    reported: bool
    returned_home: bool
    landed: bool
    detections: List[str] = field(default_factory=list)
    battery_frac_end: float = 0.0
    steps: int = 0
    decisions: List[str] = field(default_factory=list)   # (event -> objective)
    detail: str = ""
    log: object = None                  # DecisionLog: what it knew at each step


class PersistentAgent:
    def __init__(self, vehicle_id, adapter, policy=None, guardian=None,
                 home=None, cruise_altitude=-8.0, battery_total_s=900.0,
                 low_battery_frac=0.30, critical_battery_frac=0.12,
                 max_steps=60, sensor=None, roster=None, sector_ids=None,
                 link=None, message_log=None, allocator=None,
                 health=None, role_manager=None, comms=None):
        self.vehicle_id = vehicle_id
        self.adapter = adapter
        self.executor = SkillExecutor(adapter)
        self.policy = policy or SearchAgentPolicy()
        self.guardian = guardian or Guardian()
        self.max_steps = max_steps

        # The sensor is the ONLY route from ground truth into belief (Phase 6.2).
        # Without one the agent simply perceives nothing beyond its own state.
        self.sensor = sensor
        # Names the agent is briefed on - used only to ask "what don't I know?".
        self.roster = roster or []
        self.sector_ids = sector_ids or []

        # The agent's only channel to its teammates: send + receive_available.
        # It holds no reference to the bus, so it cannot read anyone else's mail.
        self.link = link
        self._message_log = message_log
        # Phase 8: decentralized task allocation. Without one the agent simply
        # flies whatever task it was handed, exactly as in Phases 5-7.
        self.allocator = allocator
        # Phase 9: teammate liveness and this agent's functional role.
        self.health = health
        # Phase 10.5: link quality is *estimated* from observed traffic, never
        # read from the network model's configuration.
        self.comms = comms
        self.roles = role_manager or (RoleManager(vehicle_id, health)
                                      if health is not None else None)
        # set by fault injection - a stopped drone does nothing at all, which is
        # what its teammates must cope with (they are not told).
        self.stopped = False

        # step() bookkeeping (set by start())
        self.task = None
        self.completed_tasks = []      # task ids this agent finished (Phase 8)
        self._idle_rounds = 0
        self.steps = 0
        self.finished = False
        self.decisions = []

        start = home or adapter.get_position(vehicle_id)
        self.belief = BeliefState(
            vehicle_id=vehicle_id, home=start, battery_total_s=battery_total_s,
            cruise_altitude=cruise_altitude, low_battery_frac=low_battery_frac,
            critical_battery_frac=critical_battery_frac)
        self.log = DecisionLog(vehicle_id)

    # --- the lifecycle loop ---

    def start(self, task=None):
        """Accept a task, or start with none and win one through allocation.

        Phases 5-7 hand the agent a task directly. From Phase 8 an agent may be
        started with `task=None` and an allocator instead: it then bids for work
        alongside its teammates and flies whatever it wins.
        """
        self.task = task
        if task is not None:
            self.belief.assign_task(task)
        self.completed_tasks = []
        self.steps = 0
        self.finished = False
        self.decisions = []
        self._idle_rounds = 0
        if task is None and self.allocator is not None:
            # kick the loop off - there is work to be had, go and bid for it
            self.belief.push(AgentEvent.TASK_ASSIGNED, "seeking work")

    def step(self) -> bool:
        """Run one turn of the lifecycle. Returns False when the agent is done.

        Exposed separately from run() so a team runner can interleave several
        agents and let them exchange messages *while* flying, rather than each
        agent flying its whole mission in isolation.
        """
        b = self.belief
        if self.stopped:
            # simulates a drone that has gone: no sensing, no messages, no
            # heartbeats. Teammates must infer this from silence alone.
            self.finished = True
            return False
        if self.finished or self.steps >= self.max_steps:
            self.finished = True
            return False
        self.steps += 1

        # observe -> update belief (own state, sensor, then delivered messages)
        b.observe(self.adapter.get_position(self.vehicle_id), self._now())
        self._sense_self(b)
        received = self._receive_messages(b)

        # Phase 9: re-assess who is still flying, then what we should be.
        # Both run before allocation, so a lost teammate's task is already
        # reclaimable and our role already reflects the new team shape.
        self._update_health(b)

        # Phase 8: run one round of decentralized allocation before deciding.
        # This may win us a task, lose us one, or reclaim an expired lease.
        if self.allocator is not None:
            self._allocate(b, received)

        self._update_role(b)

        # event-driven: only re-decide when something happened
        if not self._should_replan(b):
            if not self._idle_airborne(b):
                self.finished = True
                return False
            # still flying with nothing to do: give it a bounded number of
            # chances for work to appear, then bring it home rather than
            # leaving it hovering. Quitting the loop airborne would strand it.
            self._idle_rounds += 1
            if self._idle_rounds > MAX_IDLE_ROUNDS:
                b.no_work_remaining = True
            b.push(AgentEvent.COMMS_CHANGED,
                   f"idle with no task ({self._idle_rounds})")
        else:
            self._idle_rounds = 0
        triggers = b.drain_events()

        # log what the agent knows *and does not know* before it decides
        rec = self.log.start(step=self.steps, time_s=b.now,
                             triggers=[t.value for t, _ in triggers],
                             belief=b, roster=self.roster,
                             sectors=self.sector_ids)

        # select objective
        objective = self.policy.next_objective(b)
        b.last_objective = objective
        self.decisions.append(f"{'/'.join(t.value for t, _ in triggers)}"
                              f"->{objective.value}")

        # any message that arrived this turn contributed to this decision
        self._credit_messages(received)

        if objective is Objective.DONE:
            self.log.finish(rec, objective=objective.value)
            self._announce(MessageType.TASK_COMPLETE,
                           {"task_id": getattr(self.task, "task_id", None),
                            "targets": list(b.detections)})
            self.finished = True
            return False

        # CLAIM_TASK is deliberation, not flight - the allocation round already
        # ran this step, so there is nothing to execute. Wait for bids/awards.
        if objective is Objective.CLAIM_TASK:
            self.log.finish(rec, objective=objective.value,
                            outcome="bidding" if self._waiting_for_work(b)
                            else "no_work")
            return self._waiting_for_work(b)

        # REPORT is an internal action (transmit completion), not a flight.
        if objective is Objective.REPORT:
            self._do_report(b)
            self.log.finish(rec, objective=objective.value, outcome="reported")
            return True

        # choose skill -> validate -> guardian -> execute -> verify
        command = self.policy.choose_skill(b, objective)
        if command is None:
            self.log.finish(rec, objective=objective.value)
            return True
        self._validate(command)
        guard = self.guardian.evaluate(command, b)
        override = None
        if guard.overridden:
            b.push(AgentEvent.SAFETY_REJECTED, guard.reason)
            command = guard.command
            objective = self._objective_for(command)
            override = guard.reason

        # tell the team what we are about to do, then do it
        self._announce(MessageType.INTENT_UPDATE,
                       {"objective": objective.value,
                        "skill": command.skill_type.value}, ttl_s=90.0)

        result = self.executor.execute(self.vehicle_id, command)
        b.record(result)                 # emits SKILL_SUCCEEDED/FAILED/TIMEOUT
        self._verify(b, objective, command, result)
        self.log.finish(rec, objective=objective.value,
                        skill=str(command.skill_type.value),
                        override=override, outcome=result.status.value)

        # heartbeat + status after acting, so peers learn where we ended up
        self._heartbeat()
        return True

    def run(self, task) -> AgentRunReport:
        """Fly the whole task to completion (single-agent convenience wrapper)."""
        self.start(task)
        while self.step():
            pass
        return self.report()

    def report(self) -> AgentRunReport:
        return self._report(self.task, self.steps, self.decisions)

    # --- steps of the lifecycle ---

    def _should_replan(self, b):
        """Phase 5.2: replan on events only (never a busy loop)."""
        return b.has_events()

    def _validate(self, command):
        """Cheap precondition check before executing (contract sanity)."""
        contract = getattr(command, "contract", None)
        if contract is not None and contract.timeout_s < 0:
            raise ValueError(f"invalid contract for {command.skill_type}")

    def _do_report(self, b):
        """Transmit task completion to base, and release the task to the team."""
        b.reported = True
        if self.allocator is not None and self.task is not None:
            self.completed_tasks.append(self.task.task_id)
            self.allocator.complete_task(self.task.task_id, b)
            self._drop_current_task(b)
        found = ",".join(b.detections) if b.detections else "no targets"
        b.push(AgentEvent.REPORT_SENT, f"sector done; {found}")

    def _verify(self, b, objective, command, result):
        """Recognize success/failure and update progress (the closed loop)."""
        ok = result.status is SkillStatus.SUCCESS

        if objective is Objective.TAKE_OFF:
            if ok:
                b.airborne = True

        elif objective is Objective.GO_TO_SECTOR:
            if ok:
                b.at_sector = True
                b.nav_failures = 0
            else:
                b.nav_failures += 1

        elif objective is Objective.SEARCH_SECTOR:
            if ok:
                b.sector_searched = True
                b.nav_failures = 0
                b.note_searched(b.task.sector.sector_id, b.task.sector.footprint)
                self._check_detections(b, command)
            else:
                b.nav_failures += 1

        elif objective is Objective.RETURN_HOME:
            if not ok:
                b.nav_failures += 1

        elif objective is Objective.LAND:
            if ok:
                b.landed = True
                b.airborne = False

    def _check_detections(self, b, search_command):
        """Perceive targets along the sweep just flown.

        The agent does NOT hold the target list - it asks the sensor what it
        actually saw from the path it actually flew. With no sensor attached it
        perceives nothing, which is the correct default: no sensor, no knowledge.
        """
        if self.sensor is None:
            return
        waypoints = _lawnmower(search_command)
        entry = waypoints[0] if waypoints else b.position
        path = _timed_path(entry, waypoints, search_command.speed_mps)
        obs = self.sensor.sense_targets(self.vehicle_id, path,
                                        search_command.speed_mps, b.now)
        known = set(b.detections)
        b.note_detections([o.subject_id for o in obs],
                          positions={o.subject_id: o.position for o in obs})
        # tell the team about anything newly found
        for o in obs:
            if o.subject_id not in known:
                self._announce(MessageType.TARGET_FOUND,
                               {"target_id": o.subject_id,
                                "position": _to_list(o.position),
                                "sector_id": getattr(b.task.sector, "sector_id", None)},
                               ttl_s=120.0)

    # --- teammate health and roles (Phase 9) ---

    def _update_health(self, b):
        """Age every peer's liveness, and react to one that looks gone."""
        if self.health is None:
            return
        for h in self.health.tick(b.now, roster=self.roster):
            # mirror the health verdict into belief so the log and the bids see it
            rec = b.team.teammates.get(h.vehicle_id)
            if rec is not None:
                rec.status = ("failed" if h.presumed_lost
                              else "degraded" if h.state is HealthState.SUSPECTED
                              else "ok")
            if h.presumed_lost:
                b.push(AgentEvent.TEAMMATE_FAILED,
                       f"{h.vehicle_id} {h.state.value}")
            elif h.state is HealthState.SUSPECTED:
                b.push(AgentEvent.COMMS_CHANGED, f"{h.vehicle_id} suspected")

    def _update_role(self, b):
        """Pick our functional role from local belief, and announce a change."""
        if self.roles is None:
            return
        open_count = 0
        if self.allocator is not None:
            open_count = len(self.allocator.open_for_me(b.now))
        decision = self.roles.decide(b, open_task_count=open_count,
                                     holding_task=self.task is not None)
        b.self_.role = decision.role.value
        if decision.changed:
            b.push(AgentEvent.ROLE_CHANGED,
                   f"{decision.role.value}: {decision.reason}")
            # a role change alters what we will bid on
            if self.allocator is not None:
                self.allocator.capabilities = self.roles.capabilities_for(
                    decision.role)
            self._announce(MessageType.ROLE_CHANGE,
                           {"role": decision.role.value,
                            "reason": decision.reason}, ttl_s=180.0)

    # --- decentralized allocation (Phase 8) ---

    def _allocate(self, b, received):
        """One round of contract-net, then reconcile it with what we're flying."""
        alloc = self.allocator
        for m in received:
            alloc.on_message(m, b)

        before = {t.task_id for t in alloc.my_tasks(b.now)}
        alloc.tick(b)
        mine = alloc.my_tasks(b.now)
        after = {t.task_id for t in mine}

        # keep the belief's workload view current so bids price it correctly
        b.held_task_ids = sorted(after)

        if after != before:
            b.push(AgentEvent.TASK_ASSIGNED,
                   ",".join(sorted(after)) or "none")

        # we lost the task we were flying (conflict, or an expired lease)
        if self.task is not None and self.task.task_id not in after:
            b.push(AgentEvent.TASK_ASSIGNED, f"lost {self.task.task_id}")
            self._drop_current_task(b)

        # we hold something and aren't flying it yet - convert it to flight work
        if self.task is None and mine:
            self._adopt_task(b, mine[0])

        # nothing left for anyone: head home
        b.no_work_remaining = not mine and not alloc.open_for_me(b.now)

    def _adopt_task(self, b, mission_task):
        """Turn a won MissionTask into the SearchTask the flight policy executes."""
        from ..core.mission_models import Sector
        from .objectives import SearchTask

        region = mission_task.region
        sector = Sector(sector_id=mission_task.task_id.replace("SEARCH_SECTOR_", ""),
                        footprint=region, altitude=b.cruise_altitude)
        task = SearchTask(task_id=mission_task.task_id, sector=sector,
                          report_to=b.home)
        self.task = task
        # a fresh task means fresh progress, but not a fresh flight
        b.at_sector = False
        b.sector_searched = False
        b.reported = False
        b.assign_task(task)

    def _drop_current_task(self, b):
        self.task = None
        b.task = None
        b.at_sector = False
        b.sector_searched = False
        b.reported = False

    def _idle_airborne(self, b):
        """Flying, holding nothing, with no events - waiting on the team."""
        return b.airborne and not b.landed and self.task is None

    def _waiting_for_work(self, b):
        """True while there is still work we could win."""
        alloc = self.allocator
        if alloc is None:
            return False
        return bool(alloc.open_for_me(b.now))

    def _sense_self(self, b):
        """Sensing that is genuinely local: can I still reach the base station?

        Note what is *not* here: peer positions. From Phase 7 on, everything an
        agent believes about a teammate arrives as a delivered message. Sensing
        peers directly would be a back channel around the protocol.
        """
        if self.sensor is None:
            return
        b.communication.base_reachable = self.sensor.base_reachable(self.vehicle_id)

    # --- communication (Phase 7) ---

    def _receive_messages(self, b):
        """Fold delivered messages into belief. The only way team belief changes."""
        if self.link is None:
            return []
        messages = self.link.receive_available(now=b.now)
        for m in messages:
            if self.health is not None:
                self.health.note_heard(m.sender_id, b.now)
            if self.comms is not None:
                self.comms.observe(m, b.now)
            self._apply_message(b, m)
        if self.comms is not None:
            self.comms.apply_to(b)
        b.communication.connected_peers = [
            vid for vid, r in b.team.teammates.items() if not r.is_stale(b.now)]
        return messages

    def _apply_message(self, b, m):
        p = m.payload or {}
        pos = _position_from(p.get("position"))

        if m.message_type in (MessageType.HEARTBEAT, MessageType.STATUS_UPDATE,
                              MessageType.INTENT_UPDATE):
            b.receive_teammate_report(
                m.sender_id, position=pos, task=p.get("task"),
                role=p.get("role"), status=p.get("status"),
                sent_at=m.timestamp, confidence=m.confidence or 1.0)

        elif m.message_type is MessageType.TARGET_FOUND:
            # a teammate saw something: believe it, but mark it second-hand
            tid = p.get("target_id")
            if tid:
                b.note_detections([tid], positions={tid: pos},
                                  source=Source.PEER_MESSAGE)
                b.assume(f"{tid} located near {p.get('position')}",
                         evidence=f"reported by {m.sender_id} at t={m.timestamp:.0f}s",
                         confidence=m.confidence or 0.8)

        elif m.message_type is MessageType.TASK_COMPLETE:
            b.receive_teammate_report(m.sender_id, position=pos, status="ok",
                                      task=None, sent_at=m.timestamp)
            sector = p.get("sector_id")
            if sector:
                b.local_map.mark_searched(sector, None, m.timestamp, m.sender_id)

        elif m.message_type is MessageType.HELP_REQUEST:
            b.receive_teammate_report(m.sender_id, position=pos,
                                      status="degraded", sent_at=m.timestamp)

        elif m.message_type is MessageType.ROLE_CHANGE:
            b.receive_teammate_report(m.sender_id, role=p.get("role"),
                                      sent_at=m.timestamp)

    def _credit_messages(self, messages):
        """Mark in the message log which messages fed into this decision (7.4)."""
        if self._message_log is None or not messages:
            return
        for m in messages:
            self._message_log.mark_influential(m.message_id, self.vehicle_id)

    def _announce(self, message_type, payload=None, recipients=None, ttl_s=30.0):
        if self.link is None:
            return None
        b = self.belief
        body = {"position": _to_list(b.position),
                "battery_frac": round(b.battery_frac, 3)}
        body.update(payload or {})
        return self.link.send(message_type, payload=body, recipients=recipients,
                              now=b.now, mission_id=b.mission.mission_id,
                              ttl_s=ttl_s)

    def _heartbeat(self):
        """Cheap liveness + state share, sent after each action."""
        b = self.belief
        self._announce(MessageType.HEARTBEAT, {"status": "ok"}, ttl_s=90.0)
        self._announce(MessageType.STATUS_UPDATE, {
            "status": "ok",
            "task": b.self_.current_task,
            "skill": b.self_.current_skill,
            "searched": list(b.local_map.searched_ids),
        }, ttl_s=180.0)

    # --- helpers ---

    def _now(self):
        return self.adapter.now(self.vehicle_id) \
            if hasattr(self.adapter, "now") else 0.0

    def _objective_for(self, command):
        if isinstance(command, sk.LandCommand):
            return Objective.LAND
        if isinstance(command, sk.ReturnHomeCommand):
            return Objective.RETURN_HOME
        return self.belief.last_objective

    def _report(self, task, steps, decisions):
        b = self.belief
        task_id = (task.task_id if task is not None
                   else ",".join(self.completed_tasks) or "-")
        if self.allocator is not None:
            # in allocation mode "completed" means: did the work it took on, and
            # got home safely. An agent that legitimately won nothing still
            # counts as complete if it returned and landed.
            did_work = bool(self.completed_tasks)
            completed = (b.near_home and b.landed
                         and (did_work or not b.no_work_remaining is False))
            searched = did_work
        else:
            completed = (b.sector_searched and b.reported and b.near_home and b.landed)
            searched = b.sector_searched
        aborted_safely = (not completed) and b.landed and b.near_home
        return AgentRunReport(
            vehicle_id=self.vehicle_id, task_id=task_id,
            completed=completed, aborted_safely=aborted_safely,
            sector_searched=searched, reported=b.reported,
            returned_home=b.near_home, landed=b.landed,
            detections=list(b.detections), battery_frac_end=b.battery_frac,
            steps=steps, decisions=decisions, log=self.log,
            detail=" | ".join(f"{e}:{d}" for e, d in b.history))
