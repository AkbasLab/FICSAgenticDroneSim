# Run Ledger

Every flight this project has recorded, what it was worth, and how much of the
study remains. Maintained because "how many runs have we done" turned out to be
a harder question than it should be, and because two thirds of the runs on disk
are **not** study data for reasons that are easy to forget.

> **Updated 2026-10-20.** Update this file whenever a series is flown, in the
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
| M01 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M02 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M03 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M04 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M05 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M06 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M07 | 1 | 3 | 3 | 3 | **done** — 3/3, flown valid |
| M08 | 1 | 3 | 3 | 3 | **done** — unscoreable by design; 3/3 consistent |
| M09 | 2 | 3 | 3 | 6 | **done** — 3/3, 6/6 drone-plans, flown valid |
| M10 | 4 | 3 | 3 | 12 | **done** — 3/3, 12/12 drone-plans; Drone1–Drone3 contact every run; lands ~13/16, see below |
| **Total** | | | **30** | **42** | |

### Completion

```
runs flown and landed:   30 / 30      (100%)
plans correct:           21 / 21 scored, + 6 M09 and 12 M10 drone-plans
altitudes verified:      30 / 30      within 0.13 m of the commanded height
landings:                42 / 42      drone-landings, on evidence
obstacle collisions:      0           POLLED at 10 Hz, not inferred

single-drone (M01-M08):  24 / 24      COMPLETE
M09 (two drones):         3 /  3      COMPLETE
M10 (four drones):        3 /  3      COMPLETE; contacts recorded, see below
```

> ### The citable block is `v6-polled`, 2026-10-19
> Thirty runs on `llama3.3:70b`, Ollama **0.40.6**, `num_ctx` **98304**, with
> collision polling. **This is the first block where planning, flight, altitude,
> landing and contact are all measured rather than assumed**, and it supersedes
> every earlier one.
>
> Earlier blocks are kept with their verdicts. In particular the 2026-10-06
> `v3` block's "24/24 landed" was true **by coincidence**: `landed_on_ground` came
> from one timing-dependent collision read, and the identical M05 flight
> reported landed on the 6th and not landed on the 19th. See the phase log.
>
> **Comparability:** flight times are identical to the 2026-10-06 `v3` block across both an
> Ollama version jump and a 24x context change — M01 21.7 s, M02 17.6, M03 27.4,
> M04 22.8, M05 22.2, M06 20.6, M07 23.8, M08 30.9. Planning latency likewise.
> Neither change affected anything measured.
>
> *Corrected 2026-10-20:* this note and §4b/§5 first said "9 October". No run was
> flown that day (the agent log has no flights between 6 and 19 October). The
> block meant is `v3`, flown 6 October, whose flight times and M05 landing flags
> are the ones quoted. See the phase log's correction entry.
>
> **Reproduced from a clean clone, 2026-10-19/20.** On the server instance that
> flew v6, all 42 drone-plans came back byte-identical, and M01–M09 flew to
> within 0.10 s and 3 cm of it. Two qualifications came out of it, both now
> part of how this block is quoted:
>
> * **M10's 3/3 landings are a favourable draw.** The Drone1–Drone3 contact
>   happens on every M10 run, and across 16 runs from the clone Drone3 landed
>   in 13. The three failures had the longest contacts (2.3–3.7 s). Quote the
>   rate, not the 3/3.
> * **Temperature 0 is deterministic per server instance only.** On a second
>   Vega job, M09's Drone1 added `"z": 0` to its `fly_to`, which still scored
>   correct but flew home at ground level, as M04 does on every run.
>
> The clone's 97 flown runs are verification, not study data, and are not
> in this repository. The record is
> `phase-01-baseline-freeze/evidence/clean-clone-dry-run-2026-10-19.md`.

