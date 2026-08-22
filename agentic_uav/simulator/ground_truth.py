"""Ground truth, and the sensor that is the only bridge from it (Phase 6.2).

The simulator and the evaluator know the true state of the world. **An agent must
not.** If an agent can read this object, then a "decentralized" experiment is
silently running on perfect global information, and any result about coordination
under degraded communication is meaningless.

So the boundary is explicit:

    GroundTruth   - true target positions and true vehicle states.
                    Simulator + evaluator only. Never handed to an agent.
    SensorModel   - the ONLY way facts cross into an agent's belief. It takes
                    ground truth and returns just what a given drone could
                    actually perceive from where it flew: targets within
                    detection radius (observed long enough), peers within comms
                    range. Everything it returns is stamped with a source and a
                    timestamp.

An agent therefore holds a SensorModel, never a GroundTruth or a MissionScenario,
and its belief only ever contains observations the sensor handed it or messages a
teammate sent. tests/test_belief_state.py enforces both halves of that claim: by
inspecting the belief for smuggled truth objects, and behaviourally, by checking
that a target outside sensing range is never learned about.
"""

from dataclasses import dataclass
from typing import List, Optional

from ..agents.belief_schema import Source
from ..core.models import Position3D
from .target_model import detect_targets


@dataclass
class Observation:
    """One thing a drone actually perceived, with provenance attached."""
    kind: str                     # "target" | "peer"
    subject_id: str
    position: Optional[Position3D]
    at_time_s: float
    source: Source = Source.SELF_SENSING
    confidence: float = 1.0


class GroundTruth:
    """The true world state. Simulator and evaluator only."""

    def __init__(self, scenario):
        self._scenario = scenario
        self._true_positions = {v.vehicle_id: v.start for v in scenario.vehicles}
        self._paths = {}

    # --- simulator-side writes ---

    def set_position(self, vehicle_id, position):
        self._true_positions[vehicle_id] = position

    def record_path(self, vehicle_id, path):
        self._paths[vehicle_id] = path

    # --- simulator/evaluator-side reads ---

    @property
    def targets(self):
        return self._scenario.targets

    @property
    def vehicles(self):
        return self._scenario.vehicles

    @property
    def scenario(self):
        return self._scenario

    def true_position(self, vehicle_id):
        return self._true_positions.get(vehicle_id)

    def paths(self):
        return dict(self._paths)

    def roster(self):
        """Vehicle *names* only - safe to brief an agent with."""
        return [v.vehicle_id for v in self._scenario.vehicles]

    def sector_ids(self):
        """Sector *names* only - safe to brief an agent with."""
        return [s.sector_id for s in self._scenario.sectors]


class SensorModel:
    """The only bridge from ground truth into belief.

    Owned by the simulator side of the boundary and handed to an agent as a
    narrow interface: the agent can ask "what did I just perceive?", never
    "what is out there?".
    """

    def __init__(self, ground_truth: GroundTruth, comm_range_m: float = None):
        self._truth = ground_truth
        self._comm_range = (comm_range_m if comm_range_m is not None
                            else ground_truth.scenario.base.comm_range_m)

    def sense_targets(self, vehicle_id, path, speed_mps, now) -> List[Observation]:
        """Targets this drone genuinely observed along `path`.

        Uses the same geometric detection model as the evaluator (detection
        radius + observation period), so nothing is "seen" that the drone did not
        actually fly close enough to, for long enough.
        """
        if not path:
            return []
        dets = detect_targets(self._truth.targets, {vehicle_id: path}, speed_mps)
        out = []
        for d in dets:
            out.append(Observation(kind="target", subject_id=d.target_id,
                                   position=d.position, at_time_s=now,
                                   source=Source.SELF_SENSING, confidence=1.0))
        return out

    def sense_peers(self, vehicle_id, now) -> List[Observation]:
        """Peers currently close enough to exchange a position report with.

        Anything outside comms range is simply not observed - which is what makes
        teammate beliefs go stale later.
        """
        me = self._truth.true_position(vehicle_id)
        if me is None:
            return []
        out = []
        for v in self._truth.vehicles:
            if v.vehicle_id == vehicle_id:
                continue
            other = self._truth.true_position(v.vehicle_id)
            if other is None:
                continue
            if me.horizontal_distance_to(other) <= self._comm_range:
                out.append(Observation(kind="peer", subject_id=v.vehicle_id,
                                       position=other, at_time_s=now,
                                       source=Source.PEER_MESSAGE,
                                       confidence=1.0))
        return out

    def base_reachable(self, vehicle_id) -> bool:
        me = self._truth.true_position(vehicle_id)
        if me is None:
            return False
        base = self._truth.scenario.base.position
        return me.horizontal_distance_to(base) <= self._comm_range
