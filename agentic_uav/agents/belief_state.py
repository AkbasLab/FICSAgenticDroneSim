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
* `team`: one entry per teammate on the brief's roster, "never heard" until
  a `core.team.TeamReport` about it is received (`receive`). Nothing in a
  flight delivers one yet: Phase 7's messages will. See STALE INFORMATION.
* `communication`: whether the base is reachable, from sensing. Latency,
  loss rate and connected peers are UNKNOWN until Phase 7 measures them, and
  are held as None, never as zero: a zero would claim a perfect link.
* `assumptions`: what the agent is taking to be true, on what evidence, since
  when, how confidently. One per key; a newer one replaces the older.

STALE INFORMATION (6.3): "Agents must not treat an old position report as
current." Every teammate record carries the report's timestamp (when the
news was true at its source), its age now, its source, its confidence and
its expiration (`at + ttl_s`). Confidence falls linearly with age, from the
source's own value to zero at expiry. An expired record is KEPT, so the
agent can still say what it last heard and when, but `current_teammates()`
leaves it out and the snapshot marks it expired; the tick on which a record
expires reports it (`changes["team_expired"]`). A report older than the one
already held never replaces it: news arriving out of order is not newer.
A report about itself, about a drone not on the roster, or dated in the
future is refused, and the reason is returned.

THE LINK, ESTIMATED FROM WHAT WAS HEARD (Phase 7; AUV-10, 10.5). Once the
agent listens (`listening`), every message it takes in is noted (`heard`):
who sent it, its sequence number, when it was sent and when it arrived. From
those alone -- never from the network's settings -- the belief estimates
`connected_peers` (teammates heard within CONNECTED_WINDOW_S), the
`recent_loss_rate` (sequence numbers skipped, over those expected, across
the flight) and the `estimated_latency_s` (the mean of the last LATENCY_SAMPLES
arrivals). A message missed for any reason -- out of range or lost -- is a
gap; the agent cannot tell which, and does not pretend to. Until it has
heard something, loss and latency stay unknown; an agent that is not
listening keeps all three unknown, as in Phases 5 and 6.

WHAT THE POLICY READ (Phase 7, 7.4). A record keeps the message it came from,
and while a decision is being made the belief notes which teammate records
the policy looked at through `teammate()` and `current_teammates()`
(`start_reading`, `read`). The agent keeps those message ids with the
decision, so the message log can say not only that a message was in the
belief when a decision was made, but that the policy read it. A policy that
reached past these two accessors would not be counted; the rule policy reads
the team through them only.

EVERY FIELD COMES FROM A READING, A RECEIVED REPORT OR THE AGENT ITSELF. Position,
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
from ..core.team import TeamReport

SCHEMA_VERSION = 2                     # 1 was Phase 5's three blocks
ESTIMATED = "estimated from own positions"
HEADING_MIN_SPEED_MPS = 0.2            # slower than this, the heading is not known
FAILED_STATUSES = ("failed", "timeout")
CONNECTED_WINDOW_S = 3.0               # heard within this, a teammate counts as connected
LATENCY_SAMPLES = 10                   # the latency estimate is the mean of the last this many


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


@dataclass(frozen=True)
class TeamRecord:
    """The latest report held about one teammate, and when it arrived."""

    report: TeamReport
    received_at: float

    @property
    def expires_at(self) -> float:
        return self.report.at + self.report.ttl_s

    def age(self, now: float) -> float:
        """How old the news is: counted from when it was true, not from when it arrived."""
        return now - self.report.at

    def current(self, now: float) -> bool:
        return now < self.expires_at

    def confidence(self, now: float) -> float:
        """The source's confidence, falling linearly with age to zero at expiry."""
        left = 1.0 - self.age(now) / self.report.ttl_s
        return self.report.confidence * min(1.0, max(0.0, left))


