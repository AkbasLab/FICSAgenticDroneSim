# Phase 4 exit criterion on the mock — evidence, 2026-10-21

> A fully scripted, **non-agentic** controller can complete the canonical mission.

**Met on the mock, 20 of 20 seeds**, by `scripts/search_relay_exit.py --block exit`. Tables below are generated from `../results/search-relay-exit-mock-20261021-093521-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_relay_001.toml` (`search_relay_001`) |
| Seeds | 1–20, fixed in `experiments/search_relay.EXIT_SEEDS` before any was flown; they include the canonical 17 |
| Controller | `control/scripted.py`, planned from `scenario.brief()` alone — no targets, no seed |
| Simulator | `MockWorld`, simulated time, one thread and adapter per drone |
| Observer | the mock's exact trace (`simulator/observer.mock_trajectories`) |
| Judge | `experiments/evaluation.evaluate`: AUV-05's six criteria |
| Code | commit `bc12512` + the step-4 changes (dirty: True); `agentic_uav` digest `3729c0c3d5b1e673` |
| Wall time | 5.51 s for all 20 |

A seed **meets** when the mission report succeeds AND every planned skill succeeded with no safety landing.

## Every seed

| Seed | T1 | T2 | C1 coverage | C2 | C3 reported at s | C4 | C5 | C6 batteries % | Completion s | Met |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | (107.8, -18.9) S1 | (79.6, 36.0) S2 | 0.9995 pass | 2/2 pass | T1 85.4 by Drone1, T2 65.0 by Drone2 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 2 | (195.8, 4.5) S4 | (106.8, -21.1) S1 | 0.9995 pass | 2/2 pass | T1 61.4 by Drone4, T2 85.4 by Drone1 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 3 | (83.5, -50.4) S1 | (170.1, -74.8) S3 | 0.9995 pass | 2/2 pass | T1 27.9 by Drone3, T2 46.4 by Drone3 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 4 | (48.3, -48.3) S1 | (184.0, 61.2) S4 | 0.9995 pass | 2/2 pass | T1 57.8 by Drone1, T2 99.8 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 5 | (179.3, -16.4) S3 | (179.2, 73.8) S4 | 0.9995 pass | 2/2 pass | T1 99.8 by Drone3, T2 123.1 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 6 | (185.8, 38.8) S4 | (40.0, 53.0) S2 | 0.9995 pass | 2/2 pass | T1 86.0 by Drone4, T2 92.2 by Drone2 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 7 | (52.1, 52.1) S2 | (82.9, -50.7) S1 | 0.9995 pass | 2/2 pass | T1 89.9 by Drone2, T2 27.8 by Drone3 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 8 | (117.0, -69.9) S1 | (136.8, 51.3) S4 | 0.9995 pass | 2/2 pass | T1 44.2 by Drone3, T2 104.9 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 9 | (69.9, 11.1) S2 | (120.5, 40.2) S4 | 0.9995 pass | 2/2 pass | T1 24.5 by Drone4, T2 85.4 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 10 | (154.3, -33.8) S3 | (105.1, -14.1) S1 | 0.9995 pass | 2/2 pass | T1 85.4 by Drone3, T2 120.9 by Drone1 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 11 | (84.8, 73.9) S2 | (80.6, 47.0) S2 | 0.9995 pass | 2/2 pass | T1 104.3 by Drone2, T2 65.6 by Drone2 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 12 | (92.6, 53.3) S2 | (40.9, -50.0) S1 | 0.9995 pass | 2/2 pass | T1 85.4 by Drone2, T2 59.0 by Drone1 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 13 | (94.8, 54.7) S2 | (134.9, 18.4) S4 | 0.9995 pass | 2/2 pass | T1 85.4 by Drone2, T2 67.0 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 14 | (96.2, -27.8) S1 | (141.7, 20.5) S4 | 0.9995 pass | 2/2 pass | T1 86.1 by Drone1, T2 65.4 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 15 | (120.9, 58.9) S4 | (118.9, -78.7) S1 | 0.9995 pass | 2/2 pass | T1 85.4 by Drone2, T2 44.2 by Drone3 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 16 | (78.4, 33.4) S2 | (72.8, 52.6) S2 | 0.9995 pass | 2/2 pass | T1 65.1 by Drone2, T2 85.7 by Drone2 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 17 | (184.5, -3.2) S3 | (101.3, 56.3) S2 | 0.9995 pass | 2/2 pass | T1 149.0 by Drone3, T2 85.4 by Drone2 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 18 | (92.9, -53.2) S1 | (76.7, 21.2) S2 | 0.9995 pass | 2/2 pass | T1 44.2 by Drone3, T2 26.4 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 19 | (182.8, -38.4) S3 | (151.5, -0.3) S3 | 0.9995 pass | 2/2 pass | T1 87.3 by Drone3, T2 44.2 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |
| 20 | (174.9, 61.3) S4 | (140.8, 50.9) S4 | 0.9995 pass | 2/2 pass | T1 99.8 by Drone4, T2 104.2 by Drone4 | pass | pass | 78.6 / 78.9 / 74.0 / 73.9 pass | 182.167 | yes |

