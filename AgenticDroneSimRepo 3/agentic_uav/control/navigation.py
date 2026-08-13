"""Flight constants and low-level movement helpers.

These are the exact numbers the open-loop baseline used, kept in one place so
the simulator adapter and any future controller share them.
"""

from ..core.enums import ActionType

ALTITUDE = -8.0        # default cruise height (NED: negative is up)
SPACING = 4.0          # metres between drones when they spawn
MOVE_SPEED = 5.0       # m/s for the directional moves
FLY_TO_SPEED = 4.0     # m/s for point-to-point moves
CLIMB_SPEED = 3.0      # m/s for altitude changes

# Landing profile (matches the baseline's fast-then-gentle descent).
LAND_FAST_ABOVE = 4.0   # descend fast to this many metres above the ground
LAND_FAST_SPEED = 5.0
LAND_SLOW_SPEED = 1.5   # gentle final approach
LAND_SETTLE_SECS = 0.5  # pause to kill momentum before the slow part


def direction_velocity(action: str):
    """Map a directional action to (vx, vy). Heading is held fixed, so the
    drone strafes rather than turning to face its travel direction."""
    return {
        ActionType.FLY_STRAIGHT.value: (MOVE_SPEED, 0.0),
        ActionType.FLY_BACKWARD.value: (-MOVE_SPEED, 0.0),
        ActionType.FLY_LEFT.value: (0.0, -MOVE_SPEED),   # y is "right" in NED
        ActionType.FLY_RIGHT.value: (0.0, MOVE_SPEED),
    }[action]
