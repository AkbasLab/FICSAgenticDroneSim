# Run Ledger

Every flight this project has recorded, what it was worth, and how much of the
study remains. Maintained because "how many runs have we done" turned out to be
a harder question than it should be, and because two thirds of the runs on disk
are **not** study data for reasons that are easy to forget.

> **Updated 2026-10-06 (late evening).** Update this file whenever a series is flown, in the
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
| M09 | 2 | 3 | 3 | 6 | **plans correct** — 6/6; separation invalid; re-fly |
| M10 | 4 | 3 | 3 | 12 | 4/4 plans correct on run 1; re-fly |
| **Total** | | | **30** | **42** | |

### Completion

```
runs flown and landed:   30 / 30      (100%)
plans correct:           21 / 21 scored, + 6 M09 and 12 M10 drone-plans
altitudes verified:      30 / 30      within 0.13 m of the commanded height

single-drone (M01-M08):  24 / 24      COMPLETE, re-flown 2026-10-06
M09 (two drones):         3 /  3      COMPLETE
M10 (four drones):        3 /  3      flown; see the caveat below
```

> ### Caveat on collision and proximity, 2026-10-06
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
> Also open: M10's Drone3 climbs **14.6 m** during its backward leg, three runs
> running, which is larger than the 6 m stagger that is its only separation.
> This was first attributed to `fly_backward` and that is **withdrawn**: on one
> drone a backward leg drifts +1.24 m against a forward leg's +1.40 m, so the
> 14.6 m belongs to the four-drone context and the cause is unknown. See the
> phase log.

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

**Remaining: 6 runs** — M09 (two drones) and M10 (four).

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

Everything on disk, with a verdict. Twelve sessions, 43 recorded runs, of which
**none currently carry valid execution data**. Planning data from the five 70B
sessions stands.

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
| `20261006-184158-v2-M10` | 70b | 1 | **diagnostic** — the run that exposed the altitude defect |

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
| **2** — Repository architecture | Baseline examples run through the modular structure unchanged | A refactor plus a demonstration that behaviour is unchanged. No scored runs |
| **3** — Flight-skill layer | Four drones take off, navigate, hold, return, land, each skill returning a structured result | Flights, but a capability demonstration rather than a scored matrix |

> **Phase 3's exit criterion names four drones**, and on the evidence of M09 it
> is not blocked: multi-drone flight works when the extra drones are spawned at
> runtime rather than declared in `settings.json`. M10 tests that for four.
> The declared-roster defect remains real and unfixed, but it only bites if the
> roster is changed — which nothing now needs to do.

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
| Planning latency | 34.9 s first call, then **0.7–1.8 s** by mission |
| Flight times | M02 38 s · M05 43 s · M04 44 s · M03 48 s · M08 51 s — no variance within a mission |

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
