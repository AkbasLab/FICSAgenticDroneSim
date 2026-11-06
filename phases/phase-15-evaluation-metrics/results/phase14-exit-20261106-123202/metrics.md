# Metrics (docs/METRICS.md version 1, sha256 d722ba2b3379)

Censored values are marked `≥`; — is absent (the run's metrics.json says why).

| Run | P1.success | P2.completion_s | P3.continuity_retention | P4.recovery_s | P5.guardian_interventions | P6.messages | P6.duplicates | CE.coordination_efficiency | D3.task_reassignments |
|---|---|---|---|---|---|---|---|---|---|
| 0001-A-search_relay_001-nominal-none-s1 | yes | 192 | — | — | 0 | 1140 | 84 | 0.743 | 0 |
| 0002-A-search_relay_001-nominal-drone1-at-60s-s1 | yes | 308 | 0.998 | 58.5 | 0 | 1524 | 87 | 0.702 | 1 |
| 0003-A-search_relay_001-severe-none-s1 | yes | 330 | 1 | — | 0 | 1948 | 98 | 0.743 | 0 |
| 0004-A-search_relay_001-severe-drone1-at-60s-s1 | yes | 702 | 0.995 | 59.4 | 0 | 3031 | 108 | 0.615 | 2 |
| 0005-B-search_relay_001-nominal-none-s1 | yes | 188 | — | — | 0 | 801 | 0 | 0.746 | 0 |
| 0006-B-search_relay_001-nominal-drone1-at-60s-s1 | no | ≥900 | 0.949 | ≥128 | 0 | 652 | 0 | 0.782 | 0 |
| 0007-B-search_relay_001-severe-none-s1 | yes | 188 | 1 | — | 0 | 801 | 0 | 0.746 | 0 |
| 0008-B-search_relay_001-severe-drone1-at-60s-s1 | no | ≥900 | 0.949 | ≥128 | 0 | 652 | 0 | 0.782 | 0 |
| 0009-C-search_relay_001-nominal-none-s1 | yes | 194 | — | — | 0 | 1153 | 0 | 0.743 | 0 |
| 0010-C-search_relay_001-nominal-drone1-at-60s-s1 | yes | 309 | 0.998 | 59.6 | 0 | 1457 | 0 | 0.702 | 1 |
| 0011-C-search_relay_001-severe-none-s1 | yes | 381 | 1 | — | 0 | 2243 | 1 | 0.494 | 9 |
| 0012-C-search_relay_001-severe-drone1-at-60s-s1 | yes | 420 | 0.998 | 65.1 | 0 | 1793 | 1 | 0.522 | 7 |
| 0013-D-search_relay_001-nominal-none-s1 | yes | 194 | — | — | 0 | 1153 | 0 | 0.743 | 0 |
| 0014-D-search_relay_001-nominal-drone1-at-60s-s1 | yes | 309 | 0.998 | 59.6 | 0 | 1457 | 0 | 0.702 | 1 |
| 0015-D-search_relay_001-severe-none-s1 | yes | 381 | 1 | — | 0 | 2243 | 1 | 0.494 | 9 |
| 0016-D-search_relay_001-severe-drone1-at-60s-s1 | yes | 420 | 0.998 | 65.1 | 0 | 1793 | 1 | 0.522 | 7 |
| 0017-D-no-memory-search_relay_001-severe-drone1-at-60s-s2 | yes | 502 | — | 96.7 | 0 | 2293 | 0 | 0.448 | 11 |
| 0018-D-no-leases-search_relay_001-severe-drone1-at-60s-s2 | no | ≥900 | — | ≥684 | 0 | 2920 | 0 | 0.619 | 3 |
| 0019-D-no-roles-search_relay_001-severe-drone1-at-60s-s2 | yes | 352 | — | 12.1 | 0 | 1562 | 0 | 0.619 | 7 |
| 0020-D-perfect-comms-search_relay_001-severe-drone1-at-60s-s2 | yes | 309 | — | 59.6 | 0 | 1456 | 0 | 0.702 | 1 |
| 0021-D-fallback-search_relay_001-severe-drone1-at-60s-s2 | yes | 502 | — | 96.7 | 0 | 2293 | 0 | 0.448 | 11 |
| 0022-D-no-guardian-search_relay_001-severe-drone1-at-60s-s2 | yes | 502 | — | 96.7 | 0 | 2293 | 0 | 0.448 | 11 |
| 0023-C-link-inputs-search_relay_001-severe-drone1-at-60s-s2 | yes | 502 | — | 96.7 | 0 | 2293 | 0 | 0.448 | 11 |
| 0024-C-no-guardian-search_relay_001-severe-drone1-at-60s-s2 | yes | 502 | — | 96.7 | 0 | 2293 | 0 | 0.448 | 11 |
| 0025-E-search_relay_001-perfect-none-s1 | yes | 192 | — | — | 0 | 0 | 0 | 0.747 | 0 |
| 0026-E-search_relay_001-perfect-none-s2 | yes | 192 | — | — | 0 | 0 | 0 | 0.747 | 0 |
| 0027-A-search_pair_001-nominal-none-s1 | yes | 161 | — | — | 0 | 587 | 52 | 0.988 | 0 |
| 0028-A-search_pair_001-nominal-drone1-at-60s-s1 | yes | 285 | 1 | 57.5 | 0 | 738 | 51 | 0.845 | 1 |
| 0029-C-search_pair_001-nominal-none-s1 | yes | 161 | — | — | 0 | 497 | 0 | 0.988 | 0 |
| 0030-C-search_pair_001-nominal-drone1-at-60s-s1 | yes | 284 | 1 | 58.6 | 0 | 566 | 0 | 0.845 | 1 |
| 0031-D-search_pair_001-nominal-none-s1 | yes | 161 | — | — | 0 | 497 | 0 | 0.988 | 0 |
| 0032-D-search_pair_001-nominal-drone1-at-60s-s1 | yes | 284 | 1 | 58.6 | 0 | 566 | 0 | 0.845 | 1 |
| 0033-C-search_relay_001-partitioned-none-s1 | yes | 314 | 1 | — | 0 | 1953 | 0 | 0.452 | 4 |
| 0034-D-search_relay_001-partitioned-none-s1 | yes | 314 | 1 | — | 0 | 1953 | 0 | 0.452 | 4 |
| 0035-C-search_relay_001-nominal-unsafe-proposal-s1 | yes | 309 | 1 | — | 1 | 1465 | 0 | 0.715 | 1 |
| 0036-D-search_relay_001-nominal-unsafe-proposal-s1 | yes | 309 | 1 | — | 1 | 1465 | 0 | 0.715 | 1 |
| 0037-D-search_relay_001-perfect-none-s1 | yes | 199 | — | — | 0 | 1159 | 0 | 0.743 | 0 |
| 0038-D-search_relay_001-perfect-none-s2 | yes | 199 | — | — | 0 | 1159 | 0 | 0.743 | 0 |
| 0039-D-search_relay_001-perfect-drone1-at-60s-s1 | yes | 309 | — | 59.6 | 0 | 1457 | 0 | 0.702 | 1 |
| 0040-D-search_relay_001-perfect-drone1-at-60s-s2 | yes | 309 | — | 59.6 | 0 | 1456 | 0 | 0.702 | 1 |
| 0041-C-search_relay_001-severe-drone1-at-60s-s3 | yes | 454 | — | 58.5 | 0 | 2264 | 0 | 0.411 | 10 |
| 0042-C-search_relay_001-severe-drone1-at-60s-s4 | yes | 395 | — | 23.6 | 0 | 1924 | 1 | 0.618 | 7 |
| 0043-C-search_relay_001-severe-drone1-at-60s-s5 | yes | 547 | — | 62.1 | 0 | 2446 | 3 | 0.451 | 16 |
