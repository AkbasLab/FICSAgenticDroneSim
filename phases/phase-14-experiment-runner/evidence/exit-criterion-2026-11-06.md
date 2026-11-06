# Phase 14 exit criterion — evidence, 2026-11-06

> A batch command executes a list of scenario configurations without manual prompts and produces one complete result directory per run.

**Met on the mock.** Generated from `../results/batch-exit-20261106-114052-exit.jsonl` and the batch directory beside it; nothing is transcribed.

## What ran

| | |
|---|---|
| Batch | `configs/experiments/phase14_exit.toml`: 43 runs |
| Command | `scripts/run_batch.py phase14_exit --jobs 10`, a child process with no input; twice; then runs ['0002-A-search_relay_001-nominal-drone1-at-60s-s1', '0018-D-no-leases-search_relay_001-severe-drone1-at-60s-s2', '0037-D-search_relay_001-perfect-none-s1'] removed from the second directory and the batch resumed |
| Code | commit `4369491` (dirty: False); `agentic_uav` digest `500f08b99c200660` |
| Outcome | 43 of 43 runs completed; 40 met the mission |
| Wall time | 77.2 s for both batches and the resume |
| The batch as flown | `phases/phase-14-experiment-runner/results/phase14-exit-20261106-113936` |

## The checks

| Check | Result |
|---|---|
| unattended | yes |
| one_directory_per_run | yes |
| manifests_complete | yes |
| every_event_type | yes |
| events_well_formed | yes |
| as_configured | yes |
| failures_kept | yes |
| deterministic | yes |
| resumes | yes |

## Every event type, and the first run it happened in

| Type | Events in the batch | First seen in |
|---|---|---|
| MISSION_STARTED | 43 | 0001-A-search_relay_001-nominal-none-s1 |
| OBSERVATION_RECEIVED | 6,426 | 0001-A-search_relay_001-nominal-none-s1 |
| BELIEF_UPDATED | 6,426 | 0001-A-search_relay_001-nominal-none-s1 |
| MESSAGE_SENT | 63,396 | 0001-A-search_relay_001-nominal-none-s1 |
| MESSAGE_DROPPED | 70,664 | 0001-A-search_relay_001-nominal-none-s1 |
| MESSAGE_RECEIVED | 121,004 | 0001-A-search_relay_001-nominal-none-s1 |
| TASK_ANNOUNCED | 139 | 0010-C-search_relay_001-nominal-drone1-at-60s-s1 |
| TASK_BID | 642 | 0009-C-search_relay_001-nominal-none-s1 |
| TASK_ASSIGNED | 303 | 0001-A-search_relay_001-nominal-none-s1 |
| TASK_RELEASED | 98 | 0002-A-search_relay_001-nominal-drone1-at-60s-s1 |
| ROLE_CHANGED | 489 | 0009-C-search_relay_001-nominal-none-s1 |
| LLM_CALLED | 1,531 | 0013-D-search_relay_001-nominal-none-s1 |
| DECISION_PROPOSED | 6,426 | 0001-A-search_relay_001-nominal-none-s1 |
| GUARDIAN_INTERVENED | 2 | 0035-C-search_relay_001-nominal-unsafe-proposal-s1 |
| SKILL_STARTED | 2,232 | 0001-A-search_relay_001-nominal-none-s1 |
| SKILL_COMPLETED | 2,232 | 0001-A-search_relay_001-nominal-none-s1 |
| TARGET_FOUND | 159 | 0001-A-search_relay_001-nominal-none-s1 |
| FAULT_INJECTED | 28 | 0002-A-search_relay_001-nominal-drone1-at-60s-s1 |
| MISSION_COMPLETED | 43 | 0001-A-search_relay_001-nominal-none-s1 |

## The runs

