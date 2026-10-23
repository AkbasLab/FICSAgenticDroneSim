# Phase 6 exit criterion — evidence, 2026-10-23

> The experiment logger can show, for each decision, **exactly what the agent knew and what it did not know**.

**Met on the mock.** 40 of 40 flights met their tasks; **1340 of 1340 decisions** were logged complete, correct and without a leak. Generated from `../results/knowledge-exit-20261023-095034-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Logger | `experiments/knowledge.py`: for each decision, what the agent knew (each field, its source, its age), what it recorded as unknown, and the truth gap; three checks |
| Single | `configs/scenarios/search_single_001.toml`, one rule agent told only `'search S3'` (Phase 5's exit task) |
| Pair | `configs/scenarios/search_pair_001.toml`, two independent rule agents: Drone1 `'search S1'` at 12 m, Drone2 `'search S2'` at 16 m. Neither hears the other |
| Agents | `agents/drone_agent.py` with `agents/rule_policy.py`; the belief is `agents/belief_state.py`'s six blocks, taken BEFORE each decision |
| Seeds | 1–20, Phase 4's, for each set |
| Code | commit `8a5597f` + the step-5 files (dirty: True); `agentic_uav` digest `7bb546fe63088f65` |
| Wall time | 12.25 s for all 40 flights and their logs |

## The three checks, on every decision

* **Complete:** the snapshot has the six blocks, and every field has a known source. An unsourced field fails it.
* **Correct:** its position, battery and base link match the truth at that instant (within 0.01 m and 0.01 %: the snapshot rounds); its sightings are exactly the targets this drone had detected by then.
* **No leak:** no unseen target's id or position, and no teammate's true position, appears in what it knew.

Each is shown able to fail in `tests/test_knowledge.py` (`ChecksCanFailTests`): a field with no source, a missing block, a position 1 m off, a battery 1 % off, the link flipped, a sighting it never made, a sighting it had made dropped, an unseen target's position or id and a teammate's true position slipped into the belief.

## Every flight

| Set | Seed | Task met | Decisions | Passed | Known items | Unknown items | Truth-gap items |
|---|---|---|---|---|---|---|---|
| single | 1 | yes | 23 | 23 | 1009 | 102 | 22 |
| single | 2 | yes | 24 | 24 | 1053 | 107 | 20 |
| single | 3 | yes | 23 | 23 | 1013 | 98 | 14 |
| single | 4 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 5 | yes | 23 | 23 | 1006 | 105 | 27 |
| single | 6 | yes | 24 | 24 | 1052 | 108 | 25 |
| single | 7 | yes | 23 | 23 | 1008 | 103 | 21 |
| single | 8 | yes | 24 | 24 | 1056 | 104 | 17 |
| single | 9 | yes | 23 | 23 | 1011 | 100 | 16 |
| single | 10 | yes | 23 | 23 | 1006 | 105 | 25 |
| single | 11 | yes | 24 | 24 | 1050 | 110 | 27 |
| single | 12 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 13 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 14 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 15 | yes | 24 | 24 | 1052 | 108 | 21 |
| single | 16 | yes | 23 | 23 | 1008 | 103 | 23 |
| single | 17 | yes | 24 | 24 | 1050 | 110 | 28 |
| single | 18 | yes | 24 | 24 | 1050 | 110 | 24 |
| single | 19 | yes | 23 | 23 | 1006 | 105 | 26 |
| single | 20 | yes | 23 | 23 | 1008 | 103 | 25 |
| pair | 1 | yes | 44 | 44 | 1875 | 295 | 107 |
| pair | 2 | yes | 44 | 44 | 1864 | 306 | 104 |
| pair | 3 | yes | 42 | 42 | 1778 | 292 | 95 |
| pair | 4 | yes | 44 | 44 | 1864 | 306 | 107 |
| pair | 5 | yes | 44 | 44 | 1864 | 306 | 113 |
| pair | 6 | yes | 44 | 44 | 1864 | 306 | 110 |
| pair | 7 | yes | 42 | 42 | 1787 | 283 | 103 |
| pair | 8 | yes | 43 | 43 | 1821 | 299 | 99 |
| pair | 9 | yes | 44 | 44 | 1864 | 306 | 101 |
| pair | 10 | yes | 43 | 43 | 1821 | 299 | 109 |
| pair | 11 | yes | 44 | 44 | 1872 | 298 | 111 |
| pair | 12 | yes | 44 | 44 | 1874 | 296 | 107 |
| pair | 13 | yes | 43 | 43 | 1821 | 299 | 105 |
| pair | 14 | yes | 44 | 44 | 1864 | 306 | 107 |
| pair | 15 | yes | 43 | 43 | 1821 | 299 | 104 |
| pair | 16 | yes | 42 | 42 | 1787 | 283 | 105 |
| pair | 17 | yes | 44 | 44 | 1864 | 306 | 113 |
| pair | 18 | yes | 44 | 44 | 1864 | 306 | 109 |
| pair | 19 | yes | 43 | 43 | 1829 | 291 | 108 |
| pair | 20 | yes | 44 | 44 | 1874 | 296 | 110 |

## One decision, in full: the single agent about to search (seed 17)

At 12.0 s, on `skill_succeeded`, it decided **start SEARCH_REGION** — "at S3". Checks: all passed.

**What it knew** — 44 items, by source:

| Source | Items | For example |
|---|---|---|
| the brief | 10 | `self.vehicle_id` = "Drone1" |
| sensing, now | 6 | `self.position` = [12.9, -17.1, 12.0] |
| its own decisions | 6 | `self.current_task` = "search S3" |
| assumed | 6 | `assumptions.battery_model` = "the brief's battery model holds" |
| its own executor | 5 | `self.current_skill` = null |
| estimated from own positions | 3 | `self.velocity` = [1.71, -2.267, 0.0] |
| its own sensing | 2 | `local_map.observed_targets` = {} |
| the belief's own version | 1 | `schema` = 2 |
| its first reading | 1 | `self.home` = [0.0, 0.0] |
| the brief, against its own clock | 1 | `mission.deadline_in_s` = 888 |
| its own reckoning: seen while linked to the base | 1 | `local_map.reported_targets` = [] |
| the brief's roster | 1 | `team` = {} |
| sensing, over time | 1 | `communication.base_reachable_for_s` = 12 |

Its assumptions, as it held them:

| Assumption | Statement | Evidence | Age s | Confidence |
|---|---|---|---|---|
| battery_model | the brief's battery model holds | linear: 0.05 %/s aloft and 0.02 %/m moving, from the brief, uncalibrated | 12 | 0.8 |
| fits | the battery and the time cover the rest of the task | about 25.9 % and 203 s needed for 863 m; 99.4 % (reserve 20 + 2) and 892 s left | 4.5 | 0.5 |
| hazards | the brief's zones are all the hazards, and 2 m clear of them is safe | zones in the brief: R1; no hazard sensed | 12 | 0.8 |
| reporting | what it sees reaches the base on the way home | home is 8.0 m from the base, inside its 100 m radio | 12 | 0.8 |
| speed | the drone keeps making 5.00 m/s for the rest | the planned speed; not measured until the search is under way | 4.5 | 0.5 |
| teammates | separation is not its concern: it flies alone | no other drone on the brief's roster | 12 | 1 |

**What it recorded as unknown:**

| What | Why |
|---|---|
| `communication.estimated_latency_s` | not measured until Phase 7 |
| `communication.recent_loss_rate` | not measured until Phase 7 |
| `communication.connected_peers` | not measured until Phase 7 |
| `targets` | where 2 more target(s) are; it has seen 0 |
| `sector S3` | not searched by this drone |

**The truth gap** (from ground truth; the agent never had it):

| What | It believed | The truth |
|---|---|---|
| target T1 | not seen | at (184.5, -3.2) in S3; this drone first sees it at 134.142 s |
| target T2 | not seen | at (181.3, -23.7) in S3; this drone first sees it at 103.528 s |

Over the flight, how much it did not know (seed 17):

| t s | Decision | Targets still unseen | Unknown items | Truth-gap items |
|---|---|---|---|---|
| 0 | start TAKE_OFF — task 'search S3' | T1, T2 | 7 | 2 |
| 7.5 | start FOLLOW_WAYPOINTS — airborne | T1, T2 | 6 | 2 |
| 12 | start SEARCH_REGION — at S3 | T1, T2 | 5 | 2 |
| 27 | continue — nothing calls for a change | T1, T2 | 5 | 2 |
| 104 | continue — nothing calls for a change | T1 | 5 | 1 |
| 134.5 | continue — nothing calls for a change | - | 4 | 0 |
| 138 | start FOLLOW_WAYPOINTS — S3 searched | - | 4 | 0 |
| 161 | continue — nothing calls for a change | - | 3 | 0 |
| 181 | start LAND — home | - | 3 | 0 |
| 187.5 | finish — landed: task over | - | 4 | 0 |

## Two independent agents: what each knew of the other (seed 17)

Each knew its teammate was on the roster (the brief) and nothing more. Every decision of each, with what it believed of the other against where the other really was:

| t s | Drone | Decision | Believed of its teammate | Teammate truly at (x, y, alt) |
|---|---|---|---|---|
| 0 | Drone1 | start TAKE_OFF — task 'search S1' | never heard | (4.0, 0.0, 0.0) |
| 0 | Drone2 | start TAKE_OFF — task 'search S2' | never heard | (0.0, 0.0, 0.0) |
| 7.5 | Drone1 | start SEARCH_REGION — airborne | never heard | (4.0, 0.0, 16.0) |
| 8 | Drone2 | start FOLLOW_WAYPOINTS — airborne | never heard | (1.2, -2.2, 12.0) |
| 17 | Drone2 | start SEARCH_REGION — at S2 | never heard | (23.1, -41.5, 12.0) |
| 29 | Drone1 | continue — nothing calls for a change | never heard | (90.4, 8.0, 16.0) |
| 29 | Drone2 | continue — nothing calls for a change | never heard | (65.1, -72.0, 12.0) |
| 47 | Drone1 | continue — nothing calls for a change | never heard | (85.6, 24.0, 16.0) |
| 47 | Drone2 | continue — nothing calls for a change | never heard | (110.9, -56.0, 12.0) |
| 73 | Drone1 | continue — nothing calls for a change | never heard | (108.4, 40.0, 16.0) |
| 73 | Drone2 | continue — nothing calls for a change | never heard | (83.1, -40.0, 12.0) |
| 89.5 | Drone1 | continue — nothing calls for a change | never heard | (75.1, 56.0, 16.0) |
| 90 | Drone1 | continue — nothing calls for a change | never heard | (72.6, 56.0, 16.0) |
| 90 | Drone2 | continue — nothing calls for a change | never heard | (97.9, -24.0, 12.0) |
| 113 | Drone2 | continue — nothing calls for a change | never heard | (81.1, -8.0, 12.0) |
| 115 | Drone1 | continue — nothing calls for a change | never heard | (116.4, 72.0, 16.0) |
| 115 | Drone2 | continue — nothing calls for a change | never heard | (91.1, -8.0, 12.0) |
| 117 | Drone2 | start FOLLOW_WAYPOINTS — S2 searched | never heard | (101.1, -8.0, 12.0) |
| 122 | Drone1 | start FOLLOW_WAYPOINTS — S1 searched | never heard | (102.5, 61.0, 16.0) |
| 128 | Drone1 | continue — nothing calls for a change | never heard | (75.6, 47.8, 16.0) |
| 128 | Drone2 | continue — nothing calls for a change | never heard | (95.2, -11.1, 12.0) |
| 146 | Drone2 | start LAND — home | never heard | (8.4, -11.2, 12.0) |
| 149 | Drone1 | start LAND — home | never heard | (4.0, 0.0, 10.0) |
| 154.5 | Drone2 | finish — landed: task over | never heard | (0.0, 0.0, 1.0) |
| 155.5 | Drone1 | finish — landed: task over | never heard | (4.0, 0.0, 0.0) |

Across all 869 pair decisions: "never heard from" 869 times.

**Exit criterion: MET** on the mock.