> ### RESOLVED 2026-10-19 — the caveat below no longer applies to `v6-polled`
> Collisions are polled at 10 Hz throughout every flight, so the 30 runs of
> 2026-10-19 carry real contact data. The caveat stands for every block before
> it, which was flown without polling.
>
> The 7.55 m "contradiction" is also resolved, and was never a contradiction:
> the monitor's minimum (t+15.98) and the contact (t+16.98) are **two different
> instants**. A minimum over an interval is not a value at an event. See the
> phase log.
>
> ### Caveat on collision and proximity, 2026-10-06 (historical)
> Flight and planning results for all 30 runs stand. **Collision counts do
> not.** `collisions()` is read once after teardown and AirSim returns only the
> most recent collision, so the landing contact overwrites anything earlier — a
> flight that lands can never report a mid-flight collision.
>
> A 10 Hz trace caught Drone1 and Drone3 in contact in **two of the three M10
> runs**, penetration up to 0.152 m, while all three records say
> `collision: false`. The pre-fix M10 recorded this same contact only because
> that flight never landed.
>
> Separation is suspect too: the monitor put that pair **7.54 m apart** at the
> moment of contact. Both need polling before any proximity claim is citable.
>
> Also open, and now characterised: M10's Drone3 gains **14.6 m** during its
> backward leg, and it is **not drift**. Traced at 10 Hz, it holds 20.0 m for
> three seconds then goes 19.96 -> 32.62 in **0.44 s** -- 12.7 m at about
> 29 m/s, commanded speed 5 m/s -- arriving at Drone1's altitude. One
> discontinuity, not a climb.
>
> It needs backward flight **and** other vehicles: Drone3 flown forward in the
> same layout drifts 1.85 m with zero contacts, and one drone flying backward
> alone drifts 1.24 m. Collisions are reported at t+16.97 while two
> independent position readers agree the drones are 10.48 m apart and
> separating. Cause unknown; no claim as to which API is wrong.
>
> Separately: a `land` step has now failed to descend and failed to return three
> times, leaving a drone armed in mid air. It defeats the teardown safeguard,
> because `skip_landing` is passed exactly when `land` reports success.

**The single-drone baseline is complete on `llama3.3:70b`, plan and flight:
21/21 scored runs correct, 24/24 landed, zero obstacle collisions, and
`ground_z = 29.25` on all 24.** M08 is unscoreable by design and produced the
same plan all three times.

Re-flown on 2026-10-06 after the altitude defect, and the repeats are now
genuinely repeats — final x agreeing to 1–4 cm across three runs of every
mission, and flight times identical within each. Flight times roughly halved
against the pre-fix block (M01 42.2 → 21.7 s, M02 38.1 → 17.6 s, M03 47.9 →
27.4 s) because 29.25 m of spurious climb is no longer being flown. Horizontal
displacement is unchanged, which is the check that the altitude fix touched only
altitude: M01 20.46 → 20.22, M03 19.16 → 19.16, M05 25.26 → 25.23, M07
20.46 → 20.22.

~~**Remaining: 6 runs** — M09 (two drones) and M10 (four).~~ **None
remaining:** M09 and M10 were flown valid on 2026-10-06 and again, with
collision polling, in `v6-polled` on 2026-10-19.

> ### Correction, 2026-10-06 (late) — every altitude was 29 m too high
> `moveToZAsync` targets are relative to the map origin, and Town10HD's ground
> sits at NED z = +29.25. **Every altitude command flew to commanded + 29.25 m**
> from the first flight onward. `set_altitude -30` was measured at **59.65 m**
> above the ground; `CRUISE_ALTITUDE = -8` at **37.51 m**. `land` was the only
> altitude call already anchored to `ground_z`, which is why the 2026-09-29
> landing fix did not expose this.
>
> **Planning results stand** — they never touched the simulator. **Execution
> results do not**: flight times, ground contact, and the vertical staggering
> that is M09's and M10's only separation were all measured in the wrong
> altitude regime. Same split as Block A, for the same kind of reason.
>
> Fixed by anchoring `take_off`, `set_altitude` and `fly_to` to `ground_z`.
> Verified in flight: the same plan peaks at **32.06 m** instead of 60.85 m and
> takes **35.7 s** instead of 103.1 s. See the phase log for 2026-10-06.

