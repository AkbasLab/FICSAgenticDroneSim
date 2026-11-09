"""Where every aircraft of the fleet is and how fast it is moving, for a planner that avoids the others (NavRL).

This is peer state as a real swarm would broadcast it: each aircraft announces its own position and velocity several times a
second. Here it is read straight from every drone's adapter (the simulator's own telemetry), refreshed at most every
`refresh_s`, so it is as fresh as an ideal broadcast and not delayed or lost like the messages on the mission's bus.
"""

import threading
import time
from typing import Dict, List, Tuple


class FleetStates:
    def __init__(self, adapters: Dict[str, object], offsets: Dict[str, tuple], refresh_s: float = 0.2):
        self.adapters, self.offsets, self.refresh_s = adapters, offsets, refresh_s
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._state: Dict[str, Tuple[float, float, float, float]] = {}   # name -> (x, y, vx, vy) in world metres
        self._seen: Dict[str, Tuple[float, float, float]] = {}            # name -> (t, x, y) at the previous refresh

    def _refresh(self):
        now = time.monotonic()
        if now - self._last_refresh < self.refresh_s:
            return
        for name, adapter in self.adapters.items():
            try:
                x, y, _ = adapter.get_position()
            except Exception:
                continue
            ox, oy = self.offsets[name][0], self.offsets[name][1]
            wx, wy = x + ox, y + oy
            vx = vy = 0.0
            previous = self._seen.get(name)
            if previous is not None and now - previous[0] > 1e-3:
                vx, vy = (wx - previous[1]) / (now - previous[0]), (wy - previous[2]) / (now - previous[0])
            self._seen[name] = (now, wx, wy)
            self._state[name] = (wx, wy, vx, vy)
        self._last_refresh = now

    def peers_of(self, adapter) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """[((x, y), (vx, vy)), ...] of every aircraft except this adapter's own, world metres and m/s."""
        with self._lock:
            self._refresh()
            return [((s[0], s[1]), (s[2], s[3])) for name, s in self._state.items() if self.adapters[name] is not adapter]
