# Phase 14 — Build the experiment runner and complete logging

**Stage:** 6 · Apparatus · **Vault note:** `AUV-14 — Experiment Runner and Metrics`
**Started:** 2026-11-06 · **Completed:** 2026-11-06 (on the mock)

> Research-quality experiments must be automatic. Phase 14 makes a run one
> configuration — architecture, scenario, team size, network, failure, seed,
> planner — and a batch a file of them. One command flies the batch with
> nothing to answer, side by side if asked, and leaves one complete directory
> per run: its manifest, the judge's report, a 19-type event log and the raw
> records. A mission not met is kept like any other; a run that crashes is
> kept with its traceback; a batch interrupted is finished by running it again.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **14.1** Use one experiment configuration — id, architecture, scenario, team size, network profile, failure profile, seed, planner (`configs/experiments/*.toml`, `experiments/experiment.py`)
- [x] **14.2** Record an experiment manifest — git SHA, config files, architecture, scenario, seed, model and parameters, start/finish, versions, completion, errors (`manifest.json`, every run)
- [x] **14.3** Use structured event logs — JSON Lines; 19 event types (`events.jsonl.gz`, `experiments/events.py`)
- [x] **14.4** Preserve failed runs — **do not discard crashed or unsuccessful runs**
- [x] ✅ **Exit:** a batch command executes a list of scenario configurations without manual prompts and produces **one complete result directory per run**

## Exit criterion

> A batch command executes a list of scenario configurations without manual prompts and produces one complete result directory per run.

**Met:** yes, on the mock, 2026-11-06 — `scripts/run_batch.py phase14_exit` as a child process with no input: 43
runs, 43 complete directories, all nine checks passed; the batch flown twice the same, byte for byte, and
resumed after three runs were removed without touching the other forty · **Evidence:**
[`evidence/exit-criterion-2026-11-06.md`](evidence/exit-criterion-2026-11-06.md); the batch itself, every run's
directory, in `results/phase14-exit-20261106-113936/`.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| One configuration; a batch (14.1) | `agentic_uav/experiments/experiment.py`, `configs/experiments/`, `configs/failures/` | **Done**; read strictly |
| One run, one directory, failures kept (14.2, 14.4) | `agentic_uav/experiments/experiment_run.py` | **Done** |
| The event log (14.3) | `agentic_uav/experiments/events.py` | **Done**; 19 types, derived from the records |
| The batch command | `agentic_uav/experiments/batch.py`, `scripts/run_batch.py` | **Done**; `--jobs`, `--resume`, no prompts |
| The exit | `agentic_uav/experiments/batch_exit.py`, `scripts/batch_exit.py`, `configs/experiments/phase14_exit.toml`, `results/`, `evidence/` | **Done**; exit met on the mock |
| Tests | `tests/test_experiment.py` (18), `tests/test_batch.py` (16) | **Done**; 34 mutations, all caught |

## Plan

Approved 2026-11-06 ("Approve, build it all"), shown in full first. Steps: (1) the configuration, failure
profiles, batch expansion; (2) one run, one directory, failures kept; (3) the event log; (4) the batch command;
(5) the exit on the mock; (6) close. The user then asked for the phase to be committed, pushed and tagged at its
end without stopping to ask again. Seven recommendations, all taken:

1. **Events derived from the records, not instrumented into the agents** — every earlier run stays as it was.
2. **Observations and beliefs logged once per decision**, not per tick.
3. **Team size checked against the scenario**, not made by dropping drones (4: `search_relay_001`; 2: `search_pair_001`).
4. **JSON Lines, compressed per run**; no new dependency.
5. **Batch output under `runs/`** (not tracked); the exit's batch committed whole if under about 15 MB (it is 5 MB).
6. **Mock only, no Vega**; the runner supports the pinned model (`llm:default`), the exit uses the echo and Phase 12's replay.
7. **Phase 15's metrics not started**; the logs carry what they will need.

## Record

### 2026-11-06 — steps 1–4: the configuration, the run, the log, the batch

* **The configuration.** A batch file has `[batch]` id and description, and `[[experiment]]` blocks with the
  eight keys AUV-14 lists; any of architecture, scenario, network, failure and seed may be a list (a seed also
  `"a-b"`), and every combination is one run, in a fixed order, named `NNNN-arch-scenario-network-failure-sN`.
  A planner applies only where a model decides (`none`, `echo`, `llm:<configs/llm name>`,
  `replay:<record>`). Refused before anything flies, with the reason: an unknown key, a team size the scenario
  lacks, a partition naming drones it lacks, a stop or injection for a missing drone, an injection with no
  guardian to catch it, E on anything but a perfect network with no failure, a model arm with no planner or a
  rules arm with one, a replay with no such flight.
