"""Phase 5+6+7: one agent completes a search task with no preflight plan,
discovering targets by sensing, and now sharing what it finds with - and
learning from - teammates over an AgentLink. The lifecycle: observe (own
state + any delivered messages) -> update belief -> select objective ->
choose skill -> validate (Guardian) -> execute -> verify - repeated until the
policy returns DONE. Every objective is a response to a named event, never a
bare timer tick.
"""

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..control.navigation import DEFAULT_HEIGHT, SKILL_TIMEOUT_S
from ..control.skills import go_to_waypoint, hold_position, land, take_off
from ..coordination.bidding import DEFAULT_WEIGHTS, compute_bid
from ..coordination.message_bus import AgentLink
from ..coordination.protocols import MessageType
from ..coordination.roles import HealthMonitor, HealthState
from ..coordination.task_allocator import DEFAULT_LEASE_S
from ..coordination.tasks import TaskBoard, TaskStatus
from ..core.interfaces import VehicleAdapter
from ..core.scenario import Scenario, Sector
from ..core.skill_result import SkillStatus
from ..experiments.guardian_log import GuardianLog
from ..experiments.mission_runner import lawnmower_waypoints
from .belief import Belief, SearchLeg
from .belief_schema import MissionBelief, Provenance, SelfState, TargetSighting, TeammateRecord
from .comms_estimator import CommsEstimator
from .llm_tools import BY_NAME
from .decision_log import DecisionLogger
from .ground_truth import SensorModel
from .objectives import Objective, ReplanEvent
from .safety_guardian import Command, FallbackAction, GuardianOutcome, SafetyGuardian, SafetyLimits
from .search_policy import SearchAgentPolicy

MAX_STEPS = 500  # hard backstop against a future undiscovered infinite-loop bug in the policy -
# a real mission finishes in well under 50 decision steps even with retries, so this is generous
MAX_HELP_REQUESTS_KEPT = 5  # Phase 12.3: bounded, like every other thing shown to a model
MAX_MARKET_KEPT = 5  # Phase 12 (15-tool set): same bound for announcements, bids and offers
AGENT_REPORT_HOLD_S = 3.0  # how long THIS agent holds position to confirm a sighting - an agent-
# owned protocol constant, deliberately not read from the scenario's Target.dwell_s (that would be
# the same ground-truth leak Phase 6 exists to close, just moved to a different field)
LISTEN_HOLD_S = 5.0  # Phase 7: how long each individual listen-in-place round lasts
SEARCH_WAYPOINT_SPACING_M = 3.0  # sub-waypoints along each sweep leg, close enough together that a
# target sitting mid-lane (not at a sector corner, where the raw lawnmower waypoints all are) still
# gets a sensor check near its closest approach - same lesson as Phase 4's coverage sampling gap


def _to_local(point: Tuple[float, float, float], spawn_offset: Tuple[float, float, float]):
    return (point[0] - spawn_offset[0], point[1] - spawn_offset[1], point[2] - spawn_offset[2])


def _to_world(point: Tuple[float, float, float], spawn_offset: Tuple[float, float, float]):
    return (point[0] + spawn_offset[0], point[1] + spawn_offset[1], point[2] + spawn_offset[2])


def _subdivide(a: Tuple[float, float, float], b: Tuple[float, float, float], spacing: float):
    dist = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5
    if dist <= spacing:
        return [b]
    steps = max(1, int(dist / spacing))
    return [tuple(a[k] + (b[k] - a[k]) * (i / steps) for k in range(3)) for i in range(1, steps + 1)]


def _build_search_queue(sector: Sector, spawn_offset, height: float) -> List[SearchLeg]:
    """Pure geometry - no target information goes into this. An agent's
    search pattern must not depend on where the things it's searching for
    actually are."""
    corners = lawnmower_waypoints(sector, height)
    points = [corners[0]] if corners else []
    for a, b in zip(corners, corners[1:]):
        points.extend(_subdivide(a, b, SEARCH_WAYPOINT_SPACING_M))
    return [SearchLeg(point=_to_local(p, spawn_offset)) for p in points]


@dataclass
class AgentReport:
    trace: List[str]
    target_found: Optional[str]
    battery_frac_at_end: float


