"""Samples every drone's position on a fixed-rate timer, in a background
thread, for the duration of a mission run. The scorer needs a full path per
drone - final position alone can't catch a drone that clipped a no-fly zone
and was back outside it by the time the mission ended.

5 Hz default: at typical flight speed (5 m/s) that's one sample per metre of
travel, enough to catch a clip of anything wider than a couple of metres
without flooding the log or hammering a live AirSim connection with position
queries that compete against real flight commands.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

SAMPLE_RATE_HZ = 5.0


@dataclass
class Sample:
    t: float  # seconds since recording started
    position: Tuple[float, float, float]


class TelemetryRecorder:
    """world_offsets: {drone_name: (x, y, z)} - each drone's real-world spawn
    point. Skills/adapters report position in the drone's own LOCAL frame
    (its own (0,0,*) is its own spawn point, the convention since Phase 1),
    but everything the scorer checks (sectors, no-fly zones, separation) is
    defined in one shared WORLD frame. Adding the offset here, once, at the
    recording boundary, means neither the skills nor the scorer ever have to
    think about the other's coordinate frame."""

    def __init__(self, adapters: Dict[str, object], world_offsets: Dict[str, Tuple[float, float, float]] = None,
                 rate_hz: float = SAMPLE_RATE_HZ):
        self.adapters = adapters
        self.world_offsets = world_offsets or {name: (0.0, 0.0, 0.0) for name in adapters}
        self.interval = 1.0 / rate_hz
        self.log: Dict[str, List[Sample]] = {name: [] for name in adapters}
        self._start_time = None
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.is_set():
            t = time.monotonic() - self._start_time
            for name, adapter in self.adapters.items():
                try:
                    local = adapter.get_position()
                except Exception:
                    # Most commonly: this drone hasn't finished connect_and_takeoff()
                    # yet (no ground reference recorded), which is a normal transient
                    # state early in a run, not a reason to kill sampling for every
                    # drone for the rest of the mission. Skip this one tick for this
                    # drone and try again next tick.
                    continue
                off = self.world_offsets[name]
                world = (local[0] + off[0], local[1] + off[1], local[2] + off[2])
                self.log[name].append(Sample(t, world))
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
