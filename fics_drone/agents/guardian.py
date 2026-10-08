"""Gets the last word on every command before it reaches the vehicle - the
policy proposes, the Guardian disposes. Deterministic now, and stays exactly
this shape once an LLM policy replaces the deterministic SearchAgentPolicy in
a later phase: the LLM is held to these same rules, never trusted to enforce
them on its own. This is the direct precursor to the AI-Guardrails (GMB)
paper work - that work formalizes and extends exactly this checkpoint.
"""

from typing import List, Optional, Tuple

from ..core.scenario import NoFlyZone


class Guardian:
    def __init__(self, no_fly_zones: List[NoFlyZone]):
        self.no_fly_zones = no_fly_zones

    def check(self, target_point: Optional[Tuple[float, float, float]]) -> Tuple[bool, Optional[str]]:
        """target_point is in WORLD coordinates - the caller is responsible for
        converting from local before asking the Guardian, since every rule the
        Guardian checks (no-fly zones, later: geofence, altitude ceiling) is
        defined in world space, same as the Phase 4 scorer."""
        if target_point is None:
            return True, None
        for zone in self.no_fly_zones:
            if zone.contains(target_point[0], target_point[1]):
                return False, f"target {target_point} is inside no-fly zone {zone.id}"
        return True, None