> ### Correction, 2026-10-06
> M09 and M10 were recorded here as **blocked by the multi-drone spawn
> defect**. That was wrong, and the status was carried forward from 2026-09-28
> without retesting.
>
> **The defect affects declared rosters, not multi-drone flight.** A drone
> named in `settings.json` is created at simulator start, falls, and settles
> on top of the other — and a drone resting inside another cannot be
> repositioned. A drone added at runtime with `simAddVehicle` is placed while
> still falling, never becomes pinned, and the single `simSetVehiclePose`
> succeeds.
>
> On 2026-09-28 the roster had been set to 2 for a camera experiment. When that
> was reverted the roster returned to 1, and the defect went with it. **No
> placement code was changed** — `git diff ecd39af HEAD` shows zero changes to
> `ensure_vehicles`, `simAddVehicle`, `simSetVehiclePose` or `SPACING`.
>
> Measured 2026-10-06: placement with a runtime-spawned second drone succeeded
> **5/5 trials** at 4.02 m, and M09 then flew **6/6 drone-plans correct across
> two sessions** with separation never dropping below spawn spacing.
>
> **Implication for Phase 3**, whose exit criterion names four drones: it is
> not blocked either, provided the roster stays at one drone and the rest are
> spawned at runtime. M10 will confirm that for four.

---

## 3. Session register

Everything on disk, with a verdict. **`v6-polled` is the citable block.** The
2026-10-06 `v3` sessions are valid for plan, flight and altitude, but were
flown without collision polling. Everything else is superseded or diagnostic,
and kept on purpose. Planning data from every 70B session stands.

| Session | Model | Runs | Verdict |
|---|---|---|---|
| `20260928-212436-blockA-M01-M08` | 3b | 24 | **planning valid, execution invalid** |
| `20260929-000255-smoke-M01` | 3b | 3 | diagnostic — the landing defect visible |
| `20260929-000737-ground-fix-M01` | 3b | 3 | diagnostic — a fix that did not work |
| `20260929-001130-ground-fix-M01` | 3b | 3 | diagnostic — the same fix, still wrong |
| `20260929-001503-ground-fix2-M01` | 3b | 3 | diagnostic — the fix working |
| `20261005-233824` | 70b | 3 | exploration — `--plan-only`, non-protocol options |
| `20261006-174355-v2-M01` | 70b | 3 | **planning valid, execution invalid** — altitude |
| `20261006-175302-v2-M02-M08` | 70b | 21 | **planning valid, execution invalid** — altitude |
| `20261006-181303-v2-M05-recheck` | 70b | 3 | planning valid, execution invalid — altitude |
| `20261006-182201-v2-M09` | 70b | 3 | planning valid, execution invalid — altitude |
| `20261006-183536-v2-M09-osc` | 70b | 3 | planning valid, execution invalid — altitude |
| `20261006-190942-v3-M01-M08` | 70b | 2 | **diagnostic** — aborted; zero displacement, not reproducible |
| `20261006-200307-v3-diag` | 70b | 1 | diagnostic — traced M01 proving the altitude fix |
| `20261006-201430-v3-guard` | 70b | 2 | diagnostic — ground-reference guard verified in flight |
| **`20261006-201608-v3-M01-M08`** | **70b** | **24** | **VALID STUDY DATA** — plan and execution |
| **`20261006-203012-v3-M09`** | **70b** | **3** | **VALID** — two drones, 6/6 drone-plans |
| **`20261006-203259-v3-M10`** | **70b** | **3** | **VALID for plan, flight, altitude** — collision/proximity not trustworthy |
| `20261019-18*-v5-polled` | 70b | 24 | **diagnostic** — exposed the timing-dependent landing check |
| **`20261019-18*-v6-polled`** | **70b** | **30** | **THE CITABLE BLOCK** — plan, flight, altitude, landing and contact all measured |
| `20261006-184158-v2-M10` | 70b | 1 | **diagnostic** — the run that exposed the altitude defect |
| `20261020-192150-p2-planonly` | 70b | 30 | **Phase 2** — `--plan-only` on a fresh server; 42/42 drone-plans identical to v6 |
| `20261020-192813-p2-blockA` | 70b | 0 | **aborted** — hung in AirSim's `reset()` before the first flight; nothing flown |
| **`20261020-193347-p2-blockA`** | **70b** | **24** | **VALID — Phase 2's re-flight of v6** through the refactored code |
| **`20261020-194802-p2-blockB-M09`** | **70b** | **3** | **VALID — Phase 2's re-flight of v6** |
| **`20261020-195048-p2-blockC-M10`** | **70b** | **3** | **VALID — Phase 2's re-flight of v6**; Drone1–Drone3 contact every run, as in v6 |
| `20261021-005707` four-drone-skills, live | none | 1 (20 skills) | **Phase 3 exit run** — a skill demonstration, not a mission run: 20/20 skills, no contacts |
| `20261021-005853` four-drone-skills, mock | none | 1 (20 skills) | Phase 3 — the same script on the mock, simulated time |
| **`20261021-093521-exit`** search-relay, mock | none | 20 seeds | **Phase 4 exit run** — the scripted controller on `search_relay_001`, seeds 1–20: 20/20 met |
| `20261021-183608-overrun` search-relay, mock | none | 20 seeds | Phase 4 — the exit re-flown after lanes were made to run past sector ends: 20/20 met |
| `20261021-183614-gate` search-relay, mock | none | 20 seeds | Phase 4 — the live variant `search_relay_live_small`'s mock gate: 20/20 met |

