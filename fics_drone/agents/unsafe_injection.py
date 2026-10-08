"""A safety layer nobody has attacked is an assumption. This is the attack:
13 commands a compromised policy could plausibly emit, each paired with the
check that must catch it. Nothing here is used in normal operation - this
module exists only to be run against a SafetyGuardian by
run_guardian_demo.py and test_guardian.py.

conflicting_commands isn't in this catalogue - it's a stateful check (two
evaluate() calls, no command_completed() between them), awkward to express
as a single "bad command", so it's exercised directly in test_guardian.py
instead.
"""

from dataclasses import dataclass
from typing import Callable

from .belief import Belief
from .belief_schema import MissionBelief, Provenance, SelfState, TeammateRecord
from .safety_guardian import Command


@dataclass
class UnsafeCase:
    name: str
    expects_check: str
    build: Callable[[], Command]


def _safe_belief(position=(10.0, 10.0, 8.0), battery_frac_remaining: float = 0.9) -> Belief:
    # battery_frac_remaining = (battery_s - elapsed_s) / battery_s (see belief_schema.py) -
    # battery_s fixed at 100.0 so elapsed_s alone controls the remaining fraction.
    elapsed_s = (1.0 - battery_frac_remaining) * 100.0
    b = Belief(self_state=SelfState(position=position, elapsed_s=elapsed_s, battery_s=100.0),
               mission=MissionBelief(sector_id="A", search_queue=[]))
    return b


CATALOGUE = [
    UnsafeCase("altitude_below_floor", "altitude_bounds",
               lambda: Command(kind="fly", target=(10.0, 10.0, 1.0), speed_mps=5.0, timeout_s=30.0)),
    UnsafeCase("altitude_above_ceiling", "altitude_bounds",
               lambda: Command(kind="fly", target=(10.0, 10.0, 100.0), speed_mps=5.0, timeout_s=30.0)),
    UnsafeCase("outside_geofence", "geofence",
               lambda: Command(kind="fly", target=(5000.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)),
    UnsafeCase("inside_no_fly_zone", "restricted_zones",
               lambda: Command(kind="fly", target=(0.0, 50.0, 8.0), speed_mps=5.0, timeout_s=30.0)),  # NFZ1
    UnsafeCase("waypoint_nan", "waypoint_validity",
               lambda: Command(kind="fly", target=(float("nan"), 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)),
    UnsafeCase("waypoint_beyond_max_distance", "waypoint_validity",
               lambda: Command(kind="fly", target=(1000.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0)),
    UnsafeCase("excessive_speed", "max_speed",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=120.0, timeout_s=30.0)),
    UnsafeCase("negative_speed", "max_speed",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=-5.0, timeout_s=30.0)),
    UnsafeCase("zero_timeout", "command_timeout",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=0.0)),
    UnsafeCase("unbounded_timeout", "command_timeout",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=1e9)),
    UnsafeCase("battery_reserve_violation", "battery_reserve",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0,
                                purpose="mission")),
    UnsafeCase("teammate_separation_violation", "separation",
               lambda: Command(kind="fly", target=(10.0, 10.0, 8.0), speed_mps=5.0, timeout_s=30.0,
                                purpose="mission")),
    UnsafeCase("unsafe_landing_site", "landing_site",
               lambda: Command(kind="land", target=(0.0, 50.0, 0.0))),  # NFZ1
]


def belief_for_case(name: str) -> Belief:
    """Most cases only need the default safe belief - the two whose check
    reads belief (battery_reserve, teammate_separation_violation) get one
    built to actually trip that check, since the bad value lives in belief,
    not in the Command."""
    if name == "battery_reserve_violation":
        return _safe_belief(battery_frac_remaining=0.05)
    if name == "teammate_separation_violation":
        b = _safe_belief()
        b.team.teammates["Drone2"] = TeammateRecord(
            name="Drone2", last_known_position=(10.0, 10.0, 8.0),
            provenance=Provenance(timestamp=0.0, source="heartbeat"))
        return b
    return _safe_belief()
