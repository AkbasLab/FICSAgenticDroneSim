"""The cost function every drone runs independently to bid on a task. Lower
wins. Every term is kept so a later phase (multi-capability drones, a real
comms-degradation model) has somewhere to plug in - w_comms and w_role
contribute zero in this scenario (one drone type, perfect comms assumed
until Phase 10), which is stated here rather than silently true.
"""

import math
from dataclasses import dataclass

from ..core.scenario import Sector


@dataclass
class BidWeights:
    w_distance: float = 1.0
    w_battery: float = 1.5
    w_workload: float = 2.0
    w_comms: float = 0.5   # always 0 until Phase 10 gives comms risk a real model
    w_role: float = 5.0    # high enough to be disqualifying, once roles exist (Phase 9)


DEFAULT_WEIGHTS = BidWeights()


def sector_center(sector: Sector):
    return ((sector.x_min + sector.x_max) / 2, (sector.y_min + sector.y_max) / 2)


def compute_bid(world_position, battery_frac_remaining: float, workload: int, sector: Sector,
                 comms_risk: float = 0.0, role_mismatch: float = 0.0,
                 weights: BidWeights = DEFAULT_WEIGHTS) -> float:
    cx, cy = sector_center(sector)
    distance = math.dist((world_position[0], world_position[1]), (cx, cy))
    battery_cost = 1.0 - battery_frac_remaining  # less battery left -> worse bid
    return (weights.w_distance * distance
            + weights.w_battery * battery_cost
            + weights.w_workload * workload
            + weights.w_comms * comms_risk
            + weights.w_role * role_mismatch)
