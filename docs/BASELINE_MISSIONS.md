# Baseline Mission Set — `v0.1-open-loop-baseline`

**Phase 1.3 deliverable** · Version 1.0 · 2026-09-18
**Vault reference:** `AUV-02 — Baseline Freeze`, §1.3

Ten fixed natural-language missions. These are the frozen instrument for
measuring the open-loop baseline, and the same ten will be re-run against every
later architecture so that improvements are measured against a constant.

**Do not edit the instruction text after results are recorded.** If a mission
turns out to be badly worded, add `M11` rather than changing `M05`.

> **The machine-readable set is
> [`../configs/missions/baseline_v1.toml`](../configs/missions/baseline_v1.toml).**
> That file is what actually runs, and it is where you add or change missions —
> instruction, expected action sequence, drone count, and whether the mission is
> scoreable at all. This document explains *why* each mission exists; the config
> defines *what* runs. Execute the set with
> [`../scripts/run_missions.py`](../scripts/run_missions.py), which scores the plans
> and writes both raw JSONL and a summary table into the phase record.

---

## Coverage

The set spans every category the plan requires:

| Category | Missions |
|---|---|
| Simple movement | M01 |
| Multi-step movement | M02, M03 |
| Return and land | M04 |
| Repeated actions | M05, M06 |
| Altitude change | M03, M07 |
| Ambiguous wording | M08 |
| Two-drone simultaneous | M09 |
| Four-drone simultaneous | M10 |
| *Instruction order ≠ execution order* | M07 |

---

## The missions

### Single drone

| ID | Instruction | Expected action sequence |
|---|---|---|
| **M01** | `fly forward for 5 seconds` | `fly_straight` |
| **M02** | `hover for 3 seconds then land` | `hover` → `land` |
| **M03** | `go up to 15 meters, fly forward for 5 seconds, then land` | `set_altitude` → `fly_straight` → `land` |
| **M04** | `fly forward for 5 seconds then return home and land` | `fly_straight` → `fly_to` → `land` |
| **M05** | `fly forward for 3 seconds, then do the exact same thing again` | `fly_straight` → `fly_straight` |
| **M06** | `hover in place for 2 seconds, three times in a row` | `hover` → `hover` → `hover` |
| **M07** | `before flying forward for 5 seconds, hover in place for 2 seconds` | `hover` → `fly_straight` |
| **M08** | `go up a bit, look around for a moment, then come back down safely` | **No single correct answer** — see below |

### Multi-drone

| ID | Drones | Instructions |
|---|---|---|
| **M09** | 2 | **Drone1:** `go up to 25 meters, fly forward for 6 seconds, then return home and land`<br>**Drone2:** `go up to 12 meters, fly right for 5 seconds, hover for 2 seconds, then land` |
| **M10** | 4 | **Drone1:** `go up to 30 meters, fly forward for 5 seconds, then land`<br>**Drone2:** `go up to 24 meters, fly right for 5 seconds, then land`<br>**Drone3:** `go up to 18 meters, fly backward for 5 seconds, then land`<br>**Drone4:** `go up to 12 meters, fly left for 5 seconds, then land` |

Multi-drone altitudes are deliberately staggered because there is **no
collision avoidance anywhere in this stack**. Vertical separation is the only
thing keeping the drones apart once airborne.

> **Corrected 2026-09-28.** This previously said "the drones spawn 4 m apart on
> X". They do not. Every drone in this build spawns at the player start
> whatever `settings.json` declares, so they arrive stacked inside one another,
> already colliding. The 4 m layout is established **at runtime** by
> `ensure_vehicles()`, which has to scatter them before it can position them,
> because a drone pinned inside another cannot be moved. Details in
> [`../phases/phase-01-baseline-freeze/`](../phases/phase-01-baseline-freeze/).

---

## Notes on specific missions

**M05 and M06 — repetition.** The upstream hard-set benchmark records
`llama3.1:8b` scoring **0/3** on M05, producing
`fly_straight, fly_to, land, fly_straight, fly_to, land` — six actions for a
two-action request. M06 scored 3/3 for the same model. Both are repetition, and
the model handles one and not the other; that contrast is worth capturing.

