# Search-and-relay exit — search_relay_live_small, mock

Run 2026-10-21T18:36:14, `scripts/search_relay_exit.py`, 20 seeds (0.3 s wall). Controller: `control/scripted.py`, from the brief alone. Observer: the mock's exact trace. Judge: `experiments/evaluation.py`.

## The plan (the same for every seed)

| Drone | Sector | Height m | Lanes m | Lanes flown (x) | Length m | Estimated s | Estimated battery % |
|---|---|---|---|---|---|---|---|
| Drone1 | S1 | 12 | 16.00 | -8 to 20 | 76.6 | 42 | 4.13 |
| Drone2 | S2 | 16 | 16.00 | -8 to 20 | 73.7 | 46 | 4.4 |

## Every seed

| Seed | Targets (sector) | Met | Completion s | Coverage | Reported at s | Closest pair m | Lowest battery % | Failing |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 (12, -14) S1, T2 (11, 12) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 2 | T1 (14, 11) S2, T2 (12, -14) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 3 | T1 (7, -20) S1, T2 (8, 11) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 4 | T1 (-1, -20) S1, T2 (11, 22) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 5 | T1 (10, 23) S2, T2 (5, -11) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 9.6 | 4.0 | 96.3 | - |
| 6 | T1 (12, 18) S2, T2 (-3, -15) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 10.3 | 4.0 | 96.3 | - |
| 7 | T1 (-0, -16) S1, T2 (4, 26) S2 | yes | 31.1 | 1.0000 | T1 10.2, T2 20.2 | 4.0 | 96.3 | - |
| 8 | T1 (14, -24) S1, T2 (-1, 14) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 9 | T1 (4, -24) S1, T2 (-3, 18) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 10 | T1 (5, 19) S2, T2 (12, -13) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 11 | T1 (7, -11) S1, T2 (-1, 15) S2 | yes | 31.1 | 1.0000 | T1 9.9, T2 20.2 | 4.0 | 96.3 | - |
| 12 | T1 (9, -15) S1, T2 (7, 21) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 13 | T1 (9, -15) S1, T2 (0, 14) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 14 | T1 (10, -16) S1, T2 (2, 14) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 15 | T1 (-3, 22) S2, T2 (15, -26) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 16 | T1 (6, -19) S1, T2 (3, 23) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 17 | T1 (12, 25) S2, T2 (11, -15) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 18 | T1 (9, -21) S1, T2 (11, 24) S2 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 19 | T1 (11, 18) S2, T2 (-0, -22) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 20.2 | 4.0 | 96.3 | - |
| 20 | T1 (9, 22) S2, T2 (4, -10) S1 | yes | 31.1 | 1.0000 | T1 20.2, T2 9.3 | 4.0 | 96.3 | - |

Completion: 31.1–31.1 s of the 300 s deadline.

**Exit criterion: MET** — 20 of 20 seeds met (mission success, and every planned skill succeeded with no safety landing).
