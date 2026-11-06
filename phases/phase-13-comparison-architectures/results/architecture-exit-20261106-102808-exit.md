# Architecture exit — search_relay_001, mock

Run 2026-11-06T10:22:54, `scripts/architecture_exit.py`, 314 s wall. Every configuration in `configs/architectures/` (13) through `fly_architecture`, each seed with no stop and with Drone1 stopped at 60 s; models by the echo, and D replayed from Phase 12's 70B on seeds 1-5; seeds 1-5 flown twice. A perfect network (each arm under degraded links is Phase 17's to compare); the guardian and keep-out unless switched off.

| Seed | by_configuration | arms_as_claimed | ablations_off | limits_kept | deterministic |
|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes |
| 2 | yes | yes | yes | yes | yes |
| 3 | yes | yes | yes | yes | yes |
| 4 | yes | yes | yes | yes | yes |
| 5 | yes | yes | yes | yes | yes |
| 6 | yes | yes | yes | yes | yes |
| 7 | yes | yes | yes | yes | yes |
| 8 | yes | yes | yes | yes | yes |
| 9 | yes | yes | yes | yes | yes |
| 10 | yes | yes | yes | yes | yes |
| 11 | yes | yes | yes | yes | yes |
| 12 | yes | yes | yes | yes | yes |
| 13 | yes | yes | yes | yes | yes |
| 14 | yes | yes | yes | yes | yes |
| 15 | yes | yes | yes | yes | yes |
| 16 | yes | yes | yes | yes | yes |
| 17 | yes | yes | yes | yes | yes |
| 18 | yes | yes | yes | yes | yes |
| 19 | yes | yes | yes | yes | yes |
| 20 | yes | yes | yes | yes | yes |

**Each configuration over the seeds** (findings, not experiments: Phase 17 runs those):

| Configuration / flight | Met | Completion s (min, median, max) |
|---|---|---|
| A / Drone1 stopped | 20/20 | [308.2, 308.2, 308.2] |
| A / no stop | 20/20 | [192.1, 192.1, 192.1] |
| B / Drone1 stopped | 0/20 | None |
| B / no stop | 20/20 | [188.0, 188.0, 188.0] |
| C / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C / no stop | 20/20 | [194.1, 194.1, 194.1] |
| C-link-inputs / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C-link-inputs / no stop | 20/20 | [194.1, 194.1, 194.1] |
| C-no-guardian / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C-no-guardian / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D (70B) / Drone1 stopped | 5/5 | [308.0, 309.1, 309.1] |
| D (70B) / no stop | 5/5 | [193.0, 199.1, 199.1] |
| D / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-fallback / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-fallback / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-guardian / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-no-guardian / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-leases / Drone1 stopped | 0/20 | None |
| D-no-leases / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-memory / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-no-memory / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-roles / Drone1 stopped | 20/20 | [307.1, 307.1, 307.1] |
| D-no-roles / no stop | 20/20 | [188.0, 188.0, 188.0] |
| D-perfect-comms / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-perfect-comms / no stop | 20/20 | [194.1, 194.1, 194.1] |
| E / no stop | 20/20 | [192.1, 192.1, 192.1] |

**Exit criterion: MET** — 20 of 20 seeds passed every check.
