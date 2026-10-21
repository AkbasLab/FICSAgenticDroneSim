# baseline_v1 — llama3.3:70b

Generated 2026-10-20 19:23 by `scripts/run_missions.py`.

| Mission | Category | Valid | Correct | Extra steps | Latency (s) |
|---|---|---|---|---|---|
| M01 | simple movement | 3/3 | 3/3 | 0 | 12.3 |
| M02 | multi-step movement | 3/3 | 3/3 | 0 | 0.9 |
| M03 | altitude change, multi-step | 3/3 | 3/3 | 0 | 1.5 |
| M04 | return and land | 3/3 | 3/3 | 0 | 1.9 |
| M05 | repetition | 3/3 | 3/3 | 0 | 1.3 |
| M06 | repetition | 3/3 | 3/3 | 0 | 1.6 |
| M07 | instruction order is not execution order | 3/3 | 3/3 | 0 | 1.2 |
| M08 | ambiguous wording | 3/3 | — | — | 1.7 |
| M09 | two-drone simultaneous | 3/3 | 3/3 | 0 | 4.2 |
| M10 | four-drone simultaneous | 3/3 | 3/3 | 0 | 6.1 |

**Scored runs correct: 27/27** · median latency 1.6s · slowest 35.3s (first call of a session loads the model)

Missions marked — are unscoreable by design; see the mission set for why.
