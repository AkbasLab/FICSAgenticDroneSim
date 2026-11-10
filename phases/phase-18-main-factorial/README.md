# Phase 18 — The main factorial

**Stage:** 7 · Science · **Vault note:** `AUV-16 — Pilots, Experiment and Analysis`
**Started:** 2026-11-09 · **Completed:** 2026-11-10

> The main experiment, flown on held-out seeds and frozen code, by rules declared before any of it flew. Four
> architectures — A central, B independent, C decentralized rules, D agentic (the pinned 70B) — in every
> communication level the calibration found meaningful, with and without a drone stopped: **48 cells × 20 seeds =
> 960 runs**. A, B and C on the laptop; D's 240 on Vega. Every cell has its 20 valid paired seeds; no run was
> excluded. No results are read here: comparing the architectures is Phase 19's.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] Decide and **record** which cells run on the mock and which in AirSim — **all on the mock** (960 runs; the live gap is Phase 16's regression set); A, B, C on the laptop, D against the 70B on a Vega GPU node
- [x] **18.1** Common random numbers — the same scenario, network and failure files for a seed in every architecture (targets, start, restricted zones, planned faults), every message's fate one seeded function of (sender, recipient, message number); **checked run by run** (`scripts/factorial_checks.py`)
- [x] **18.2** Held-out test seeds — the 20 of `configs/seeds/heldout.toml`, derived from the freeze and flown for the first time here; nothing tuned after (the freeze, versions 3–6, changed only the checker and its rules' record)
- [x] **18.3** The local model as primary — `llama3.3:70b` `a6eb4748fd29`, Ollama 0.40.6, temperature 0, one request at a time; a Gemini comparison not run
- [x] **18.4** Save every decision — model input, replies, validation, action, fallback, and every guardian verdict, checked for every D decision
- [x] ✅ **Exit:** every final cell has sufficient valid replications, and exclusions rest on predeclared technical criteria — *met 2026-11-10*

## Exit criterion

> Every final cell has sufficient valid replications, and exclusions rest on predeclared technical criteria rather
> than unfavourable outcomes.

**Met:** yes, 2026-11-10. All 12 cells × 4 architectures have **20 valid paired seeds**; **0 runs excluded**; the
criteria (`docs/EXCLUSIONS.md`, committed and pushed before any held-out run) never look at an outcome. All eight
checks of `scripts/factorial_exit.py` pass on the 960 runs of record. · **Evidence:**
[`results/factorial-exit-20261110-104348.md`](results/factorial-exit-20261110-104348.md),
[`evidence/exit-criterion-2026-11-10.md`](evidence/exit-criterion-2026-11-10.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Exclusion, replacement and completeness rules | `docs/EXCLUSIONS.md` (v1 before any run; v2 how an interruption is recorded) | **Done** |
| The four batch files | `configs/experiments/phase18_abc.toml`, `phase18_d_pair.toml`, `phase18_d_four_a.toml`, `phase18_d_four_b.toml` | **Done**; 960 runs |
| The exit check | `scripts/factorial_checks.py` (outside the package), `scripts/factorial_exit.py`, `tests/test_factorial_exit.py` | **Done**; 20 tests, 12 planted defects caught |
| A non-interactive Vega job | `docs/vega/phase18_d.pbs` | **Done**; flew four-b and pair's resume |
| The runs of record | `results/phase18-abc-…`, `phase18-d-pair-…`, `phase18-d-four-a-…`, `phase18-d-four-b-…` (each run's directory, metrics, server logs, variability, job printouts) | **Done** |
| The freeze | `configs/frozen.toml` v3–v6 | **Done** |

## Plan

Approved 2026-11-09 ("Approve, build it all"), shown in full first, after the user chose the **full design, 960 runs**
(team size 8 out: nothing for it is frozen; ablations out). Steps: pre-register the exclusions; the batch files; the
exit check; freeze; a dry run on development seeds; commit and push; A, B, C on the laptop; D on Vega (the user running
every Vega step); the exit check, the record, push and tag.

## Record

### 2026-11-09 — pre-registration, and what the dry run found

`docs/EXCLUSIONS.md` v1 (`1f296e7`): a run is set aside only if it crashed (X1), the model did not answer — a timeout
or the server gone, not an unusable answer (X2), the model ran off the GPU (X3), the code was not the frozen code
(X4), or the model was not the pinned one (X5); never for its outcome. An excluded seed is set aside for all four
architectures and the next reserve flown by all four. Writing it found that Phase 17's first pilot (run 0022) had lost
its first decision to a 60 s timeout while the model loaded — so every D batch now starts with a **warm-up request**.

The four batch files flown on development seeds 1–2 (D by the echo) found two faults **in the checker**, both fixed
before any held-out run: a partition fault could not be compared, and A's controller stops Drone1 at 60.1 s for 60 s
(its own clock's next step) — faults are compared as planned, their taking hold held to within 1 s.

### 2026-11-09 — A, B and C, and a flaw in where the checker lived

A, B, C on the held-out seeds (720 runs, 6 min) and checked alone before any Vega time: in some (4 drones, severe)
seeds **A's Drone1 had landed at 19 s**, so the stop planned at 60 s took hold of nothing — the plan is the common random
number (the failure file's digest), and this is recorded for Phase 19 as a finding, not an exclusion. It also exposed
a flaw: the checker lived in `agentic_uav/`, whose digest every run is held to (X4), so a fix to the checker set aside
every run already flown. It moved to `scripts/factorial_checks.py`, frozen by name (`95b71bd`, freeze v5), and A, B, C
were flown again on that commit (the first 720 kept, superseded, outside the record). **All 960 runs of record are
at `95b71bd`, clean.** `95b71bd` was pushed before any D run.

### 2026-11-09/10 — D on Vega

| Batch | Runs | Job(s), GPU | Flown | Variability |
|---|---|---|---|---|
| `phase18-d-pair` | 80 | 78901 (interactive), then 78961 (`phase18_d.pbs`, resume) | 12:39–14:39, 19:05–19:29 | 99 / 100 |
| `phase18-d-four-a` | 80 | 78907 (interactive), gpu01 `82:00.0` | 12:47–18:44 | 98 / 100 |
| `phase18-d-four-b` | 80 | 78956 (`phase18_d.pbs`), gpu01 `02:00.0` | 14:53–02:44 | 99 / 100 |

Each server on its own GPU and port, its CUDA line checked and the model warmed before the first decision. Vega
allows **2 running jobs a user, across all queues** (support, 2026-11-09), so four-b was queued; on support's advice it
went in as a **non-interactive job** (`docs/vega/phase18_d.pbs`), which checks the commit, requires CUDA, warms up,
flies, runs the variability check and keeps its server log by itself.

**Pair's interruption.** At 14:39–14:40 a Ctrl+C meant for a waiting `qsub` reached pair's batch window: its parent
process stopped at 68 of 80; its two orphaned workers kept flying the runs they held until job 78901 ended at 14:48.
None of those runs finished; all twelve were flown again from the start by `run_batch --resume` (job 78961). Its server
log therefore holds 240 requests and 3 failed (HTTP 500, all at 14:48:45, the job's end) that no record holds —
investigated, declared in `interruptions.json`, and **verified** by the check (`docs/EXCLUSIONS.md` v2, freeze v6). No
run was excluded or changed.

**Variability.** 100 / 100 in both Phase 17 batches; here 99, 98, 99. Four of the five differences across Phase 18
are one question — Drone3 at 13.0 s in a 4-drone flight with no failure, before anything degrades, asked identically
in every such run: `start_search` that night, `accept_task` asked again. Above the 95 % line: not flagged, recorded
for Phase 19 and for AUV-12F.

### 2026-11-10 — the exit and the close

The 960 runs of record copied into `results/` (server logs gzipped), metrics computed (`metrics.jsonl` per batch;
timelines not committed: they are rebuilt from the runs), and the exit check run on them: **MET**.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-09 | **Full design, 960 runs** (the user) | All four architectures, both sizes, every frozen level; size 8 has nothing frozen |
| 2026-11-09 | **Exclusions only by technical criteria, pre-registered; replacements paired** | AUV-22's exit; a comparison by seed stays a comparison by seed |
| 2026-11-09 | **A warm-up request before every D batch** | Phase 17's run 0022 lost its first decision to a cold start |
| 2026-11-09 | **The checker outside the package** | A checker fix must never set aside a run |
| 2026-11-09 | **Faults compared as planned** | A planned stop can find nothing to stop; the plan is the common random number |
| 2026-11-09 | **Non-interactive jobs on Vega** (support's advice; the user: "sure let's do it") | Nobody needs to be at the keyboard when a job starts |
| 2026-11-09 | **Pair resumed, not re-flown** | Its 68 finished runs are valid; resuming fit the job that held the GPU |
| 2026-11-10 | **Record pair's interruption so the check verifies it** (the user: "Yes, at the close") | A mismatch is investigated and reported, never waved through |

## Open questions (for Phase 19 and after)

1. **What the 960 runs say** — Phase 19, by the pre-registered metrics (`docs/METRICS.md`) and the decision traces.
2. **A's Drone1 down before its stop** in some severe-link seeds: a failure cell where the failure found nothing to do.
3. **The one question the 70B answers two ways** at temperature 0 (98–99 % variability here, 100 % in Phase 17).
4. **Latency** — AUV-12F: the mock pauses its clock during a model call; a real-clock run is its own work.
5. **Tooling** — AUV-25: one multi-GPU job, a campaign runner, a `vega` command, then a dashboard (after this phase).

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
