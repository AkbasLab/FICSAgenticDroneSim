"""Per-agent local belief state (Phase 5).

What one drone believes about itself and its task: where it is, how much battery
is left, which task it holds, how far through it is, what it has detected, and a
queue of events that have happened since the last decision. The policy reads the
belief to decide; the agent writes to it from observations and skill results.

It is deliberately *local* - no global truth, no direct teammate state yet - so
the multi-agent phase can extend it (teammates, messages) without changing how a
single agent reasons.
"""

from collections import deque

from ..core.models import Position3D
from .objectives import AgentEvent


class BeliefState:
    def __init__(self, vehicle_id, home, battery_total_s,
                 cruise_altitude=-8.0, low_battery_frac=0.30,
                 critical_battery_frac=0.12, home_tolerance_m=2.0):
        self.vehicle_id = vehicle_id
        self.home = home
        self.cruise_altitude = cruise_altitude

        # self-state
        self.position = Position3D(home.x, home.y, home.z)
        self.airborne = False
        self.landed = False

        # battery
        self.battery_total_s = float(battery_total_s)
        self.battery_remaining_s = float(battery_total_s)
        self.low_battery_frac = low_battery_frac
        self.critical_battery_frac = critical_battery_frac
        self._battery_low_fired = False
        self._battery_critical_fired = False

        # task + progress
        self.task = None
        self.at_sector = False
        self.sector_searched = False
        self.reported = False
        self.rtb_forced = False           # a safety guard forced return-to-base
        self.nav_failures = 0             # consecutive nav failures (for recovery)

        # observations
        self.detections = []              # target ids this agent has found

        # bookkeeping
        self.last_result = None
        self.last_objective = None
        self._events = deque()
        self.history = []                 # (event/objective, detail) log
        self.home_tolerance_m = home_tolerance_m

    # --- events ---

    def push(self, event, detail=""):
        self._events.append((event, detail))
        self.history.append((event.value, detail))

    def has_events(self):
        return len(self._events) > 0

    def drain_events(self):
        evs = list(self._events)
        self._events.clear()
        return evs

    # --- task ---

    def assign_task(self, task):
        self.task = task
        self.push(AgentEvent.TASK_ASSIGNED, task.task_id)

    # --- observe (perception step) ---

    def observe(self, position, elapsed_s):
        """Update from a fresh observation of the world."""
        self.position = position
        self.battery_remaining_s = self.battery_total_s - elapsed_s

        if self.critical_battery and not self._battery_critical_fired:
            self._battery_critical_fired = True
            self.push(AgentEvent.BATTERY_CRITICAL,
                      f"{self.battery_frac:.0%}")
        elif self.low_battery and not self._battery_low_fired:
            self._battery_low_fired = True
            self.push(AgentEvent.BATTERY_LOW, f"{self.battery_frac:.0%}")

    def note_detections(self, target_ids):
        for tid in target_ids:
            if tid not in self.detections:
                self.detections.append(tid)
                self.push(AgentEvent.TARGET_DETECTED, tid)

    # --- verify (record the outcome of a skill) ---

    def record(self, result):
        self.last_result = result
        from ..core.enums import SkillStatus
        if result.status is SkillStatus.SUCCESS:
            self.push(AgentEvent.SKILL_SUCCEEDED, result.skill)
        elif result.status is SkillStatus.TIMEOUT:
            self.push(AgentEvent.SKILL_TIMEOUT, result.skill)
        else:
            self.push(AgentEvent.SKILL_FAILED, result.skill)

    # --- derived facts the policy reads ---

    @property
    def battery_frac(self):
        if self.battery_total_s <= 0:
            return 0.0
        return max(0.0, self.battery_remaining_s / self.battery_total_s)

    @property
    def low_battery(self):
        return self.battery_frac <= self.low_battery_frac

    @property
    def critical_battery(self):
        return self.battery_frac <= self.critical_battery_frac

    @property
    def near_home(self):
        return self.position.horizontal_distance_to(self.home) <= self.home_tolerance_m

    @property
    def mission_complete(self):
        return self.reported and self.landed and self.near_home
