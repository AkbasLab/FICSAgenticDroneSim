# Knowledge log — Phase 6 live, search_single_live_small

Run 2026-11-02T19:39:17, `scripts/knowledge_exit.py --sim airsim`, 44.6 s of flight. Told only 'search S1'. Observer polled-10Hz. Logger: `experiments/knowledge.py`; agent: `agents/drone_agent.py` with `agents/rule_policy.py`.

Correct here means within **0.625 m** and **0.0188 %** of battery: one poll of flight: 5 m/s across 0.125 s (8 Hz). The belief is the last poll before a decision and the truth is interpolated between the polls around it, so they stand up to one poll of flight apart however right the logger is. The mock's own allowance, 0.01 m, holds only where both sides come from one trajectory.

The poller was asked for 10 Hz and kept 8 Hz across 351 samples: worst gap 0.125 s, median 0.109 s. The allowance is the WORST gap, since that is what bounds the lag; the median is here so that one stalled poll widening it would show.

| | Live | Mock twin |
|---|---|---|
| Task met | yes | yes |
| Decisions | 10 | 10 |
| Passed all three checks | 10 | 10 |
| Known items | 431 | 431 |
| Unknown items | 46 | 46 |
| Truth-gap items | 9 | 9 |
| Completion s | 37.1 | 30.0 |
| Skills | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success | TAKE_OFF success, FOLLOW_WAYPOINTS success, SEARCH_REGION success, FOLLOW_WAYPOINTS success, LAND success |
| Contacts | Drone1-SM_seaM | - |

**MET** — 10 of 10 decisions logged complete, correct and without a leak.