* **Failure profiles** (`configs/failures/`): `none`; `drone1-at-60s` (Phase 9's stop); `unsafe-proposal`
  (Phase 11's `rule-fence-far`: Drone1's decision at 40 s replaced by one 600 m past the fence). To fly an
  injection through any arm, `fly_architecture` now passes `wrap_policy` / `wrap_handle` through; Phase 13's run
  of record reproduces identically.
* **The run directory.** `report.json`, `events.jsonl.gz`, `records.json.gz`, then `manifest.json` last: the
  configuration, every configuration file with its digest, the code (commit, dirty flag, package digest),
  software versions, the model, start and finish, the status and the outcome — or, for a crash, the error and
  its traceback. Only the manifest carries wall-clock times.
* **The event log.** The 19 types, from the bus's deliveries, the decision traces, the skills started and the
  executor's statuses, the guardians' and models' logs, the base controller's log and the judge's facts. Two
  things found by running it: a skill the agent replaces by starting the next is never "heard" ending, so skill
  ends come from the executor's own status for every skill started; and drones act in threads, so events at one
  instant were listed in whatever order the threads ran — the log is now in a total order and a re-run is
  byte-identical. A message still waiting when its recipient stopped is dropped as `never_read`. D-fallback logs
  no model calls: no model was there to ask. A replay logs its own latency (about zero), not the 70B's.
* **The batch command** checks a model server before the first run, flies runs side by side with `--jobs`,
  finishes an interrupted directory with `--resume` (and refuses to resume a different batch), and exits 0 only
  if every run completed.

### 2026-11-06 — step 5: the exit, met on the mock

The exit batch (`configs/experiments/phase14_exit.toml`, 43 runs) was fixed before any run of it: every arm on
nominal and severe networks with and without the stop; every ablation; E; the 2-drone scenario; a partition; the
unsafe proposal; D replayed from Phase 12's 70B. Trials in the scratchpad found four things, each fixed: a
parameter clash in the event helper (the crashes were kept, with tracebacks — 14.4 working on its first day); E's
skill events missing fields; event order depending on thread timing; a check forgetting A's base controller.

**Run of record** `results/batch-exit-20261106-114052-exit` at `4369491` (clean), 77 s: the batch command twice and
a resume; **all nine checks passed**. 43 runs, 43 completed, 40 met the mission; the three not met — B and
D-no-leases with Drone1 stopped — kept like the rest.

**Verification.** The full suite passes: **1,314 tests, 29 skipped**, on the final code. Phase 13's
run of record reproduced identically. Mutations: 34 on the new code, all caught — 26 at first; the eight gaps
(a skill's status, a target's report time, the not-met flag, `never_read`, the index's order when runs finish out
of it, the partition and guardian checks, the time-order check alone) each have a test now.

**Beside the checks** (not experiments): on the severe network the seed now changes the flight — C with Drone1
stopped completes in 395–547 s over seeds 1–5, where on a perfect network every seed flew the same (Phase 13).

### 2026-11-06 — close

**Phase 14 is complete on the mock.** All four objectives and the exit criterion are met. 1,314 tests pass,
29 skipped; the goldens unedited; Phase 13's run of record reproduced. No Vega was needed.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-06 | **Events derived from the records, not written by the agents** | No agent behaviour changes; old flights' logs can be rebuilt |
| 2026-11-06 | **Skill ends from the executor's status for every skill started** | A skill replaced by the next is never heard ending; the decision trace alone missed half |
| 2026-11-06 | **A total order on events** | Threads list same-instant events in any order; a re-run must be byte-identical |
| 2026-11-06 | **The manifest written last** | A directory without one is unfinished, and `--resume` flies it again |
| 2026-11-06 | **A planner applies only where a model decides** | One block can hold A, C and D; the rules arms record `none` |
| 2026-11-06 | **An injection needs the guardian** | Without it the unsafe command flies 600 m out: an experiment to choose deliberately, not by accident |
| 2026-11-06 | **Commit, push and tag at the end without asking again** | The user's instruction, given during step 5 |

## Open questions

1. **Live CarlaAir runs through the runner** — the AirSim confirmation subset of Phase 18 — wait for Phase 16–17.
2. **The model's own latency in a replay** is not carried over: a replay logs its own. Real-clock latency is
   AUV-12F's experiment, kept apart from the phases.
3. **Phase 15's metrics** come next, defined and tested before any experiment's results are seen.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