The `p2-` sessions are in `phases/phase-02-repository-architecture/results/`,
not Phase 1's. They meet every condition in §1 and are the Phase 2 exit
evidence: the same 30 runs as v6, flown by the code at `ac48cb0`, compared run
by run in that phase's `evidence/`. **v6 stays the citable Phase 1 block**; the
re-flight shows the refactor did not change it.

The two Phase 3 rows are in `phases/phase-03-flight-skill-layer/results/`. They
are not mission runs and plan nothing: a fixed four-drone skill script
(`scripts/four_drone_skills.py`), counted here because the live one flew four
drones in CarlaAir. Its conditions: v6's simulator setup, no model.

The Phase 4 row is in `phases/phase-04-search-relay-mission/results/`. It is
the first run judged as a mission against AUV-05's six criteria, but on the
mock, not in CarlaAir, and by a scripted controller with no model: a
feasibility check of the canonical mission (AUV-19's gate G1), not study data.
Its 20 seeds move the targets; the plan is the same for all of them.
The two later rows are the same exit re-flown after a controller fix, and
the mock gate of the small variant meant for a live flight; see the phase
record, step 5.

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

### Why M05 was re-flown

Its three runs in `v2-M02-M08` recorded `landed_on_ground: false`. The flights
were fine; the **check** was wrong.

A landed drone rests about **1.2 m above its arming `ground_z`**, because `land`
descends to `ground_z - 1.0` before handing over to `landAsync`. The test
allowed 1.5 m, leaving 0.3 m of margin. M05 flies furthest — two 3-second legs,
25 m out — and the terrain there is 0.8 m higher, so it read **1.99 m** and
failed a test it should have passed.

The simulator had been saying so all along: M05 was the only mission reporting
`Town10HD_Terrain_Ground` with `is_ground: true`. The physics engine said the
aircraft was touching terrain while the check said it had not landed.

`landed_on_ground` now accepts terrain contact as proof. The re-flight returned
identical plans, identical positions and identical flight times, with the flag
corrected — which is what a measurement fix should look like.

**Both sessions are kept.** The original records what was measured; this one
records it correctly. Phase rule 4: nothing is revised after the fact.

### The oscillation that was not there

M09 was flown a second time while both drones' altitude was sampled at 10 Hz,
because the drones appeared to oscillate continuously in the viewport.

They do not. Across three concurrent two-drone missions, **72 hold segments
contained zero direction reversals**, with mean peak-to-peak altitude drift of
**1.5–1.8 cm**. A separate single-drone test at ~1,300 Hz found zero reversals
in 16,500 samples and a 2.5 cm range over 8 seconds of holding.

The reversals that do appear in the trace are mission events, not instability:
three of about 10 m each are `reset_world` dropping the drone between runs, and
the 0.83–0.86 m ones immediately after are the landing bounce. Both drones show
them at identical timestamps.

What is real, and visible, is a transient at every altitude change: a **1.4 m
wrong-way excursion** as the controller reverses existing vertical velocity, and
a **1.5 m overshoot** with one bounce on arrival, settling in 2–3 seconds.
Consistent run to run, so a characteristic rather than a fault.

The apparent continuous bobbing is the **viewport**. The laptop GPU sits at
3765/4096 MiB and 100% utilisation rendering Town10HD at Epic with traffic;
smooth motion at a low, uneven frame rate reads as oscillation, most strongly on
vertical movement. That GPU load is in the protocol deliberately.

---

## 4. Phases 2 and 3 have no run inventory

Neither is a measurement phase, so neither has a run count. Their exit criteria
are demonstrations.

| Phase | Exit criterion | What it needs |
|---|---|---|
| **2** — Repository architecture | Baseline examples run through the modular structure unchanged | A refactor plus a demonstration that behaviour is unchanged. No scored runs. **Done 2026-10-20**: a 30-run re-flight of the mission set (plus a plan-only pass), every drone-plan identical to v6, every outcome equal; see §3 |
| **3** — Flight-skill layer | Four drones take off, navigate, hold, return, land, each skill returning a structured result | Flights, but a capability demonstration rather than a scored matrix. **Done 2026-10-21**: one live four-drone run, 20/20 skills, no contacts; see §3 |

> **Phase 3's exit criterion names four drones**, and on the evidence of M09 it
> is not blocked: multi-drone flight works when the extra drones are spawned at
> runtime rather than declared in `settings.json`. M10 tests that for four.
> The declared-roster defect remains real and unfixed, but it only bites if the
> roster is changed — which nothing now needs to do.

Phase 18 is the next phase with a large run inventory: a factorial design
against the mock adapter, roughly 1,920 runs, requiring no simulator and no GPU.

---

## 4b. Context length, and why it is 98,304

From 2026-10-19 the protocol declares **`num_ctx = 98304`** -- 96K, the largest
context that fits entirely in one H100 alongside the weights.

### The arithmetic

| | MiB |
|---|---|
| H100 PCIe | 81,559 |
| weights, `llama3.3:70b` Q4_K_M *(measured)* | 42,007 |
| KV cache at 0.3125 MiB/token, 98,304 tokens | 30,720 |
| **total** | **72,727**, leaving 8.8 GB |

The model's own maximum of 131,072 needs 40,960 MiB of cache and totals
**82,967** -- over the card by **1,408 MiB**. Ollama does not refuse; it moves
about 67% of the model onto CPU cores and carries on, far slower, which is no
longer the measurement intended. **Missing by 1.4 GB is the whole reason a
second GPU appeared to be necessary**, and a two-GPU job estimated a 12-hour
wait.

### Why this is sizing, not capping

Ollama reserves the cache for the context **declared**, not the context used.
So `num_ctx` is a memory reservation, not a limit on anything the model may do.

Measured from the real prompt: the longest request in the mission set is
**1,302 characters, about 326 tokens**, plus a 512-token reply cap -- roughly
**838 tokens**. 98,304 is therefore **117x** what the task can consume.

That matters for the write-up. "Did capping the context affect your results?"
can be answered by re-running the whole experiment on more hardware, or by
observing that the prompt is 326 tokens against a 98,304 window. The second is
stronger: it shows the limit could never be **reached**, not merely that it
happened not to be -- and it costs no queue time and no card somebody else could
use.

### What this means for earlier runs

The runs of 6 October used `num_ctx = 4096`. By the same argument their
plans cannot have been affected either: 4,096 was already 4.9x the 838 tokens
needed. They remain valid, and no comparison run is required to establish it.

---

## 5. Conditions of the valid data

Recorded here because a run's conditions are part of the result. These are
`v6-polled`'s. Every row also carries them in its `protocol` field.

| | |
|---|---|
| Model | `llama3.3:70b`, 4-bit |
| Server | Ollama **0.40.6** |
| Placement | 100% GPU on one NVIDIA H100 PCIe, 80 GB |
| Host | ERAU Vega, node **`gpu02`, card 0**, job 70633, reached by SSH tunnel through `vegaln1` |
| Simulator | local — CarlaAir v0.1.7, Town10HD, Epic, 1080p, traffic on (30 vehicles, 50 walkers) |
| `num_ctx` | **98304** (§4b) |
| `num_gpu` | 999 (all layers) |
| `temperature` | 0 |
| Planning latency | 35.6 s first call, then **0.8–6.0 s** by mission (M10 sums four drones) |
| Flight times | M01 21.7 · M02 17.7 · M03 27.4 · M04 22.8 · M05 22.2 · M06 20.7 · M07 23.7 · M08 30.9 · M09 33.5 · M10 38.3–39.1 s |

Phase 2's re-flight (2026-10-20) ran under these same conditions, from
`gpu02` **card 1**, job 71111; flight times match v6's to within 1.1 s.

The 6 October runs used Ollama 0.35.1 and `num_ctx = 4096`. §4b shows
the context could not have affected their plans, and the comparability note in
§2 shows the version and context change left flight times unchanged.

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
