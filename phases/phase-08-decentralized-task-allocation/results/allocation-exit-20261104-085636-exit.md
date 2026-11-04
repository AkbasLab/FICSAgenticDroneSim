# Allocation exit — search_relay_001, mock

Run 2026-11-04T08:53:17, `scripts/allocation_exit.py`, 198.7 s wall. Four rule agents told only the team mission, every message delivered; each seed flown deliberating (bid window 1 s) and contested (no window), each twice. Manifest `configs/allocation/default.toml`: weights {'w_d': 1.0, 'w_b': 1.0, 'w_l': 1.0, 'w_c': 0.0, 'w_r': 1.0}, progress every 2 s, lease 10 s.

| Seed | met | no_central_assignment | one_holder_each | conflicts_resolved | leases_renewed | deterministic | known_exactly | Division (deliberating) | Conflicts (contested) | Completion s |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 2 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 3 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 4 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 5 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 6 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 7 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 8 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 9 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 10 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 11 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 12 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 13 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 14 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 15 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 16 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 17 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 18 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 19 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |
| 20 | yes | yes | yes | yes | yes | yes | yes | Drone1 S3, Drone2 S4, Drone3 S1, Drone4 S2 | S2: 4 claims, Drone4 kept | 188.0 / 188.0 |

Phase 4's scripted controller, with the hand assignment Drone *i* to S*i*, completes in 192.1 s on the mock -- for comparison, not a pass condition.

**The finding beside the exit** -- the scenario's own 100 m radio, one flight: met True; 8 searches of 4 sectors; 20 lease expiries: a drone searching a far sector is out of everyone's reach, its reports go unheard, its lease runs out while it works, and a teammate searches the sector again. Not part of the exit (decided 2026-11-04); Phase 10's subject.

**Exit criterion: MET** — 20 of 20 seeds passed every check.
