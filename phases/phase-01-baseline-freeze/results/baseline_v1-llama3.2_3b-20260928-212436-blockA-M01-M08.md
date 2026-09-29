# baseline_v1 — llama3.2:3b

Generated 2026-09-28 21:30 by `scripts/run_missions.py`.

| Mission | Category | Valid | Correct | Extra steps | Latency (s) |
|---|---|---|---|---|---|
| M01 | simple movement | 3/3 | 3/3 | 0 | 4.9 |
| M02 | multi-step movement | 3/3 | 3/3 | 0 | 1.5 |
| M03 | altitude change, multi-step | 3/3 | 3/3 | 0 | 2.5 |
| M04 | return and land | 3/3 | 3/3 | 0 | 2.8 |
| M05 | repetition | 3/3 | 3/3 | 0 | 2.1 |
| M06 | repetition | 3/3 | 3/3 | 0 | 2.7 |
| M07 | instruction order is not execution order | 3/3 | 3/3 | 0 | 2.2 |
| M08 | ambiguous wording | 3/3 | — | — | 3.6 |

**Scored runs correct: 21/21** · median latency 2.5s · slowest 12.4s (first call of a session loads the model)

Missions marked — are unscoreable by design; see the mission set for why.
