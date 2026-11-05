# Phase 18: the main factorial experiment

```powershell
# 1. check the pipeline end to end (development split, scripted planner, ~10 s)
python scripts/run_factorial.py configs/experiments/factorial_dev.yaml

# 2. see what the real run will cost
python scripts/run_factorial.py configs/experiments/factorial_main.yaml --dry-run

# 3. the experiment (held-out split, llama3.1:8b) - resumable, stop and restart freely
ollama pull llama3.1:8b
python scripts/run_factorial.py configs/experiments/factorial_main.yaml
python scripts/run_factorial.py configs/experiments/factorial_main.yaml --stage 2   # 8 drones, later

# 4. the secondary comparison (needs a paid Gemini key)
python scripts/run_factorial.py configs/experiments/factorial_gemini.yaml
```

Results go to `results/<design_id>/`:

| file | contents |
|---|---|
| `report.md` | summary of the run |
| `runs.csv` | every run, with its validity verdict |
| `cells.csv` | valid replications per cell, against the requirement |
| `exclusions.csv` | every excluded run, with the criterion that excluded it |
| `by_network.csv`, `by_failure.csv` | the two key comparisons |

Every run directory holds the full Phase 14/17 record, including `llm/`.

## The design

| factor | levels |
|---|---|
| architecture | A centralized, B independent, C deterministic decentralized, D agentic decentralized |
| team size | 2, 4 (stage 1); 8 (stage 2, after the smaller cases are stable) |
| network | `final_nominal`, `final_moderate`, `final_severe` (calibrated in Phase 17), `final_partitioned` |
| failure | none, one vehicle failure during the mission |
| seeds | the first 20 held-out seeds, common to every cell |

**Size:**

- Stage 1: 64 cells × 20 = **1,280 runs**.
- With stage 2: 96 cells × 20 = **1,920 runs**.

**Cost** (`--dry-run` on the pilot machine): runs without a model take a
fraction of a second. The cost is the 320 agentic runs in stage 1, about 7,200
model calls at ~6 s, so **about 12 hours**. All three stages together take
about 28 hours.

The development run measured about 10 calls per 2-drone D run and 22 per
4-drone D run. A few runs needed far more (107 at most), because an idle D drone
consults the model on every waiting round.

`final_partitioned` was not part of the Phase 17 ladder. It splits whichever
team is flying into two halves for 30–150 s, over the loss-free final link, so
the partition is the only degradation:

- The window outlasts the presumed-lost threshold (4 × 8 s heartbeat).
- It ends before a typical mission does.
- The centralized controller sits on the base side of the split. Without that,
  the partition would never touch a drone-to-controller link and would have no
  effect on A at all. The development run found this and it is fixed.

## 18.1 Common random numbers

For any seed, every architecture, network condition and team size gets the same:

- **target locations**: two targets, each inside a sector
  (`simulator/scenario_family.py`)
- **restricted region**: a 12 m square 60 m from base, on a random side, never
  over a sector or the base
- **initial vehicle conditions**: each drone's battery (900 s ± 10%) and its
  start pad
- **fault**: which vehicle fails, and when (10–90 s); used only in the failure
  condition
- **message-loss sequence**: with `crn: true`, every directed link has its own
  random stream seeded from (seed, sender, recipient). Every message makes
  exactly three draws, so the *k*-th message on Drone1→Drone3 meets the same
  luck under every architecture, whatever else is on the air. The shared stream
  used before Phase 18 does not do this; a test shows the difference. Default
  behaviour is unchanged, so earlier results stay reproducible.

The draws are made in a fixed order and always for an 8-drone team. That way 2-,
4- and 8-drone runs on one seed share the targets, the zone and the batteries of
the drones they have in common.

**A failure now costs the work it interrupts.** Simulated time jumps one whole
skill per step, so before this phase a drone killed 20 s into a 70 s sweep
finished the sweep and only then stopped. With one sector per drone, a failure
therefore never cost any work. With `fault_interrupts_skill`, the step that
crosses the fault time is undone from the fault onwards:

- The sweep is not credited.
- Nothing the drone sensed after the fault is kept.
- Nothing it queued at the end of the step is sent.
- Its track stops at the fault time.

## 18.2 Development, validation and test

