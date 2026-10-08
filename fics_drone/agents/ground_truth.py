"""The one wall between ground truth and belief. GroundTruth wraps the real
scenario for the test harness only - an agent must never hold one.
SensorModel is the *only* path target information is allowed to reach an
agent through: it returns what a drone could actually perceive from where it
is, as plain data (id, position, radius), never the scenario's own Target
instance. This is what Phase 6 exists to enforce - Phase 5's agent was
handed scenario.targets directly, which meant it "found" targets it already
secretly knew about before ever searching for them.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple

from ..core.scenario import Scenario


class GroundTruth:
    """Harness/test-only access to the real world. Never passed to an agent."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario


@dataclass
class PerceivedTarget:
    """What a sensor read told the agent - plain values, not a reference to
    the scenario's own Target object, so belief can never transitively hold
    ground truth even by accident."""
    target_id: str
    world_position: Tuple[float, float, float]
    detection_radius_m: float


class SensorModel:
    """perceive() is the only function anywhere that is allowed to read
    scenario.targets - everything downstream of it deals in PerceivedTarget."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def perceive(self, world_position: Tuple[float, float, float]) -> List[PerceivedTarget]:
        seen = []
        for t in self.scenario.targets:
            if math.dist((world_position[0], world_position[1]), (t.x, t.y)) <= t.detection_radius_m:
                seen.append(PerceivedTarget(target_id=t.id, world_position=(t.x, t.y, world_position[2]),
                                             detection_radius_m=t.detection_radius_m))
        return seen
