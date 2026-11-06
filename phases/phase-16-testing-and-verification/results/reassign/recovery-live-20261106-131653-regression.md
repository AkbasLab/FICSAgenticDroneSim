# Recovery live — search_relay_live_small

Run 2026-11-06T13:15:50, `scripts/recovery_exit.py --sim airsim`, 60.5 s of flight. Two rule agents told only the team mission, every message delivered; Drone2 stopped from outside at 17 s (at 17.453 s, as it happened); observer polled-10Hz. **With the guardian and the keep-out** (5 m either side of a teammate silent 10 s in the air).

Correct here means within **0.705 m** and **0.0212 %** of battery: one poll of flight: 5 m/s across 0.141 s (7.092 Hz).

| Check | Live | Mock twin |
|---|---|---|
| detected | yes | yes |
| no_false_alarm | yes | yes |
| reassigned | yes | yes |
| continued | **no** | **no** |
| no_new_command | yes | yes |
| roles_from_interactions | yes | yes |
| deterministic | - | yes |
| known_exactly | yes | yes |
| kept_out | yes | yes |
| no_interventions | yes | yes |
| Closest pass to Drone2 | Drone1 19.72 m | Drone1 15.36 m |
| Division | Drone1 search S2, search S1; Drone2 - | Drone1 search S2, search S1; Drone2 - |
| Survivor's ladder | Drone1: suspected 3.125 s, unreachable 10.437 s, failed 30.468 s | Drone1: suspected 3 s, unreachable 10 s, failed 30.1 s |
| Survivor's roles | Drone1: scout → reserve → relay → scout → relay → reserve | Drone1: scout → reserve → relay → scout → relay → reserve |
| Completion s | - | 49.1 |
| Skills | Drone1: TAKE_OFF success, SEARCH_REGION success, HOLD_POSITION aborted, HOLD_POSITION success, HOLD_POSITION aborted, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success; Drone2: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted | - |
| Contacts | Drone1-SM_seaM, Drone2-SM_seaM | - |

Determinism needs a second flight: that row is the mock twin's alone. The twin is the seed flown with no stop and with each drone stopped, each stopped flight twice.

**Live flight: NOT MET** — the 9 checks one flight can be held to; failed: continued. A live flight of the variant, not the exit. The stopped drone is left hovering: reset the simulator before the next flight.

Problems:

* continued: the mission was not met: search_relay_live_small seed 17 [polled-10Hz]: FAILED
  FAIL  C1 coverage threshold reached: 0.9097 (required 0.95) -- S1 0.819, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  PASS  C3 detections reported to base, or eventually synchronized: 2 (required 2) -- reported: T1 by Drone1 at 43.1 s, T2 by Drone1 at 43.1 s
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.05 m
  FAIL  C6 all functioning drones return safely: 0 (required 1) -- Drone1: 2.1 m from its pad
