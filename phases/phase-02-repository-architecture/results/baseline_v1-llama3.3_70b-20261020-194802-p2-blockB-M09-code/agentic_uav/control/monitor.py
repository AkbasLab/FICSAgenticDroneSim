"""Polls separation and collisions while a mission flies.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 3. Only
calls to the AirSim client were changed, to calls on the adapter;
`tests/test_golden.py` proves the simulator sees the same calls as before.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from ..simulator.adapter import VehicleAdapter
from .contacts import classify_contact, is_ground


class SeparationMonitor:
    """Samples inter-drone distance AND collisions while a mission flies.

    Section 1.3 asks for "collision or proximity events". NEITHER is visible from
    the start and end states: the closest approach happens in between, and
    AirSim keeps only the most recent collision, which the landing overwrites.
    Both have to be watched while the flight is happening.

    Runs in its own thread at a fixed interval and keeps only the minimum
    separation seen and when it happened -- enough to answer "did they come
    dangerously close", without writing a position trace per sample.

    There is no collision avoidance anywhere in this stack. Vertical staggering
    and spawn spacing are the only separation M09 and M10 have, so this is the
    measurement that says whether that was enough.
    """

    def __init__(self, adapter: VehicleAdapter, names: list[str], interval: float = 0.1) -> None:
        # Its OWN adapter, so its own connection: it polls while the flight
        # threads command, and a shared client fails under that.
        self.adapter = adapter
        self.names = names
        self.interval = interval
        self.min_distance: float | None = None
        self.min_at: float | None = None
        # Per pair as well as overall. M10 reported a single 4.0 m minimum for a
        # flight in which two drones interpenetrated by 0.115 m, because one
        # overall figure cannot say WHICH pair was close, and the pair that
        # collided was not the pair that set the minimum. Six pairs at four
        # drones, and only one of them mattered.
        self.pair_min: dict[str, float] = {}
        self.pair_min_at: dict[str, float] = {}
        # Collisions have to be polled for the same reason proximity does: the
        # end state does not contain them. `simGetCollisionInfo` returns only the
        # MOST RECENT collision, and every flight that lands ends touching the
        # ground, so a single read after teardown can never see a mid-flight
        # collision -- it has already been overwritten. Measured 2026-10-06: a
        # 10 Hz trace caught Drone1 and Drone3 in contact in two of three M10
        # runs, penetration to 0.152 m, while all three records said
        # `collision: false`. The pre-fix M10 recorded that same contact only
        # because the flight never landed.
        self._by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        self._seen: set[tuple[str, Any]] = set()
        self.samples = 0
        self.errors = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def _positions(self) -> dict[str, tuple[float, float, float]]:
        found = {}
        for name in self.names:
            p = self.adapter.get_state(name).position
            found[name] = (p.x, p.y, p.z)
        return found

    def _collisions(self) -> None:
        """Record every distinct collision, once each, as it happens."""
        for name in self.names:
            info = self.adapter.get_collision(name)
            if not getattr(info, "has_collided", False):
                continue
            stamp = getattr(info, "time_stamp", None)
            if (name, stamp) in self._seen:
                continue
            self._seen.add((name, stamp))
            obj = getattr(info, "object_name", "") or ""
            at = round(time.time() - self._started, 2)
            pen = round(float(getattr(info, "penetration_depth", 0.0)), 3)
            # Collapsed per (drone, object). Sustained contact produces a new
            # timestamp every poll: one stalled flight on 2026-10-06 recorded
            # 3256 events, which would bury the record it is meant to inform.
            # First seen, last seen, how many and the worst penetration say
            # everything those 3256 rows said.
            existing = self._by_pair.get((name, obj))
            if existing is None:
                self._by_pair[(name, obj)] = {
                    "drone": name,
                    "object": obj,
                    "kind": classify_contact(obj, self.names),
                    "is_ground": is_ground(obj),
                    "events": 1,
                    "first_at_s": at,
                    "last_at_s": at,
                    "max_penetration_depth": pen,
                }
            else:
                existing["events"] += 1
                existing["last_at_s"] = at
                existing["max_penetration_depth"] = max(
                    existing["max_penetration_depth"], pen)

    @property
    def contacts(self) -> list[dict[str, Any]]:
        """One row per (drone, object) pair, in the order first seen."""
        return sorted(self._by_pair.values(), key=lambda c: c["first_at_s"])

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._collisions()
                positions = self._positions()
                self.samples += 1
                names = list(positions)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        a, b = positions[names[i]], positions[names[j]]
                        distance = math.dist(a, b)
                        at = round(time.time() - self._started, 1)
                        pair = f"{names[i]}-{names[j]}"
                        if distance < self.pair_min.get(pair, float("inf")):
                            self.pair_min[pair] = distance
                            self.pair_min_at[pair] = at
                        if self.min_distance is None or distance < self.min_distance:
                            self.min_distance = distance
                            self.min_at = at
            except Exception:
                # A sampling failure must never disturb a flight; count it so a
                # monitor that silently failed cannot look like a clean run.
                self.errors += 1
            self._stop.wait(self.interval)

    def start(self) -> None:
        # Runs for a single drone too. Separation needs two, but collisions need
        # only one, and a single-drone mission was previously unpolled -- so the
        # 24 single-drone runs flown on 2026-10-06 cannot support a collision
        # claim either.
        if not self.names:
            return
        self._started = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        return {
            "measured": self._thread is not None,
            "samples": self.samples,
            "sample_errors": self.errors,
            "min_separation_m": None if self.min_distance is None else round(self.min_distance, 2),
            "min_separation_at_s": self.min_at,
            "interval_s": self.interval,
            "per_pair_min_m": {k: round(v, 2) for k, v in sorted(self.pair_min.items())},
            "per_pair_min_at_s": dict(sorted(self.pair_min_at.items())),
            "collisions_polled": self.contacts,
            "drone_collisions": [c for c in self.contacts if c["kind"] == "drone"],
            "obstacle_collisions": [c for c in self.contacts if c["kind"] == "obstacle"],
        }
