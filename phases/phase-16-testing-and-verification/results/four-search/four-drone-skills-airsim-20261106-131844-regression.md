# Four-drone skill run — airsim

Run 2026-11-06T13:17:53, `scripts/four_drone_skills.py`, clock `RealClock`.

| Drone | # | Skill | Status | Error | Start s | End s | Final altitude m | Heading ° |
|---|---|---|---|---|---|---|---|---|
| Drone1 | 0 | TAKE_OFF | success |  | 0.0 | 11.5 | 12.24 | 0.0 |
| Drone1 | 1 | GO_TO_WAYPOINT | success |  | 11.5 | 19.5 | 12.52 | -87.5 |
| Drone1 | 2 | HOLD_POSITION | success |  | 19.5 | 24.5 | 12.51 | -87.6 |
| Drone1 | 3 | RETURN_HOME | success |  | 24.5 | 30.1 | 13.01 | -87.6 |
| Drone1 | 4 | LAND | success |  | 30.1 | 37.9 | 1.17 | -87.7 |
| Drone2 | 0 | TAKE_OFF | success |  | 0.0 | 12.3 | 16.30 | 0.0 |
| Drone2 | 1 | GO_TO_WAYPOINT | success |  | 12.3 | 20.3 | 16.54 | 87.6 |
| Drone2 | 2 | HOLD_POSITION | success |  | 20.3 | 25.4 | 16.54 | 87.7 |
| Drone2 | 3 | RETURN_HOME | success |  | 25.4 | 31.0 | 17.03 | 87.7 |
| Drone2 | 4 | LAND | success |  | 31.0 | 40.8 | 1.17 | 87.7 |
| Drone3 | 0 | TAKE_OFF | success |  | 0.0 | 13.1 | 20.24 | 0.0 |
| Drone3 | 1 | GO_TO_WAYPOINT | success |  | 13.1 | 21.1 | 20.54 | -87.6 |
| Drone3 | 2 | HOLD_POSITION | success |  | 21.1 | 26.1 | 20.54 | -87.7 |
| Drone3 | 3 | RETURN_HOME | success |  | 26.1 | 31.8 | 21.04 | -87.7 |
| Drone3 | 4 | LAND | success |  | 31.8 | 43.6 | 1.20 | -87.7 |
| Drone4 | 0 | TAKE_OFF | success |  | 0.0 | 13.9 | 24.31 | 0.0 |
| Drone4 | 1 | GO_TO_WAYPOINT | success |  | 13.9 | 22.0 | 24.53 | 87.6 |
| Drone4 | 2 | HOLD_POSITION | success |  | 22.0 | 27.0 | 24.53 | 87.7 |
| Drone4 | 3 | RETURN_HOME | success |  | 27.0 | 32.6 | 25.02 | 87.7 |
| Drone4 | 4 | LAND | success |  | 32.6 | 46.4 | 1.18 | 87.7 |

Closest approach per pair (SeparationMonitor, 10 Hz): Drone1-Drone2 4.03 m, Drone1-Drone3 8.02 m, Drone1-Drone4 12.02 m, Drone2-Drone3 4.0 m, Drone2-Drone4 8.0 m, Drone3-Drone4 4.0 m. Drone-to-drone contacts: 0.

**Exit criterion: MET** — every skill of every drone succeeded and returned a structured result.
