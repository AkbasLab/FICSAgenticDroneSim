# Messaging live — search_relay_live_small

Run 2026-11-04T01:55:07, `scripts/messaging_exit.py --sim airsim`, 47.0 s of flight. 2 rule agents talking, Drone1 told 'search S1', Drone2 told 'search S2'; radio 20 m, judged on the poller's latest positions; observer polled-10Hz.

Correct here means within **0.625 m** and **0.0188 %** of battery: one poll of flight: 5 m/s across 0.125 s (8 Hz) (the poller kept 9.132 Hz over 720 samples, worst gap 0.125 s).

| Check | Live | Mock twin |
|---|---|---|
| met | yes | yes |
| exchanged | yes | yes |
| only_on_delivery | yes | yes |
| known_exactly | yes | yes |
| blocked_moves_nothing | - | yes |
| steers_nothing | - | yes |
| Teammate records checked | 15 | 15 |
| Delivered / out of range / pending | 57 / 35 / 2 | 51 / 26 / 3 |
| In a belief / read by the policy | 10 / 8 | 11 / 9 |
| Skills | Drone1: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success; Drone2: TAKE_OFF success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success | - |
| Contacts | Drone1-SM_seaM, Drone2-SM_seaM | - |

Blocked and silent cannot be flown live: those rows are the mock twin's alone.

**Live flight: MET** — the four checks one flight can be held to. A live flight of the variant, not the exit.
