"""Time, as the skill layer sees it: real for a simulator, simulated for the mock.

Every skill has a timeout and every result says when it started and ended
(AUV-04, 3.3), so the skill layer needs a clock -- and it must not be the
wall clock when the vehicles are simulated. In the mock, four drones flying
for a minute should take milliseconds and come out the same every time.

    RealClock    monotonic seconds; `sleep` really sleeps. For AirSim.
    SimClock     simulated seconds; `sleep` advances simulated time.

ONE TIMELINE FOR SEVERAL THREADS. The flying code gives each drone its own
thread (Phase 1: one connection per thread). With a simulated clock those
threads must still share one timeline, or a separation check between two
drones would compare positions from different instants. So `SimClock` runs a
conservative discrete-event scheme: threads that fly together enter
`participate()`; a participant that sleeps waits until EVERY participant is
sleeping, then time jumps to the earliest wake-up and those participants
wake. Time never passes while any participant is computing, which is what
makes a run deterministic: the simulated instant at which anything happens
does not depend on how fast the machine is.

Whether computing time -- a language model thinking, in Phase 12 -- should be
charged to simulated time is a decision AUV-19 asks to be made deliberately.
This clock does not charge it. A caller that wants it charged sleeps for it.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Iterator, Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float:
        """Seconds, from an arbitrary origin. Only differences mean anything."""
        ...

    def sleep(self, seconds: float) -> None:
        """Let `seconds` pass for the caller."""
        ...


class RealClock:
    """The machine's monotonic clock. What a real simulator runs on."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


class SimClock:
    """Simulated time, shared deterministically by any number of threads.

    Used without `participate()`, it is a simple counter: `sleep` advances it
    at once. Used with participants, see the module docstring.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)
        self._cv = threading.Condition()
        self._participants: set[int] = set()
        self._wake_at: dict[int, float] = {}

    def now(self) -> float:
        with self._cv:
            return self._now

    @contextlib.contextmanager
    def participate(self) -> Iterator[None]:
        """Join the shared timeline for the duration of the block.

        Every thread that sleeps on this clock while others are flying must
        be a participant; otherwise time could not know when it may move.
        """
        me = threading.get_ident()
        with self._cv:
            if me in self._participants:
                raise RuntimeError("this thread already participates in this clock")
            self._participants.add(me)
        try:
            yield
        finally:
            with self._cv:
                self._participants.discard(me)
                self._wake_at.pop(me, None)
                self._advance()
                self._cv.notify_all()

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        me = threading.get_ident()
        with self._cv:
            if not self._participants:
                self._now += seconds
                return
            if me not in self._participants:
                raise RuntimeError("a thread sleeping on a shared SimClock must participate()")
            wake = self._now + seconds
            self._wake_at[me] = wake
            self._advance()
            self._cv.notify_all()
            while self._now < wake:
                self._cv.wait()
            del self._wake_at[me]

    def advance(self, seconds: float) -> None:
        """Move time forward from outside, with no participants waiting on it."""
        with self._cv:
            if self._participants:
                raise RuntimeError("advance() would race the participants; let them sleep instead")
            self._now += max(0.0, float(seconds))

    def _advance(self) -> None:
        # Caller holds the lock. Move only when every participant is asleep.
        if self._participants and len(self._wake_at) == len(self._participants):
            earliest = min(self._wake_at.values())
            if earliest > self._now:
                self._now = earliest
