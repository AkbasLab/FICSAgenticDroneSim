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
# Ground reference (connect_and_takeoff): ground_z is read from wherever the drone is
# at that moment, so it is only trustworthy once the drone has stopped moving. A drone
# still falling onto its spawn point would record a ground that is too high and put every
# later altitude, and the landing target, off by the missing drop.
GROUND_SETTLE_SPEED_MPS = 0.2   # below this counts as "not moving"
GROUND_SETTLE_DRIFT_M = 0.05    # and vertical position must stay within this...
GROUND_SETTLE_WINDOW_S = 1.0    # ...for this long before ground_z is recorded
GROUND_SETTLE_TIMEOUT_S = 15.0  # give up (take-off fails) rather than record a bad ground
GROUND_SETTLE_POLL_S = 0.1

# After land() the drone should be resting on the ground reference. Anything further than this from it
# means the landing did not end where it was meant to (observed live: a full mission read -11.8 m and
# took ~64 s; landing on an awning reads high). Reported as a failed landing, not a quiet success.
LAND_END_TOLERANCE_M = 1.5

# Root cause of the -11.8 m landing, found 2026-10-09 from a live trace: AirSim's landAsync() descends at
# a constant 0.2 m/s until it senses contact, with a 60 s timeout. If the ground under the drone reports
# no collision (the beach spawn's `SM_seaM` sometimes does not), it sinks through the ground for the
# whole timeout: 0.2 m/s x 60 s = 12 m. So landAsync is only used when the slow approach left the drone
# clearly ABOVE the ground reference (something is holding it up, e.g. an awning); at the ground
# reference it just disarms.
LAND_TOUCHDOWN_HEIGHT_M = 1.0   # above this after the slow approach, something is holding it up: use landAsync
LAND_PROBE_DEPTH_M = 0.5        # at the ground reference: probe at most this far BELOW it looking for contact
LAND_PROBE_SPEED_MPS = 0.5
LAND_PROBE_TIMEOUT_S = 8.0

# Actual trigger, confirmed live 2026-10-09: pressing P in the CarlaAir window toggles NOCLIP, after which
# nothing collides, the ground included. Then landAsync sinks 12 m, and disarming at the ground
# free-falls (-47 m and still going). A landing therefore disarms only if the final approach registered
# real ground contact; with no contact it holds position at the ground reference and stays armed.

SKILL_SETTLE_SECS = 0.5   # HOLD_POSITION: small extra margin after start_hover(), on top
                          # of go_to_waypoint's own speed gate - same idea as
                          # LAND_SETTLE_SECS above, applied to holding instead of landing
