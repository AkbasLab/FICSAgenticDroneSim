"""Time source. A thin wrapper now; later this lets experiments run on a
simulated clock (fixed timestep) instead of wall-clock time."""

import time


class Clock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


REAL_CLOCK = Clock()
