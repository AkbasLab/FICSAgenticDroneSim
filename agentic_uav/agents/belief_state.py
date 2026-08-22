"""Per-agent local belief state (Phase 5, restructured in Phase 6).

One drone's persistent memory, held as an explicit structured object rather than
an LLM conversation transcript. It is organised into the Phase 6.1 sections -
`self`, `mission`, `local_map`, `team`, `communication`, `assumptions` - each
defined in belief_schema.py.

Two rules this class exists to enforce:

  1. *Belief is not truth.* Everything in here arrived through local sensing or a
     received message. The agent has no access to the simulator's ground truth,
     so a "decentralized" agent cannot accidentally read global state
     (see simulator/ground_truth.py).

  2. *Beliefs age.* Anything learned from a teammate carries a timestamp, source,
     confidence and expiry, so an old position report is never mistaken for a
     current one.

The Phase 5 flat accessors (`belief.position`, `belief.low_battery`, ...) are kept
as properties over the new sections, so the policy, guardian and agent loop did
not have to change when the structure was introduced.
"""

from collections import deque

from ..core.models import Position3D
from .belief_schema import (
    Assumption, CommunicationBelief, LocalMap, MissionBelief, Provenance,
    SelfBelief, Source, TeamBelief,
)
from .objectives import AgentEvent


