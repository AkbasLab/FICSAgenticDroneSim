"""Flight constants, positive-up altitude throughout (flipped to AirSim's
native NED only at the one boundary inside the adapter that talks to AirSim)."""

DEFAULT_HEIGHT = 8.0   # default cruise height, metres above the recorded ground
MOVE_SPEED = 5.0       # m/s for directional moves and set_height

# Landing profile: fast descent for most of the drop (precision doesn't matter
# yet), then a slow final approach only once close to the ground (this is
# where an over-fast touchdown could damage the drone or overshoot the mesh).
LAND_FAST_ABOVE = 4.0   # descend fast until this many metres above ground_z
LAND_FAST_SPEED = 5.0
LAND_SLOW_SPEED = 1.5
LAND_SETTLE_SECS = 0.5  # brief hover to kill momentum before the slow approach

# Skill contracts (Phase 3): how a skill's polling loop decides success vs
# giving up, instead of the unbounded .join() the raw actions above use.
SKILL_TOLERANCE_M = 1.0   # "close enough" to a waypoint, or "not drifting" while holding
SKILL_TIMEOUT_S = 30.0    # give up and report TIMEOUT after this long
SKILL_POLL_INTERVAL_S = 0.1
SKILL_STOP_SPEED_MPS = 0.5  # GO_TO_WAYPOINT requires speed below this, not just position
                            # within tolerance, before declaring SUCCESS - otherwise it can
                            # call itself "arrived" while still passing through the target
                            # at speed, which is what was breaking HOLD_POSITION right after
SKILL_SETTLE_SECS = 0.5   # HOLD_POSITION: small extra margin after start_hover(), on top
                          # of go_to_waypoint's own speed gate - same idea as
                          # LAND_SETTLE_SECS above, applied to holding instead of landing
