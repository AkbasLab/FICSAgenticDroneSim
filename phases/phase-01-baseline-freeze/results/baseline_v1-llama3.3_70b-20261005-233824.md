# baseline_v1 — llama3.3:70b

Generated 2026-10-05 23:39 by `scripts/run_missions.py`.

| Mission | Category | Valid | Correct | Extra steps | Latency (s) |
|---|---|---|---|---|---|
| M01 | simple movement | 1/1 | 1/1 | 0 | 41.6 |
| M07 | instruction order is not execution order | 1/1 | 1/1 | 0 | 1.2 |
| M08 | ambiguous wording | 1/1 | — | — | 1.6 |

**Scored runs correct: 2/2** · median latency 1.6s · slowest 41.6s (first call of a session loads the model)

Missions marked — are unscoreable by design; see the mission set for why.
