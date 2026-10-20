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

Multi-drone altitudes are deliberately staggered — the drones spawn 4 m apart on
X and there is **no collision avoidance anywhere in this stack**. Vertical
separation is the only thing keeping them apart.

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

**M09 / M10 — extra drones are spawned, and they stay.** `settings.json`
declares one drone and is never rewritten. M09 and M10 add their extra drones
to the running simulator, and those drones remain in the scene until the
simulator restarts. Hence the ordering rule under Protocol.

> **Changed 2026-10-20.** This used to warn that answering more than 1 to
> *"How many drones?"* rewrote `settings.json` permanently. It no longer does:
> drones are spawned at runtime instead, and `write_settings()` is no longer
> called.

**M10 — a contact in every run.** Drone3 flies backward beneath Drone1, and on
every recorded run it jumps from about 18 m to about 33 m AGL in under half a
second, arriving at Drone1's altitude. The two touch at t ≈ 17 s. Usually the
contact is brief and both land. When it lasts more than about 2 s, Drone3 is
left unable to descend. The cause is open: see `RUN_LEDGER.md`.

---

## Protocol

**Three runs per mission**, matching the upstream benchmark so results are
directly comparable.

| | |
|---|---|
| Model | **`llama3.3:70b`**, 4-bit, on one NVIDIA H100 80 GB (ERAU Vega), reached by SSH tunnel. See [`SETUP.md`](SETUP.md) §7 |
| Server | Ollama **0.40.6**, recorded on every row as `ollama_version` |
| Options | `num_gpu: 999`, `num_ctx: 98304`, `temperature: 0`, `num_predict: 512`, `num_thread: 12` |
| Map | Town10HD |
| Launch | `.\CarlaAir.ps1 Town10HD` |
| Quality | Epic (launcher default), 1920×1080 |
| Traffic | 30 vehicles, 50 walkers — the platform as it is actually used |

The authoritative copy of these values is `[protocol]` in
[`../configs/missions/baseline_v1.toml`](../configs/missions/baseline_v1.toml),
which is what the runner reads, sends and records.

> **Changed 2026-10-06 and 2026-10-19.** The model was `llama3.2:3b` on the
> laptop CPU (`num_gpu: 0`). It moved to `llama3.3:70b` on an H100 on
> 2026-10-06. `num_ctx` was set to 98,304 on 2026-10-19, the largest context
> one H100 holds alongside the weights, and Ollama went from 0.35.1 to 0.40.6
> the same day. The reasoning is in `RUN_LEDGER.md` §4b and the phase log.

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

**Fly in increasing drone count, and restart the simulator before going back
down.** Keep `settings.json` at one declared drone. Extra drones are spawned at
runtime when a mission needs them, so M01–M08, then M09, then M10 fly in one
simulator session with no restart. But a spawned drone stays in the scene
until the simulator restarts — `client.reset()` returns it to its spawn pose
rather than removing it — and spawn poses lie along +X, on every forward
mission's flight path. So **any mission flown after one that used more drones
flies into the leftovers.**

> **Changed 2026-10-20.** This previously read "restart the simulator between
> multi-drone missions; single-drone missions may run back to back", which
> never said that single-drone missions after a multi-drone one need a restart
> too. Measured 2026-10-19 from a clean clone: M01–M09 flown after M10 without
> a restart, **17 of 27 runs hit the leftover drones** and were recorded as
> ordinary obstacle collisions. `v6-polled` was unaffected only because it
> flew M10 last. `run_missions.py` now checks the whole series against the
> scene before the first takeoff and refuses an order that breaks this rule.

Note that only the **first plan of a session** pays the prompt-cache cost, so
record whether each run was cold or warm.

### What to record per run

`run_missions.py` records all of these on every row of its JSONL. Nothing is
read off the viewport.

| Field | Where it is in the row |
|---|---|
| Plan **syntactically valid** | `all_valid`; per drone `valid` |
| **Matches expected sequence** | `all_correct`; per drone `correct`, `extra_steps` |
| **Planning latency** | `plan_seconds` (the first run of a session is cold) |
| **Raw model output** | per drone `raw_output` |
| **Execution** | `execution.outcomes`: steps executed, `flight_seconds`, `ground_z`, altitude after each step, `final_position` |
| **Landing** | `landed_on_ground`, with `landed_evidence` saying how it was decided |
| **Collisions** | `execution.separation`: contacts **polled at 10 Hz** throughout the flight, split into `obstacle_collisions` and `drone_collisions` |
| **Separation** (multi-drone) | `min_separation_m`, `per_pair_min_m`. Note that these are minima over the flight, not values at a contact |
| Conditions | `protocol`: model, options actually sent, `ollama_version`, endpoint, code commit and digests |

Generated token counts are only in the Ollama server's own log
(`stop processing: n_tokens`), and are not recorded.

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

`✔` correct, `✘` incorrect, `—` not applicable. Which blocks are valid data,
and why the others are not, is in [`../phases/RUN_LEDGER.md`](../phases/RUN_LEDGER.md).

### `llama3.3:70b` — `v6-polled`, the citable block

Flown 2026-10-19, 18:24–18:40, under the protocol above. Thirty runs in three
invocations, in increasing drone count, on one simulator session. Raw data and
the code that flew it are in `phases/phase-01-baseline-freeze/results/`:
`baseline_v1-llama3.3_70b-20261019-182324-v6-polled` (M01–M08),
`…-183553-v6-polled` (M09) and `…-183805-v6-polled` (M10).

