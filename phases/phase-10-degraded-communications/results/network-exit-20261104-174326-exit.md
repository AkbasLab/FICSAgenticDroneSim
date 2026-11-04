# Network exit — search_relay_001, mock

Run 2026-11-04T17:19:13, `scripts/network_exit.py`, 1453.0 s wall. Four rule agents told only the team mission; each seed under nominal, moderate, severe, partitioned, with no stop and with Drone1 stopped at 60 s, every flight twice, and on Phase 9's network once.

| Seed | reproducible | as_configured | nominal_is_phase_9 | known_exactly |
|---|---|---|---|---|
| 1 | yes | yes | yes | yes |
| 2 | yes | yes | yes | yes |
| 3 | yes | yes | yes | yes |
| 4 | yes | yes | yes | yes |
| 5 | yes | yes | yes | yes |
| 6 | yes | yes | yes | yes |
| 7 | yes | yes | yes | yes |
| 8 | yes | yes | yes | yes |
| 9 | yes | yes | yes | yes |
| 10 | yes | yes | yes | yes |
| 11 | yes | yes | yes | yes |
| 12 | yes | yes | yes | yes |
| 13 | yes | yes | yes | yes |
| 14 | yes | yes | yes | yes |
| 15 | yes | yes | yes | yes |
| 16 | yes | yes | yes | yes |
| 17 | yes | yes | yes | yes |
| 18 | yes | yes | yes | yes |
| 19 | yes | yes | yes | yes |
| 20 | yes | yes | yes | yes |

**How the team fared, beside the exit** (over the seeds; not pass conditions):

| Condition / flight | Met | Completion s (min, median, max) | Searched twice | Leases run out | False alarms (suspected, unreachable, failed) | Loss estimated | Stale decisions | Stop detected, task taken |
|---|---|---|---|---|---|---|---|---|
| nominal / no stop | 20/20 | [194.1, 194.1, 194.1] | 0 | 0 | 0, 0, 0 | 0.0 | 0 | - |
| nominal / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] | 0 | 20 | 0, 0, 0 | 0.0 | 0 | 20/20, 20/20 |
| moderate / no stop | 20/20 | [194.1, 307.7, 439.7] | 20 | 18 | 30, 7, 4 | 0.0881 | 0 | - |
| moderate / Drone1 stopped | 20/20 | [308.7, 311.9, 596.3] | 22 | 41 | 12, 2, 0 | 0.0879 | 0 | 20/20, 8/20 |
| severe / no stop | 20/20 | [342.4, 510.9, 684.5] | 54 | 161 | 1129, 30, 22 | 0.2898 | 0 | - |
| severe / Drone1 stopped | 20/20 | [394.5, 494.4, 604.9] | 43 | 136 | 467, 12, 9 | 0.2902 | 0 | 1/20, 3/20 |
| partitioned / no stop | 20/20 | [313.3, 313.3, 313.3] | 20 | 80 | 160, 160, 160 | 0.0 | 0 | - |
| partitioned / Drone1 stopped | 20/20 | [432.4, 432.4, 432.4] | 20 | 80 | 80, 80, 80 | 0.0 | 0 | 20/20, 20/20 |

**Exit criterion: MET** — 20 of 20 seeds passed every check.
