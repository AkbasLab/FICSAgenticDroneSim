# Evaluation metrics — definitions, version 1

**Pre-registered 2026-11-06 (Phase 15, AUV-14), before any metric was implemented or computed.**

This file is the definition of every metric the study reports. `agentic_uav/experiments/metrics.py` implements
exactly these, under these ids, and records this file's SHA-256 in every result it writes; it refuses to score if
the registry and this file disagree. **A definition is never edited silently**: a change is a new version of this
file, recorded with its date and reason under "Versions" below, and results carry the version they were computed
with. No metric may be added after results it would describe have been seen (AUV-14: "no metric should be invented
after inspecting the final results").

## Inputs

Every metric is computed from **one run's directory** (Phase 14) alone, or — for paired metrics — from the
directories of one batch:

| File | What the metrics read |
|---|---|
| `manifest.json` | the configuration: architecture, scenario, network, failure, seed, planner |
| `report.json` | the judge (AUV-05): `report.success`, `report.completion_s`, `report.components` (coverage, target_detection, safe_return, collisions, separation_violations, zone_entries), `report.coverage.by_sector`, `report.facts.batteries`, `searched` |
| `events.jsonl.gz` | the 19-type event log (Phase 14) |
| `trajectories.json.gz` | each drone's flown knots (Phase 15) |
| the scenario | `mission.deadline_s`, `mission.required_coverage`, the sectors |

**Missing input.** A metric whose input a run does not have (an older directory, no model in the run) is
reported as `null` with a reason, never as 0. Three kinds of absence are kept apart: **not available** (the input
is missing), **not applicable** (the question does not arise in this run — e.g. recovery with nothing lost), and
**undefined** (a ratio whose denominator is 0).

**Censoring.** A quantity that never happened within the flight (a mission not completed, a task never
recovered) is **censored**: reported with `censored: true` and the time left in the window, never as a short
time. Summaries treat a censored value as at least that long.

## Primary metrics

### P1 — Mission completion

| Id | Definition |
|---|---|
| `P1.success` | `true` if and only if the judge passed every AUV-05 criterion (`report.success`). **The primary outcome.** |
| `P1.coverage` | fraction of the searchable area searched (the judge's `components.coverage`, 0–1) |
| `P1.target_detection` | fraction of targets detected (`components.target_detection`, 0–1) |
| `P1.safe_return` | fraction of the drones still functioning that returned and landed (`components.safe_return`, 0–1) |
| `P1.mission_score` | `(P1.coverage + P1.target_detection + P1.safe_return) / 3` — equal weights, fixed here. Used only for P3; the paper reports success and the components. |

### P2 — Mission completion time

| Id | Definition |
|---|---|
| `P2.completion_s` | if `P1.success`: the judge's `completion_s` (seconds from the flight's start). Otherwise **censored at the deadline**: the value is `mission.deadline_s` and `P2.censored` is `true` — "timeout", never a fast completion. |
| `P2.censored` | `true` when the mission was not completed |

### P3 — Continuity retention

| Id | Definition |
|---|---|
| `P3.continuity_retention` | for a run in a **degraded condition** (network other than `nominal`, or failure other than `none`): `P1.mission_score(run) / P1.mission_score(twin)`, where the twin is the run of the same batch with the same architecture, scenario, team size, seed and planner, network `nominal` and failure `none`. **Undefined** if the twin's score is 0; **not available** if the batch has no twin; **not applicable** to a run that is itself in the nominal condition. A paired metric: computed across the batch. |

### P4 — Recovery time

| Id | Definition |
|---|---|
| `P4.recovery_s` | for a run whose failure profile **stops** a drone: let `t0` be its `FAULT_INJECTED` (stop) time. The drone's **lost tasks** are those it was assigned (`TASK_ASSIGNED` to it) before `t0`, not released by it (`TASK_RELEASED` for it) before `t0`, and not among the tasks it completed (`records.policies[drone].completed`). Recovery time is the first `TASK_ASSIGNED`, after `t0`, of a lost task to **another** drone, minus `t0`. **Not applicable** if nothing was lost (no stop, or the drone had finished its tasks). **Censored** (value: window end − `t0`) if never recovered. With several stopped drones, the longest. Partitions lose no task: their cost is measured by P1–P3 and D3, and P4 is not applicable to them. |
| `P4.censored` | `true` when a lost task was never taken by another drone |

### P5 — Safety

| Id | Definition |
|---|---|
| `P5.collisions` | the judge's `components.collisions` |
| `P5.separation_violations` | the judge's `components.separation_violations` |
| `P5.zone_entries` | the judge's `components.zone_entries` (restricted-zone entries) |
| `P5.emergency_fallbacks` | `GUARDIAN_INTERVENED` events with outcome `execute_safe_fallback` |
| `P5.unsafe_proposals` | `GUARDIAN_INTERVENED` events with outcome `reject_and_replan` or `approve_with_modification`: proposals the guardian would not run as proposed |
| `P5.guardian_interventions` | every `GUARDIAN_INTERVENED` event |

A run with no guardian (an ablation) reports 0 for the guardian's three — there was nothing to intervene — and the
judge's three still count what happened.

### P6 — Communication overhead

| Id | Definition |
|---|---|
| `P6.messages` | `MESSAGE_SENT` events (each message once, whatever its recipients) |
| `P6.bytes` | the sum of their `bytes` |
| `P6.messages_per_completed_task` | `P6.messages / completed tasks`, where completed tasks = distinct sectors in the report's `searched`. **Undefined** if none. |
| `P6.duplicates` | `MESSAGE_SENT` events, heartbeats excluded, whose sender, type, recipients and `payload_digest` equal those of an earlier message from the same sender still within its lifetime (`t − t_earlier < ttl_s` of the earlier): saying the same thing again before the first was stale. **Not available** for an event log without `payload_digest` (Phase 14's). |
| `P6.expired` | `MESSAGE_DROPPED` events with why `expired` |

## Coordination efficiency

| Id | Definition |
|---|---|
| `CE.coordination_efficiency` | unique productive work ÷ total work, for area search (AUV-14). On the judge's own grid (`simulator/coverage.py`, `cell_m` 1 m) and its own rule — a cell is searched when a drone has held it within the detection radius for the minimum observation time — computed for **each drone alone** over the flight's window: total work = Σ over drones of the cells that drone searched; productive work = the cells searched by any drone. 1 means no drone searched what another searched. **Undefined** if no cell was searched; **not available** without trajectories. |
| `CE.total_cells` | the total work, in cells |
| `CE.unique_cells` | the productive work, in cells |

A drone re-searching its own ground is not counted here (each drone's cells are a set); that is D2's.

## Diagnostic metrics

| Id | Definition |
|---|---|
| `D1.area_searched_pct` | `100 × P1.coverage` |
| `D2.redundant_searches` | searches of a sector beyond its first: Σ over sectors of max(0, times it appears in the report's `searched` − 1) |
| `D3.task_reassignments` | assignments of a task beyond its first: Σ over tasks of max(0, its `TASK_ASSIGNED` events − 1) |
| `D4.orphaned_tasks` | sectors whose judged coverage (`report.coverage.by_sector`) is below `mission.required_coverage` at the end |
| `D5.role_changes` | `ROLE_CHANGED` events |
| `D6.role_oscillations` | `ROLE_CHANGED` events that return a drone to the role it left in its previous change, within 30 s of that change |
| `D7.stale_message_decisions` | `DECISION_PROPOSED` events triggered by a message (`message` in triggers) at an instant when the deciding drone received a message (`MESSAGE_RECEIVED`, same drone, same `t`) more than 2.0 s after it was sent (`delay_s > 2.0`; the guardian's command timeout) |
| `D8.invalid_llm_outputs` | `LLM_CALLED` events with a non-empty `problems` list. **Not applicable** where no model decides. |
| `D9.llm_latency_p50_s`, `D9.llm_latency_p95_s` | the 50th and 95th percentile (nearest-rank) of every model call's latency (each entry of `LLM_CALLED.latency_s`). **Not applicable** where no model decides. A replay's latency is its own. |
| `D10.llm_calls` | the number of model calls: Σ of `LLM_CALLED.calls`. **Not applicable** where no model decides. |
| `D11.fallback_use` | `LLM_CALLED` events of kind `fallback`: decisions the model could not make, taken by the rule policy. **Not applicable** where no model decides. |
| `D12.tokens` | prompt + reply tokens over the flight, from the model log's `tokens` where recorded. **Not recorded** until the model client records them (planned with the first live-model batch, Phase 17): reported `null` with that reason, never 0. |
| `D13.battery_used_pct` | Σ over drones of the judge's `facts.batteries[].used` (percentage points of battery) |
| `D14.distance_m` | Σ over drones of the judge's `facts.batteries[].flown_m` |
| `D15.conflicting_claims` | conflicts settled by the protocol's rules: `TASK_RELEASED` events whose why begins `lost: lost to` (a holder displaced by another's claim) |

## Versions

| Version | Date | What |
|---|---|---|
| 1 | 2026-11-06 | First definitions, before any implementation or result (Phase 15) |
