# Phase 3 exit criterion — evidence, 2026-10-21

> A deterministic script makes four drones take off, navigate to distinct waypoints, hold, return
> and land — and each skill returns a structured result rather than merely printing output.

**Met**, in CarlaAir and on the mock, by the same script and plan (`scripts/four_drone_skills.py`,
`agentic_uav/experiments/team_flight.exit_plan`), at commit `5738760`. Tables below are generated
from the two result files in `../results/`; the live contract's results are transcribed from the
terminal, where unittest printed them.

## The two runs

| | Live (CarlaAir, `RealClock`) | Mock (`SimClock`) |
|---|---|---|
| File | `four-drone-skills-airsim-20261021-005707-live` | `four-drone-skills-mock-20261021-005853-mock` |
| Skills succeeded | 20 / 20 | 20 / 20 |
| Flight span | 46.3 s real | 36.0 s simulated |
| Closest approach per pair | Drone1-Drone2 4.03 m, Drone1-Drone3 8.02 m, Drone1-Drone4 12.02 m, Drone2-Drone3 4.0 m, Drone2-Drone4 8.0 m, Drone3-Drone4 4.0 m (420 samples at 10 Hz) | Drone1-Drone2 4.0 m, Drone1-Drone3 8.0 m, Drone1-Drone4 12.0 m, Drone2-Drone3 4.0 m, Drone2-Drone4 8.0 m, Drone3-Drone4 4.0 m (exact) |
| Drone-to-drone contacts | 0 | 0 |
| Drones spawned at runtime | Drone2, Drone3, Drone4 | Drone2, Drone3, Drone4 |

## Every skill, live beside mock

Times from each run's first skill. Altitude is metres above the ground TAKE_OFF measured.

| Drone | Skill | Live status | Live start–end s | Live altitude m | Live heading ° | Mock start–end s | Mock altitude m |
|---|---|---|---|---|---|---|---|
| Drone1 | TAKE_OFF | success | 0.0–11.5 | 12.24 | 0.0 | 0.0–7.1 | 12.00 |
| Drone1 | GO_TO_WAYPOINT | success | 11.5–19.4 | 12.52 | -87.5 | 7.1–12.1 | 12.00 |
| Drone1 | HOLD_POSITION | success | 19.4–24.4 | 12.51 | -87.6 | 12.1–17.1 | 12.00 |
| Drone1 | RETURN_HOME | success | 24.4–30.1 | 13.01 | -87.6 | 17.1–21.1 | 12.00 |
| Drone1 | LAND | success | 30.1–37.9 | 1.17 | -87.7 | 21.1–27.6 | 0.00 |
| Drone2 | TAKE_OFF | success | 0.0–12.3 | 16.30 | 0.0 | 0.0–7.9 | 16.00 |
| Drone2 | GO_TO_WAYPOINT | success | 12.3–20.3 | 16.54 | 87.6 | 7.9–12.9 | 16.00 |
| Drone2 | HOLD_POSITION | success | 20.3–25.3 | 16.54 | 87.7 | 12.9–17.9 | 16.00 |
| Drone2 | RETURN_HOME | success | 25.3–30.9 | 17.03 | 87.7 | 17.9–21.9 | 16.00 |
| Drone2 | LAND | success | 30.9–40.8 | 1.17 | 87.7 | 21.9–30.4 | 0.00 |
| Drone3 | TAKE_OFF | success | 0.0–13.1 | 20.24 | 0.0 | 0.0–8.7 | 20.00 |
| Drone3 | GO_TO_WAYPOINT | success | 13.1–21.1 | 20.54 | -87.6 | 8.7–13.7 | 20.00 |
| Drone3 | HOLD_POSITION | success | 21.1–26.1 | 20.54 | -87.7 | 13.7–18.7 | 20.00 |
| Drone3 | RETURN_HOME | success | 26.1–31.7 | 21.04 | -87.7 | 18.7–22.7 | 20.00 |
| Drone3 | LAND | success | 31.7–43.6 | 1.16 | -87.7 | 22.7–33.2 | 0.00 |
| Drone4 | TAKE_OFF | success | 0.0–13.9 | 24.31 | 0.0 | 0.0–9.5 | 24.00 |
| Drone4 | GO_TO_WAYPOINT | success | 13.9–21.9 | 24.52 | 87.6 | 9.5–14.5 | 24.00 |
| Drone4 | HOLD_POSITION | success | 21.9–26.9 | 24.52 | 87.7 | 14.5–19.5 | 24.00 |
| Drone4 | RETURN_HOME | success | 26.9–32.5 | 25.01 | 87.7 | 19.5–23.5 | 24.00 |
| Drone4 | LAND | success | 32.5–46.3 | 1.17 | 87.7 | 23.5–36.0 | 0.00 |

## Grounds measured by TAKE_OFF, live

| Drone | Ground z (NED) |
|---|---|
| Drone1 | 29.245 |
| Drone2 | 29.282 |
| Drone3 | 29.281 |
| Drone4 | 27.29 |

Phase 1 recorded 29.25, 29.28 and 27.29 across M10's four spawn points (which drone stood
on which was not recorded): the same three values, measured here with the drone at rest and
uncontrolled.

## The live adapter contract

`AUV_LIVE_AIRSIM=1 python tests	est_adapter_contract.py -v LiveAirSimContract`, on a fresh
launch with Drone1 only, before the exit run: **Ran 15 tests in 178.517s — OK (skipped=1)**.

| Test | Result |
|---|---|
| `test_a_vehicle_starts_on_the_ground_uncontrolled` | ok |
| `test_add_ignores_the_pose_and_place_sets_it` | skipped by design (a spawned drone stays until restart) |
| `test_cancel_from_a_second_connection_stops_a_move` | **ok** — `cancelLastTask` on a third connection stopped a move running on a second |
| `test_cancel_with_nothing_moving_is_harmless` | ok |
| `test_confirm_connection` | ok |
| `test_declared_vehicles_are_listed` | ok |
| `test_hover_holds` | ok |
| `test_is_both_protocols` | ok |
| `test_land_returns_to_the_ground` | ok |
| `test_move_to_z_and_to_position` | ok |
| `test_reset_returns_to_spawn` | ok |
| `test_rotate_to_yaw` | **ok** — 90°, −135°, 0°, each within 5° |
| `test_take_control_and_release` | ok |
| `test_take_off_leaves_the_ground` | ok |
| `test_the_skills_fly_end_to_end` | ok |

Before any flight, a read-only check of the fresh scene read Drone1's heading as −45.6°;
Phase 1 measured the spawn heading as −45.59°.