| Mission | Valid | Correct | Consistent | Extra steps | Latency (s) | Flight (s) | Landed | Obstacle contacts | Notes |
|---|---|---|---|---|---|---|---|---|---|
| M01 | ✔ 3/3 | 3/3 | ✔ | 0 | 0.8 (35.6 cold) | 21.7 | 3/3 | 0 | |
| M02 | ✔ 3/3 | 3/3 | ✔ | 0 | 0.9 | 17.7 | 3/3 | 0 | |
| M03 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.5 | 27.4 | 3/3 | 0 | |
| M04 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.9 | 22.8 | 3/3 | 0 | `fly_to(0, 0, z: 0)`: returns at ground level, by design (`fba0c98`) |
| M05 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.3 | 22.2 | 3/3 | 0 | landing decided by polled terrain contact |
| M06 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.6 | 20.7 | 3/3 | 0 | |
| M07 | ✔ 3/3 | 3/3 | ✔ | 0 | 1.2 | 23.7 | 3/3 | 0 | reordering handled |
| M08 | ✔ 3/3 | — | ✔ | — | 1.7 | 30.9 | 3/3 | 0 | unscoreable by design; see below |
| M09 | ✔ 3/3 | 3/3 | ✔ | 0 | 4.1 | 33.5 | 6/6 | 0 | 2 drones; min separation 4.02 m |
| M10 | ✔ 3/3 | 3/3 | ✔ | 0 | 6.0 | 38.3–39.1 | 12/12 | 0 | 4 drones; **Drone1–Drone3 contact in 3/3** |

**27/27 scored runs correct (39/39 drone-plans) · every mission gave the same
raw output on all three runs · 42/42 drone-landings · 0 obstacle contacts.**
Latency is per run, summed over a mission's drones. Flight time is the
longest drone's.

**M08.** All three runs planned `set_altitude(-25) → hover(5) →
set_altitude(-20)`: up to 25 m, hold, then down to 20 m. "Come back down" got
the right direction, unlike the 3B model (below), but "safely" did not become
a landing. The harness's teardown landed the drone, which is outside the plan.

**M10's landings are not a property of the mission.** The contact happens in
every M10 run. In the clean-clone reproduction of 2026-10-19/20, M10 landed in
**13 of 16** runs: the three failures had the longest contacts (2.3–3.7 s),
which left Drone3 unable to descend. So v6's 3/3 is a correct record of those
three runs and a favourable draw: at 13/16 per run, three clean landings in a
row is roughly a coin toss. Quote the rate, not the 3/3. Evidence:
`phases/phase-01-baseline-freeze/evidence/clean-clone-dry-run-2026-10-19.md`.

**Reproduced from a clean clone.** On the server instance that flew v6, all
42 drone-plans came back byte-identical, and every M01–M09 run flown with those
plans matched v6 to within 0.10 s and 3 cm. A complete 30-run repeat block
landed 30/30. On a second Vega job, M09's Drone1 answered with an extra
`"z": 0` on `fly_to`. It still scored correct, but flew home at ground level
and finished 3.3 s sooner. That is what M04 does on every run (below). Temperature 0 is deterministic per server instance,
not across instances.

### `llama3.2:3b` — Block A, superseded

Planning results stand; execution results do not. This was the study's model
until 2026-10-06, run on the laptop's CPU.

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

> ### ⚠ The execution columns above are invalid. Re-fly required.
>
> **Found 2026-09-29.** Every Block A flight ended roughly 17 m above the
> ground, not on it. `arm()` read `ground_z` while the drone was still falling
> after being placed, and arming a falling drone makes the controller catch and
> hold it — so the recorded "ground" was a mid-air hover. Block A logged
> `ground_z` of 10.87–11.02 against a true ground of 29.25.
>
> **The planning columns are unaffected** — validity, correctness, consistency,
> extra steps, latency and raw output are model behaviour and never touched the
> simulator. 21/21 correct stands, as does the M08 ambiguity result.
>
> **Flight time, "Executed", collisions and ground contact do not stand.** M01
> measured 25.3 s here; flown correctly after the fix it is **42.2 s**.
>
> Fixed in `arm()` — the drone must settle *before* API control is enabled.
> Details in
> [`../phases/phase-01-baseline-freeze/`](../phases/phase-01-baseline-freeze/).

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

### `llama3.1:8b` — not run

Not part of the protocol. It is staged on Vega, and running it would connect
these numbers to the upstream benchmark's (M05 0/3, M06 3/3, M07 1/3 there).
Whether to run it, and a 3B column, is an open question, not a commitment.

### Summary

| Model | Scored runs correct | Fully-correct missions | Consistent missions | Extra steps | Latency, warm |
|---|---|---|---|---|---|
| **`llama3.3:70b`** (`v6-polled`) | **27/27** | **9/9** | **10/10** | 0 | 0.8–6.0 s |
| `llama3.2:3b` (Block A, single-drone, planning only) | 21/21 | 7/7 | 7/8 | 0 | 1.2–3.3 s |

Scored counts exclude M08, which is unscoreable. Consistency counts it.

---

## Why this set matters beyond the baseline

The upstream repository established informally that **stricter output schemas
improve local-model reliability** and that **harder prompts produce omitted or
invented steps**. Those findings currently exist only as prose in a README.
Running this set turns them into measured, re-runnable evidence attached to a
named environment — and gives every later architecture something constant to be
compared against.

It also produces results nobody has: the upstream benchmarks cover only
`llama3.1:8b` and `mistral-nemo`. Both the 70B results and the 3B planning
column are new.

---

## Change log

| Date | Change |
|---|---|
| 2026-09-18 | v1.0 — mission set frozen. |
| 2026-10-20 | Protocol and results brought up to date: `llama3.3:70b` on Vega, `v6-polled` as the citable block, the M10 landing rate, the restart rule. Mission text unchanged. |
