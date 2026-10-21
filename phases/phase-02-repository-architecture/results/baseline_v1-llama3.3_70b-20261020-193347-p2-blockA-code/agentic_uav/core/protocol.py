"""Constants that belong to the measurement protocol, not to any one layer.

The planner tells the model the speed (it is in the system prompt), and the
executor flies at it. The planner's validator fills in the cruise altitude for
a `fly_to` without z, and the executor climbs to it after take-off. One
definition each, here, so the two can never disagree.

Moved from `agentic_uav/control/executor.py` in Phase 2 step 4, values unchanged.
"""

CRUISE_ALTITUDE = -8.0   # metres, NED: negative is up
MOVE_SPEED = 5.0         # m/s for every directional move
