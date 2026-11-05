# Allocation live — search_relay_live_small

Run 2026-11-04T22:27:33, `scripts/allocation_exit.py --sim airsim`, 47.9 s of flight. Two rule agents told only the team mission, every message delivered, deliberating (bid window 1 s); observer polled-10Hz.

Correct here means within **0.7 m** and **0.021 %** of battery: one poll of flight: 5 m/s across 0.14 s (7.143 Hz).

| Check | Live | Mock twin |
|---|---|---|
| met | yes | yes |
| no_central_assignment | yes | yes |
| one_holder_each | yes | yes |
| conflicts_resolved | yes | yes |
| leases_renewed | yes | yes |
| deterministic | - | yes |
| known_exactly | yes | yes |
| Division | Drone1 search S2; Drone2 search S1 | Drone1 search S2; Drone2 search S1 |
| Completion s | 38.6 | 32.0 |
| Skills | Drone1: TAKE_OFF success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success; Drone2: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success | - |
| Contacts | Drone1-SM_seaM, Drone2-SM_seaM | - |

Determinism needs a second flight: that row is the mock twin's alone.

**Live flight: MET** — the six checks one flight can be held to. A live flight of the variant, not the exit.
