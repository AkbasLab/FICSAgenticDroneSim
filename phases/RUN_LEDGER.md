# Run Ledger

Every flight this project has recorded, what it was worth, and how much of the
study remains. Maintained because "how many runs have we done" turned out to be
a harder question than it should be, and because two thirds of the runs on disk
are **not** study data for reasons that are easy to forget.

> **Updated 2026-10-06.** Update this file whenever a series is flown, in the
> same commit as the data.

---

## 1. What counts as a run

A **run** is one mission flown once, by however many drones that mission needs.
A **drone-plan** is one planning call: M01 is one of each, M10 is one run and
four drone-plans.

Scored totals in the results use runs. The distinction matters only for M09 and
M10.

A run is **valid study data** only if all of these hold:

| | |
|---|---|
| Model | the protocol's model — currently `llama3.3:70b` |
| Inference options | as recorded in `[protocol.options]`, actually sent |
| Flight | actually flown, not `--plan-only` |
| Landing | `landed_on_ground: true` |
| Ground reference | `ground_z` matches the measured ground for that session |

The last two exist because every flight before 2026-10-06 ended roughly 17 m
above the ground and nothing in the data revealed it. See the phase log entry
for 2026-10-06.

---

## 2. Phase 1 — the only phase with a run inventory

**Required: 30 runs** (42 drone-plans). Ten missions, three repeats each,
matching the upstream benchmark so results are comparable.

| Mission | Drones | Repeats | Runs | Drone-plans | Status on `llama3.3:70b` |
|---|---|---|---|---|---|
| M01 | 1 | 3 | 3 | 3 | **done** — 3/3 correct, 3/3 landed |
| M02 | 1 | 3 | 3 | 3 | not flown |
| M03 | 1 | 3 | 3 | 3 | not flown |
| M04 | 1 | 3 | 3 | 3 | not flown |
| M05 | 1 | 3 | 3 | 3 | not flown |
| M06 | 1 | 3 | 3 | 3 | not flown |
| M07 | 1 | 3 | 3 | 3 | not flown |
| M08 | 1 | 3 | 3 | 3 | not flown — unscoreable by design |
| M09 | 2 | 3 | 3 | 6 | **blocked** — multi-drone spawn defect |
| M10 | 4 | 3 | 3 | 12 | **blocked** — multi-drone spawn defect |
| **Total** | | | **30** | **42** | |

### Completion

```
valid study runs:     3 / 30      (10%)
single-drone (M01-M08):   3 / 24  (12.5%)
multi-drone (M09-M10):    0 /  6  — blocked
```

**Immediately flyable: 21 runs** (M02–M08). About 20 minutes of GPU time at
roughly 55 s per run.

**Blocked: 6 runs.** M09 and M10 cannot be flown until the multi-drone spawn
defect is fixed — drones spawn inside one another because this build ignores
declared spawn offsets. A two-pass placement fix was written, verified at 4.00 m
separation, and then deliberately reverted because the volume of pose requests
destabilised the simulator. See the phase log, 2026-09-28 and 2026-09-29.

---

## 3. Session register

Everything on disk, with a verdict. Seven sessions, 42 recorded runs, of which
**three are valid study data**.

| Session | Model | Runs | Verdict |
|---|---|---|---|
| `20260928-212436-blockA-M01-M08` | 3b | 24 | **planning valid, execution invalid** |
| `20260929-000255-smoke-M01` | 3b | 3 | diagnostic — the landing defect visible |
| `20260929-000737-ground-fix-M01` | 3b | 3 | diagnostic — a fix that did not work |
| `20260929-001130-ground-fix-M01` | 3b | 3 | diagnostic — the same fix, still wrong |
| `20260929-001503-ground-fix2-M01` | 3b | 3 | diagnostic — the fix working |
| `20261005-233824` | 70b | 3 | exploration — `--plan-only`, non-protocol options |
| **`20261006-174355-v2-M01`** | **70b** | **3** | **VALID STUDY DATA** |

### Why Block A is split

Its 24 runs recorded `ground_z` between 9.14 and 11.02 against a true ground of
29.25, so every flight ended about 17 m in the air.

- **Planning results stand.** Validity, exact-sequence correctness, consistency,
  extra steps, latency and raw output are model behaviour and never touched the
  simulator. 21/21 correct, and the M08 ambiguity finding, remain citable.
- **Execution results do not.** Flight times, completion, collisions and ground
  contact were measured on flights that never landed.

It is also `llama3.2:3b`, which is no longer the study's model. A 3B column
would need re-flying to exist properly; whether that is worth doing is an open
question, not a commitment.

### The four diagnostic sessions

Kept deliberately. They are the evidence trail of the landing investigation —
the defect visible at `ground_z` 12.1, two failed fixes, and the working one at
29.25. Phase rule 5: failed attempts stay.

---

## 4. Phases 2 and 3 have no run inventory

Neither is a measurement phase, so neither has a run count. Their exit criteria
are demonstrations.

| Phase | Exit criterion | What it needs |
|---|---|---|
| **2** — Repository architecture | Baseline examples run through the modular structure unchanged | A refactor plus a demonstration that behaviour is unchanged. No scored runs |
| **3** — Flight-skill layer | Four drones take off, navigate, hold, return, land, each skill returning a structured result | Flights, but a capability demonstration rather than a scored matrix |

> **Phase 3 depends on the multi-drone spawn defect being fixed**, since its
> exit criterion names four drones. That makes the defect blocking for Phase 3
> as well as for M09 and M10 — it is the single most consequential open item in
> the project.

Phase 18 is the next phase with a large run inventory: a factorial design
against the mock adapter, roughly 1,920 runs, requiring no simulator and no GPU.

---

## 5. Conditions of the valid data

Recorded here because a run's conditions are part of the result.

| | |
|---|---|
| Model | `llama3.3:70b`, 4-bit |
| Placement | 100% GPU on one NVIDIA H100 PCIe, 80 GB |
| Host | ERAU Vega, node `gpu01`, reached by SSH tunnel through `vegaln1` |
| Simulator | local — CarlaAir v0.1.7, Town10HD, Epic, traffic on |
| `num_ctx` | 4096 |
| `num_gpu` | 999 (all layers) |
| `temperature` | 0 |
| Planning latency | 34.9 s first call, **0.7 s** warm |
| Flight time, M01 | 42.2 s, no variance across three runs |

For comparison, `llama3.2:3b` on this laptop's CPU plans in 1.2–1.3 s. The 70B
on an H100 is roughly **twice as fast** despite being twenty-three times larger,
because the work moved off laptop cores. There is no latency cost to the larger
model in this architecture.

---

## 6. Keeping this honest

1. Update in the **same commit** as the data it describes.
2. A session that is not valid study data says **why**, in the register.
3. Nothing is deleted. A superseded session stays with its verdict.
4. When a run count changes, change it **here** — not in prose elsewhere that
   will drift.
