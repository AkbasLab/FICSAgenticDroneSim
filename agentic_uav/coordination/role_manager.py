"""Deterministic role selection and role change (Phase 9.1, 9.3).

Every agent runs this against its own belief. There is no role assigner: a drone
decides what it should be from what it can see, and announces the change. Two
agents with the same beliefs pick the same role, so the team's shape is
reproducible even though nothing coordinates it.

The rules, in priority order:

  1. No usable comms path to base and nobody is relaying -> become RELAY.
     Connectivity is worth more than another sector, because a searched sector
     nobody hears about is wasted work.
  2. The relay went silent and we were RESERVE -> take over as RELAY.
  3. Work is available and we have battery -> be a SCOUT.
  4. Nothing to do, or too little battery to start something new -> RESERVE.

`w_role` in the bidding function then does the rest: a RELAY bids poorly on
search tasks, so it stops being handed them without any special case.
"""

from dataclasses import dataclass
from typing import List, Optional

from .roles import HealthState, Role

# below this fraction, a drone should not take on new search work
ROLE_BATTERY_FLOOR = 0.35


@dataclass
class RoleDecision:
    role: Role
    reason: str
    changed: bool = False

    def __str__(self):
        return f"{self.role.value} ({self.reason})"


class RoleManager:
    """One agent's role policy. Deterministic given the agent's belief."""

    def __init__(self, vehicle_id, health_monitor=None,
                 battery_floor=ROLE_BATTERY_FLOOR, min_scouts=1):
        self.vehicle_id = vehicle_id
        self.health = health_monitor
        self.battery_floor = battery_floor
        self.min_scouts = min_scouts
        self.role = Role.SCOUT
        self.history = []          # (time, from, to, reason)

    # --- the policy ---

    def decide(self, belief, open_task_count=0, holding_task=False) -> RoleDecision:
        now = belief.now
        previous = self.role
        role, reason = self._select(belief, open_task_count, holding_task)

        changed = role is not previous
        if changed:
            self.role = role
            self.history.append((now, previous.value, role.value, reason))
        return RoleDecision(role=role, reason=reason, changed=changed)

    def _select(self, belief, open_task_count, holding_task):
        comms = belief.communication
        battery_ok = belief.battery_frac > self.battery_floor

        # 1. keeping the team connected outranks searching
        if not comms.base_reachable and not self._someone_is_relaying(belief):
            return Role.RELAY, "base unreachable and no relay active"

        # 2. the relay went quiet - if we are spare, cover it
        lost_relay = self._lost_relay(belief)
        if lost_relay and self.role is Role.RESERVE:
            return Role.RELAY, f"relay {lost_relay} presumed lost"

        # 2b. a scout with nothing to do can also cover a lost relay
        if lost_relay and not holding_task and open_task_count == 0:
            return Role.RELAY, f"relay {lost_relay} lost; no search work left"

        # 3. there is work and we can do it
        if holding_task:
            return Role.SCOUT, "holding a search task"
        if open_task_count > 0 and battery_ok:
            return Role.SCOUT, "search work available"

        # 4. otherwise stand by
        if not battery_ok:
            return Role.RESERVE, f"battery {belief.battery_frac:.0%} below floor"
        return Role.RESERVE, "no work available"

    # --- helpers over the agent's own belief ---

    def _someone_is_relaying(self, belief):
        for vid, rec in belief.team.teammates.items():
            if rec.current_role == Role.RELAY.value and self._alive(vid):
                return True
        return False

    def _lost_relay(self, belief) -> Optional[str]:
        """A teammate we believed was the relay, that we now think is gone."""
        if self.health is None:
            return None
        for vid, rec in belief.team.teammates.items():
            if rec.current_role == Role.RELAY.value and not self._alive(vid):
                return vid
        return None

    def _alive(self, vehicle_id):
        if self.health is None:
            return True
        return self.health.state_of(vehicle_id) not in (
            HealthState.UNREACHABLE, HealthState.FAILED)

    # --- reporting ---

    def capabilities_for(self, role: Role):
        """What a drone in this role is willing to bid on.

        A RELAY holds station, so it drops the `search` capability and stops
        winning sectors - the capability check in bidding does the work, no
        special-casing needed in the allocator.
        """
        if role is Role.RELAY:
            return {"relay"}
        if role is Role.RESERVE:
            return {"search", "relay", "inspect"}   # available for anything
        return {"search", "inspect"}

    def summary(self):
        return {"role": self.role.value,
                "changes": [{"t": round(t, 1), "from": a, "to": b, "why": why}
                            for (t, a, b, why) in self.history]}
