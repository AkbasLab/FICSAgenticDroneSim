"""Deterministic bid computation (Phase 8.3).

    Bid(i,k) = w_d*D(i,k) + w_b*B(i,k) + w_l*L(i) + w_c*C(i) + w_r*R(i,k)

Lowest bid wins; ties break on vehicle ID.

Two properties matter more than the exact weights:

*Deterministic* - a bid is a pure function of the bidding agent's own belief and
the task. No randomness, no wall-clock, no global state. The same belief always
produces the same number, so a whole allocation can be replayed and audited.

*Transparent* - every bid carries its term-by-term breakdown. When a drone wins
a sector you can see whether it won on distance, or because a rival was low on
battery. That is what makes the later comparison against an LLM allocator
meaningful: we can say exactly why the deterministic baseline chose what it did.

Each term is normalised to roughly 0..1 so the weights are comparable.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from .tasks import TaskType

# normalisation constants (metres / seconds) - scale terms into 0..1
MAX_RANGE_M = 150.0
MAX_WORKLOAD = 3.0


@dataclass
class BidWeights:
    w_distance: float = 1.0        # travel cost to reach the work
    w_battery: float = 1.5         # penalty for bidding when low on power
    w_workload: float = 2.0        # penalty for taking on more than one job
    w_comms: float = 0.5           # penalty for working out of contact
    w_role: float = 5.0            # capability mismatch - effectively disqualifying

    def as_dict(self):
        return {"w_d": self.w_distance, "w_b": self.w_battery,
                "w_l": self.w_workload, "w_c": self.w_comms,
                "w_r": self.w_role}


@dataclass
class Bid:
    """One agent's cost for one task, with its reasoning attached."""
    vehicle_id: str
    task_id: str
    value: float
    task_version: int = 0
    eligible: bool = True
    breakdown: Dict[str, float] = field(default_factory=dict)

    def to_payload(self):
        return {"task_id": self.task_id, "value": round(self.value, 6),
                "task_version": self.task_version, "eligible": self.eligible,
                "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()}}

    @staticmethod
    def from_payload(vehicle_id, p):
        return Bid(vehicle_id=vehicle_id, task_id=p["task_id"],
                   value=float(p["value"]), task_version=p.get("task_version", 0),
                   eligible=p.get("eligible", True),
                   breakdown=p.get("breakdown") or {})

    def beats(self, other: "Bid") -> bool:
        """Strict ordering: lower cost wins; ties broken by vehicle ID (8.5)."""
        if other is None:
            return True
        if self.value != other.value:
            return self.value < other.value
        return self.vehicle_id < other.vehicle_id


def _task_anchor(task):
    """The point an agent must fly to in order to start the task."""
    r = task.region
    if r is None:
        return None
    if hasattr(r, "min_x"):                     # Rect: enter at its near corner
        from ..core.models import Position3D
        return Position3D(r.min_x, r.min_y, -8.0)
    return r


def compute_bid(task, belief, weights: BidWeights = None,
                capabilities=None, now=None) -> Bid:
    """Compute this agent's bid for `task` from its own belief only."""
    weights = weights or BidWeights()
    now = belief.now if now is None else now
    caps = set(capabilities or {"search", "relay", "inspect"})

    # --- R: capability / role mismatch ---
    missing = task.required_capabilities - caps
    role_term = 1.0 if missing else 0.0

    # --- D: distance to the work ---
    anchor = _task_anchor(task)
    if anchor is None:
        distance_term = 0.0
    else:
        d = belief.position.horizontal_distance_to(anchor)
        distance_term = min(d / MAX_RANGE_M, 1.0)

    # --- B: battery penalty. Cheap when full, punishing when nearly empty ---
    frac = max(0.0, min(1.0, belief.battery_frac))
    battery_term = (1.0 - frac) ** 2

    # --- L: current workload ---
    workload = float(len(getattr(belief, "held_task_ids", []) or []))
    workload_term = min(workload / MAX_WORKLOAD, 1.0)

    # --- C: communication risk (out of contact with base is riskier) ---
    comms = belief.communication
    comms_term = 0.0
    if not comms.base_reachable:
        comms_term += 0.5
    comms_term += min(comms.recent_loss_rate, 1.0) * 0.5
    comms_term = min(comms_term, 1.0)

    value = (weights.w_distance * distance_term
             + weights.w_battery * battery_term
             + weights.w_workload * workload_term
             + weights.w_comms * comms_term
             + weights.w_role * role_term)

    return Bid(vehicle_id=belief.vehicle_id, task_id=task.task_id,
               value=value, task_version=task.version,
               eligible=not missing,
               breakdown={"D": distance_term, "B": battery_term,
                          "L": workload_term, "C": comms_term,
                          "R": role_term})


def best_bid(bids):
    """The winning bid under the deterministic ordering, or None."""
    winner = None
    for b in bids:
        if not b.eligible:
            continue
        if b.beats(winner):
            winner = b
    return winner


def explain(bid: Bid, weights: BidWeights = None) -> str:
    """Human-readable term-by-term explanation of a bid."""
    w = weights or BidWeights()
    b = bid.breakdown
    parts = [
        f"D={b.get('D', 0):.2f}*{w.w_distance}",
        f"B={b.get('B', 0):.2f}*{w.w_battery}",
        f"L={b.get('L', 0):.2f}*{w.w_workload}",
        f"C={b.get('C', 0):.2f}*{w.w_comms}",
        f"R={b.get('R', 0):.2f}*{w.w_role}",
    ]
    return f"{bid.vehicle_id} bids {bid.value:.3f} on {bid.task_id}  [{' + '.join(parts)}]"
