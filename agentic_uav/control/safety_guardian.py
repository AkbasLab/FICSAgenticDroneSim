"""Safety checks over planned/edited actions. Placeholder.

Intended to enforce hard limits (altitude bounds, geofence, min separation)
before a SkillCommand reaches the adapter. Not active in the baseline refactor -
added so later phases have a clear home for safety logic.
"""

from ..core.models import SkillCommand


class SafetyGuardian:
    def check(self, vehicle_id: str, command: SkillCommand) -> bool:
        """Return True if the command is allowed. Currently always True."""
        return True
