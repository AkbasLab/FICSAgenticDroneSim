"""Safety guard (Phase 5.1's `guardian.evaluate`).

The policy proposes a command; the guardian gets the last word. It is a small,
deterministic safety layer that sits between deciding and executing, so an unsafe
command never reaches the vehicle. Keeping it separate from the policy means the
LLM policy (later) is held to the same safety rules without being trusted to
enforce them itself.

Rules (single-drone phase):
  - critical battery  -> land immediately, wherever we are;
  - low battery while still on the mission -> stop extending the mission and
    return home (or land if already home);
  - otherwise -> pass the command through unchanged.
"""

from dataclasses import dataclass

from ..control import skills as sk
from ..core.models import Position3D

RETURN_SPEED = 4.0
RETURN_TOLERANCE = 1.5
LEG_TIMEOUT = 600.0

# commands that extend the mission (i.e. cost battery without heading home)
_MISSION_EXTENDING = (sk.SearchRegionCommand, sk.GoToWaypointCommand,
                      sk.FollowWaypointsCommand, sk.InspectPointCommand)


@dataclass
class GuardDecision:
    command: object
    overridden: bool
    reason: str


class Guardian:
    def evaluate(self, command, belief) -> GuardDecision:
        # critical: land now, don't try to fly anywhere.
        if belief.critical_battery and not isinstance(command, sk.LandCommand):
            belief.rtb_forced = True
            return GuardDecision(sk.LandCommand(timeout_s=LEG_TIMEOUT),
                                 True, "battery_critical: emergency land")

        # low battery: refuse to extend the mission; head home instead.
        if belief.low_battery and isinstance(command, _MISSION_EXTENDING) \
                and not belief.reported:
            belief.rtb_forced = True
            home = belief.home
            return GuardDecision(
                sk.ReturnHomeCommand(home=home, speed_mps=RETURN_SPEED,
                                     tolerance_m=RETURN_TOLERANCE,
                                     timeout_s=LEG_TIMEOUT),
                True, "battery_low: return home instead of extending mission")

        return GuardDecision(command, False, "")