| split | seeds | used for |
|---|---|---|
| development | every seed not in the other two (1, 2, 3, …) | implementation, prompt work, `factorial_dev.yaml` |
| validation | the Phase 17 pilot and calibration seeds | pilot calibration (already done) |
| test | the 100 held-out seeds in `configs/frozen/heldout_seeds.yaml` | final results only |

**Enforcement:**

- `scenario_family.generate()` refuses a seed outside the split it is asked for.
- A design on the `test` split runs only with an unchanged freeze.
- **The first test run seals the configuration** into
  `configs/frozen/test_seal.json`: the fingerprint of the prompts, rules,
  metrics, profiles, scenarios and the exclusion criteria.
- After that, a test run under any other fingerprint is refused, naming what
  changed. The prompt cannot be tuned after the held-out results have been
  seen; tuning means a new design on the development split.

## 18.3 The model

The principal agent model is **llama3.1:8b through Ollama**, at temperature 0.
Each run's manifest records the exact build (digest, quantisation).

Gemini (`gemini-3.5-flash`) is a secondary comparison in `factorial_gemini.yaml`:

- **Scope:** agentic architecture only, 4 drones, nominal and severe, with the failure.
- **Seeds:** the same seeds as the main design, so its cells line up with
  `main_v1`'s D cells seed for seed.
- **Cost:** about 25 calls per run. The free tier's 20 requests a day cannot
  run it; it needs a paid key.

## 18.4 Every decision is saved

`llm/<drone>.json` in every agentic run holds, per decision:

- the **input**: system prompt and the full context;
- the **structured output**: raw reply and parsed decision;
- every **attempt**: the correction prompt and its reply are saved too, which
  they were not before this phase;
- the **validation result** of each attempt;
- the **selected tool and the objective it became**;
- any **fallback**, with its cause;
- the **model card**.

The guardian's verdict on the resulting command is in the guardian log and the
event stream. The log audit checks the transcript: a decision missing its
input, reply, parse or validation makes the run's logs incomplete (X2).

## Exit criterion: exclusions and sufficient replications

`configs/experiments/exclusion_criteria.yaml` was written before any held-out
run, is part of the freeze, and is sealed with it. **Exclusions are technical
only:**

| id | excluded when |
|---|---|
| X1 infrastructure error | the run stopped because of the machine: model server unreachable, memory/disk, operator interrupt |
| X2 incomplete logs | a finished run fails the log audit, or a model decision is not fully saved |
| X3 configuration mismatch | the freeze fingerprint, seed, architecture or team differ from what the run claims |
| X4 model unreachable | more than 20% of model calls never reached the model (connection refused/reset) |

**Never grounds for exclusion:**

- poor coverage, duplicates, long missions, or hitting the step cap
- drones not returning home
- guardian interventions or safety violations
- invalid model output, timeouts or fallbacks
- an exception in the system under test (kept as a failed mission)

`classify()` never reads an outcome value. A test makes the outcomes absurd
and confirms the verdict does not change. The defect-injection catalogue
includes "exclude a run for low coverage", and the suite catches it.

An excluded run is retried with the **same seed**, so the common random numbers
across architectures hold, up to 3 attempts. Each excluded attempt is kept
under `_excluded_attempts/` as evidence.

A cell needs **18 of its 20** replications valid. `cells.csv` reports every
cell against that, and the runner exits non-zero if any cell falls short.

## What the development run already shows

These come from 192 runs with the scripted planner, so they are not results.
They are things to know before the real run:

- **B at 2 drones always misses half the mission.** It starts with one sector
  per drone and never renegotiates. The 2-drone B cells are failures by
  construction, which is correct for B.
- **A struggles under loss and partition.** Moderate loss: 619 ± 454 s.
  Partition: 992 s and 42% success; drones cut off from the controller wait for
  orders. This may be a real property of centralization, or it may need a look
  at how A's drones behave when they lose the controller. Look at the timelines
  before the held-out run.
- **Detecting a teammate's death can be late.** Liveness is stamped when a
  message is *read*, not when it was *sent*. A drone in a 70 s sweep reads its
  inbox only at the end, so a heartbeat sent at 3 s counts as "heard at 76 s".
  In one D run this made a dead teammate look alive until every survivor had
  gone home, and its sector was never flown. Stamping liveness at send time
  instead breaks five existing tests: live drones send no heartbeat during a
  sweep, so they would look dead too. The proper fix is heartbeats between
  sweep legs, which is the open item from Phase 9. It changes task rules, so it
  needs a decision and a refreeze before the held-out run.
