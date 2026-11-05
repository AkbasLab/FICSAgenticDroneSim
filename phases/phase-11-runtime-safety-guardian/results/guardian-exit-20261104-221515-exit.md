# Guardian exit — search_relay_001, mock

Run 2026-11-04T21:47:37, `scripts/guardian_exit.py`, 1658.4 s wall. Four rule agents told only the team mission, on Phase 9's network; each seed flown without a guardian, guarded and clean, guarded through the LLM channel, and once per injection (33): 36 flights a seed, 720 in all.

| Seed | clean_is_phase_9 | channel_transparent | no_interventions | injections_stopped | limits_kept |
|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes |
| 2 | yes | yes | yes | yes | yes |
| 3 | yes | yes | yes | yes | yes |
| 4 | yes | yes | yes | yes | yes |
| 5 | yes | yes | yes | yes | yes |
| 6 | yes | yes | yes | yes | yes |
| 7 | yes | yes | yes | yes | yes |
| 8 | yes | yes | yes | yes | yes |
| 9 | yes | yes | yes | yes | yes |
| 10 | yes | yes | yes | yes | yes |
| 11 | yes | yes | yes | yes | yes |
| 12 | yes | yes | yes | yes | yes |
| 13 | yes | yes | yes | yes | yes |
| 14 | yes | yes | yes | yes | yes |
| 15 | yes | yes | yes | yes | yes |
| 16 | yes | yes | yes | yes | yes |
| 17 | yes | yes | yes | yes | yes |
| 18 | yes | yes | yes | yes | yes |
| 19 | yes | yes | yes | yes | yes |
| 20 | yes | yes | yes | yes | yes |

**Each injection, over the seeds** (outcome and check as expected is part of the exit; the mission's cost is a finding):

| Injection | Channel | Expected | Made | As expected | Fallback | Mission met | Delay s (min, median, max) | Knock-on |
|---|---|---|---|---|---|---|---|---|
| rule-altitude-high | rule | approve_with_modification (altitude) | 20/20 | 20/20 | - | 20/20 | [10.0, 10.0, 10.0] | 0 |
| rule-altitude-low | rule | approve_with_modification (altitude) | 20/20 | 20/20 | - | 20/20 | [-1.5, -1.5, -1.5] | 0 |
| rule-speed | rule | approve_with_modification (speed) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 0 |
| rule-fence-near | rule | approve_with_modification (geofence) | 20/20 | 20/20 | - | 20/20 | [15.0, 15.0, 15.0] | 0 |
| rule-fence-far | rule | reject_and_replan (geofence) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| rule-zone | rule | reject_and_replan (restricted_zone) | 20/20 | 20/20 | - | 20/20 | [98.1, 98.1, 98.1] | 0 |
| rule-waypoint | rule | reject_and_replan (waypoint) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| rule-battery | rule | reject_and_replan (battery) | 20/20 | 20/20 | - | 20/20 | [100.0, 100.0, 100.0] | 0 |
| rule-timeout | rule | reject_and_replan (timeout) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 20 (landing_site 20) |
| rule-separation | rule | reject_and_replan (separation) | 20/20 | 20/20 | - | 20/20 | [98.1, 98.1, 98.1] | 0 |
| rule-landing | rule | reject_and_replan (landing_site) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| rule-finish | rule | reject_and_replan (finish_airborne) | 20/20 | 20/20 | - | 20/20 | [100.0, 100.0, 100.0] | 0 |
| rule-conflict | rule | reject_and_replan (conflict) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 0 |
| rule-bypass | rule | reject_and_replan (restricted_zone) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 0 |
| rule-fallback | rule | execute_safe_fallback (restricted_zone) | 20/20 | 20/20 | CONTINUE_LAST_VALID_PLAN 20 | 20/20 | [0.0, 0.0, 0.0] | 0 |
| llm-malformed | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-unknown-skill | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [98.1, 98.1, 98.1] | 0 |
| llm-nan | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-word | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [100.0, 100.0, 100.0] | 0 |
| llm-extra-key | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-out-of-range | llm | reject_and_replan (proposal) | 20/20 | 20/20 | - | 20/20 | [98.1, 98.1, 98.1] | 0 |
| llm-speed | llm | approve_with_modification (speed) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 0 |
| llm-altitude | llm | approve_with_modification (altitude) | 20/20 | 20/20 | - | 20/20 | [0.0, 0.0, 0.0] | 0 |
| llm-fence-near | llm | approve_with_modification (geofence) | 20/20 | 20/20 | - | 20/20 | [15.0, 15.0, 15.0] | 0 |
| llm-fence-far | llm | reject_and_replan (geofence) | 20/20 | 20/20 | - | 20/20 | [98.1, 98.1, 98.1] | 0 |
| llm-zone | llm | reject_and_replan (restricted_zone) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-landing | llm | reject_and_replan (landing_site) | 20/20 | 20/20 | - | 20/20 | [100.0, 100.0, 100.0] | 0 |
| llm-two-commands | llm | reject_and_replan (conflict) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-stale | llm | reject_and_replan (timeout) | 20/20 | 20/20 | - | 20/20 | [-1.0, -1.0, -1.0] | 0 |
| llm-separation | llm | reject_and_replan (separation) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-battery | llm | reject_and_replan (battery) | 20/20 | 20/20 | - | 20/20 | [100.0, 100.0, 100.0] | 0 |
| llm-finish | llm | reject_and_replan (finish_airborne) | 20/20 | 20/20 | - | 20/20 | [115.0, 115.0, 115.0] | 0 |
| llm-fallback | llm | execute_safe_fallback (proposal) | 20/20 | 20/20 | CONTINUE_LAST_VALID_PLAN 20 | 20/20 | [0.0, 0.0, 0.0] | 0 |

Clean flights: 2275 commands approved as they stood over the seeds, none modified, refused or replaced.

**Exit criterion: MET** — 20 of 20 seeds passed every check.
