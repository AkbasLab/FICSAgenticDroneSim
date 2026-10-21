"""Where trajectories come from: exactly, from the mock; by polling, from a live simulator.

    trajs = mock_trajectories(world)                       # exact

    observer = PollingObserver(connect, drones, grounds)   # live, in real time
    observer.start(); ...fly...; observer.stop()
    trajs = observer.trajectories()

Both give `Trajectory` objects in the mission's frame -- map x, y, and
altitude above the measured ground -- so `mission_world.observe` judges a
mock flight and a CarlaAir flight by the same code. They differ in how much
they can know, and the record says which was used:

* THE MOCK is exact. Its `trace` holds a knot before and after every change
  of motion, and motion between them is straight and constant. Nothing is
  missed, however brief.
* A POLLER sees samples, `hz` times a second, and joins them with straight
  lines. Between samples it can miss things: a 0.1 s corner clipped off a
  restricted zone, a closest approach between two polls. Airborne is decided
  from height (above `airborne_above_m`), since nothing else is reported
  reliably. It is the observer for a live run; on the mock the trace is used.
  It keeps the raw NED samples, so the grounds may be given after the flight
  -- the ones each drone's TAKE_OFF measured -- and a saved flight can be
  turned into trajectories again (`trajectories_from_samples`).

The poller reads with its own adapter, as every thread does (Phase 1: one
connection per thread), and never commands anything.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..core.clock import Clock, RealClock, SimClock
from .mock_adapter import MockWorld
from .trajectory import Knot, Trajectory

DEFAULT_POLL_HZ = 10.0
# Above this, a polled drone is flying. NOT a small margin: CarlaAir reports
# a LANDED drone 1.16-1.17 m above the ground its take-off measured (Phase 3,
# live; v6 the same), so anything under that height would call every landed
# drone airborne. 3 m is the skill layer's own line, `skills.LANDED_ALTITUDE_M`
# ("above this, LAND did not land"), repeated rather than imported:
# simulator/ depends on core/ only. The cost: the first and last 3 m of each
# flight count as ground, a second or two of hover drain at 2 m/s climb.
DEFAULT_AIRBORNE_ABOVE_M = 3.0


def _altitude(z: float, ground_z: float) -> float:
    # NED up is negative z. The same conversion as control.navigation.z_to_altitude,
    # repeated rather than imported: simulator/ depends on core/ only.
    return ground_z - z


Sample = tuple[float, float, float, float]       # t, x, y, NED z


def trajectories_from_samples(samples: dict[str, list[Sample]] | dict[str, list[list[float]]],
                              grounds: dict[str, float],
                              airborne_above_m: float = DEFAULT_AIRBORNE_ABOVE_M) -> dict[str, Trajectory]:
    """Trajectories from polled NED samples and each drone's measured ground."""
    missing = [d for d in samples if d not in grounds]
    if missing:
        raise ValueError(f"no measured ground for {missing}")
    out = {}
    for drone, rows in samples.items():
        if rows:
            knots = []
            for t, x, y, z in rows:
                altitude = _altitude(z, grounds[drone])
                knots.append(Knot(t, x, y, altitude, altitude > airborne_above_m))
            out[drone] = Trajectory(drone, knots)
    return out


def mock_trajectories(world: MockWorld, drones: list[str] | tuple[str, ...] | None = None,
                      until_now: bool = False) -> dict[str, Trajectory]:
    """Every (or each named) mock drone's exact trajectory so far.

    The trace has a knot at every change of motion, so mid-move its last knot
    is where the move began. `until_now` adds a knot at the present instant,
    where the drone is now, which is what a reading taken in flight needs; a
    finished flight does not.
    """
    names = list(world.vehicles) if drones is None else list(drones)
    out = {}
    with world.lock:                         # trace and present position at one instant
        now = world.clock.now()
        for name in names:
            knots = [Knot(t, p.x, p.y, _altitude(p.z, world.ground_z), airborne)
                     for t, p, airborne in world.trace(name)]
            if until_now and (not knots or now > knots[-1].t):
                p = world.position(name)
                knots.append(Knot(now, p.x, p.y, _altitude(p.z, world.ground_z),
                                  not world.vehicles[name].landed))
            out[name] = Trajectory(name, knots)
    return out


class PollingObserver:
    """Samples every drone's pose on its own thread until stopped.

    `grounds` is each drone's measured ground in NED (the executor's ground
    reference), so altitude is above the ground the drone stands on, as
    Phase 1 measured it varies. It may be given here or to `trajectories()`
    after the flight.
    """

    def __init__(self, connect: Callable[[], object], drones: list[str] | tuple[str, ...],
                 grounds: dict[str, float] | None = None, clock: Clock | None = None,
                 hz: float = DEFAULT_POLL_HZ,
                 airborne_above_m: float = DEFAULT_AIRBORNE_ABOVE_M) -> None:
        clock = clock if clock is not None else RealClock()
        if isinstance(clock, SimClock):
            # A lone participant's sleeps would run simulated time away
            # before and after the flight; the mock's trace is exact anyway.
            raise ValueError("PollingObserver is for real time; on the mock use mock_trajectories()")
        if hz <= 0:
            raise ValueError("poll rate must be positive")
        missing = [d for d in drones if grounds is not None and d not in grounds]
        if missing:
            raise ValueError(f"no measured ground for {missing}")
        self.connect = connect
        self.drones = tuple(drones)
        self.grounds = None if grounds is None else dict(grounds)
        self.clock = clock
        self.period = 1.0 / hz
        self.airborne_above_m = airborne_above_m
        self._samples: dict[str, list[Sample]] = {d: [] for d in self.drones}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("this observer has already been started")
        self._thread = threading.Thread(target=self._run, name="observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Take one last sample, stop, and raise if polling failed."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self._error is not None:
            raise RuntimeError(f"the observer failed: {type(self._error).__name__}: {self._error}") \
                from self._error

    def sample(self, adapter) -> None:
        """One poll of every drone, each stamped when it was read."""
        for drone in self.drones:
            p = adapter.get_pose(drone)
            t = self.clock.now()
            with self._lock:
                self._samples[drone].append((t, p.x, p.y, p.z))

    def samples(self) -> dict[str, list[Sample]]:
        """The raw polls, NED, per drone: what a record keeps."""
        with self._lock:
            return {d: list(rows) for d, rows in self._samples.items()}

    def trajectories(self, grounds: dict[str, float] | None = None) -> dict[str, Trajectory]:
        grounds = grounds if grounds is not None else self.grounds
        if grounds is None:
            raise ValueError("no grounds: give them to the observer or to trajectories()")
        return trajectories_from_samples(self.samples(), grounds, self.airborne_above_m)

    def _run(self) -> None:
        try:
            adapter = self.connect()
            while not self._stop.is_set():
                began = self.clock.now()
                self.sample(adapter)
                self._stop.wait(max(0.0, self.period - (self.clock.now() - began)))
            self.sample(adapter)
        except BaseException as exc:            # reported by stop(), never silent
            self._error = exc
