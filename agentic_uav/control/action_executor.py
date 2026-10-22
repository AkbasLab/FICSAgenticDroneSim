"""Run one skill at a time on its own thread, so the agent can watch it and stop it (AUV-06, 5.1-5.2).

    executor = ActionExecutor(runner)
    executor.start(GoToWaypointCommand(...))      # returns at once
    ...                                           # the agent observes, decides
    executor.current().running                    # still flying?
    executor.abort()                              # stop it, from the agent's thread
    executor.current().result                     # the SkillResult, once it ends

AUV-06's loop is "executor.start(safe_decision); executor.monitor()": the
agent starts a skill and keeps watching the world while it flies. A blocking
`SkillRunner.run` would leave the agent deaf until the skill ended: no
target sighted mid-search, no battery threshold crossed mid-leg, until too
late. And AUV-06, 5.2: "low-level motion must never depend on LLM response
time" -- here the motion runs on its own thread whatever the agent is doing.

ONE SKILL AT A TIME. A drone flies one thing; starting a second while the
first runs is refused (`ExecutorBusy`). To change course, abort, then start.

ON THE SIMULATED CLOCK every thread that sleeps must take part in the shared
timeline (`SimClock.participate`). The skill's thread does, and `start`
returns only once it has joined: otherwise the agent could fall asleep first,
time would jump to the agent's wake-up with nothing flying, and two runs of
the same agent would differ. A participant must also never block on the
skill thread (that would stop time for everyone): `wait` sleeps on the clock
in slices instead. On a real clock none of this matters and the same code
runs unchanged.

THE AGENT NOTICES AN ENDING WITHIN ONE SLICE. `wait` (and any agent loop
that polls) sees a skill has ended at its next check, up to WAIT_SLICE_S
later; the drone holds where the skill left it meanwhile. That is the
agent's reaction time, and it is the only difference from calling the
skills directly: the same outcomes, durations and positions (tested).

LIVE, pass `connect`: each skill's thread then opens its own connection
before it flies, as every flying thread in this project does (Phase 1: an
AirSim client cannot be shared between threads). The runner itself -- its
measured ground, its home -- carries over from skill to skill.

ABORT goes through `SkillRunner.request_abort`: the skill stops at its next
check and holds where it is (every skill contract's abort behaviour). For
AirSim pass `abort_via`, an adapter on the AGENT's own connection: one
connection per thread (Phase 1).
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

from ..core.clock import Clock, SimClock
from .skills import SkillCommand, SkillResult, SkillRunner

WAIT_SLICE_S = 0.1


class ExecutorBusy(RuntimeError):
    """A skill is still running: abort it, or wait for it, first."""


@dataclass(frozen=True)
class Execution:
    """One skill started by the executor: what, when, and how it ended."""

    serial: int
    command: SkillCommand
    started_at: float
    result: SkillResult | None = None    # None while it runs
    error: str | None = None             # the skill's thread itself raised (a bug, not a flight outcome)
    abort_requested: bool = False

    @property
    def running(self) -> bool:
        return self.result is None and self.error is None


class ActionExecutor:
    """Runs one drone's skills, one at a time, each on its own thread."""

    def __init__(self, runner: SkillRunner, clock: Clock | None = None, abort_via: Any = None,
                 connect: Callable[[], Any] | None = None) -> None:
        self.runner = runner
        self.clock = clock if clock is not None else runner.clock
        self.abort_via = abort_via
        # Live, every skill thread opens its own connection: AirSim's client
        # cannot be used from more than one thread (Phase 1), and each skill
        # runs on a new thread. The runner keeps its measured ground and home.
        self.connect = connect
        self._lock = threading.Lock()
        self._history: list[Execution] = []
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------- interface

    def start(self, command: SkillCommand) -> Execution:
        """Start `command` and return at once, with its `Execution` (still running)."""
        if not isinstance(command, SkillCommand):
            raise TypeError(f"not a skill command: {command!r}")
        with self._lock:
            if self._history and self._history[-1].running:
                raise ExecutorBusy(f"{self._history[-1].command.skill.value} is still running")
            execution = Execution(len(self._history) + 1, command, self.clock.now())
            self._history.append(execution)
        # Cleared here, not by the skill's thread: an abort asked for between
        # this return and the thread reaching the skill must not be lost.
        self.runner.clear_abort()
        joined = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(execution, joined),
                                        name=f"{self.runner.vehicle_id}-{command.skill.value}", daemon=True)
        self._thread.start()
        joined.wait()                      # it is on the timeline before the caller can sleep
        return execution

    def current(self) -> Execution | None:
        """The latest execution, as it stands now."""
        with self._lock:
            return self._history[-1] if self._history else None

    def history(self) -> tuple[Execution, ...]:
        with self._lock:
            return tuple(self._history)

    @property
    def busy(self) -> bool:
        latest = self.current()
        return latest is not None and latest.running

    def abort(self) -> bool:
        """Ask the running skill to stop and hold. False if nothing was running."""
        with self._lock:
            if not (self._history and self._history[-1].running):
                return False
            self._history[-1] = replace(self._history[-1], abort_requested=True)
        self.runner.request_abort(via=self.abort_via)
        return True

    def wait(self, timeout_s: float | None = None) -> Execution | None:
        """Sleep on the clock until the running skill ends (or `timeout_s` passes).

        For a thread on the shared simulated clock: it sleeps in slices, so
        time keeps moving. Returns the latest execution.
        """
        end = None if timeout_s is None else self.clock.now() + timeout_s
        while self.busy:
            if end is not None and self.clock.now() >= end:
                break
            step = WAIT_SLICE_S if end is None else max(0.0, min(WAIT_SLICE_S, end - self.clock.now()))
            self.clock.sleep(step)
        return self.current()

    def close(self) -> None:
        """Join the skill thread. Only from a thread that is NOT on the simulated timeline."""
        if self._thread is not None:
            self._thread.join()

    # ------------------------------------------------------------ internal

    def _run(self, execution: Execution, joined: threading.Event) -> None:
        sim = isinstance(self.clock, SimClock)
        with (self.clock.participate() if sim else contextlib.nullcontext()):
            joined.set()
            try:
                if self.connect is not None:
                    self.runner.vehicle = self.connect()
                result = self.runner.run(execution.command, clear_abort=False)
                ended = {"result": result}
            except BaseException as exc:        # recorded, never silent
                ended = {"error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                index = execution.serial - 1
                self._history[index] = replace(self._history[index], **ended)
