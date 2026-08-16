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
from ..core.enums import SkillStatus
from ..experiments.mission_runner import _timed_path
from ..simulator.target_model import detect_targets
from .belief_state import BeliefState
from .guardian import Guardian
from .objectives import AgentEvent, Objective
from .search_policy import SearchAgentPolicy


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


class PersistentAgent:
    def __init__(self, vehicle_id, adapter, policy=None, guardian=None,
                 home=None, cruise_altitude=-8.0, battery_total_s=900.0,
                 low_battery_frac=0.30, critical_battery_frac=0.12,
                 max_steps=60):
        self.vehicle_id = vehicle_id
        self.adapter = adapter
        self.executor = SkillExecutor(adapter)
        self.policy = policy or SearchAgentPolicy()
        self.guardian = guardian or Guardian()
        self.max_steps = max_steps

        start = home or adapter.get_position(vehicle_id)
        self.belief = BeliefState(
            vehicle_id=vehicle_id, home=start, battery_total_s=battery_total_s,
            cruise_altitude=cruise_altitude, low_battery_frac=low_battery_frac,
            critical_battery_frac=critical_battery_frac)

    # --- the lifecycle loop ---

    def run(self, task) -> AgentRunReport:
        b = self.belief
        b.assign_task(task)
        decisions = []

        steps = 0
        while steps < self.max_steps:
            steps += 1

            # observe -> update belief
            b.observe(self.adapter.get_position(self.vehicle_id),
                      self._now())

            # event-driven: only re-decide when something happened
            if not self._should_replan(b):
                break
            triggers = b.drain_events()

            # select objective
            objective = self.policy.next_objective(b)
            b.last_objective = objective
            decisions.append(f"{'/'.join(t.value for t, _ in triggers)}"
                             f"->{objective.value}")
            if objective is Objective.DONE:
                break

            # REPORT is an internal action (transmit completion), not a flight.
            if objective is Objective.REPORT:
                self._do_report(b)
                continue

            # choose skill -> validate -> guardian -> execute -> verify
            command = self.policy.choose_skill(b, objective)
            if command is None:
                continue
            self._validate(command)
            guard = self.guardian.evaluate(command, b)
            if guard.overridden:
                b.push(AgentEvent.SAFETY_REJECTED, guard.reason)
                command = guard.command
                objective = self._objective_for(command)

            result = self.executor.execute(self.vehicle_id, command)
            b.record(result)                 # emits SKILL_SUCCEEDED/FAILED/TIMEOUT
            self._verify(b, objective, command, result)

        return self._report(task, steps, decisions)

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
        """Transmit task completion to base (single-drone: log it locally)."""
        b.reported = True
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
        """Perceive targets along the sweep just flown (geometric, no NN)."""
        targets = getattr(b.task, "targets_of_interest", None)
        if not targets:
            return
        waypoints = _lawnmower(search_command)
        entry = waypoints[0] if waypoints else b.position
        path = _timed_path(entry, waypoints, search_command.speed_mps)
        dets = detect_targets(targets, {self.vehicle_id: path},
                              search_command.speed_mps)
        b.note_detections([d.target_id for d in dets])

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
        completed = (b.sector_searched and b.reported and b.near_home and b.landed)
        aborted_safely = (not completed) and b.landed and b.near_home
        return AgentRunReport(
            vehicle_id=self.vehicle_id, task_id=task.task_id,
            completed=completed, aborted_safely=aborted_safely,
            sector_searched=b.sector_searched, reported=b.reported,
            returned_home=b.near_home, landed=b.landed,
            detections=list(b.detections), battery_frac_end=b.battery_frac,
            steps=steps, decisions=decisions,
            detail=" | ".join(f"{e}:{d}" for e, d in b.history))