@dataclass
class TeamBelief:
    """One entry per teammate on the roster; None means never heard from."""

    members: dict[str, TeamRecord | None] = field(default_factory=dict)
    expired: set[str] = field(default_factory=set)       # members whose record has been seen to expire


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
    read_ids: set[str] = field(default_factory=set, repr=False)    # message ids read during this decision
    listening: bool = False                                        # does the agent take in messages
    links: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)   # per sender: what was heard
    # Phase 9: each teammate's rung on its own failure detector's ladder, when it has one.
    teammate_health: dict[str, str] | None = field(default=None, repr=False)

    @classmethod
    def start(cls, brief: MissionBrief, vehicle_id: str, first: Observation) -> "BeliefState":
        """A fresh belief: home is where the drone stands at the first observation."""
        me = SelfBelief(vehicle_id, first.x, first.y, first.altitude_m, first.airborne, first.battery,
                        (first.x, first.y), first.base_link, first.skill, None, first.at)
        constraints = {"restricted_zones": [z.id for z in brief.restricted_zones],
                       "reserve": brief.battery.reserve,
                       "min_separation_m": brief.safety.min_separation_m,
                       "deadline_s": brief.mission.deadline_s,
                       "targets_to_find": brief.mission.targets_to_find,
                       "sectors": [{"id": s.id, "bounds": [s.region.x_min, s.region.y_min, s.region.x_max, s.region.y_max]}
                                   for s in brief.sectors]}
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
        self._estimate_link(obs.at)
        expired = sorted(d for d, r in self.team.members.items()
                         if r is not None and not r.current(obs.at) and d not in self.team.expired)
        if expired:
            self.team.expired.update(expired)
            changes["team_expired"] = expired
        return changes

    def receive(self, report: TeamReport, now: float) -> tuple[bool, str]:
        """Take in one report about a teammate. Returns whether it was kept, and why."""
        me = self.self_.vehicle_id
        if report.drone == me:
            return False, "about itself"
        if report.drone not in self.team.members:
            return False, f"{report.drone} is not on the roster"
        if report.at > now:
            return False, f"dated {report.at - now:.3f} s in the future"
        held = self.team.members[report.drone]
        if held is not None and report.at <= held.report.at:
            return False, f"no newer than the report held (from {held.report.at:.3f})"
        record = TeamRecord(report, now)
        self.team.members[report.drone] = record
        if record.current(now):
            self.team.expired.discard(report.drone)
        return True, "kept"

    def teammate(self, drone: str) -> TeamRecord | None:
        """The latest record held about `drone`, current or not; None if never heard."""
        record = self.team.members[drone]
        self._noted(record)
        return record

    def current_teammates(self) -> dict[str, TeamRecord]:
        """Only the records still current now: what may be acted on as fact."""
        now = self.self_.updated_at
        current = {d: r for d, r in self.team.members.items() if r is not None and r.current(now)}
        for r in current.values():
            self._noted(r)
        return current

    def heard(self, sender: str, sequence_number: int, sent_at: float, now: float) -> None:
        """Note one message taken in, for the link estimates. Called for every arrival, kept or not."""
        link = self.links.setdefault(sender, {"last_seq": 0, "received": 0, "missed": 0, "last_heard": None,
                                              "latencies": []})
        if sequence_number > link["last_seq"]:
            if link["last_seq"]:
                link["missed"] += sequence_number - link["last_seq"] - 1
            link["last_seq"] = sequence_number
        link["received"] += 1
        link["last_heard"] = now
        link["latencies"] = (link["latencies"] + [now - sent_at])[-LATENCY_SAMPLES:]
        self._estimate_link(now)

    def _estimate_link(self, now: float) -> None:
        if not self.listening:
            return
        c = self.communication
        c.connected_peers = tuple(sorted(s for s, l in self.links.items()
                                         if l["last_heard"] is not None and now - l["last_heard"] <= CONNECTED_WINDOW_S))
        received = sum(l["received"] for l in self.links.values())
        if received:
            missed = sum(l["missed"] for l in self.links.values())
            c.recent_loss_rate = missed / (received + missed)
            samples = [x for l in self.links.values() for x in l["latencies"]]
            c.estimated_latency_s = sum(samples) / len(samples)

    def start_reading(self) -> None:
        """A decision begins: forget what the last one read."""
        self.read_ids.clear()

    def read(self) -> tuple[str, ...]:
        """The message ids of the teammate records read since `start_reading`, sorted."""
        return tuple(sorted(self.read_ids))

    def _noted(self, record: TeamRecord | None) -> None:
        if record is not None and record.report.message_id is not None:
            self.read_ids.add(record.report.message_id)

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
        snap = {
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
            "team": {d: _team_view(rec, now) for d, rec in sorted(self.team.members.items())},
            "communication": {"base_reachable": c.base_reachable,
                              "base_reachable_for_s": round(now - c.base_reachable_since, 3),
                              "estimated_latency_s": _known(None if c.estimated_latency_s is None
                                                            else round(c.estimated_latency_s, 3)),
                              "recent_loss_rate": _known(None if c.recent_loss_rate is None
                                                         else round(c.recent_loss_rate, 4)),
                              "connected_peers": _known(None if c.connected_peers is None else list(c.connected_peers))},
            "assumptions": [{"key": a.key, "statement": a.statement, "evidence": a.evidence,
                             "age_s": round(now - a.at, 3), "confidence": a.confidence}
                            for a in sorted(self.assumptions.values(), key=lambda a: a.key)],
        }
        if self.teammate_health is not None:
            # Only a drone with a failure detector (Phase 9) has it: every earlier snapshot is as it was.
            snap["communication"]["teammate_health"] = dict(sorted(self.teammate_health.items()))
        return snap

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


def _team_view(record: TeamRecord | None, now: float) -> Any:
    if record is None:
        return "never heard"
    r = record.report
    return {"position": _known(None if r.position is None else [round(v, 3) for v in r.position]),
            "role": _known(r.role), "task": _known(r.task), "status": _known(r.status),
            "source": r.source, "age_s": round(record.age(now), 3),
            "received_age_s": round(now - record.received_at, 3),
            "confidence": round(record.confidence(now), 3), "expires_in_s": round(record.expires_at - now, 3),
            "current": record.current(now), "message_id": r.message_id}


def _known(value: Any) -> Any:
    """A value, or the word 'unknown': never a made-up zero."""
    return "unknown" if value is None else value
