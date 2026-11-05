# Recovery live — search_relay_live_small

Run 2026-11-04T22:29:40, `scripts/recovery_exit.py --sim airsim`, 127.4 s of flight. Two rule agents told only the team mission, every message delivered; Drone2 stopped from outside at 17 s (at 17.344 s, as it happened); observer polled-10Hz.

Correct here means within **0.78 m** and **0.0234 %** of battery: one poll of flight: 5 m/s across 0.156 s (6.41 Hz).

| Check | Live | Mock twin |
|---|---|---|
| detected | yes | yes |
| no_false_alarm | yes | yes |
| reassigned | **no** | yes |
| continued | **no** | yes |
| no_new_command | yes | yes |
| roles_from_interactions | yes | yes |
| deterministic | - | yes |
| known_exactly | yes | yes |
| Division | Drone1 search S2; Drone2 - | Drone1 search S2, search S1; Drone2 - |
| Survivor's ladder | Drone1: suspected 3.093 s, unreachable 10.375 s, failed 30.359 s | Drone1: suspected 3 s, unreachable 10 s, failed 30.1 s |
| Survivor's roles | Drone1: scout → reserve → relay → scout → reserve | Drone1: scout → reserve → relay → scout → relay → reserve |
| Completion s | - | 55.6 |
| Skills | Drone1: TAKE_OFF success, SEARCH_REGION success, HOLD_POSITION aborted, HOLD_POSITION success, HOLD_POSITION aborted, FOLLOW_WAYPOINTS success, SEARCH_REGION failed, SEARCH_REGION failed, SEARCH_REGION failed, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, LAND timeout; Drone2: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted | - |
| Contacts | Drone1-SM_seaM, Drone2-SM_seaM, Drone1-Drone2, Drone2-Drone1 | - |

Determinism needs a second flight: that row is the mock twin's alone. The twin is the seed flown with no stop and with each drone stopped, each stopped flight twice.

**Live flight: NOT MET** — the seven checks one flight can be held to; failed: reassigned, continued. A live flight of the variant, not the exit. The stopped drone is left hovering: reset the simulator before the next flight.

Problems:

* reassigned: search S1, Drone2's, was searched by no survivor
* reassigned: Drone1's book ends with search S1 as open v3 by None
* continued: the mission was not met: search_relay_live_small seed 17 [polled-10Hz]: FAILED
  FAIL  C1 coverage threshold reached: 0.7691 (required 0.95) -- S1 0.538, S2 1.000
  FAIL  C2 all targets detected: 1 (required 2) -- detected: T1
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone1 at 33.7 s
  PASS  C4 no restricted-region entry: 0 (required 0)
  FAIL  C5 no collision or separation violation: {'collisions': 2, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- Drone1 hit Drone2 at 42.0 s; Drone2 hit Drone1 at 42.0 s
  FAIL  C6 all functioning drones return safely: 0 (required 1) -- Drone1: still airborne, 19.0 m from its pad
