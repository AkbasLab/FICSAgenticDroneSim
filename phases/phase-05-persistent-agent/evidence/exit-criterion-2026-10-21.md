# Phase 5 exit criterion — evidence, 2026-10-21

> One deterministic persistent agent completes a search task **without receiving a complete
> preflight action list**, recognises success or failure, and decides what to do next.

**Met on the mock.** 20 of 20 seeds completed the task; 5 of 5 kinds of trouble were recognised and answered as fixed beforehand. Generated from `../results/single-agent-exit-20261021-215820-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_single_001.toml`: the canonical mission cut to one drone and the far sector S3 |
| Task | `'search S3'` — the agent's only instruction |
| Agent | `agents/drone_agent.py` (observe every 0.5 s tick, decide only on events, validate, execute, verify) with `agents/rule_policy.py` |
| Its knowledge | `core.sensing` readings (own position, battery, sightings, base link) and the public brief; no scenario, targets or seed (a test refuses it) |
| Judge | `experiments/evaluation.py`, AUV-05's six criteria |
| Seeds | 1–20, Phase 4's, fixed before flying |
| Code | commit `cbb3913` + the step-5 files (dirty: True); `agentic_uav` digest `218ab87329156ed8` |
| Wall time | 4.28 s for all 25 flights |

## Part 1 — completes the task, with no preflight list

A seed meets when the mission report succeeds, the agent itself decided it was finished, and every skill was a START decision made in answer to an event.

| Seed | Targets | Met | Completion s | Coverage | Reported at s | Battery left % | Skills | Decisions |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 (188, -19), T2 (160, -44) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 2 | T1 (196, -75), T2 (187, -21) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 3 | T1 (164, -50), T2 (170, -75) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 4 | T1 (128, -48), T2 (184, -19) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 5 | T1 (179, -16), T2 (157, -5) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 6 | T1 (186, -41), T2 (120, -27) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 7 | T1 (132, -28), T2 (163, -51) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 8 | T1 (197, -70), T2 (127, -60) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 9 | T1 (150, -69), T2 (121, -40) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 10 | T1 (154, -34), T2 (185, -14) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 11 | T1 (165, -6), T2 (161, -33) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 12 | T1 (173, -27), T2 (121, -50) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 13 | T1 (175, -25), T2 (135, -62) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 14 | T1 (176, -28), T2 (142, -60) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 15 | T1 (121, -21), T2 (199, -79) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 16 | T1 (158, -47), T2 (153, -27) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 17 | T1 (185, -3), T2 (181, -24) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 18 | T1 (173, -53), T2 (183, -11) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 24 |
| 19 | T1 (183, -38), T2 (151, -0) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |
| 20 | T1 (175, -19), T2 (141, -29) | yes | 187.5 | 1.0 | T1 161.0, T2 161.0 | 72.9 | 5 | 23 |

Every seed flew the same 5 skills — TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND — each chosen when the one before it ended. Seed 17's decisions, without the quiet periodic checks it simply carried on through:

| t s | Events | It knew (position, battery, base link, stage) | Decision | Reason | What it did |
|---|---|---|---|---|---|
| 0.0 | task_assigned | (0, 0, 0 m), 100.0 %, link, - | start TAKE_OFF | task 'search S3' | started TAKE_OFF #1 |
| 7.5 | skill_succeeded | (0, 0, 12 m), 99.4 %, link, taking_off | start FOLLOW_WAYPOINTS | airborne | started FOLLOW_WAYPOINTS #2 |
| 12.0 | skill_succeeded | (13, -17, 12 m), 98.7 %, link, to_sector | start SEARCH_REGION | at S3 | started SEARCH_REGION #3 |
| 138.0 | skill_succeeded | (205, -8, 12 m), 79.8 %, no link, searching | start FOLLOW_WAYPOINTS | S3 searched | started FOLLOW_WAYPOINTS #4 |
| 181.0 | skill_succeeded | (0, 0, 12 m), 73.4 %, link, going_home | start LAND | home | started LAND #5 |
| 187.5 | skill_succeeded | (0, 0, 0 m), 72.9 %, link, landing | finish | landed: task over | finished |

## Part 2 — recognises success or failure, and decides

Each trouble and what the agent had to do were written into `experiments/single_agent.TROUBLES` before any was flown. A trouble is met when the agent did that, ended the task itself, decided something after every failed skill, and came home safe.

