# Phase 15 — Define the evaluation metrics before running the main experiments

**Stage:** 6 · Apparatus · **Vault note:** `AUV-14 — Experiment Runner and Metrics`
**Started:** 2026-11-06 · **Completed:** 2026-11-06 (on the mock)

> Research-quality experiments need every metric defined before any result is
> seen. Phase 15 wrote the definitions first — `docs/METRICS.md`, committed on
> its own before a line of metric code — and then implemented exactly those:
> six primary metrics, coordination efficiency and fifteen diagnostics, each
> computed from a run's directory alone, each absent with its reason rather
> than 0, every result stamped with the definitions' SHA-256.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **P1** Mission completion — coverage, target detection, safe return (`P1.success` primary; components; `P1.mission_score`)
- [x] **P2** Mission completion time — **timeout** for failed missions, not a fast completion (censored at the deadline)
- [x] **P3** Continuity retention — degraded score ÷ nominal score (paired with the nominal twin; undefined, not 0, on a zero twin)
- [x] **P4** Recovery time — replacement task accepted − failure (stops; censored if never; partitions lose no task)
- [x] **P5** Safety — collisions, separation violations, restricted-zone entries, emergency fallbacks, unsafe proposals, guardian interventions
- [x] **P6** Communication overhead — messages, bytes, messages per completed task, duplicates, expired
- [x] Diagnostic metrics — all 15 (D1–D15)
- [x] Coordination efficiency — unique productive work ÷ total work (per drone, on the judge's grid)
- [x] ✅ **Exit:** every primary metric has a **written definition and a tested implementation**; **no metric invented after inspecting results**

## Exit criterion

> Every primary metric has a written definition and a tested implementation. No metric should be invented after inspecting the final results.

**Met:** yes, on the mock, 2026-11-06 — the definitions committed first (`63cf653`, 12:04), the implementation
after (`50c5efd`); all eight checks passed on a 43-run batch flown twice and scored twice, and Phase 14's
committed batch scored as it is · **Evidence:**
[`evidence/exit-criterion-2026-11-06.md`](evidence/exit-criterion-2026-11-06.md); the scored batch, every run's
`metrics.json`, in `results/phase14-exit-20261106-123202/`.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The definitions, pre-registered | `docs/METRICS.md` (version 1, sha256 `d722ba2b3379…`) | **Done**; committed before any code |
| The implementation | `agentic_uav/experiments/metrics.py` | **Done**; the registry is the document's ids |
| The scoring command | `scripts/compute_metrics.py` | **Done** |
| What the run directory needed | `trajectories.json.gz`; the event log version 2 (`payload_digest`, sizes as numbers) | **Done** |
| The exit | `agentic_uav/experiments/metrics_exit.py`, `scripts/metrics_exit.py`, `results/`, `evidence/` | **Done**; exit met on the mock |
| Tests | `tests/test_metrics.py` (27); `tests/test_experiment.py` (20) updated | **Done**; 26 mutations, all caught |

## Plan

Approved 2026-11-06 ("Approve, build it all"), shown in full first. Steps: (1) pre-register the definitions;
(2) trajectories in each run directory; (3) the implementation and scoring command; (4) exact tests; (5) the exit
on the mock; (6) close, committing, pushing and tagging without asking again. Nine recommendations, all taken:
pre-registration with the document's digest in every result; strict binary success primary, the mission score
only for P3; censoring; P3 paired with its nominal twin and undefined rather than 0; coordination efficiency
across drones on the judge's grid; tokens defined but not recorded until a live model runs; scoring from run
directories only; laptop only; push and tag at the end.

## Record

### 2026-11-06 — step 1: the definitions, first

`docs/METRICS.md` (version 1): every metric's id, definition, source fields, edges and summary rule; three kinds
of absence (not available, not applicable, undefined) and "not recorded"; censoring. Two refinements were made
while writing it, before any code or number: **P4 covers stops** — a partition loses no task, and its cost is in
P1–P3 and D3 — and **P6 duplicates need a digest of each message's payload**, so the event log would gain one.
Committed alone as `63cf653` at 12:04:53.

### 2026-11-06 — steps 2–4: the inputs, the implementation, the tests

* **The run directory** gains `trajectories.json.gz` (each drone's knots: what coordination efficiency is
  measured from). **The event log becomes version 2**: `MESSAGE_SENT` carries `payload_digest` — and its size as a
  number. Scoring Phase 14's batch found that **version 1 wrote the method's name where the byte count belonged**
  (`m.size_bytes` instead of `m.size_bytes()`), in every run including Phase 14's pushed record; Phase 14's
  checks never looked at the field's type. Fixed; Phase 14's well-formed check now requires a positive whole
  number; a version-1 log's bytes score as "not available". Reports and records are unchanged: Phase 14's
  committed batch reproduces byte for byte in both, and its events are the same as a set (the order of
  same-instant events, which sorts on content, moved with the two new fields).
* **`experiments/metrics.py`**: 40 ids, exactly the document's (`check_registry`; scoring is refused if they
  differ). Coordination efficiency applies the judge's own coverage rule to each drone alone; the union of
  their cells is exactly the judge's coverage on every run, checked.
* **Tests**: each metric on a run built by hand against an answer worked out by hand, with its edges; the
  registry against the document; the exit's checks each able to fail. Mutations: 26 — 21 at first; the five gaps
  (a duplicate exactly a lifetime later, the longer of two recoveries, a model arm with no planner, the payload
  digest being of the payload, the exit's "tested" check) each have a test now. **1,340 tests pass**, 29 skipped.

### 2026-11-06 — step 5: the exit, met on the mock

**Run of record** `results/metrics-exit-20261106-123325-exit` at `50c5efd` (clean), 83 s: the batch
`phase14_exit` flown twice by `scripts/run_batch.py` and scored by `scripts/compute_metrics.py`, child processes
with no input; Phase 14's committed batch scored as it is. **All eight checks passed**: defined, tested,
pre-registered (from git), computed everywhere, in range, agrees with the judge, deterministic, old logs.

**Beside the checks** — what the metrics show on this batch (not an experiment; these are the exit's runs):

* A's base re-sends awards it has already made: 84–108 duplicate messages a flight, against 0–3 for C and D.
* On the severe network coordination efficiency falls from 0.74 to 0.41–0.62: drones search ground others have.
* Recovery after Drone1's stop: 57.5–59.6 s for A, C and D on the nominal network; on the severe network (seed 2)
  12.1 s without roles, against 96.7 s with them; B never (censored).

### 2026-11-06 — close

**Phase 15 is complete on the mock.** Every primary metric has a written definition and a tested
implementation, and the definitions came first. No Vega was needed.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-06 | **The definitions committed alone, first; every result carries their SHA-256** | AUV-14: no metric invented after the results; a definition can be traced from any number |
| 2026-11-06 | **P4 covers stops; partitions lose no task** | Settled while writing the definitions, before any number |
| 2026-11-06 | **The event log, version 2** | Duplicates need a payload digest; and version 1's sizes were not numbers |
| 2026-11-06 | **Absent, never 0** | A missing input, an inapplicable question and a zero denominator are different things from zero |
| 2026-11-06 | **P4's censored value is the window's end, as registered** | The definition says "window end − t0"; for a team that finishes the rest early the window ends with the record, not the deadline. Kept as registered, noted here |

## Open questions

1. **Tokens** (D12) are defined but not recorded: the model client should record them with the first live-model
   batch (Phase 17).
2. **P4 for partitions**, if Phase 17's pilots show a team losing tasks to one, would be a version 2 of the
   definitions — dated, with its reason.
3. **Phase 16**: testing and verification.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
