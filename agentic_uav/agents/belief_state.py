"""What one drone believes: AUV-06's six blocks (6.1).

    belief = BeliefState.start(brief, "Drone1", first_observation)
    changes = belief.update(observation)          # facts that changed, for the event detector
    belief.assume("speed", "the drone makes 2.5 m/s", "measured over 40 s", at=t, confidence=0.9)
    belief.snapshot()                             # for the decision trace

THE SIX BLOCKS (AUV-06, 6.1):

* `self`: position, velocity, heading, battery, health, the current skill
  and task, home, the base link.
* `mission`: id, objective, constraints, deadline, progress.
* `local_map`: searched regions, observed and reported targets, known
  hazards, restricted zones.
* `team`: one entry per teammate on the brief's roster. Phase 6 leaves every
  entry "never heard": nothing yet carries a teammate's state to this drone.
  Phase 7's messages fill it.
* `communication`: whether the base is reachable, from sensing. Latency,
  loss rate and connected peers are UNKNOWN until Phase 7 measures them, and
  are held as None, never as zero: a zero would claim a perfect link.
* `assumptions`: what the agent is taking to be true, on what evidence, since
  when, how confidently. One per key; a newer one replaces the older.

EVERY FIELD COMES FROM A READING OR FROM THE AGENT ITSELF. Position,
airborne, battery, sightings and the base link from `core.sensing`; the
current skill and health from the agent's own executor; the task, progress
and assumptions from its own decisions; zones, constraints, deadline,
reserve and the roster from the public brief. Velocity and heading are
ESTIMATES, from the drone's own successive positions, and say so. Nothing
here can hold ground truth, because nothing that holds it is in reach
(`agents/__init__.py`, enforced by test).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..core.geometry import Region
from ..core.scenario import MissionBrief
from ..core.sensing import Sighting

SCHEMA_VERSION = 2                     # 1 was Phase 5's three blocks
ESTIMATED = "estimated from own positions"
HEADING_MIN_SPEED_MPS = 0.2            # slower than this, the heading is not known
FAILED_STATUSES = ("failed", "timeout")


@dataclass(frozen=True)
class Observation:
    """One tick's readings, plus what the agent's own executor says."""

    at: float
    x: float
    y: float
    altitude_m: float
    airborne: bool
    battery: float
    sightings: tuple[Sighting, ...]
    base_link: bool
    skill: str | None                  # the skill running now, if any
    last_skill_serial: int             # 0 before any
    last_skill_status: str | None      # how the latest skill ended, or None while it runs
    last_skill: str | None = None      # the latest skill's name, running or ended


@dataclass
class Health:
    """What the drone's own skill results say about it."""

    skill_failures: int = 0            # skills that ended failed or timed out
    last_failure: str | None = None    # "<skill> <status>"
    last_failure_at: float | None = None
    degraded: bool = False             # the latest skill to end failed


@dataclass
class SelfBelief:
    vehicle_id: str
    x: float
    y: float
    altitude_m: float
    airborne: bool
    battery: float
    home: tuple[float, float]
    base_link: bool
    current_skill: str | None = None
    current_task: str | None = None
    updated_at: float = 0.0
    velocity: tuple[float, float, float] | None = None    # vx, vy, climb rate; None until two readings
    heading_deg: float | None = None                       # 0 = +x, 90 = +y; None when slower than the floor
    health: Health = field(default_factory=Health)


@dataclass
class MissionBelief:
    mission_id: str
    objective: str | None              # what the agent is working towards now
    deadline_at: float                 # absolute clock time
    reserve: float
    progress: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalMap:
    searched_regions: list[Region] = field(default_factory=list)
    observed_targets: dict[str, Sighting] = field(default_factory=dict)
    known_hazards: list[str] = field(default_factory=list)
    reported_targets: set[str] = field(default_factory=set)   # seen while the base was in reach
    restricted_zones: dict[str, tuple[tuple[float, float], ...]] = field(default_factory=dict)


@dataclass
class TeamBelief:
    """One entry per teammate on the roster; None means never heard from."""

    members: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommunicationBelief:
    base_reachable: bool
    base_reachable_since: float        # when the base link last changed (or was first read)
    estimated_latency_s: float | None = None      # unknown until Phase 7
    recent_loss_rate: float | None = None         # unknown until Phase 7
    connected_peers: tuple[str, ...] | None = None    # unknown until Phase 7


@dataclass(frozen=True)
class Assumption:
    key: str
    statement: str
    evidence: str
    at: float
    confidence: float                  # 0..1, the agent's own