**M07 — instruction order differs from execution order.** *"Before flying
forward, hover"* requires reordering. `llama3.1:8b` scored **1/3** and was
inconsistent across runs.

**M08 — deliberately ambiguous.** There is no expected sequence and it must not
be scored for correctness. Record instead:

- Which actions were chosen for *"a bit"*, *"look around"* and *"safely"*
- Whether the plan was schema-valid at all
- Whether the same phrasing produced the same plan across the three runs

Consistency on M08 is the interesting variable, not accuracy. It is also the
only mission that speaks to the ambiguity clause in H4.

**M09 / M10 — a side effect to expect.** Answering more than 1 to *"How many
drones?"* causes the agent to **rewrite `settings.json` permanently** with that
many drones. The simulator will boot with that count from then on. Restore
afterwards, or the single-drone missions become invalid:

```
$f = Join-Path ([Environment]::GetFolderPath('MyDocuments')) "AirSim\settings.json"
Get-Content $f | Select-String '"Drone'
```

---

## Protocol

**Three runs per mission**, matching the upstream benchmark so results are
directly comparable.

| | |
|---|---|
| Model | `llama3.2:3b` (primary) — repeat with `llama3.1:8b` where memory allows |
| Options | `num_gpu: 0`, `temperature: 0`, `num_predict: 512`, `num_thread: 12` |
| Map | Town10HD |
| Launch | `.\CarlaAir.ps1 Town10HD` |
| Quality | Epic (launcher default), 1920×1080 |
| Traffic | 30 vehicles, 50 walkers — the platform as it is actually used |

> **Changed 2026-09-28.** This previously read `--no-traffic --quality Low`,
> with traffic off "to remove a confound and free GPU". Changed deliberately to
> measure the platform in the configuration it is actually used in. No results
> had been recorded under the old protocol, so nothing is invalidated — but the
> change accepts real costs, recorded in
> [`../phases/phase-01-baseline-freeze/`](../phases/phase-01-baseline-freeze/):
> traffic adds variance that has nothing to do with whether a plan executed,
> and Town10HD at Epic and 1080p already sits at 93% of this machine's 4 GB of
> VRAM.
>
> If later analysis shows flight timing moving with frame rate, this is the
> first thing to suspect, and the comparison to make is a re-run with traffic
> off.

Restart the simulator between multi-drone missions. Single-drone missions may
run back to back; note that only the **first plan of a session** pays the
prompt-cache cost, so record whether each run was cold or warm.

### What to record per run

| Field | Source |
|---|---|
| Plan **syntactically valid** | Agent accepted it without raising |
| **Matches expected sequence** | Exact match, no missing or extra actions |
| **Planning latency** | `plan_seconds` in `agent-log.jsonl` |
| **Execution success** | Mission ran to `Control released` without hanging |
| **Collision / proximity events** | Observed in the viewport; `simGetCollisionInfo()` |
| **Raw model output** | `raw_output` in `agent-log.jsonl` |
| Cold or warm cache | First plan of a session, or later |
| Generated tokens | Ollama `server.log`, `stop processing: n_tokens` |

A plan is **correct** only if its action sequence matches exactly — no missing
steps and no invented ones. Partial credit is not recorded; extra actions are
counted separately as `extra_steps`.

### Logging

The agent logs every planning call itself, to `runs/agent-log.jsonl` — one JSON
object per call carrying the instruction, the model's raw output, the validated
plan, the model id and `plan_seconds`.

This is deliberately not optional and not a separate step. The fields above
cannot be reconstructed after a run, so an agent that only prints to the console
produces unrepeatable measurements.

---

## Results

Fill in as runs complete. `✔` correct, `✘` incorrect, `—` not applicable.

### `llama3.2:3b`

Single-drone missions flown 2026-09-28, Town10HD, Epic, traffic on. Raw data:
`phases/phase-01-baseline-freeze/results/baseline_v1-llama3.2_3b-20260928-212436-blockA-M01-M08.jsonl`