class BeliefState:
    def __init__(self, vehicle_id, home, battery_total_s,
                 cruise_altitude=-8.0, low_battery_frac=0.30,
                 critical_battery_frac=0.12, home_tolerance_m=2.0):
        self.home = home
        self.cruise_altitude = cruise_altitude
        self.low_battery_frac = low_battery_frac
        self.critical_battery_frac = critical_battery_frac
        self.home_tolerance_m = home_tolerance_m

        # --- the structured sections (Phase 6.1) ---
        self.self_ = SelfBelief(
            vehicle_id=vehicle_id,
            position=Position3D(home.x, home.y, home.z),
            battery_remaining_s=float(battery_total_s),
            battery_total_s=float(battery_total_s))
        self.mission = MissionBelief()
        self.local_map = LocalMap()
        self.team = TeamBelief()
        self.communication = CommunicationBelief()
        self.assumptions = []

        # --- task progress (this agent's own bookkeeping) ---
        self.task = None
        self.at_sector = False
        self.sector_searched = False
        self.reported = False
        self.rtb_forced = False
        self.nav_failures = 0

        # --- bookkeeping ---
        self.last_result = None
        self.last_objective = None
        self.now = 0.0
        self._battery_low_fired = False
        self._battery_critical_fired = False
        self._events = deque()
        self.history = []

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

    # --- task / briefing ---

    def assign_task(self, task):
        self.task = task
        self.self_.current_task = task.task_id
        self.mission.mission_id = task.task_id
        self.mission.objective = f"search {task.sector.sector_id} and report"
        self.push(AgentEvent.TASK_ASSIGNED, task.task_id)

    def brief(self, scenario):
        """Pre-launch briefing: what the agent is *told* before it flies.

        Restricted zones and the deadline are legitimately known up front. Target
        positions are NOT briefed - those must be discovered by sensing.
        """
        self.mission.deadline_s = scenario.mission.deadline_s
        self.mission.constraints = {
            "min_separation_m": scenario.mission.min_separation_m,
            "required_coverage": scenario.mission.required_coverage,
        }
        self.local_map.restricted_zones = list(scenario.restricted_zones)
        self.communication.base_reachable = True

    # --- observe (perception step) ---

    def observe(self, position, elapsed_s):
        """Update from a fresh observation of *this* drone's own state."""
        self.now = elapsed_s
        self.self_.position = position
        self.self_.battery_remaining_s = self.self_.battery_total_s - elapsed_s

        if self.critical_battery and not self._battery_critical_fired:
            self._battery_critical_fired = True
            self.push(AgentEvent.BATTERY_CRITICAL, f"{self.battery_frac:.0%}")
        elif self.low_battery and not self._battery_low_fired:
            self._battery_low_fired = True
            self.push(AgentEvent.BATTERY_LOW, f"{self.battery_frac:.0%}")

    def note_detections(self, target_ids, positions=None, source=Source.SELF_SENSING):
        """Record targets this drone has actually sensed."""
        positions = positions or {}
        for tid in target_ids:
            prov = Provenance(timestamp=self.now, source=source, confidence=1.0)
            if self.local_map.note_target(tid, positions.get(tid), prov):
                self.push(AgentEvent.TARGET_DETECTED, tid)

    def note_searched(self, region_id, footprint, coverage=1.0):
        self.local_map.mark_searched(region_id, footprint, self.now,
                                     self.self_.vehicle_id, coverage)

    # --- messages from teammates (the only other way beliefs enter) ---

    def receive_teammate_report(self, vehicle_id, position=None, role=None,
                                task=None, status=None, sent_at=None,
                                source=Source.PEER_MESSAGE, confidence=1.0):
        """Fold a peer's report into the team section, stamped and expiring.

        Only raises MESSAGE_RECEIVED when the report *changes mission state* - a
        peer we hadn't heard from, or one whose status/role/task changed. A
        routine position refresh updates the record but must not trigger a
        replan, or the agent would re-decide on every sensing tick (5.2).
        """
        sent_at = self.now if sent_at is None else sent_at
        prior = self.team.teammates.get(vehicle_id)
        material = (
            prior is None
            or (status is not None and status != prior.status)
            or (role is not None and role != prior.current_role)
            or (task is not None and task != prior.current_task)
        )
        rec = self.team.update(vehicle_id, now=sent_at, source=source,
                               position=position, role=role, task=task,
                               status=status, confidence=confidence)
        if material:
            self.push(AgentEvent.MESSAGE_RECEIVED, vehicle_id)
        return rec

    def assume(self, statement, evidence, confidence=0.5):
        a = Assumption(statement=statement, evidence=evidence,
                       timestamp=self.now, confidence=confidence)
        self.assumptions.append(a)
        return a

    # --- verify (record the outcome of a skill) ---

    def record(self, result):
        from ..core.enums import SkillStatus
        self.last_result = result
        self.self_.current_skill = result.skill
        if result.status is SkillStatus.SUCCESS:
            self.push(AgentEvent.SKILL_SUCCEEDED, result.skill)
        elif result.status is SkillStatus.TIMEOUT:
            self.push(AgentEvent.SKILL_TIMEOUT, result.skill)
        else:
            self.push(AgentEvent.SKILL_FAILED, result.skill)

    # --- Phase 5 flat accessors, now views over the structured sections ---

    @property
    def vehicle_id(self):
        return self.self_.vehicle_id

    @property
    def position(self):
        return self.self_.position

    @position.setter
    def position(self, value):
        self.self_.position = value

    @property
    def airborne(self):
        return self.self_.airborne

    @airborne.setter
    def airborne(self, value):
        self.self_.airborne = value

    @property
    def landed(self):
        return self.self_.landed

    @landed.setter
    def landed(self, value):
        self.self_.landed = value

    @property
    def battery_total_s(self):
        return self.self_.battery_total_s

    @property
    def battery_remaining_s(self):
        return self.self_.battery_remaining_s

    @property
    def detections(self):
        return self.local_map.target_ids

    @property
    def battery_frac(self):
        return self.self_.battery_frac

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

    # --- introspection: what do I know, and what don't I know? (6.3 / exit criterion) ---

    def known(self):
        """A serialisable snapshot of everything this agent currently believes."""
        s = self.self_
        return {
            "self": {
                "vehicle_id": s.vehicle_id,
                "position": _pt(s.position),
                "battery_frac": round(s.battery_frac, 3),
                "health": s.health,
                "current_skill": s.current_skill,
                "current_task": s.current_task,
                "airborne": s.airborne,
                "landed": s.landed,
            },
            "mission": {
                "mission_id": self.mission.mission_id,
                "objective": self.mission.objective,
                "deadline_s": self.mission.deadline_s,
                "progress": {
                    "at_sector": self.at_sector,
                    "sector_searched": self.sector_searched,
                    "reported": self.reported,
                },
            },
            "local_map": {
                "searched_regions": self.local_map.searched_ids,
                "observed_targets": self.local_map.target_ids,
                "known_hazards": len(self.local_map.known_hazards),
                "restricted_zones": [getattr(z, "zone_id", "?")
                                     for z in self.local_map.restricted_zones],
            },
            "team": {
                vid: {
                    "last_position": _pt(r.last_position),
                    "current_role": r.current_role,
                    "current_task": r.current_task,
                    "status": r.status,
                    "age_s": round(r.age(self.now), 1),
                    "status_confidence": round(r.status_confidence(self.now), 2),
                    "stale": r.is_stale(self.now),
                }
                for vid, r in self.team.teammates.items()
            },
            "communication": {
                "estimated_latency_s": self.communication.estimated_latency_s,
                "recent_loss_rate": self.communication.recent_loss_rate,
                "connected_peers": list(self.communication.connected_peers),
                "base_reachable": self.communication.base_reachable,
            },
            "assumptions": [a.to_dict() for a in self.assumptions],
        }

    def unknown(self, roster=None, all_sectors=None):
        """What this agent explicitly does NOT know right now.

        This is the other half of the exit criterion: a decision log is only
        auditable if it shows the gaps as well as the knowledge. `roster` and
        `all_sectors` are the *names* the agent was briefed on - not their
        contents - so asking the question leaks nothing.
        """
        gaps = []
        for vid in (roster or []):
            if vid == self.vehicle_id:
                continue
            rec = self.team.teammates.get(vid)
            if rec is None:
                gaps.append(f"no information about {vid}")
            elif rec.is_expired(self.now):
                gaps.append(f"{vid} information expired "
                            f"({rec.age(self.now):.0f}s old)")
            elif rec.is_stale(self.now):
                gaps.append(f"{vid} position is stale "
                            f"({rec.age(self.now):.0f}s old, "
                            f"confidence {rec.status_confidence(self.now):.2f})")
        for sid in (all_sectors or []):
            if sid not in self.local_map.searched_ids:
                gaps.append(f"sector {sid} not searched by me")
        if not self.communication.base_reachable:
            gaps.append("base station unreachable")
        if not self.local_map.observed_targets:
            gaps.append("no targets observed yet")
        return gaps


def _pt(p):
    if p is None:
        return None
    return [round(p.x, 2), round(p.y, 2), round(p.z, 2)]