| Run | Status | Met | Completion s | Events |
|---|---|---|---|---|
| 0001-A-search_relay_001-nominal-none-s1 | completed | True | 192.1 | 6,006 |
| 0002-A-search_relay_001-nominal-drone1-at-60s-s1 | completed | True | 308.2 | 8,114 |
| 0003-A-search_relay_001-severe-none-s1 | completed | True | 330.5 | 10,438 |
| 0004-A-search_relay_001-severe-drone1-at-60s-s1 | completed | True | 702.1 | 16,189 |
| 0005-B-search_relay_001-nominal-none-s1 | completed | True | 188.0 | 3,563 |
| 0006-B-search_relay_001-nominal-drone1-at-60s-s1 | completed | False | None | 2,897 |
| 0007-B-search_relay_001-severe-none-s1 | completed | True | 188.0 | 3,563 |
| 0008-B-search_relay_001-severe-drone1-at-60s-s1 | completed | False | None | 2,897 |
| 0009-C-search_relay_001-nominal-none-s1 | completed | True | 194.1 | 5,053 |
| 0010-C-search_relay_001-nominal-drone1-at-60s-s1 | completed | True | 309.1 | 6,477 |
| 0011-C-search_relay_001-severe-none-s1 | completed | True | 381.3 | 9,798 |
| 0012-C-search_relay_001-severe-drone1-at-60s-s1 | completed | True | 420.4 | 7,889 |
| 0013-D-search_relay_001-nominal-none-s1 | completed | True | 194.1 | 5,119 |
| 0014-D-search_relay_001-nominal-drone1-at-60s-s1 | completed | True | 309.1 | 6,545 |
| 0015-D-search_relay_001-severe-none-s1 | completed | True | 381.3 | 9,946 |
| 0016-D-search_relay_001-severe-drone1-at-60s-s1 | completed | True | 420.4 | 8,000 |
| 0017-D-no-memory-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 502.0 | 10,196 |
| 0018-D-no-leases-search_relay_001-severe-drone1-at-60s-s2 | completed | False | None | 13,708 |
| 0019-D-no-roles-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 352.3 | 6,899 |
| 0020-D-perfect-comms-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 309.1 | 6,537 |
| 0021-D-fallback-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 502.0 | 10,024 |
| 0022-D-no-guardian-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 502.0 | 10,196 |
| 0023-C-link-inputs-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 502.0 | 10,024 |
| 0024-C-no-guardian-search_relay_001-severe-drone1-at-60s-s2 | completed | True | 502.0 | 10,024 |
| 0025-E-search_relay_001-perfect-none-s1 | completed | True | 192.134 | 44 |
| 0026-E-search_relay_001-perfect-none-s2 | completed | True | 192.134 | 43 |
| 0027-A-search_pair_001-nominal-none-s1 | completed | True | 161.1 | 1,919 |
| 0028-A-search_pair_001-nominal-drone1-at-60s-s1 | completed | True | 284.7 | 2,377 |
| 0029-C-search_pair_001-nominal-none-s1 | completed | True | 160.6 | 1,174 |
| 0030-C-search_pair_001-nominal-drone1-at-60s-s1 | completed | True | 283.7 | 1,326 |
| 0031-D-search_pair_001-nominal-none-s1 | completed | True | 160.6 | 1,203 |
| 0032-D-search_pair_001-nominal-drone1-at-60s-s1 | completed | True | 283.7 | 1,364 |
| 0033-C-search_relay_001-partitioned-none-s1 | completed | True | 313.8 | 8,517 |
| 0034-D-search_relay_001-partitioned-none-s1 | completed | True | 313.8 | 8,645 |
| 0035-C-search_relay_001-nominal-unsafe-proposal-s1 | completed | True | 309.1 | 6,518 |
| 0036-D-search_relay_001-nominal-unsafe-proposal-s1 | completed | True | 309.1 | 6,579 |
| 0037-D-search_relay_001-perfect-none-s1 | completed | True | 199.1 | 5,145 |
| 0038-D-search_relay_001-perfect-none-s2 | completed | True | 199.1 | 5,144 |
| 0039-D-search_relay_001-perfect-drone1-at-60s-s1 | completed | True | 309.1 | 6,543 |
| 0040-D-search_relay_001-perfect-drone1-at-60s-s2 | completed | True | 309.1 | 6,535 |
| 0041-C-search_relay_001-severe-drone1-at-60s-s3 | completed | True | 454.0 | 9,818 |
| 0042-C-search_relay_001-severe-drone1-at-60s-s4 | completed | True | 395.0 | 8,499 |
| 0043-C-search_relay_001-severe-drone1-at-60s-s5 | completed | True | 546.6 | 10,788 |