| Mission | Valid 3/3 | Correct | Consistent | Extra steps | Latency (s) | Executed | Notes |
|---|---|---|---|---|---|---|---|
| M01 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.2 (12.4 cold) | 3/3 | flight 25.3 s, σ ≈ 0.1 |
| M02 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.4 | 3/3 | flight 21.2 s ×3 |
| M03 | ✔ 3/3 | 3/3 | ✔ | 0 | 2.5 | 3/3 | flight 31.0 s |
| M04 | ✔ 3/3 | 3/3 | ✔ | 0 | 2.8 | 3/3 | `return home` → `fly_to(0,0)` every time |
| M05 | ✔ 3/3 | 3/3 | ✔ | 0 | 2.1 | 3/3 | repetition handled; upstream reports 0/3 for `8b` |
| M06 | ✔ 3/3 | 3/3 | ✔ | 0 | 2.6 | 3/3 | |
| M07 | ✔ 3/3 | 3/3 | ✔ | 0 | 2.2 | 3/3 | reordering handled; one run armed 1.8 m high — see below |
| M08 | ✔ 3/3 | — | **2/3** | — | 3.3 | 3/3 | ambiguous; "come back down" became a **climb** — see below |
| M09 | | /3 | | | | | 2 drones — not yet flown |
| M10 | | /3 | | | | | 4 drones — not yet flown |

**21/21 scored runs correct · 24/24 executed to completion · 0 collisions.**

#### Two results the table cannot carry

**M08 got the direction of "down" wrong, consistently.** All three runs read
*"go up a bit, look around for a moment, then come back down safely"* as
`set_altitude(-10) → hover(1) → [climb to -20] → land`. In NED, −20 is *higher*
than −10, so "come back down" produced a climb. The landing saved it. Two runs
were identical; attempt 1 used `fly_to(0,0,-20)` instead of `set_altitude(-20)`,
hence consistency 2/3.

This is the only mission that speaks to H4's ambiguity clause, and it produced a
concrete, repeatable ambiguity failure rather than a vague one.

**Flight timing is stable, and traffic did not disturb it.** Every mission's
flight time repeated within ~0.1 s. M02 measured 21.2/21.2/21.2 s with traffic
against 21.2/21.0/21.2 s without it, which settles — for a single drone — the
open question about whether a heavier scene stretches flights because AirSim
physics advances with the Unreal tick.

**One anomaly.** M07 attempt 2 armed at `ground_z 9.14` against 10.87 and 10.95
elsewhere: 1.8 m higher, with no collision recorded and a normal flight. Most
likely the reset placed the drone on or beside a traffic vehicle — the confound
the original protocol avoided by disabling traffic. Worth watching; if it
recurs, a spawn-clearance check before arming is the fix.

### `llama3.1:8b`

| Mission | Valid 3/3 | Correct | Consistent | Extra steps | Latency (s) | Executed | Notes |
|---|---|---|---|---|---|---|---|
| M01 | | /3 | | | | | |
| M02 | | /3 | | | | | |
| M03 | | /3 | | | | | |
| M04 | | /3 | | | | | |
| M05 | | /3 | | | | | upstream reports 0/3 |
| M06 | | /3 | | | | | upstream reports 3/3 |
| M07 | | /3 | | | | | upstream reports 1/3 |
| M08 | | — | | — | | | |
| M09 | | /3 | | | | | |
| M10 | | /3 | | | | | |

### Summary

| Model | Correct runs | Fully-correct missions | Consistent missions | Avg extra steps | Avg latency |
|---|---|---|---|---|---|
| `llama3.2:3b` | /24 | /8 | /8 | | |
| `llama3.1:8b` | /24 | /8 | /8 | | |

Denominators exclude M08 (unscoreable) and count M09/M10 per drone.

---

## Why this set matters beyond the baseline

The upstream repository established informally that **stricter output schemas
improve local-model reliability** and that **harder prompts produce omitted or
invented steps**. Those findings currently exist only as prose in a README.
Running this set turns them into measured, re-runnable evidence attached to a
named environment — and gives every later architecture something constant to be
compared against.

It also produces a result nobody has: the upstream benchmarks cover only
`llama3.1:8b` and `mistral-nemo`. **A 3B column is new**, and if 3B holds up it
is the difference between this project running on available hardware and not.

---

## Change log

| Date | Change |
|---|---|
| 2026-09-18 | v1.0 — mission set frozen. |
