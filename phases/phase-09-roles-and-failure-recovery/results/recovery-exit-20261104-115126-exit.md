# Recovery exit — search_relay_001, mock

Run 2026-11-04T11:43:38, `scripts/recovery_exit.py`, 467.8 s wall. Four rule agents told only the team mission, every message delivered; each seed flown with no stop and with each drone stopped at 60 s, each stopped flight twice. Health thresholds {'suspected_s': 3.0, 'unreachable_s': 10.0, 'failed_s': 30.0}.

| Seed | detected | no_false_alarm | reassigned | continued | no_new_command | roles_from_interactions | deterministic | known_exactly | Reassigned (stopped → taken by) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 2 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 3 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 4 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 5 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 6 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 7 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 8 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 9 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 10 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 11 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 12 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 13 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 14 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 15 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 16 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 17 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 18 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 19 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |
| 20 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1's S3 → Drone4; Drone2's S4 → Drone4; Drone3's S1 → Drone4; Drone4's S2 → Drone3 |

**Reprioritization, beside the exit** -- Drone1 stopped, the deadline cut to 250 s: as it should. search S3 abandoned in every survivor's book (Drone2 at 69 s, Drone3 at 69 s, Drone4 at 69 s); nobody chased it; the team ended at 188 s with the partial result (S1 1.000, S2 0.999, S3 0.387, S4 1.000).

**9.4, controlled emergence** -- the five conditions:

* a team-level objective: held -- every drone told only the team mission, in every flight
* no central controller: held -- no task given to any drone, by anyone, after the start; the flight code calls only assign_team (tests/test_recovery_exit.py)
* only local beliefs and delivered messages: held -- the boundary checks over agents/ and coordination/; every decision known exactly
* allocation and roles from interactions: held -- every role change traced to the drone's own claim, completion or detector; every claim to its bids
* deterministic constraints: held -- every executed decision passed the validation step

Proxies (AUV-19), reported, not claimed: 4 of 4 drones off the one-drone-per-sector assignment; 1 distinct division(s) over 20 seeds -- these agents are deterministic and the bids depend on geometry, not targets: one division on every seed is expected, and is not emergence measured.

**Exit criterion: MET** — 20 of 20 seeds passed every check.
