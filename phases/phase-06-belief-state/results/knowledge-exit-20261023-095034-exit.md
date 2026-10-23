# Knowledge log — Phase 6 exit, mock

Run 2026-10-23T09:50:22, `scripts/knowledge_exit.py`, 12.3 s wall. Logger: `experiments/knowledge.py`; agents: `agents/drone_agent.py` with `agents/rule_policy.py`.

| Set | Seed | Task met | Decisions | Passed | Known items | Unknown items | Truth-gap items |
|---|---|---|---|---|---|---|---|
| single | 1 | yes | 23 | 23 | 1009 | 102 | 22 |
| single | 2 | yes | 24 | 24 | 1053 | 107 | 20 |
| single | 3 | yes | 23 | 23 | 1013 | 98 | 14 |
| single | 4 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 5 | yes | 23 | 23 | 1006 | 105 | 27 |
| single | 6 | yes | 24 | 24 | 1052 | 108 | 25 |
| single | 7 | yes | 23 | 23 | 1008 | 103 | 21 |
| single | 8 | yes | 24 | 24 | 1056 | 104 | 17 |
| single | 9 | yes | 23 | 23 | 1011 | 100 | 16 |
| single | 10 | yes | 23 | 23 | 1006 | 105 | 25 |
| single | 11 | yes | 24 | 24 | 1050 | 110 | 27 |
| single | 12 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 13 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 14 | yes | 24 | 24 | 1053 | 107 | 22 |
| single | 15 | yes | 24 | 24 | 1052 | 108 | 21 |
| single | 16 | yes | 23 | 23 | 1008 | 103 | 23 |
| single | 17 | yes | 24 | 24 | 1050 | 110 | 28 |
| single | 18 | yes | 24 | 24 | 1050 | 110 | 24 |
| single | 19 | yes | 23 | 23 | 1006 | 105 | 26 |
| single | 20 | yes | 23 | 23 | 1008 | 103 | 25 |
| pair | 1 | yes | 44 | 44 | 1875 | 295 | 107 |
| pair | 2 | yes | 44 | 44 | 1864 | 306 | 104 |
| pair | 3 | yes | 42 | 42 | 1778 | 292 | 95 |
| pair | 4 | yes | 44 | 44 | 1864 | 306 | 107 |
| pair | 5 | yes | 44 | 44 | 1864 | 306 | 113 |
| pair | 6 | yes | 44 | 44 | 1864 | 306 | 110 |
| pair | 7 | yes | 42 | 42 | 1787 | 283 | 103 |
| pair | 8 | yes | 43 | 43 | 1821 | 299 | 99 |
| pair | 9 | yes | 44 | 44 | 1864 | 306 | 101 |
| pair | 10 | yes | 43 | 43 | 1821 | 299 | 109 |
| pair | 11 | yes | 44 | 44 | 1872 | 298 | 111 |
| pair | 12 | yes | 44 | 44 | 1874 | 296 | 107 |
| pair | 13 | yes | 43 | 43 | 1821 | 299 | 105 |
| pair | 14 | yes | 44 | 44 | 1864 | 306 | 107 |
| pair | 15 | yes | 43 | 43 | 1821 | 299 | 104 |
| pair | 16 | yes | 42 | 42 | 1787 | 283 | 105 |
| pair | 17 | yes | 44 | 44 | 1864 | 306 | 113 |
| pair | 18 | yes | 44 | 44 | 1864 | 306 | 109 |
| pair | 19 | yes | 43 | 43 | 1829 | 291 | 108 |
| pair | 20 | yes | 44 | 44 | 1874 | 296 | 110 |

**Exit criterion: MET** — 40 of 40 flights met their tasks; 1340 of 1340 decisions logged complete, correct and without a leak.