@dataclass
class BeliefState:
    self_: SelfBelief
    mission: MissionBelief
    local_map: LocalMap
    brief: MissionBrief
    team: TeamBelief = field(default_factory=TeamBelief)
    communication: CommunicationBelief | None = None
    assumptions: dict[str, Assumption] = field(default_factory=dict)
    skill_serial_seen: int = field(default=0, repr=False)      # the last ended skill counted in health

    @classmethod
    def start(cls, brief: MissionBrief, vehicle_id: str, first: Observation) -> "BeliefState":
        """A fresh belief: home is where the drone stands at the first observation."""
        me = SelfBelief(vehicle_id, first.x, first.y, first.altitude_m, first.airborne, first.battery,
                        (first.x, first.y), first.base_link, first.skill, None, first.at)
        constraints = {"restricted_zones": [z.id for z in brief.restricted_zones],
                       "reserve": brief.battery.reserve,
                       "min_separation_m": brief.safety.min_separation_m,
                       "deadline_s": brief.mission.deadline_s}
        mission = MissionBelief(brief.scenario_id, None, first.at + brief.mission.deadline_s,
                                brief.battery.reserve, constraints=constraints)
        local_map = LocalMap(restricted_zones={z.id: z.polygon.vertices for z in brief.restricted_zones})
        team = TeamBelief({v.id: None for v in brief.vehicles if v.id != vehicle_id})
        belief = cls(me, mission, local_map, brief, team, CommunicationBelief(first.base_link, first.at))
        belief.update(first)
        return belief

    def update(self, obs: Observation) -> dict[str, Any]:
        """Take in one observation; return what changed that an agent may care about."""
        me = self.self_
        changes: dict[str, Any] = {}
        new = [s for s in obs.sightings if s.label not in self.local_map.observed_targets]
        for s in new:
            self.local_map.observed_targets[s.label] = s
        if new:
            changes["new_sightings"] = [s.label for s in new]
        if obs.base_link != me.base_link:
            changes["base_link"] = obs.base_link
            self.communication.base_reachable_since = obs.at
        if obs.battery < me.battery:
            changes["battery_from"] = me.battery
        if obs.base_link:
            # Connected now: everything seen so far has reached the base.
            self.local_map.reported_targets.update(self.local_map.observed_targets)
        self._estimate_motion(obs)
        self._note_skill_end(obs)
        me.x, me.y, me.altitude_m, me.airborne = obs.x, obs.y, obs.altitude_m, obs.airborne
        me.battery, me.base_link, me.current_skill, me.updated_at = obs.battery, obs.base_link, obs.skill, obs.at
        self.communication.base_reachable = obs.base_link
        return changes

    def assume(self, key: str, statement: str, evidence: str, at: float, confidence: float) -> Assumption:
        """Record what the agent is taking to be true; a newer assumption under `key` replaces the older."""
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {confidence}")
        held = Assumption(key, statement, evidence, at, confidence)
        self.assumptions[key] = held
        return held

    def drop_assumption(self, key: str) -> None:
        self.assumptions.pop(key, None)

    @property
    def time_left(self) -> float:
        return self.mission.deadline_at - self.self_.updated_at

    def snapshot(self) -> dict[str, Any]:
        """The belief as plain data, for the decision trace."""
        me, m, lm, c = self.self_, self.mission, self.local_map, self.communication
        now = me.updated_at
        h = me.health
        return {
            "schema": SCHEMA_VERSION,
            "self": {"vehicle_id": me.vehicle_id, "position": [round(me.x, 3), round(me.y, 3), round(me.altitude_m, 3)],
                     "velocity": _known([round(v, 3) for v in me.velocity] if me.velocity else None),
                     "heading_deg": _known(None if me.heading_deg is None else round(me.heading_deg, 1)),
                     "motion_source": ESTIMATED,
                     "airborne": me.airborne, "battery": round(me.battery, 3), "home": list(me.home),
                     "base_link": me.base_link, "current_skill": me.current_skill,
                     "current_task": me.current_task, "updated_at": round(me.updated_at, 3),
                     "health": {"degraded": h.degraded, "skill_failures": h.skill_failures,
                                "last_failure": h.last_failure,
                                "last_failure_at": None if h.last_failure_at is None else round(h.last_failure_at, 3)}},
            "mission": {"mission_id": m.mission_id, "objective": m.objective,
                        "deadline_in_s": round(self.time_left, 3), "reserve": m.reserve,
                        "constraints": dict(m.constraints), "progress": dict(m.progress)},
            "local_map": {"searched_regions": [[r.x_min, r.y_min, r.x_max, r.y_max] for r in lm.searched_regions],
                          "observed_targets": {k: [round(s.x, 3), round(s.y, 3), round(s.at, 3)]
                                               for k, s in sorted(lm.observed_targets.items())},
                          "reported_targets": sorted(lm.reported_targets),
                          "known_hazards": list(lm.known_hazards),
                          "restricted_zones": {k: [list(p) for p in v] for k, v in sorted(lm.restricted_zones.items())}},
            "team": {d: (rec if rec is not None else "never heard") for d, rec in sorted(self.team.members.items())},
            "communication": {"base_reachable": c.base_reachable,
                              "base_reachable_for_s": round(now - c.base_reachable_since, 3),
                              "estimated_latency_s": _known(c.estimated_latency_s),
                              "recent_loss_rate": _known(c.recent_loss_rate),
                              "connected_peers": _known(None if c.connected_peers is None else list(c.connected_peers))},
            "assumptions": [{"key": a.key, "statement": a.statement, "evidence": a.evidence,
                             "age_s": round(now - a.at, 3), "confidence": a.confidence}
                            for a in sorted(self.assumptions.values(), key=lambda a: a.key)],
        }

    # ------------------------------------------------------------ internal

    def _estimate_motion(self, obs: Observation) -> None:
        me = self.self_
        dt = obs.at - me.updated_at
        if dt <= 0:
            return
        vx, vy, vz = (obs.x - me.x) / dt, (obs.y - me.y) / dt, (obs.altitude_m - me.altitude_m) / dt
        me.velocity = (vx, vy, vz)
        me.heading_deg = (math.degrees(math.atan2(vy, vx)) % 360.0
                          if math.hypot(vx, vy) >= HEADING_MIN_SPEED_MPS else None)

    def _note_skill_end(self, obs: Observation) -> None:
        """Health from the agent's own skill results: each ended skill counted once."""
        h = self.self_.health
        if obs.last_skill_status is None or obs.last_skill_serial <= self.skill_serial_seen:
            return
        self.skill_serial_seen = obs.last_skill_serial
        h.degraded = obs.last_skill_status in FAILED_STATUSES
        if h.degraded:
            h.skill_failures += 1
            h.last_failure = f"{obs.last_skill or 'skill'} {obs.last_skill_status}"
            h.last_failure_at = obs.at


def _known(value: Any) -> Any:
    """A value, or the word 'unknown': never a made-up zero."""
    return "unknown" if value is None else value
