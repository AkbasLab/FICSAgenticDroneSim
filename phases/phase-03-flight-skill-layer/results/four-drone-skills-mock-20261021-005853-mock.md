# Four-drone skill run — mock

Run 2026-10-21T00:58:52, `scripts/four_drone_skills.py`, clock `SimClock`.

| Drone | # | Skill | Status | Error | Start s | End s | Final altitude m | Heading ° |
|---|---|---|---|---|---|---|---|---|
| Drone1 | 0 | TAKE_OFF | success |  | 0.0 | 7.1 | 12.00 | 0.0 |
| Drone1 | 1 | GO_TO_WAYPOINT | success |  | 7.1 | 12.1 | 12.00 | -90.0 |
| Drone1 | 2 | HOLD_POSITION | success |  | 12.1 | 17.1 | 12.00 | -90.0 |
| Drone1 | 3 | RETURN_HOME | success |  | 17.1 | 21.1 | 12.00 | -90.0 |
| Drone1 | 4 | LAND | success |  | 21.1 | 27.6 | 0.00 | -90.0 |
| Drone2 | 0 | TAKE_OFF | success |  | 0.0 | 7.9 | 16.00 | 0.0 |
| Drone2 | 1 | GO_TO_WAYPOINT | success |  | 7.9 | 12.9 | 16.00 | 90.0 |
| Drone2 | 2 | HOLD_POSITION | success |  | 12.9 | 17.9 | 16.00 | 90.0 |
| Drone2 | 3 | RETURN_HOME | success |  | 17.9 | 21.9 | 16.00 | 90.0 |
| Drone2 | 4 | LAND | success |  | 21.9 | 30.4 | 0.00 | 90.0 |
| Drone3 | 0 | TAKE_OFF | success |  | 0.0 | 8.7 | 20.00 | 0.0 |
| Drone3 | 1 | GO_TO_WAYPOINT | success |  | 8.7 | 13.7 | 20.00 | -90.0 |
| Drone3 | 2 | HOLD_POSITION | success |  | 13.7 | 18.7 | 20.00 | -90.0 |
| Drone3 | 3 | RETURN_HOME | success |  | 18.7 | 22.7 | 20.00 | -90.0 |
| Drone3 | 4 | LAND | success |  | 22.7 | 33.2 | 0.00 | -90.0 |
| Drone4 | 0 | TAKE_OFF | success |  | 0.0 | 9.5 | 24.00 | 0.0 |
| Drone4 | 1 | GO_TO_WAYPOINT | success |  | 9.5 | 14.5 | 24.00 | 90.0 |
| Drone4 | 2 | HOLD_POSITION | success |  | 14.5 | 19.5 | 24.00 | 90.0 |
| Drone4 | 3 | RETURN_HOME | success |  | 19.5 | 23.5 | 24.00 | 90.0 |
| Drone4 | 4 | LAND | success |  | 23.5 | 36.0 | 0.00 | 90.0 |

Closest approach per pair (mock world, exact): Drone1-Drone2 4.0 m, Drone1-Drone3 8.0 m, Drone1-Drone4 12.0 m, Drone2-Drone3 4.0 m, Drone2-Drone4 8.0 m, Drone3-Drone4 4.0 m. Drone-to-drone contacts: 0.

**Exit criterion: MET** — every skill of every drone succeeded and returned a structured result.
