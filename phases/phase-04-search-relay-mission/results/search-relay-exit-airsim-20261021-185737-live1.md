# Search-and-relay — search_relay_live_small, CarlaAir, one flight

Run 2026-10-21T18:57:36, `scripts/search_relay_exit.py`. Controller: `control/scripted.py`, from the brief alone. Observer: polled-10Hz. Judge: `experiments/evaluation.py`, against 20 seeds — the one flight judged on every target layout.

## The plan

| Drone | Sector | Height m | Lanes m | Lanes flown (x) | Length m | Estimated s | Estimated battery % |
|---|---|---|---|---|---|---|---|
| Drone1 | S1 | 12 | 16.00 | -8 to 20 | 76.6 | 42 | 4.13 |
| Drone2 | S2 | 16 | 16.00 | -8 to 20 | 73.7 | 46 | 4.4 |

Skills: Drone1: TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success; Drone2: TAKE_OFF success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success. Contacts polled: Drone1–SM_seaM, Drone2–SM_seaM.

## Live beside the mock (seed 17)

| Drone | Polls | Max off track m | Median off track m | Max height error at cruise m | Pad error m |
|---|---|---|---|---|---|
| Drone1 | 378 | 2.79 | 0.1 | 8.9 | 0.34 |
| Drone2 | 378 | 2.77 | 0.1 | 12.86 | 0.17 |

| | Live | Mock |
|---|---|---|
| Completion s | 39.9 | 31.1 |
| Coverage | 1.0 | 1.0 |
| Closest pair m | 4.031 | 4.0 |
| Drone1 battery used % (estimated 4.13) | 4.19 | 3.44 |
| Drone2 battery used % (estimated 4.4) | 4.31 | 3.66 |

## Every seed

| Seed | Targets (sector) | Met | Completion s | Coverage | Reported at s | Closest pair m | Lowest battery % | Failing |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 (12, -14) S1, T2 (11, 12) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 2 | T1 (14, 11) S2, T2 (12, -14) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 3 | T1 (7, -20) S1, T2 (8, 11) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 4 | T1 (-1, -20) S1, T2 (11, 22) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 5 | T1 (10, 23) S2, T2 (5, -11) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 14.6 | 4.031 | 95.7 | - |
| 6 | T1 (12, 18) S2, T2 (-3, -15) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 7 | T1 (-0, -16) S1, T2 (4, 26) S2 | yes | 39.9 | 1.0000 | T1 15.4, T2 30.1 | 4.031 | 95.7 | - |
| 8 | T1 (14, -24) S1, T2 (-1, 14) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 9 | T1 (4, -24) S1, T2 (-3, 18) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 10 | T1 (5, 19) S2, T2 (12, -13) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 11 | T1 (7, -11) S1, T2 (-1, 15) S2 | yes | 39.9 | 1.0000 | T1 15.1, T2 30.1 | 4.031 | 95.7 | - |
| 12 | T1 (9, -15) S1, T2 (7, 21) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 13 | T1 (9, -15) S1, T2 (0, 14) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 14 | T1 (10, -16) S1, T2 (2, 14) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 15 | T1 (-3, 22) S2, T2 (15, -26) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 16 | T1 (6, -19) S1, T2 (3, 23) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 17 | T1 (12, 25) S2, T2 (11, -15) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 18 | T1 (9, -21) S1, T2 (11, 24) S2 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 19 | T1 (11, 18) S2, T2 (-0, -22) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 30.1 | 4.031 | 95.7 | - |
| 20 | T1 (9, 22) S2, T2 (4, -10) S1 | yes | 39.9 | 1.0000 | T1 30.1, T2 14.2 | 4.031 | 95.7 | - |

**MET** — 20 of 20 seeds met (mission success, and every planned skill succeeded with no safety landing).
