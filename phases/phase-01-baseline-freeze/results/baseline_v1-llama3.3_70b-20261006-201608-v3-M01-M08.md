# baseline_v1 — llama3.3:70b

Generated 2026-10-06 20:27 by `scripts/run_missions.py`.

| Mission | Category | Valid | Correct | Extra steps | Latency (s) |
|---|---|---|---|---|---|
| M01 | simple movement | 3/3 | 3/3 | 0 | 0.7 |
| M02 | multi-step movement | 3/3 | 3/3 | 0 | 1.0 |
| M03 | altitude change, multi-step | 3/3 | 3/3 | 0 | 1.5 |
| M04 | return and land | 3/3 | 3/3 | 0 | 1.8 |
| M05 | repetition | 3/3 | 3/3 | 0 | 1.3 |
| M06 | repetition | 3/3 | 3/3 | 0 | 1.5 |
| M07 | instruction order is not execution order | 3/3 | 3/3 | 0 | 1.2 |
| M08 | ambiguous wording | 3/3 | — | — | 1.7 |

**Scored runs correct: 21/21** · median latency 1.4s · slowest 1.9s (first call of a session loads the model)

Missions marked — are unscoreable by design; see the mission set for why.