## The plan, the same for every seed

| Drone | Sector | Height m | Lanes m | Planned length m | Estimated s | Estimated battery % | Skills |
|---|---|---|---|---|---|---|---|
| Drone1 | S1 | 12 | 16.0 | 675.4 | 162.1 | 22.09 | TAKE_OFF → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND |
| Drone2 | S2 | 16 | 16.0 | 656.7 | 162.3 | 21.89 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND |
| Drone3 | S3 | 20 | 16.0 | 807.3 | 196.5 | 26.77 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND |
| Drone4 | S4 | 24 | 16.0 | 800.8 | 199.2 | 26.94 | TAKE_OFF → FOLLOW_WAYPOINTS → SEARCH_REGION → FOLLOW_WAYPOINTS → LAND |

Every planned skill succeeded on every seed: 380 of 380 skill results, none a safety landing.


## Observations, measured from the same 20 flights

Re-flown in-process from the same code, which is deterministic: the saved
reports are identical, seed by seed, to an earlier dry run, and a test flies
seed 17 twice and compares the records.

* **Reports went through relays more often than not, with no relay logic.**
  Of the 40 first reports, 27 were made while the detecting drone was itself
  out of the base's 100 m: 13 at the moment of detection, through other drones
  that happened to be nearer the base, and 14 later. 9 were direct at the
  moment of detection, 4 direct on the way back. 17 of the 40 targets lay in
  the far sectors S3 and S4.
* **Drones detect in transit.** Drone3 crosses S1 on its way to S3: the first
  report of 5 of the 11 S1 targets came from Drone3, not Drone1. Likewise
  Drone4 for 2 of the 12 S2 targets, and one each the other way round in the
  far sectors (an S3 target by Drone4, an S4 target by Drone2). Detection does
  not care whose sector a target is in.
* **The closest pair is Drone1–Drone2, 3.31 m, at 141.6 s, on every seed.**
  Drone1, inbound at 12 m, is at (1.64, −2.18) as Drone2 descends on its pad
  through 11.2 m: 3.21 m apart horizontally, 0.8 m vertically. That is 1.3 m clear of the 2 m minimum
  on the mock, which holds a line exactly; live flight does not, so a live run
  should keep it in mind.
* **Margins.** Completion 182.2 s of the 900 s deadline; the lowest battery
  73.9 %, against a 20 % reserve; coverage 0.9995 against 0.95.

## Dated note, 2026-10-21, later the same day: re-met after the lane-end overrun

Everything above stands for the code that produced it (digest
`3729c0c3d5b1e673`, at `1bcfcdc`). In step 5 the controller changed: lanes
now run 5 m past each sector end where the restricted zones allow, after a
corner target in the live variant went undetected (see the phase record,
"step 5, before flying"). The canonical exit was flown again with that
change, by the same script and seeds:
`../results/search-relay-exit-mock-20261021-183608-overrun.jsonl`.

**20 of 20 seeds met**: every criterion on every seed, 380/380 skills.
Completion 192.1 s (was 182.2), coverage 0.99977 (was 0.9995), closest pair
3.36 m (was 3.31), lowest battery 72.4 % (was 73.9). Over seeds 1–2000, the
plan now misses a target on 1 seed, against 3 before.
