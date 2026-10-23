"""One persistent drone agent: Observe → Update belief → Select objective → Choose skill → Validate → Execute → Verify.

    agent = DroneAgent(brief, sensors, executor, policy)
    agent.assign("search S1")
    agent.run(max_s=900)                 # on the shared clock: from a participating thread
    agent.trace                          # every decision, with what it was based on

AUV-06, 5.1, as the plan gives it:

    while not mission_finished:
        observations = perceive_environment()
        belief_state.update(observations)
        if should_replan(belief_state):
            decision      = policy.decide(belief_state)
            safe_decision = guardian.evaluate(decision, belief_state)
            executor.start(safe_decision)
        executor.monitor()
        belief_state.record(executor.status())

EVERY TICK (`tick_s`, half a second) the agent OBSERVES -- its sensors and
its own executor -- and UPDATES its belief. That is cheap. It DECIDES only
when an event fired (`core.events`): a task given, a skill ending, a new
sighting, the base link coming or going, the battery falling through one of
its levels, the guard refusing a decision, or the slow periodic check
(`periodic_s`) with nothing else happening. AUV-06, 5.2: "Do not call the
LLM continuously."

THEN, for each decision: the policy SELECTS an objective and CHOOSES a skill
(`Decision`); the validation step checks it (`agents.validation`); if
refused, the policy is asked again with GUARD_REJECTED among its events, up
to MAX_REJECTIONS times, after which the agent holds where it is. An
accepted decision is EXECUTED on the non-blocking executor, so motion never
waits on the next decision; and the next ticks VERIFY it, by observing how
the skill ends.

THE TRACE records every decision: when, the events that caused it, the
belief it was made on (a snapshot), the decision, the verdict, and what the
agent then did. Phase 6 turns this into the full "what it knew and what it
did not know" logger; it starts here.

The agent holds a brief, its sensors and its executor -- nothing that leads
to ground truth (`agents/__init__.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..control.action_executor import ActionExecutor, SkillHandle
from ..core.events import Event, Trigger
from ..core.scenario import MissionBrief
from ..core.sensing import Sensors
from .belief_state import BeliefState, Observation
from .decision import Decision, DecisionKind, Policy
from .validation import Verdict, validate

DEFAULT_TICK_S = 0.5
DEFAULT_PERIODIC_S = 10.0
DEFAULT_BATTERY_LEVELS = (50.0, 35.0)       # percent: the agent re-thinks as it falls through each
MAX_REJECTIONS = 3

_ENDINGS = {"success": Trigger.SKILL_SUCCEEDED, "failed": Trigger.SKILL_FAILED,
            "timeout": Trigger.SKILL_FAILED, "aborted": Trigger.SKILL_ABORTED}


@dataclass(frozen=True)
class TraceEntry:
    at: float
    events: tuple[Event, ...]
    belief: dict[str, Any]
    decision: Decision
    verdict: Verdict
    action: str

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "events": [e.as_json() for e in self.events], "belief": self.belief,
                "decision": self.decision.as_json(),
                "verdict": {"ok": self.verdict.ok, "reasons": list(self.verdict.reasons)},
                "action": self.action}


class DroneAgent:
    def __init__(self, brief: MissionBrief, sensors: Sensors, executor: ActionExecutor | SkillHandle, policy: Policy,
                 validator: Callable[[Decision, BeliefState], Verdict] = validate,
                 tick_s: float = DEFAULT_TICK_S, periodic_s: float = DEFAULT_PERIODIC_S,
                 battery_levels: tuple[float, ...] = DEFAULT_BATTERY_LEVELS) -> None:
        if tick_s <= 0 or periodic_s <= 0:
            raise ValueError("tick and periodic check must be positive")
        self.brief = brief
        self.sensors = sensors
        # Only the handle: the executor itself leads, through its runner and
        # adapter, to the simulator (6.2).
        self.executor: SkillHandle = executor.handle() if isinstance(executor, ActionExecutor) else executor
        self.policy = policy
        self.validator = validator
        self.tick_s = tick_s
        self.periodic_s = periodic_s
        self.battery_levels = tuple(sorted(battery_levels, reverse=True))
        self.clock = self.executor.clock
        self.trace: list[TraceEntry] = []
        self.observations = 0
        self.finished = False
        self._pending: list[Event] = []
        self._reported_serial = 0
        # The agent looks only at its LATEST skill. One aborted to make way
        # for a new START is never seen ending: the new one is latest by the
        # next tick. So replacing a skill makes no false SKILL_ABORTED news.
        self.belief = BeliefState.start(brief, sensors.drone, self.observe())
        self._last_decision_at = self.belief.self_.updated_at

    # ---------------------------------------------------------- interface

    def assign(self, task: str) -> None:
        """Give the agent a task. It is news at the next tick."""
        self.belief.self_.current_task = task
        self._pending.append(Event(Trigger.TASK_ASSIGNED, self.clock.now(), {"task": task}))

    def run(self, max_s: float | None = None) -> None:
        """Tick until the policy says FINISH, or `max_s` has passed."""
        end = None if max_s is None else self.clock.now() + max_s
        while not self.finished:
            self.step()
            if self.finished or (end is not None and self.clock.now() >= end):
                break
            self.clock.sleep(self.tick_s)

    def step(self) -> tuple[Event, ...]:
        """One tick: observe, update, and decide if anything happened. Returns the events."""
        obs = self.observe()
        changes = self.belief.update(obs)
        events = self._events(obs, changes)
        if events:
            self._decide(events)
        return events

    def observe(self) -> Observation:
        self.observations += 1
        state = self.sensors.own_state()
        latest = self.executor.current()
        running = latest is not None and latest.running
        status = None
        if latest is not None and not running:
            status = latest.result.status.value if latest.result is not None else "failed"
        return Observation(state.t, state.x, state.y, state.altitude_m, state.airborne, self.sensors.battery(),
                           self.sensors.sightings(), self.sensors.base_link(),
                           latest.command.skill.value if running else None,
                           0 if latest is None else latest.serial, status,
                           None if latest is None else latest.command.skill.value)

    # ------------------------------------------------------------ internal

    def _events(self, obs: Observation, changes: dict[str, Any]) -> tuple[Event, ...]:
        now = obs.at
        events = list(self._pending)
        self._pending.clear()
        if obs.last_skill_status is not None and obs.last_skill_serial > self._reported_serial:
            self._reported_serial = obs.last_skill_serial
            latest = self.executor.current()
            detail = {"skill": latest.command.skill.value, "status": obs.last_skill_status,
                      "serial": latest.serial}
            if latest.result is not None:
                detail["message"] = latest.result.message
                if latest.result.error_code is not None:
                    detail["error_code"] = latest.result.error_code.value
            else:
                detail["message"] = latest.error
            events.append(Event(_ENDINGS.get(obs.last_skill_status, Trigger.SKILL_FAILED), now, detail))
        for label in changes.get("new_sightings", []):
            s = self.belief.local_map.observed_targets[label]
            events.append(Event(Trigger.TARGET_DETECTED, now, {"label": label, "x": s.x, "y": s.y}))
        if "base_link" in changes:
            events.append(Event(Trigger.COMMS_CHANGED, now, {"base_link": changes["base_link"]}))
        if "battery_from" in changes:
            for level in self.battery_levels:
                if changes["battery_from"] > level >= obs.battery:
                    events.append(Event(Trigger.BATTERY_THRESHOLD, now, {"level": level, "battery": obs.battery}))
        if not events and now - self._last_decision_at >= self.periodic_s:
            events.append(Event(Trigger.PERIODIC, now))
        return tuple(events)

    def _decide(self, events: tuple[Event, ...]) -> None:
        now = self.clock.now()
        self._last_decision_at = now
        asked = events
        for _ in range(MAX_REJECTIONS + 1):
            snapshot = self.belief.snapshot()            # what it knew BEFORE deciding
            decision = self.policy.decide(self.belief, asked)
            verdict = self.validator(decision, self.belief)
            if verdict.ok:
                action = self._act(decision)
                self.trace.append(TraceEntry(now, asked, snapshot, decision, verdict, action))
                return
            self.trace.append(TraceEntry(now, asked, snapshot, decision, verdict, "refused"))
            asked = asked + (Event(Trigger.GUARD_REJECTED, now,
                                   {"refused": decision.as_json(), "reasons": list(verdict.reasons)}),)
        # Refused every time: hold where it is, and think again at the next event.
        held = self.executor.abort()
        self.trace.append(TraceEntry(now, asked, self.belief.snapshot(), Decision.abort(reason="refused "
                                     f"{MAX_REJECTIONS + 1} times"), Verdict(True),
                                     "held after repeated refusals" if held else "nothing to hold"))

    def _act(self, decision: Decision) -> str:
        if decision.objective is not None:
            self.belief.mission.objective = decision.objective
        if decision.kind is DecisionKind.START:
            replaced = ""
            if self.executor.busy:
                running = self.executor.current()
                self.executor.abort()
                self.executor.wait()
                replaced = f"aborted {running.command.skill.value} #{running.serial}, then "
            started = self.executor.start(decision.command)
            self.belief.self_.current_skill = decision.command.skill.value
            return f"{replaced}started {decision.command.skill.value} #{started.serial}"
        if decision.kind is DecisionKind.ABORT:
            return "aborted the running skill" if self.executor.abort() else "nothing to abort"
        if decision.kind is DecisionKind.FINISH:
            self.finished = True
            return "finished"
        return "carried on"