| Trouble | What went wrong | What it had to do | Skills, and how each ended | Its reason | Met |
|---|---|---|---|---|---|
| fault once | the first horizontal move fails, once (the transit round R1) | retry from where it is, then complete the task | TAKE_OFF success, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success | - | **yes** |
| fault for good | every horizontal move fails | retry twice, give up, land on its pad | TAKE_OFF success, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, FOLLOW_WAYPOINTS failed, LAND success | gave up to_sector after 2 retries: FOLLOW_WAYPOINTS failed: RuntimeError: injected fault that does not clear | **yes** |
| slow, short battery | half speed, hover drain 0.25 %/s (enough at full speed) | turn back on battery, land above the reserve | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted, FOLLOW_WAYPOINTS success, LAND success | low battery: 82.6 % left, about 63.8 % to finish and get home, under the 20 % reserve plus 2 | **yes** |
| slow, short deadline | half speed, deadline 260 s (enough at full speed) | turn back on time, land before the deadline | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION aborted, FOLLOW_WAYPOINTS success, LAND success | short of time: 220 s left, about 237 s to finish and get home | **yes** |
| too little battery | hover drain 0.5 %/s: the search cannot be flown at all | not begin the search; land | TAKE_OFF success, LAND success | low battery: 96.2 % left, about 103.6 % to finish and get home, under the 20 % reserve plus 2 | **yes** |

**fault once** — the decisions:

| t s | Events | It knew (position, battery, base link, stage) | Decision | Reason | What it did |
|---|---|---|---|---|---|
| 0.0 | task_assigned | (0, 0, 0 m), 100.0 %, link, - | start TAKE_OFF | task 'search S3' | started TAKE_OFF #1 |
| 7.5 | skill_succeeded | (0, 0, 12 m), 99.4 %, link, taking_off | start FOLLOW_WAYPOINTS | airborne | started FOLLOW_WAYPOINTS #2 |
| 8.0 | skill_failed | (0, 0, 12 m), 99.4 %, link, to_sector | start FOLLOW_WAYPOINTS | retry 1: FOLLOW_WAYPOINTS failed: RuntimeError: injected passing fault (0 more to come) | started FOLLOW_WAYPOINTS #3 |
| 12.5 | skill_succeeded | (13, -17, 12 m), 98.7 %, link, to_sector | start SEARCH_REGION | at S3 | started SEARCH_REGION #4 |
| 138.5 | skill_succeeded | (205, -8, 12 m), 79.8 %, no link, searching | start FOLLOW_WAYPOINTS | S3 searched | started FOLLOW_WAYPOINTS #5 |
| 181.5 | skill_succeeded | (0, 0, 12 m), 73.4 %, link, going_home | start LAND | home | started LAND #6 |
| 188.0 | skill_succeeded | (0, 0, 0 m), 72.8 %, link, landing | finish | landed: task over | finished |

**slow, short battery** — the decisions:

| t s | Events | It knew (position, battery, base link, stage) | Decision | Reason | What it did |
|---|---|---|---|---|---|
| 0.0 | task_assigned | (0, 0, 0 m), 100.0 %, link, - | start TAKE_OFF | task 'search S3' | started TAKE_OFF #1 |
| 11.0 | skill_succeeded | (0, 0, 12 m), 97.1 %, link, taking_off | start FOLLOW_WAYPOINTS | airborne | started FOLLOW_WAYPOINTS #2 |
| 20.0 | skill_succeeded | (13, -17, 12 m), 94.4 %, link, to_sector | start SEARCH_REGION | at S3 | started SEARCH_REGION #3 |
| 59.5 | periodic | (100, -64, 12 m), 82.6 %, no link, searching | start FOLLOW_WAYPOINTS | low battery: 82.6 % left, about 63.8 % to finish and get home, under the 20 % reserve plus 2 | aborted SEARCH_REGION #3, then started FOLLOW_WAYPOINTS #4 |
| 108.1 | skill_succeeded | (0, 0, 12 m), 68.0 %, link, going_home | start LAND | home | started LAND #5 |
| 121.1 | skill_succeeded | (0, 0, 0 m), 64.5 %, link, landing | finish | landed: task over (low battery: 82.6 % left, about 63.8 % to finish and get home, under the 20 % reserve plus 2) | finished |

**Exit criterion: MET** on the mock.

