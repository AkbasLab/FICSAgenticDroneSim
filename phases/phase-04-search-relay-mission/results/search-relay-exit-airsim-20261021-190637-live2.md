# Search-and-relay — search_relay_live_small, CarlaAir, one flight

Run 2026-10-21T19:06:37, `scripts/search_relay_exit.py`. Controller: `control/scripted.py`, from the brief alone. Observer: polled-10Hz. Judge: `experiments/evaluation.py`, against 20 seeds — the one flight judged on every target layout.

## The plan

| Drone | Sector | Height m | Lanes m | Lanes flown (x) | Length m | Estimated s | Estimated battery % |
|---|---|---|---|---|---|---|---|
| Drone1 | S1 | 12 | 16.00 | -8 to 20 | 76.6 | 42 | 4.13 |
| Drone2 | S2 | 16 | 16.00 | -8 to 20 | 73.7 | 46 | 4.4 |

Skills: Drone1: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success; Drone2: TAKE_OFF success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success. Contacts polled: Drone1–SM_seaM, Drone2–SM_seaM.

## Live beside the mock (seed 17)

| Drone | Polls | Max off track m | Median off track m | Max height error at cruise m | Pad error m |
|---|---|---|---|---|---|
| Drone1 | 357 | 2.76 | 0.11 | 2.48 | 0.26 |
| Drone2 | 357 | 2.75 | 0.12 | 2.07 | 0.18 |

| | Live | Mock |
|---|---|---|
| Completion s | 37.5 | 31.1 |
| Coverage | 1.0 | 1.0 |
| Closest pair m | 4.047 | 4.0 |
| Drone1 battery used % (estimated 4.13) | 3.83 | 3.44 |
| Drone2 battery used % (estimated 4.4) | 3.92 | 3.66 |

## Every seed

| Seed | Targets (sector) | Met | Completion s | Coverage | Reported at s | Closest pair m | Lowest battery % | Failing |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 (12, -14) S1, T2 (11, 12) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 2 | T1 (14, 11) S2, T2 (12, -14) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 3 | T1 (7, -20) S1, T2 (8, 11) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 4 | T1 (-1, -20) S1, T2 (11, 22) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 5 | T1 (10, 23) S2, T2 (5, -11) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 12.5 | 4.047 | 96.1 | - |
| 6 | T1 (12, 18) S2, T2 (-3, -15) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 13.3 | 4.047 | 96.1 | - |
| 7 | T1 (-0, -16) S1, T2 (4, 26) S2 | yes | 37.5 | 1.0000 | T1 13.2, T2 27.9 | 4.047 | 96.1 | - |
| 8 | T1 (14, -24) S1, T2 (-1, 14) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 9 | T1 (4, -24) S1, T2 (-3, 18) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 10 | T1 (5, 19) S2, T2 (12, -13) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 11 | T1 (7, -11) S1, T2 (-1, 15) S2 | yes | 37.5 | 1.0000 | T1 12.9, T2 27.9 | 4.047 | 96.1 | - |
| 12 | T1 (9, -15) S1, T2 (7, 21) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 13 | T1 (9, -15) S1, T2 (0, 14) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 14 | T1 (10, -16) S1, T2 (2, 14) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 15 | T1 (-3, 22) S2, T2 (15, -26) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 16 | T1 (6, -19) S1, T2 (3, 23) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 17 | T1 (12, 25) S2, T2 (11, -15) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 18 | T1 (9, -21) S1, T2 (11, 24) S2 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 19 | T1 (11, 18) S2, T2 (-0, -22) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 27.9 | 4.047 | 96.1 | - |
| 20 | T1 (9, 22) S2, T2 (4, -10) S1 | yes | 37.5 | 1.0000 | T1 27.9, T2 12.1 | 4.047 | 96.1 | - |

**MET** — 20 of 20 seeds met (mission success, and every planned skill succeeded with no safety landing).
