# Single-agent exit — search_single_001, mock

Run 2026-10-21T21:58:16, `scripts/single_agent_exit.py`, 4.3 s wall. Agent: `agents/drone_agent.py` with `agents/rule_policy.py`, told only `'search S3'`. Judge: `experiments/evaluation.py`.

## Nominal: the task, on every seed

| Seed | Met | Completion s | Coverage | Targets reported at s | Battery left % | Skills | Decisions |
|---|---|---|---|---|---|---|---|
| 1 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 2 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 3 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 4 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 5 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 6 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 7 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 8 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 9 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 10 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 11 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 12 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 13 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 14 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 15 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 16 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 17 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 18 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 24 |
| 19 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |
| 20 | yes | 187.5 | 1.0000 | T1 161.0, T2 161.0 | 72.9 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND | 23 |

## Trouble: what went wrong, what the agent had to do, what it did

| Trouble | What | Expected | Skills (how each ended) | Its reason | Criteria failing | Check |
|---|---|---|---|---|---|---|
| fault once | the first horizontal move fails, once (the transit round R1) | retry from where it is, then complete the task | TAKE_OFF success, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success | - | - | **met** |
| fault for good | every horizontal move fails | retry twice, give up, land on its pad | TAKE_OFF success, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, LAND success | gave up to_sector after 2 retries: FOLLOW_WAYPOINTS failed: RuntimeError: injected fault that does not clear | C1, C2, C3 | **met** |
| slow, short battery | half speed, hover drain 0.25 %/s (enough at full speed) | turn back on battery, land above the reserve | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted, FOLLOW_WAYPOINTS success, LAND success | low battery: 82.6 % left, about 63.8 % to finish and get home, under the 20 % reserve plus 2 | C1, C2, C3 | **met** |
| slow, short deadline | half speed, deadline 260 s (enough at full speed) | turn back on time, land before the deadline | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted, FOLLOW_WAYPOINTS success, LAND success | short of time: 220 s left, about 237 s to finish and get home | C1, C2, C3 | **met** |
| too little battery | hover drain 0.5 %/s: the search cannot be flown at all | not begin the search; land | TAKE_OFF success, LAND success | low battery: 96.2 % left, about 103.6 % to finish and get home, under the 20 % reserve plus 2 | C1, C2, C3 | **met** |

**Exit criterion: MET** — 20 of 20 nominal seeds met (mission success, finished by the agent, every skill chosen as it went); 5 of 5 troubles met their checks.
