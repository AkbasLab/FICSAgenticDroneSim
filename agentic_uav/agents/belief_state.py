"""What one drone believes: AUV-06's first three blocks -- self, mission, local map (6.1).

    belief = BeliefState.start(brief, "Drone1", first_observation)
    changes = belief.update(observation)          # facts that changed, for the event detector
    belief.snapshot()                             # for the decision trace

Phase 5 keeps the belief minimal on purpose (plan, decision 3): the
lifecycle needs something to update and decide from, and these three blocks
are what a single drone with a task has. The team and communication blocks,
assumptions, staleness and the "what it knew" logger are Phase 6's.

EVERY FIELD COMES FROM A READING OR FROM THE AGENT ITSELF. Position,
airborne, battery, sightings and the base link from `core.sensing`; the
current skill from the agent's own executor; the task and progress from its
own decisions; zones, deadline and reserve from the public brief. Nothing
here can hold ground truth, because nothing that holds it is in reach
(`agents/__init__.py`, enforced by test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.geometry import Region
from ..core.scenario import MissionBrief
from ..core.sensing import Sighting


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


@dataclass
class MissionBelief:
    mission_id: str
    objective: str | None              # what the agent is working towards now
    deadline_at: float                 # absolute clock time
    reserve: float
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalMap:
    searched_regions: list[Region] = field(default_factory=list)
    observed_targets: dict[str, Sighting] = field(default_factory=dict)
    known_hazards: list[str] = field(default_factory=list)
    reported_targets: set[str] = field(default_factory=set)   # seen while the base was in reach


@dataclass
class BeliefState:
    self_: SelfBelief
    mission: MissionBelief
    local_map: LocalMap
    brief: MissionBrief

    @classmethod
    def start(cls, brief: MissionBrief, vehicle_id: str, first: Observation) -> "BeliefState":
        """A fresh belief: home is where the drone stands at the first observation."""
        me = SelfBelief(vehicle_id, first.x, first.y, first.altitude_m, first.airborne, first.battery,
                        (first.x, first.y), first.base_link, first.skill, None, first.at)
        mission = MissionBelief(brief.scenario_id, None, first.at + brief.mission.deadline_s,
                                brief.battery.reserve)
        belief = cls(me, mission, LocalMap(), brief)
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
        if obs.battery < me.battery:
            changes["battery_from"] = me.battery
        if obs.base_link:
            # Connected now: everything seen so far has reached the base.
            self.local_map.reported_targets.update(self.local_map.observed_targets)
        me.x, me.y, me.altitude_m, me.airborne = obs.x, obs.y, obs.altitude_m, obs.airborne
        me.battery, me.base_link, me.current_skill, me.updated_at = obs.battery, obs.base_link, obs.skill, obs.at
        return changes

    @property
    def time_left(self) -> float:
        return self.mission.deadline_at - self.self_.updated_at

    def snapshot(self) -> dict[str, Any]:
        """The belief as plain data, for the decision trace."""
        me, m, lm = self.self_, self.mission, self.local_map
        return {
            "self": {"vehicle_id": me.vehicle_id, "position": [round(me.x, 3), round(me.y, 3), round(me.altitude_m, 3)],
                     "airborne": me.airborne, "battery": round(me.battery, 3), "home": list(me.home),
                     "base_link": me.base_link, "current_skill": me.current_skill,
                     "current_task": me.current_task, "updated_at": round(me.updated_at, 3)},
            "mission": {"mission_id": m.mission_id, "objective": m.objective,
                        "deadline_in_s": round(self.time_left, 3), "reserve": m.reserve,
                        "progress": dict(m.progress)},
            "local_map": {"searched_regions": [[r.x_min, r.y_min, r.x_max, r.y_max] for r in lm.searched_regions],
                          "observed_targets": {k: [round(s.x, 3), round(s.y, 3), round(s.at, 3)]
                                               for k, s in sorted(lm.observed_targets.items())},
                          "reported_targets": sorted(lm.reported_targets),
                          "known_hazards": list(lm.known_hazards)},
        }