class PersistentAgent:
    def __init__(self, adapter: VehicleAdapter, scenario: Scenario, sector_id: str,
                 spawn_offset: Tuple[float, float, float], battery_s: float,
                 policy: SearchAgentPolicy = None, guardian: SafetyGuardian = None,
                 cruise_height: float = DEFAULT_HEIGHT, logger: DecisionLogger = None,
                 drone_name: str = "drone", link: AgentLink = None,
                 task_board: TaskBoard = None, health_monitor: HealthMonitor = None,
                 kill_at_s: Optional[float] = None, comms_estimator: CommsEstimator = None):
        self.adapter = adapter
        self.scenario = scenario
        self.sector = scenario.sector(sector_id)
        self.spawn_offset = spawn_offset
        self.cruise_height = cruise_height
        self.policy = policy or SearchAgentPolicy()
        # Phase 11: SafetyGuardian supersedes Phase 5's Guardian (no-fly-zones only,
        # binary pass/fail) as the default - Guardian itself is untouched, still its
        # own class with its own tests, just no longer what a real agent flies with.
        self.guardian = guardian or SafetyGuardian(limits=SafetyLimits.from_scenario(scenario))
        self.guardian_log = GuardianLog()
        self._pending_waypoint = None  # Phase 12: coordinates for a model-chosen GO_TO_WAYPOINT, one-shot
        self._pending_action = None  # Phase 12 (15-tool set): (tool, validated args) the model just chose, one-shot
        self.sensor = SensorModel(scenario)  # the ONLY thing here allowed to read scenario.targets
        self.logger = logger
        self.drone_name = drone_name
        self.link = link  # Phase 7: the only thing this agent holds for talking to teammates -
        # never the bus itself, never another agent's inbox. None = solo (Phase 5/6 behavior, unchanged).
        self.task_board = task_board  # Phase 9: this agent's OWN view of the allocation board from
        # Phase 8 (kept alive after allocation, not thrown away) - None disables dynamic reassignment
        self.health_monitor = health_monitor
        self.kill_at_s = kill_at_s  # fault-injection hook for testing failure recovery - simulates
        # a drone going silent (no flight, no sensing, no heartbeats, nobody told), never used in
        # a real mission
        self.comms_estimator = comms_estimator  # Phase 10: this agent's own inferred view of link
        # quality per teammate, built only from messages that actually arrived - never given access
        # to the NetworkModel/NetworkProfile that's actually degrading the link
        self.belief = Belief(
            self_state=SelfState(position=(0.0, 0.0, 0.0), elapsed_s=0.0, battery_s=battery_s),
            mission=MissionBelief(sector_id=sector_id,
                                   search_queue=_build_search_queue(self.sector, spawn_offset, cruise_height)),
        )
        if self.task_board:
            # Seed a baseline "heard from at mission start" for every OTHER known
            # drone (participated in allocation, so known to be alive then) - without
            # this, a drone that dies before ever sending its first HEARTBEAT (e.g.
            # killed during its initial climb) would never appear in team.teammates
            # at all, and classify(None, ...) treats a total stranger as HEALTHY by
            # design (absence of contact isn't evidence of failure for someone we
            # don't even know exists). A known teammate's silence should actually be
            # able to age into SUSPECTED/UNREACHABLE/FAILED, not default to healthy
            # forever just because its very first message never arrived.
            for spec in scenario.drones:
                if spec.name != drone_name:
                    self.belief.team.teammates[spec.name] = TeammateRecord(
                        name=spec.name, last_known_position=None,
                        provenance=Provenance(timestamp=0.0, source="mission_start"))

    def run(self) -> AgentReport:
        start = time.monotonic()
        event = ReplanEvent.TASK_ASSIGNED
        trace = []
        step = 0

        while True:
            if self.kill_at_s is not None and self.belief.elapsed_s >= self.kill_at_s:
                # Simulated total failure: stop here, send nothing further. No LAND, no
                # final HEARTBEAT, nobody told - exactly what a real crash/comms-total-loss
                # looks like to the rest of the team, which is the only honest way to test
                # whether they actually detect and recover from it.
                trace.append(f"simulated_failure_at({self.kill_at_s}s)->killed")
                break

            self._observe_messages()  # "observe" now includes anything teammates delivered

            self._refresh_task_view()  # a bounded snapshot of THIS agent's own board, for the model's prompt
            objective, next_phase = self.policy.decide(self.belief, event)
            # Phase 12: only an LLM policy ever has coordinates to hand over, and only for
            # GO_TO_WAYPOINT; the deterministic policy has no such method.
            take_waypoint = getattr(self.policy, "take_waypoint", None)
            self._pending_waypoint = take_waypoint() if take_waypoint else None
            # Phase 12 (15-tool set): which tool the model chose and with what validated arguments. Every
            # tool except the progress-making ones (start_search, report_target, return_home) costs one of
            # the hard-capped model actions - that cap is what guarantees a model cannot loop.
            take_action = getattr(self.policy, "take_action", None)
            self._pending_action = take_action() if take_action else None
            if self._pending_action is not None and not BY_NAME[self._pending_action[0]].free:
                self.belief.self_state.model_actions += 1
            # Phase 12.3: messages the model authored, already validated (closed type, known
            # recipients, closed payload). Sent before acting, like any other agent message.
            take_messages = getattr(self.policy, "take_messages", None)
            for m in (take_messages() if take_messages else ()):
                if self.link:
                    self.link.send(m.type, dict(m.payload), recipients=list(m.recipients))
            trace.append(f"{event.value}->{objective.value}")
            self.belief.phase = next_phase
            if self.logger:
                self.logger.record(step, self.drone_name, event, self.belief, objective)
            step += 1

            if objective == Objective.DONE:
                break

            if step > MAX_STEPS:
                # Belt-and-braces: a genuine infinite-loop bug in the policy (found
                # live - returning's retry/abort degenerated to the same objective
                # forever) spun this exact loop with no exit for over an hour before
                # being caught by hand. That bug is fixed, but nothing should ever
                # again be able to hang a whole multi-drone mission on one agent
                # with no error at all - this is the hard backstop for a future one.
                trace.append(f"step_limit_exceeded({MAX_STEPS})->aborted")
                break

            event = self._execute(objective, trace)
            self.belief.elapsed_s = time.monotonic() - start

            if event == ReplanEvent.GUARDIAN_ESCALATED:
                # The guardian stopped asking and flew/landed the aircraft itself -
                # already a terminal, already-safe outcome, nothing left for the
                # policy to decide. See safety_guardian.py's sticky `escalated` flag.
                trace.append("guardian_escalated->mission_terminated")
                break

            if objective == Objective.TAKE_OFF and event == ReplanEvent.SKILL_FAILED:
                # No ground reference was ever recorded - RETURN_HOME/LAND both need
                # one, so there is nothing safe left to command. Stop here, don't
                # route through the normal failure path (which assumes airborne).
                trace.append("takeoff_failed->aborted")
                break

        return AgentReport(trace=trace, target_found=self.belief.target_found,
                            battery_frac_at_end=self.belief.battery_frac_remaining)

    def _execute(self, objective: Objective, trace: List[str]) -> ReplanEvent:
        if objective == Objective.TAKE_OFF:
            result = take_off(self.adapter)
            self.belief.position = result.final_position or self.belief.position
            return ReplanEvent.SKILL_SUCCEEDED if result.status == SkillStatus.SUCCESS else ReplanEvent.SKILL_FAILED

        if objective == Objective.GO_TO_SECTOR:
            return self._guarded_fly((0.0, 0.0, self.cruise_height), trace)

        if objective == Objective.SEARCH_SECTOR:
            if not self.belief.mission.search_queue:
                return ReplanEvent.SKILL_SUCCEEDED
            leg = self.belief.mission.search_queue.pop(0)
            event = self._guarded_fly(leg.point, trace)
            if event != ReplanEvent.SKILL_SUCCEEDED:
                return event
            if self.task_board:
                # Keep my own claim fresh from OTHER agents' point of view - same cadence
                # as the heartbeat above. claimed_by() (my own view) never needs this; it's
                # purely so nobody else's board thinks my lease lapsed mid-sweep.
                own_task_id = f"search_{self.belief.mission.sector_id}"
                self.task_board.renew_lease(own_task_id, self.drone_name, self.belief.elapsed_s, DEFAULT_LEASE_S)
            return self._sense_after_arrival()

        if objective == Objective.REPORT:
            # Finding a target also means this sector's search is done, same as an
            # exhausted queue - this path bypasses LISTEN entirely (searching ->
            # reporting -> returning, never touching "listening"), so it needs its
            # own copy of the same completion signal, not just LISTEN's.
            self._mark_own_task_complete()
            result = hold_position(self.adapter, AGENT_REPORT_HOLD_S)
            self.belief.position = result.final_position or self.belief.position
            unconfirmed = [s for s in self.belief.mission.targets_known.values()
                           if not s.confirmed and s.source == "sensor"]
            wanted = (self._pending_action[1].get("target_id") if self._pending_action else None)
            unconfirmed = [t for t in unconfirmed if t.target_id == wanted] or unconfirmed
            if unconfirmed:
                sighting = unconfirmed[0]
                sighting.confirmed = True
                if self.link:
                    self.link.send(MessageType.TARGET_FOUND,
                                    {"target_id": sighting.target_id,
                                     "world_position": _to_world(sighting.local_position, self.spawn_offset)})
            self.belief.communication.last_report_sent = unconfirmed[0].target_id if unconfirmed else None
            return ReplanEvent.REPORT_SENT

        if objective == Objective.LISTEN:
            if self.belief.listen_rounds == 0:
                # The first LISTEN round is the exact moment this agent's own search
                # just ended with nothing found - mark completion here too (REPORT's
                # branch covers the "found a target" path, which never touches LISTEN).
                self._mark_own_task_complete()
            result = hold_position(self.adapter, LISTEN_HOLD_S)
            self.belief.position = result.final_position or self.belief.position
            self.belief.listen_rounds += 1
            self._send_heartbeat()
            return ReplanEvent.SKILL_SUCCEEDED if result.status == SkillStatus.SUCCESS else ReplanEvent.SKILL_FAILED

        if objective == Objective.CHECK_FOR_ORPHANS:
            return self._check_for_orphans()

        if objective == Objective.TOOL_ACTION:
            return self._execute_tool()

        if objective == Objective.GO_TO_WAYPOINT:
            # Consumes one of the code-capped listen rounds whether or not the flight succeeds,
            # so a model cannot keep proposing waypoints forever (the Phase 8 infinite-loop lesson).
            self.belief.listen_rounds += 1
            if self._pending_waypoint is None:
                return ReplanEvent.SKILL_FAILED
            wx, wy = self._pending_waypoint
            self._pending_waypoint = None
            # World (x, y) from the model; altitude is code-owned, never the model's to choose.
            local_target = _to_local((wx, wy, self.cruise_height + self.spawn_offset[2]), self.spawn_offset)
            event = self._guarded_fly(local_target, trace)
            if event != ReplanEvent.SKILL_SUCCEEDED:
                return event
            return self._sense_after_arrival()  # somewhere new: a real sensor reading, as always

        if objective == Objective.RETURN_HOME:
            return self._guarded_fly((0.0, 0.0, DEFAULT_HEIGHT), trace, purpose="home")

        if objective == Objective.LAND:
            result = land(self.adapter)
            self.belief.position = result.final_position or self.belief.position
            return ReplanEvent.SKILL_SUCCEEDED if result.status == SkillStatus.SUCCESS else ReplanEvent.SKILL_FAILED

        return ReplanEvent.SKILL_SUCCEEDED

    def _observe_messages(self):
        """Part of 'observe', every loop iteration - belief updates only on
        what was actually delivered, never by reaching into a teammate's
        state directly. TARGET_FOUND fills in belief as explicitly
        second-hand (source='message'); it never overwrites an existing
        own-sensor sighting, and this agent never re-derives it from
        anything but the message itself."""
        if not self.link:
            return
        for msg in self.link.receive_available():
            if self.comms_estimator:
                self.comms_estimator.observe(msg, self.belief.elapsed_s)
            if msg.type == MessageType.TARGET_FOUND:
                target_id = msg.payload["target_id"]
                if target_id not in self.belief.mission.targets_known:
                    local = _to_local(msg.payload["world_position"], self.spawn_offset)
                    self.belief.mission.targets_known[target_id] = TargetSighting(
                        target_id=target_id, local_position=local, first_seen_t=self.belief.elapsed_s,
                        confirmed=True, source="message")
            elif msg.type == MessageType.HELP_REQUEST:
                # Informational only: record it (capped), change nothing else. A request for help
                # is never an order, and receiving one never alters this agent's task or tasks.
                self.belief.communication.help_requests.append(
                    (msg.sender, msg.payload.get("reason_code", "?"), self.belief.elapsed_s))
                del self.belief.communication.help_requests[:-MAX_HELP_REQUESTS_KEPT]
            elif msg.type == MessageType.TASK_ANNOUNCE and self.task_board:
                # A teammate says a task it holds is up for bids. Recorded, nothing more: hearing an
                # announcement never obliges this agent to bid, and never changes the board.
                tid = msg.payload.get("task_id")
                if tid in self.task_board.tasks and msg.sender != self.drone_name:
                    comm = self.belief.communication
                    comm.announced_tasks = [e for e in comm.announced_tasks if e[0] != tid] + \
                        [(tid, msg.sender, self.belief.elapsed_s)]
                    del comm.announced_tasks[:-MAX_MARKET_KEPT]
            elif msg.type == MessageType.TASK_BID and self.task_board:
                tid = msg.payload.get("task_id")
                if tid in self.task_board.tasks and msg.sender != self.drone_name:
                    bid = float(msg.payload["bid"])
                    self.task_board.apply_bid(tid, msg.sender, bid)
                    comm = self.belief.communication
                    comm.bids_received.append((tid, msg.sender, bid, self.belief.elapsed_s))
                    del comm.bids_received[:-MAX_MARKET_KEPT]
            elif msg.type == MessageType.TASK_RELEASE and self.task_board:
                tid = msg.payload.get("task_id")
                if tid in self.task_board.tasks and self.task_board.apply_release(
                        tid, msg.sender, int(msg.payload["version"])):
                    comm = self.belief.communication
                    comm.announced_tasks = [e for e in comm.announced_tasks if e[0] != tid]
                    if msg.payload.get("awarded_to") == self.drone_name:
                        comm.offers_to_me.append((tid, msg.sender, self.belief.elapsed_s))
                        del comm.offers_to_me[:-MAX_MARKET_KEPT]
            elif msg.type == MessageType.HEARTBEAT:
                self.belief.team.teammates[msg.sender] = TeammateRecord(
                    name=msg.sender, last_known_position=msg.payload["position"],
                    provenance=Provenance(timestamp=self.belief.elapsed_s, source="heartbeat",
                                           base_confidence=msg.confidence))
            elif msg.type == MessageType.TASK_COMPLETE and self.task_board:
                self.task_board.mark_complete(msg.payload["task_id"], msg.sender)
                # A message of any kind is proof of life too, not just a HEARTBEAT -
                # update the sender's last-known-alive timestamp so finishing
                # normally doesn't itself look like the silence that precedes it.
                existing = self.belief.team.teammates.get(msg.sender)
                self.belief.team.teammates[msg.sender] = TeammateRecord(
                    name=msg.sender, last_known_position=existing.last_known_position if existing else None,
                    provenance=Provenance(timestamp=self.belief.elapsed_s, source="task_complete"))
            elif msg.type == MessageType.TASK_CLAIM and self.task_board:
                # A survivor's reclaim-claim, broadcast from _check_for_orphans -
                # every other agent's board needs to reflect it too, same Lamport
                # acceptance rule as the original Phase 8 allocation round.
                self.task_board.apply_claim(msg.payload["task_id"], msg.sender, msg.payload["bid"],
                                             msg.payload["version"], self.belief.elapsed_s, DEFAULT_LEASE_S)
                # someone took it: it is no longer announced or on offer to this agent
                comm = self.belief.communication
                tid = msg.payload["task_id"]
                comm.announced_tasks = [e for e in comm.announced_tasks if e[0] != tid]
                comm.offers_to_me = [e for e in comm.offers_to_me if e[0] != tid]

    def _release_failed_holders(self):
        """Phase 9's lease short-circuit: a task held by a teammate HealthMonitor classifies FAILED
        becomes available immediately, not after waiting out the full lease (FICS's bug #3). Shared by
        the deterministic orphan check AND the model's task view, so a model sees a dead drone's work
        as unheld exactly when the deterministic policy would."""
        if not self.task_board or not self.health_monitor:
            return
        now = self.belief.elapsed_s
        for name, record in list(self.belief.team.teammates.items()):
            if self.health_monitor.classify(record, now) == HealthState.FAILED:
                for task_id in list(self.task_board.tasks):
                    self.task_board.release_if_failed(task_id, name)

    def _claim(self, task_id: str) -> bool:
        """Take an unheld task: bid (a deterministic cost - no model ever picks a number), claim it on this
        agent's own board, tell the team, queue its sector. Used by the deterministic orphan check and by
        the model's claim_task / accept_task alike, so there is exactly one way to take work."""
        now = self.belief.elapsed_s
        task = self.task_board.tasks[task_id]
        sector = self.scenario.sector(task.sector_id)
        bid = compute_bid(_to_world(self.belief.position, self.spawn_offset),
                          self.belief.battery_frac_remaining, workload=0, sector=sector,
                          role_mismatch=self._role_mismatch(), weights=DEFAULT_WEIGHTS)
        version = self.task_board.next_version(task_id)
        accepted = self.task_board.apply_claim(task_id, self.drone_name, bid, version, now, DEFAULT_LEASE_S)
        if accepted:
            if self.link:
                self.link.send(MessageType.TASK_CLAIM, {"task_id": task_id, "bid": bid, "version": version})
            self.belief.mission.sector_id = task.sector_id
            self.belief.mission.search_queue = _build_search_queue(sector, self.spawn_offset, self.cruise_height)
            self.belief.listen_rounds = 0  # the new sector gets its own full listen window later
        return accepted

    def _role_mismatch(self) -> float:
        """Only a scout does scouting work; a relay or reserve bidding on a search task is a mismatch."""
        return 0.0 if self.belief.self_state.role == "scout" else 1.0

    def _check_for_orphans(self) -> ReplanEvent:
        """Phase 9's actual 'team changes shape' behavior. Reclassifies every
        known teammate's health from belief alone, releases any task held by
        one classified FAILED (short-circuits the lease - FICS's bug #3),
        then looks for a task that's unheld and isn't my own. Claims it
        directly if found - this agent is the one who noticed, so it claims
        unilaterally rather than running a full bid round (which would need
        another message round-trip, with no guarantee anyone else is even
        still listening)."""
        if not self.task_board or not self.health_monitor:
            return ReplanEvent.SKILL_SUCCEEDED  # no Phase 9 wiring - behave exactly like Phase 7
        if self.belief.self_state.role != "scout":
            return ReplanEvent.SKILL_SUCCEEDED  # a relay or reserve doesn't pick up search work

        now = self.belief.elapsed_s
        self._release_failed_holders()

        own_sector = self.belief.mission.sector_id
        declined = set(self.belief.communication.declined_tasks)
        for task_id, task in self.task_board.tasks.items():
            if task.sector_id == own_sector or task.status == TaskStatus.COMPLETE or task_id in declined:
                continue
            if self.task_board.held_by(task_id, now) is not None:
                continue  # someone genuinely still holds it
            if self._claim(task_id):
                return ReplanEvent.NEW_TASK_ASSIGNED
        return ReplanEvent.SKILL_SUCCEEDED

    # ---- Phase 12 (15-tool set): the board snapshot and the coordination / information tools ----
    def _refresh_task_view(self):
        """A bounded snapshot of THIS agent's own board for the model's prompt - the policy never
        touches the board itself. Applies the same dead-holder short-circuit the deterministic orphan
        check uses first, so the model sees a failed drone's work as unheld at the same moment."""
        if not self.task_board:
            return
        self._release_failed_holders()
        now = self.belief.elapsed_s
        view = []
        for task_id, task in self.task_board.tasks.items():
            if task.status == TaskStatus.COMPLETE:
                view.append((task_id, task.sector_id, "complete", task.assignee))
            elif task.assignee == self.drone_name:
                view.append((task_id, task.sector_id, "mine", self.drone_name))
            elif self.task_board.held_by(task_id, now) is None:
                view.append((task_id, task.sector_id, "unheld", None))
            else:
                view.append((task_id, task.sector_id, "held", task.assignee))
        self.belief.team.task_view = view

    def _own_bid(self, task_id: str) -> float:
        task = self.task_board.tasks[task_id]
        workload = sum(1 for t in self.task_board.claimed_by(self.drone_name)
                       if self.task_board.tasks[t].status != TaskStatus.COMPLETE)
        return compute_bid(_to_world(self.belief.position, self.spawn_offset), self.belief.battery_frac_remaining,
                           workload=workload, sector=self.scenario.sector(task.sector_id),
                           role_mismatch=self._role_mismatch(), weights=DEFAULT_WEIGHTS)

    def _execute_tool(self) -> ReplanEvent:
        """Run the coordination/information tool the model chose. Every precondition is re-checked HERE
        - the menu was built a moment ago, but belief and board can change between menu and action - and
        every message is built by code from this agent's own board: a model never authors a payload."""
        if self._pending_action is None:
            return ReplanEvent.SKILL_FAILED
        tool, args = self._pending_action
        s, comm, board = self.belief.self_state, self.belief.communication, self.task_board
        task_id = args.get("task_id")

        def fail(why: str) -> ReplanEvent:
            s.last_tool_result = f"{tool} did nothing: {why}"
            return ReplanEvent.SKILL_FAILED

        def done(what: str) -> ReplanEvent:
            s.last_tool_result = what
            return ReplanEvent.SKILL_SUCCEEDED

        if tool == "change_role":
            s.role = args["new_role"]
            self._send_heartbeat()
            return done(f"you are now a {s.role}")

        if tool == "act_as_relay":
            s.role = "relay"
            result = hold_position(self.adapter, LISTEN_HOLD_S)
            self.belief.position = result.final_position or self.belief.position
            self.belief.listen_rounds += 1
            self._send_heartbeat()
            return done("holding station as a relay") if result.status == SkillStatus.SUCCESS else fail("hold failed")

        if tool == "request_help":
            if self.link:
                self.link.send(MessageType.HELP_REQUEST, {"reason_code": args.get("reason_code", "teammate_may_need_help")},
                               recipients=list(args["recipients"]))
            return done(f"asked {', '.join(args['recipients'])} for help")

        if board is None or task_id not in board.tasks:
            return fail("no such task on your board")
        task, now = board.tasks[task_id], self.belief.elapsed_s

        if tool == "compute_task_cost":
            return done(f"your cost for {task_id} is {self._own_bid(task_id):.1f} (lower is better)")

        if tool == "announce_task":
            if task.assignee != self.drone_name or task.status != TaskStatus.CLAIMED:
                return fail("you do not hold that task")
            if self.link:
                self.link.send(MessageType.TASK_ANNOUNCE, {"task_id": task_id})
            return done(f"announced {task_id}; teammates may bid")

        if tool == "send_bid":
            announcer = next((who for t, who, _ in comm.announced_tasks if t == task_id), None)
            if announcer is None or task.assignee == self.drone_name:
                return fail("that task was not announced by a teammate")
            bid = self._own_bid(task_id)
            board.apply_bid(task_id, self.drone_name, bid)
            comm.bids_sent.append(task_id)
            if self.link:
                self.link.send(MessageType.TASK_BID, {"task_id": task_id, "bid": bid}, recipients=[announcer])
            return done(f"bid {bid:.1f} on {task_id}")

        if tool == "release_task":
            version = board.release(task_id, self.drone_name)
            if version is None:
                return fail("you do not hold that task, or it is already complete")
            others = {b: v for b, v in board.bids_for(task_id).items() if b != self.drone_name}
            winner = min(others, key=lambda b: (others[b], b)) if others else None   # deterministic award
            if self.link:
                self.link.send(MessageType.TASK_RELEASE,
                               {"task_id": task_id, "version": version, "awarded_to": winner})
            if task.sector_id == self.belief.mission.sector_id:
                self.belief.mission.search_queue = []   # I no longer hold this sector, so I will not sweep it
            comm.announced_tasks = [e for e in comm.announced_tasks if e[0] != task_id]
            return done(f"released {task_id}" + (f", offered to {winner} (best bid)" if winner else ", nobody had bid"))

        if tool in ("claim_task", "accept_task"):
            if task.status == TaskStatus.COMPLETE or task.assignee == self.drone_name \
                    or board.held_by(task_id, now) is not None:
                return fail("that task is not available")
            if tool == "accept_task" and not any(t == task_id for t, _, _ in comm.offers_to_me):
                return fail("that task was not released to you")
            if not self._claim(task_id):
                return fail("a better claim already exists")
            comm.offers_to_me = [e for e in comm.offers_to_me if e[0] != task_id]
            comm.announced_tasks = [e for e in comm.announced_tasks if e[0] != task_id]
            return done(f"you now hold {task_id}; its sector is queued")

        if tool == "decline_task":
            if not any(t == task_id for t, _, _ in comm.offers_to_me):
                return fail("that task was not released to you")
            comm.offers_to_me = [e for e in comm.offers_to_me if e[0] != task_id]
            comm.declined_tasks.append(task_id)
            return done(f"declined {task_id}; it stays open and you will not auto-claim it")

        return fail("unknown tool")

    def _sense_after_arrival(self) -> ReplanEvent:
        """The only place a target can enter belief: a real sensor reading at
        the drone's actual current position, after actually flying there."""
        world_pos = _to_world(self.belief.position, self.spawn_offset)
        for seen in self.sensor.perceive(world_pos):
            if seen.target_id not in self.belief.mission.targets_known:
                self.belief.mission.targets_known[seen.target_id] = TargetSighting(
                    target_id=seen.target_id, local_position=self.belief.position,
                    first_seen_t=self.belief.elapsed_s)
                return ReplanEvent.TARGET_DETECTED
        return ReplanEvent.SKILL_SUCCEEDED

    def _guarded_fly(self, local_target: Tuple[float, float, float], trace: List[str],
                      purpose: str = "mission") -> ReplanEvent:
        """Every proposed flight target goes through the SafetyGuardian before
        reaching the vehicle - the policy proposes, the guardian disposes.
        `purpose="home"` (RETURN_HOME) exempts battery_reserve/separation, which
        would otherwise block the exact recovery move a low-battery drone needs
        most, or fire on every mission's own ending (every drone here returns to
        the same shared home point, so teammates converging there is expected,
        not a near-miss). speed_mps is read from the adapter when it exposes one
        (KinematicMockVehicleAdapter does; AirSimVehicleAdapter doesn't expose a
        fixed cruise speed the way this architecture is built) - a real per-
        command speed proposal doesn't exist here the way FICS's own does, so
        this check is honest about what it can and can't see, not faked."""
        world_target = _to_world(local_target, self.spawn_offset)
        command = Command(kind="fly", target=world_target, purpose=purpose,
                           speed_mps=getattr(self.adapter, "speed_mps", 0.0), timeout_s=SKILL_TIMEOUT_S)
        evaluation = self.guardian.evaluate(command, self.belief,
                                           position_world=_to_world(self.belief.position, self.spawn_offset))
        self.guardian_log.record(len(self.guardian_log.entries), command, evaluation)

        if evaluation.outcome == GuardianOutcome.REJECT_AND_REPLAN:
            self.belief.self_state.last_block_reason = evaluation.reason
            trace.append(f"guardian_blocked({evaluation.reason})")
            return ReplanEvent.GUARDIAN_BLOCKED

        if evaluation.outcome == GuardianOutcome.EXECUTE_SAFE_FALLBACK:
            trace.append(f"guardian_escalated({evaluation.fallback.value}: {evaluation.reason})")
            if evaluation.command.kind == "land":
                result = land(self.adapter)
            else:
                result = go_to_waypoint(self.adapter, *_to_local(evaluation.command.target, self.spawn_offset))
            self.belief.position = result.final_position or self.belief.position
            self.guardian.command_completed()
            if evaluation.fallback == FallbackAction.EXIT_ZONE:
                # GMB: a zone switched on over the aircraft and the guardian steered it out.
                # That is one corrective move, not the end of the flight. Reported as
                # GUARDIAN_BLOCKED, not success: the proposed command was NOT flown (the exit
                # was), so the policy must re-plan from where the aircraft now is - a
                # RETURN_HOME leg that was replaced by an exit has not reached home yet.
                # (Every other fallback is terminal: home, then land.)
                self.belief.self_state.last_block_reason = evaluation.reason
                return ReplanEvent.GUARDIAN_BLOCKED
            return ReplanEvent.GUARDIAN_ESCALATED

        # APPROVE or APPROVE_WITH_MODIFICATION - fly whatever the guardian actually approved,
        # which may differ from what was proposed (e.g. altitude clamped into the envelope).
        self.belief.self_state.last_block_reason = None
        final_local = _to_local(evaluation.command.target, self.spawn_offset)
        result = go_to_waypoint(self.adapter, *final_local)
        self.belief.position = result.final_position or self.belief.position
        self.guardian.command_completed()
        if result.status == SkillStatus.SUCCESS:
            # Every successful flight command sends a heartbeat - GO_TO_SECTOR,
            # SEARCH_SECTOR legs, and RETURN_HOME all go through here, covering nearly
            # the whole mission lifecycle. Found live: heartbeats sent only during
            # active search meant a drone that finished normally (found its target,
            # reporting/returning/landing) went quiet exactly like a dead one would -
            # survivors couldn't tell "done" from "failed" and stole an already-
            # finished sector instead of the actually-orphaned one.
            self._send_heartbeat()
            return ReplanEvent.SKILL_SUCCEEDED
        self.belief.nav_retries += 1
        return ReplanEvent.SKILL_FAILED

    def _mark_own_task_complete(self):
        """Explicit completion signal, not just going quiet - silence alone
        can't distinguish 'finished normally' from 'died', since both look
        identical to a teammate as 'stopped sending heartbeats'. Called
        exactly once per sector this agent works, from whichever path ends
        that sector's search first (REPORT if a target was found, LISTEN's
        first round if nothing was)."""
        if not self.task_board:
            return
        own_task_id = f"search_{self.belief.mission.sector_id}"
        self.task_board.mark_complete(own_task_id, self.drone_name)
        if self.link:
            self.link.send(MessageType.TASK_COMPLETE, {"task_id": own_task_id})

    def _send_heartbeat(self):
        if self.link:
            self.link.send(MessageType.HEARTBEAT,
                            {"position": _to_world(self.belief.position, self.spawn_offset),
                             "battery_frac": self.belief.battery_frac_remaining,
                             "role": self.belief.self_state.role})
