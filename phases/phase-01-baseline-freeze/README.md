# Phase 1 — Freeze and document the baseline

**Stage:** 0 · Foundations · **Vault note:** `AUV-02 — Baseline Freeze`
**Started:** 2026-09-18 · **Completed:** —

> Preserve an open-loop system as an experimental constant. You cannot show you
> improved something you did not first pin down.

---

## Objectives

- [ ] **1.1** Tag the baseline release — `v0.1-open-loop-baseline`
- [x] **1.2** Record the exact environment — OS, Python, simulator, models, packages, settings, startup procedure
- [x] 📄 `requirements.txt`, `environment.yml`, [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md)
- [x] **1.0** Write the open-loop agent — *added 2026-09-24, see the record below*
- [ ] **1.3** Run the ten-mission baseline set and record the results
- [ ] ✅ **Exit criterion** — see below

## Exit criterion

> A new student can clone the repository, follow the documentation, and
> reproduce the baseline flights **without help from the original developer.**

**Met:** no. Untested — and it cannot be self-certified. It needs either a real
second person, or at minimum a clean-clone dry run performed using nothing
outside the clone.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Open-loop agent | [`baseline/open_loop_agent.py`](../../baseline/open_loop_agent.py) | Written; planner and single-drone flight verified (M01, M02). Multi-drone unflown |
| Baseline tag | `v0.1-open-loop-baseline` | Pending — tagged once the agent runs the mission set |
| Environment record | [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md) | v1.0, §9 rewritten 2026-09-24 |
| Mission set | [`docs/BASELINE_MISSIONS.md`](../../docs/BASELINE_MISSIONS.md) | Defined; **results empty** |
| Package manifests | `requirements.txt`, `environment.yml` | Done |
| Run data | [`results/`](results/) | Empty |

## Record

### 2026-09-18 — environment and mission set documented

Environment captured by reading the machine rather than transcribing
documentation: hardware, OS, Python 3.10.21, CarlaAir v0.1.7 with archive
SHA-256, AirSim settings and hash, 43 pinned packages, Ollama models with
manifest and weight digests.

Ten missions defined (M01–M10) spanning simple movement, multi-step movement,
return-and-land, repetition, altitude change, ambiguous wording, and two- and
four-drone simultaneous flight. Protocol: three runs per mission,
`llama3.2:3b` primary at `temperature 0`, Town10HD, no traffic.

### 2026-09-24 — baseline frozen into its own repository

The tag existed in an external repository but **did not match the documented
baseline**. Three changes lived only as uncommitted working-tree edits: the
OneDrive Documents-path fix, the frozen Ollama options, and the multi-drone
spawn spacing. The frozen options *are* the measurement protocol, so the
documented system and the tagged system were not the same thing.

Resolved by creating this repository and tagging the baseline here.

### 2026-09-24 — decision reversed: write our own agent

The external code carried **no licence**, so default copyright applied: no right
to redistribute, no right to create derivative works. Vendoring it made Phase 20
— which publishes a public artifact — dependent on a licence grant that had not
been sought and might never be given.

**The project chose to reimplement rather than ask.** All external code was
purged from this repository's history, not merely deleted going forward, so no
commit contains it. The tag `v0.1-open-loop-baseline` was dropped with it: after
the purge it named a commit containing no baseline at all, which would have been
a lie in the record. It returns when there is a baseline to name.

This adds implementation work (objective 1.0) before 1.3 can run. It buys an
artifact that is wholly ours to licence, and it removes a publication blocker
that would otherwise have surfaced at the worst possible moment.

Carried across as specification, not code: the eight-action vocabulary, the
open-loop property, the JSON-schema finding, and the NED and known-folder
behaviours — facts and APIs rather than anyone's expression of them. Prior
published benchmark figures stay in `BASELINE_MISSIONS.md` as attributed
citations.

Removed with it: `tools/apply_logging.py`, which existed only to patch logging
into someone else's script. The new agent logs natively, so measurement is not
an opt-in step that can be forgotten.

### 2026-09-24 — agent written, planner verified without the simulator

`baseline/open_loop_agent.py` written from the specification in §9 of
`BASELINE_ENVIRONMENT.md`. Structure: schema-constrained planning → validation →
concurrent execution, one thread per drone, no replanning.

Choices worth recording:

- **`--plan-only`** plans and validates without touching AirSim, so the planner
  can be exercised without occupying the GPU. Every result below was obtained
  that way.
- **Nothing arms until every plan validates.** A half-flown mission is harder to
  interpret than one that never started.
- **Validation covers what the schema cannot**: parameters present for the
  action that needs them, positive durations under a 60 s leg limit, altitudes
  within a floor and ceiling.
- **A positive `z` is normalised, not obeyed, and the normalisation is logged.**
  In NED a positive z flies into the ground. Silently correcting it would hide a
  real model failure mode, so the correction appears in the record.
- **Logging is native**, one JSON object per planning call in
  `runs/agent-log.jsonl`: instruction, raw output, validated plan, model,
  `plan_seconds`, validity, and any normalisation.

**A flaw I introduced and then removed.** The first draft's worked examples
included `"before flying forward for 5 seconds, hover in place for 2 seconds"` —
which is **M07 verbatim** — and a close paraphrase of M03. Either would have made
those missions score correct because they sat in the prompt, not because the
model solved them. Examples were replaced with phrasings absent from the mission
set, and the affected missions re-planned. They still came out correct, so the
result stands — but it would not have been a result before the fix.

First planner pass, `llama3.2:3b`, one run each, uncontaminated prompt:

| Mission | Plan produced | Expected | Latency |
|---|---|---|---|
| M01 | `fly_straight` | ✔ | 1.1 s |
| M02 | `hover, land` | ✔ | 1.2 s |
| M03 | `set_altitude, fly_straight, land` | ✔ | 3.0 s |
| M04 | `fly_straight, fly_to, land` | ✔ | 2.2 s |
| M05 | `fly_straight, fly_straight` | ✔ | 1.7 s |
| M06 | `hover, hover, hover` | ✔ | 2.1 s |
| M07 | `hover, fly_straight` | ✔ | 1.7 s |
| M08 | `set_altitude, hover, fly_to, land` | unscored | 3.1 s |

**This is not 1.3.** These are single planning passes with no flight, no
repetition and no execution check; the protocol requires three runs per mission
with execution. They are recorded as an early signal that the planner works, and
because M05 and M07 are the two the prior project reported its model failing
(0/3 and 1/3). That comparison is **not like-for-like** — different model,
different prompt, different schema — and must not be reported as a replication.

### 2026-09-28 — first flight: M01 flew, then fell out of the sky

First execution against the live simulator, Town10HD at default quality with
traffic running (not the protocol's `--no-traffic --quality Low`; this was an
executor test, not a scored run).

**What worked.** Planning produced `fly_straight` in 13.4 s (cold, model
loading). The drone armed, took off, climbed to cruise, and flew its forward
leg. The executor's arm → takeoff → step path is sound.

**What failed.** At the end of the plan the aircraft **dropped out of the air**.

M01 has no `land` step, so the plan correctly ended with the drone hovering at
roughly 8 m. Teardown then ran `armDisarm(False)` unconditionally, which cuts
the motors. The code even commented that hovering was "the safe end state" two
lines above the call that made it unsafe.

This is exactly the class of defect `--plan-only` cannot find: every planner
run had been correct, and the mistake was in the last four lines of execution.

**Fix.** Teardown now checks whether the vehicle is above its arming height and
lands it before releasing control (`_is_airborne`, `_land_and_release`). If the
state cannot be read it assumes airborne, because an unnecessary landing is
harmless and a skipped one is not. A failed teardown landing is reported but
still proceeds to release control — leaving a vehicle armed and under API
control is worse than an ungraceful landing.

**The landing is teardown, not a plan step.** It is not scored and does not
appear in the plan record: the plan is what the model produced, and getting the
aircraft down afterwards is the harness's job. Keeping those separate matters
for 1.3, where "did the plan execute" must not be contaminated by cleanup.

Not yet re-verified in flight — the fix needs an M01 re-run, then M02, which is
the first real exercise of the landing path.

### 2026-09-28 — the agent's settings.json killed the simulator

After the first flight, every subsequent launch died during startup: the
process started, reached ~750 MB resident, and exited before opening its ports.
**No error dialog, no log, no crash dump, and no entry in the Windows event
log.** From the outside it looked like a broken install.

The timing was the clue. The 19:54 launch was healthy; the agent ran at 19:55
and rewrote `settings.json`; every launch after that failed.

**A/B, run twice each way:**

| `settings.json` | Result |
|---|---|
| Shipped `AirSimConfig/settings.json` | both ports up in 5 s |
| Written by `write_settings()` | process dead in 10 s |
| Written by the fixed `build_settings()` | both ports up in 5 s |

**Cause.** The generated file carried vehicle-level `"X"`, `"Y"` and `"Z"`
keys, which the shipped template does not. `"Z": 0.0` is **world origin height
in NED, not ground level**, so the vehicle was being placed inside the terrain.
AirSim did not report this; the simulator simply stopped.

The failing file is kept at
[`evidence/settings-that-killed-the-simulator.json`](evidence/settings-that-killed-the-simulator.json).

**Fix.** `build_settings()` now mirrors the shipped template: no vehicle-level
`Z` or `Y`, both shipped cameras with their offsets and FOV verbatim, and `X`
emitted only from the second drone onwards — purely as spawn spacing, since
nothing in this stack avoids collisions.

Split out as a pure function so it can be tested without writing into the
Documents folder, and covered by `tests/test_settings.py`: no vehicle-level Z
or Y, first drone unoffset, later drones spaced, both cameras present with
their offsets. Those tests cannot prove the simulator will start — only a
launch does that — but they pin the exact mistake that caused this.

**Worth remembering for later phases:** AirSim's failure mode for a
configuration it dislikes is *silent exit during startup*. Anything that
generates `settings.json` — Phase 4's scenario configs especially — should be
A/B tested against a known-good file rather than trusted because it looks
reasonable.

### 2026-09-28 — M01 flown clean, both fixes verified in flight

Re-run of M01 after the teardown and settings fixes, recorded on screen.

| | |
|---|---|
| Mission | M01 — `fly forward for 5 seconds` |
| Model | `llama3.2:3b`, plan `fly_straight` in 14.18 s (cold) |
| Map | Town10HD, Epic quality |
| Recording | `20260928-2018_phase01_M01_llama3.2-3b_Town10HD_run01.mp4` |
| Outcome | **As expected throughout** |

The drone armed, took off, climbed to cruise, flew its forward leg, held
position, then **descended under control and settled** before control was
released. No drop.

That verifies both defects found earlier today:

* **teardown disarming mid-air** — the aircraft now lands before control is
  released, and the landing is visible in the recording;
* **`settings.json` killing the simulator** — the run launched and completed
  normally on a file written by the fixed `build_settings()`.

Neither fix could have been confirmed without flying. The planner had been
correct in every run while both defects were live.

#### Recording convention

```
YYYYMMDD-HHMM_phaseNN_MISSION_model_map_runNN.mp4
```

Timestamp first so captures sort chronologically, then the context needed to
identify a clip without opening it. No spaces or colons, so it is safe to quote
in a shell and on any filesystem. **The outcome is deliberately not in the
filename** — it belongs here, where it can be corrected without renaming a file
that other documents already cite.

Recordings live outside the repository. Video has no place in version control:
this one clip is 64 MB, and a full mission set would be gigabytes in history
that can never be removed.

### 2026-09-28 — M02 flown, scripted flight enabled, teardown refined

M02 (`hover for 3 seconds then land`) flown against the live simulator. Plan
`hover, land` in 1.7 s warm; both steps executed; final state confirmed over
the API as `z = 29.25` — exactly the arming height — with `landed_state =
Landed`. The **planned** landing path works, which matters in a build with no
terrain collision, where landing depends entirely on the ground height recorded
at arm time.

**Scripted flight.** Flying 8 missions × 3 repeats by hand means 24 sessions of
pressing Enter, which is both tedious and a source of inconsistency. `--yes`
skips the interactive gates for scripted runs.

It deliberately does **not** skip the settings-changed gate: if `settings.json`
no longer matches the running simulator, the roster on disk is wrong and flying
on would address vehicles that do not exist. A scripted run stops there and
tells its caller to restart the simulator.

**Execution logging.** `fly()` now returns an execution record — planned steps,
executed steps, completion, failure, flight seconds, ground height — appended
to `runs/agent-log.jsonl` tagged `"kind": "execution"`. Kept separate from the
planning record because a plan exists even when nothing flies, and a correct
plan can still fail in flight. 1.3 has to report both.

**A redundant landing, found and removed.** With execution working, M02 landed
**twice**: once from the plan, once from teardown. `landAsync` returns before
AirSim updates `landed_state`, so checking vehicle state immediately afterwards
reports "flying" for an aircraft that is already descending. Both a height
heuristic and the `landed_state` field failed this way.

Fixed by trusting the plan instead of polling the vehicle: if the last executed
step was a successful `land`, teardown skips its own. Verified both directions
in flight — M02 lands once, M01 (which ends airborne) still gets its teardown
landing.

Timing-dependent state checks are worth distrusting generally here; this is the
second time a plausible one has been wrong.

### 2026-09-28 — mission-by-mission flight harness

1.3 needs each mission flown, repeated, and recorded in a form that survives
the session. The pieces that were missing:

**Collision and proximity capture.** Section 1.3 requires "collision or
proximity events" and nothing recorded them. Collisions now come from
`simGetCollisionInfo`; proximity from a `SeparationMonitor` that samples
inter-drone distance at 4 Hz during flight and keeps the closest approach and
when it happened. Closest approach is invisible from start and end states, so
it has to be watched while flying.

Two corrections the first live capture forced:

* **Every landing registers a terrain collision.** The first capture returned
  `Town10HD_Terrain_Ground_64` at zero penetration depth — a drone sitting
  correctly on the ground. Ground contact is now classified separately, or the
  metric would read "collision" on every successful mission. Note this also
  contradicts the manual's claim that the build has no terrain collision.
* **AirSim keeps the last collision across flights.** The raw flag says nothing
  about *this* run, so the timestamp at arm time is the baseline and
  `new_this_flight` is derived from it.

**Reset between runs.** Each flight previously began where the last one ended —
M01 flies 25 m and lands there, so the next mission armed from different ground.
Observed drifting 29.25 → 27.27. `reset_world()` now restores the start pose
before every run. Verified over three repeats of M02: ground height 10.95,
10.59, 10.97 (0.4 m of settling noise) and flight time 21.2, 21.0, 21.2 s.
Without it, three "repeats" were three different experiments.

**One flight path, not two.** `fly_plans()` is extracted into the agent and used
by both the interactive script and the runner. Had they diverged, a scored run
and a hand-flown run would not have been the same procedure.

**`scripts/run_missions.py` now flies.** Per run it resets, plans, flies, scores
and appends to JSONL immediately — a hang three hours into a set must not cost
the runs already completed. `--pause` waits between runs for watching each one.
It refuses to start when the roster in `settings.json` does not match what the
missions need, and refuses a mixed set outright, because changing the roster
requires a simulator restart it cannot perform.

Verified end to end on M02: planned, reset, flown, scored, logged — plan
`hover, land` executed, 21 s, no collision, no ground contact flagged.

### 2026-09-28 — protocol changed: Epic quality, traffic on

The mission protocol, written 2026-09-18, specified
`.\CarlaAir.ps1 Town10HD --no-traffic --quality Low` with the stated reason
that traffic is a confound and Low quality frees GPU. The flights run so far
were at Epic, 1080p, no traffic — so the config no longer described what the
project actually did.

**Decision: change the protocol rather than the practice.** The study measures
this platform, and the platform is used with traffic at full quality. Results
recorded under a protocol nobody follows are the quiet kind of wrong.

Nothing had been measured under the old protocol, so no result is invalidated.
The old values and the reason for the change are recorded in the config and in
`BASELINE_MISSIONS.md` rather than deleted.

**What this accepts, stated plainly:**

* **Traffic adds variance** that has nothing to do with whether a plan
  executed — vehicles and pedestrians move, contend for GPU, and change frame
  timing run to run. That was the original author's point and it remains true.
* **VRAM is at the limit.** Town10HD at Epic and 1080p measured 3827 MiB of
  4096 MiB, so texture streaming is already dropping detail, and traffic adds
  to it.
* **An open question worth watching:** whether flight timing moves with frame
  rate. AirSim's physics advances with the Unreal tick, so a heavier scene
  could lengthen wall-clock flights even if simulated durations hold. The M02
  repeats measured 21.2 / 21.0 / 21.2 s without traffic — that is the baseline
  to compare against once traffic is running. If flight seconds move, suspect
  this first.

### 2026-09-28 — Block A: the eight single-drone missions flown, 3 repeats each

Town10HD, Epic, 1080p, traffic on — the protocol as revised earlier the same
day. 24 runs. Raw data in
[`results/baseline_v1-llama3.2_3b-20260928-212436-blockA-M01-M08.jsonl`](results/baseline_v1-llama3.2_3b-20260928-212436-blockA-M01-M08.jsonl),
summary beside it.

**21/21 scored runs correct. 24/24 executed to completion. Zero collisions.**

| | M01 | M02 | M03 | M04 | M05 | M06 | M07 | M08 |
|---|---|---|---|---|---|---|---|---|
| Correct | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | — |
| Flight s | 25.3 | 21.2 | 31.0 | 31.2 | 26.3 | 24.2 | 27.0 | 29.3 |
| Plan s | 1.2 | 1.4 | 2.5 | 2.8 | 2.1 | 2.6 | 2.2 | 3.3 |

#### The frame-rate question is answered, for one drone

Changing the protocol to Epic with traffic accepted a risk: AirSim physics
advances with the Unreal tick, so a heavier scene might stretch flights. It did
not. Every mission repeated within ~0.1 s, and M02 measured 21.2/21.2/21.2 s
with traffic against 21.2/21.0/21.2 s without it.

That closes the question for single-drone flight. It says nothing yet about four
drones, where the scene is heavier still.

#### M08 produced a real ambiguity failure

All three runs read *"go up a bit, look around for a moment, then come back down
safely"* as climb to 10 m, hover, **climb to 20 m**, land. In NED −20 is higher
than −10, so "come back down" became a climb; the landing rescued the mission.
Consistency 2/3 — attempt 1 used `fly_to(0,0,-20)` where the others used
`set_altitude(-20)`.

M08 is the only mission touching H4's ambiguity clause, and it has produced a
concrete, repeatable failure rather than a vague one. Worth keeping in mind when
that hypothesis is tested properly in the perturbation sub-experiment.

#### M05 and M07 both passed 3/3

These are the two the prior project reported its model failing — 0/3 on
repetition, 1/3 on instruction reordering. **This is not a replication**:
different model, different prompt, different schema. What it does show is that a
3B model with a constrained schema handles both reliably here, which is the
finding that matters for running this study on available hardware.

#### One anomaly worth watching

M07 attempt 2 armed at `ground_z 9.14` where the other runs armed at 10.87 and
10.95 — 1.8 m higher, no collision recorded, normal flight. The likely cause is
the reset placing the drone on or beside a traffic vehicle, which is exactly the
confound the original protocol avoided by turning traffic off. If it recurs, the
fix is a spawn-clearance check before arming.

#### A scoring artifact, fixed

The first summary reported **12 extra steps** for M08 — an artifact of comparing
four sensible actions against an empty `expected` list. Unscoreable missions now
report `—` for both correctness and extra steps, and the Block A summary was
regenerated from the same raw data rather than re-flown.

### 2026-09-28 — multi-drone: two platform defects, both found by flying

Getting M09 airborne exposed two problems. Neither was visible from planning,
and one was a genuine safety issue.

#### No more roster edits: drones are spawned at runtime

`settings.json` is read only at process start, so adding a drone meant editing
it and restarting the simulator — once per mission block. That was accepted as
a platform constraint. **It is not one.** `simAddVehicle` adds a vehicle to a
running simulator, and it is documented in this project's own reference set
(`docs/carlaair/04-actors-and-traffic.md`), which was not checked before the
roster workflow was built.

`ensure_vehicles()` now creates whatever a mission needs against whatever is
running. Verified: a simulator booted with one drone flew a two-drone mission.
`reset()` does not remove runtime vehicles, which matters because the runner
resets before every run.

Two properties, both acceptable here: runtime drones get **no cameras** (this
agent never reads an image), and they **do not persist** across a restart (they
are simply re-added). `settings.json` keeps a narrower role — a persistent
fleet with cameras, via `tools/write_roster.py`.

#### One AirSim client cannot be shared across threads

The open question from `docs/carlaair/00-architecture.md` is answered, and the
answer is no. The first two-drone flight failed on both drones at once:

```
[Drone1] FAILED: RuntimeError: IOLoop is already running
[Drone2] FAILED: BufferError: Existing exports of data: object cannot be re-sized
```

`msgpack-rpc` multiplexes a single socket over a tornado IOLoop that is not
thread-safe. Neither drone left the ground. Each `DroneRunner` thread now opens
its own connection, and the separation monitor has its own as well. Connections
are cheap; sharing them is not.

This is why the single-drone work never caught it — one thread, one client, no
contention.

#### simAddVehicle ignores the pose it is given

The second two-drone flight flew, and reported a **closest approach of 0.08 m**.
Eight centimetres, between drones cruising at 25 m and 12 m.

Cause: `simAddVehicle` accepts a pose and discards it. Measured directly —
asked for `x=12`, the vehicle appeared at `x=0`. **Every runtime-spawned drone
appears at the player start, stacked on whatever is already there.** With no
collision avoidance anywhere in this stack, four drones would have occupied one
point.

Fixed by placing each drone explicitly with `simSetVehiclePose` after spawning,
then **verifying** the result and refusing to fly if any drone is more than a
metre from its slot. A silent failure here puts aircraft on top of each other,
so it fails loudly instead.

Re-flown: layout `Drone1(0,0) Drone2(4,0)`, both drones executed their own
four-step plans concurrently, closest approach **4.0 m at t+0.0s** — the spawn
spacing, on the ground, before either took off. Exactly as intended.

**The proximity measurement earned its keep on its first real use.** Without
it, that 0.08 m flight would have been recorded as a success: both plans
correct, both executed, no collision reported.

### 2026-09-28 — every series now archives the code that flew it

A result is only evidence if you can say which code produced it. A git SHA
alone does not: development happens with a dirty tree, and **most flights in
this project were flown from uncommitted work** — including all of Block A.

Each series now writes `<stem>-code/` beside its data, holding the exact
`open_loop_agent.py`, `run_missions.py` and mission config that ran, plus a
`manifest.json` with the commit, a dirty-tree flag, per-file digests and the
Python version. Every row in the JSONL carries the same manifest, so a single
run can be traced to its code without opening anything else.

One snapshot per series rather than per run, because every run in a series is
flown by the same code and the per-row digests prove it. Three small text files
against two dozen runs.

This is `AUV-14` §14.2 — the experiment manifest — arriving nine phases early,
because the question it answers is already live.

**Block A predates this**, so its 24 runs carry conditions but no code
snapshot. The agent has changed materially since (teardown landing, runtime
spawning, per-thread connections), so those runs cannot be reproduced exactly
from the current tree. That is an argument for re-flying Block A once the
harness settles, and the reason is now recorded rather than discovered later.

### 2026-09-29 — the drone was never landing, and every flight time is wrong

Reported as "it is still hovering in the air". It was, and it had been since the
first flight of this project.

**The chain.** `ensure_vehicles` places each drone at `z = 0.0`. Zero is the
world origin, not the ground: here the terrain sits at **z = +29.25**, so that
teleport lifted the drone 29 m and dropped it. It then slept 1.5 s. The fall
takes **4.4 s**, measured. So `arm()` ran while the drone was still falling —
and arming a falling drone does not let it finish falling. SimpleFlight
*catches* it:

```
after simSetVehiclePose(z=0) + 1.5 s   z = 12.17   still falling
  +0.5 s after arming                  z = 14.82
  +2.0 s after arming                  z = 13.00
  +5.0 s after arming                  z = 12.20   caught, held indefinitely
```

`arm()` recorded that mid-air hover as `ground_z`. Landing descends to
`ground_z - 1.0` and stops, so **every flight ended about 17 m above the
ground** and hung there until teardown.

**The first fix was wrong, and wrong in an instructive way.** Waiting for the
drone to stop moving before reading the ground *sounds* sufficient. It is not,
after arming: the drone genuinely is motionless, so the check reports
`settled = True` with complete confidence and a 17 m error. Three runs came
back `ground_z` 12.16, 12.26, 12.21, all flagged settled.

The order was the defect, not the waiting. An **unpowered** drone falls to the
ground and stops there; an armed one holds station wherever it happens to be.
So the settle now happens *before* `enableApiControl`, and only then does the
agent take control.

**Result.** Three M01 runs, `ground_z` = **29.25, 29.25, 29.25** — exact, zero
error, and the drone finishes at 0.00 m above the ground instead of 17 m up.

| | Before | After |
|---|---|---|
| `ground_z` recorded | 12.1 (17 m wrong) | **29.25 (exact)** |
| M01 flight time | 28.1 s | **42.2 s** |
| Ends the flight | ~17 m in the air | **on the ground** |

#### This invalidates Block A's execution data

Block A recorded `ground_z` of **10.87 to 11.02** across all 24 runs — the same
error, and the reason its flight times looked so stable is that every one of
them was cut short by a landing that stopped in mid air. M01 measured 25.3 s
there against **42.2 s** flown correctly.

What survives and what does not:

- **The plans survive.** Validity, exact-sequence correctness, extra steps,
  planning latency and raw model output are all model behaviour and never
  touched the simulator. 21/21 correct still stands, as does the M08 ambiguity
  finding.
- **The execution data does not.** Flight times, "executed to completion",
  collision counts and ground contact were all measured on flights that never
  landed. They have to be re-flown.

This also explains the very first symptom this project ever saw — *"the drone
took off and it flew straight and then shut off in mid air"* — recorded on
2026-09-28 and attributed then to teardown disarming. Teardown was a real bug
and the fix was right, but this was underneath it the whole time.

**A smaller finding, closed.** The drone spawns yawed **−45.59°**, which is the
slant visible in the viewport at startup, and it pitches 4.4° for about a second
while it falls. Neither survives takeoff: yaw reads 0.00° by the time the first
plan step runs, and M01 landed at y = 0.05, straight along world X. So
`_velocity`'s body-frame assumption holds in flight after all.

### 2026-10-06 — the study's model becomes llama3.3:70b on an H100

Until now the protocol named `llama3.2:3b`, chosen by necessity: this laptop
has 4 GB of VRAM and the simulator already owns ~93% of it, so inference ran on
CPU. Access to ERAU's Vega cluster changes that, and the study now runs on
**`llama3.3:70b`** on an **H100 with 80 GB**, reached from the laptop over an
SSH tunnel.

**The simulator does not move.** CarlaAir v0.1.7 is a Windows build needing a
display context, so it stays here. Only the model relocates, which the open-loop
baseline makes painless: planning happens before takeoff and the model is never
consulted again, so nothing latency-sensitive crosses the network.

Proven end to end on 2026-10-05: laptop to `gpu02`, 70B at **100% GPU**,
planning calls answered in **1.2–1.6 s warm** — the same as the 3B on this
laptop's CPU. A model twenty-three times larger, at no latency cost.

#### What this does to the existing results

| | |
|---|---|
| Block A (24 runs, `3b`) | superseded as the baseline; **kept** as the small-model column |
| `blockC` | never flown; it would have been a 3B series |
| The mission set | unchanged. Same ten missions, same scoring |

The 3B data is not discarded. "Is a 3-billion-parameter model viable for UAV
mission planning?" is a real question and nobody has published a 3B column — it
simply stops being the *baseline* and becomes a comparison point.

#### Two protocol values that now matter and did not before

**`num_gpu` is per request and machine-specific.** The config now says 999, all
layers on the GPU, which is right for the H100. On this laptop it must be
overridden to 0 with `--option num_gpu=0`, because the simulator owns the VRAM.
Sending 0 to the cluster would make the server reload a 42 GB model onto CPU
cores — the whole point, silently undone.

**`num_ctx` was never pinned, and should have been.** Left unset, Ollama uses
the model's own maximum. For `llama3.3` that is 131072, whose KV cache on a 70B
is about 43 GB on top of 42 GB of weights: 86 GB, too large for an 80 GB card,
so it loaded **67%/33% CPU/GPU**. Pinned to 4096 it reports 43 GB and **100%
GPU**. It also stops the value depending on each machine's Ollama version,
which it silently did before.

Both are now recorded per run rather than assumed, along with the endpoint that
answered — a model name alone does not say where it ran.

### 2026-10-06 — M09 was never blocked, and the drones were never oscillating

Two things recorded as problems turned out not to be, and both were recorded
without being retested. Worth writing down as much for the method as for the
facts.

#### The multi-drone defect is narrower than recorded

M09 and M10 were marked blocked by the spawn defect. **The defect affects
declared rosters, not multi-drone flight.**

A drone named in `settings.json` is created at simulator start, falls, and
settles on top of the other — and a drone resting inside another cannot be
repositioned, which was established as a matrix of five conditions on
2026-09-28. A drone added at runtime with `simAddVehicle` is placed **while
still falling**, never becomes pinned, and the single `simSetVehiclePose`
succeeds.

On 2026-09-28 the roster had been set to two drones for the camera-viewer
experiment. When that was reverted the roster returned to one, and the defect
went with it — but the "blocked" status was carried forward anyway.

**No placement code was changed.** `git diff ecd39af HEAD` shows zero changes
to `ensure_vehicles`, `simAddVehicle`, `simSetVehiclePose` or `SPACING`.
Measured: placement succeeded **5/5 trials** at 4.02 m, and M09 then flew
**6/6 drone-plans correct across two sessions**, separation never below spawn
spacing across 208 samples per run.

This also unblocks **Phase 3**, whose exit criterion names four drones. The
declared-roster defect is real and unfixed, but it only bites if the roster is
changed, and nothing now needs to.

> The lesson is the project's own rule, broken by me: fly it, do not assert it.
> A status carried forward from a configuration that had already been undone
> would have stopped someone attempting a whole phase.

#### The oscillation was the viewport, not the aircraft

The drones appeared to oscillate continuously while climbing and descending.
Measured three ways:

| Measurement | Result |
|---|---|
| Single drone, ~1,300 Hz, holding | **0 reversals** in 16,500 samples, 2.5 cm range over 8 s |
| Single drone, ~1,300 Hz, climbing | **0 reversals** in 5,137 samples |
| Two drones during M09, 10 Hz, 230 s | **0 reversals** across **72 hold segments**; mean drift **1.5–1.8 cm** |

The reversals in the trace are mission events: three of ~10 m are
`reset_world` dropping the drone between runs, and the 0.83–0.86 m ones
immediately after are the landing bounce. Both drones show them at identical
timestamps, which is what mission events look like and instability does not.

**What is real** is a transient at every altitude change: a **1.4 m wrong-way
excursion** as the controller reverses the vertical velocity it already has,
then a **1.5 m overshoot** with one bounce on arrival, settling in 2–3 seconds.
Repeatable, so a characteristic rather than a fault, and well inside the 6 m
altitude stagger M10 uses.

The apparent continuous bobbing is frame rate. The laptop GPU sits at
**3765/4096 MiB and 100% utilisation** rendering Town10HD at Epic with 30
vehicles and 50 walkers. Smooth motion at a low, uneven frame rate reads as
oscillation, most strongly on vertical movement where the eye has no horizontal
reference. That GPU load is in the protocol deliberately, and the physics is
unaffected — flight times repeat within 0.3 s and separation held at exactly
4.02 m.

### 2026-10-06 — every altitude ever flown was 29 m too high

Found by flying M10, the last three runs of Phase 1. Four drones, and the
mission failed in a way two drones never did: oscillation in the viewport,
collisions, and drones left hovering after the agent printed `control released`.
One run had to be killed by hand.

The cause is not multi-drone at all. **`moveToZAsync` targets are relative to
the map origin, and Town10HD's ground sits at NED z = +29.25.** So every
altitude command in this agent has been flying to *commanded + 29.25 m* since
the first flight. `land` was the only altitude call that was already correct,
because it alone used `self.ground_z` — which is why the error survived the
2026-09-29 landing fix untouched.

Measured directly, one drone, the plan `set_altitude -30 / fly_straight 5 / land`:

| Commanded | Intended | Before | After |
|---|---|---|---|
| `CRUISE_ALTITUDE = -8` | 8 m above ground | **37.51 m** | 8 m |
| `set_altitude z = -30` | 30 m | **59.65 m**, peak 60.85 | peak **32.06 m** |
| Flight time, same plan | — | 103.1 s (M10 Drone1) | **35.7 s** |

Ground was read as world z 29.25 in both frames: `simGetVehiclePose` and
`kinematics_estimated` agree exactly, so this is not the frame-divergence
problem — it is a missing ground reference.

What it did to M10 run 1:

- Contact between Drone1 and Drone3 at world z ≈ **−31**, which is Drone1
  sitting at its *actual* target of 59.65 m rather than the 30 m the
  instruction asked for. Penetration 0.115 m. Both drones report the same
  world point; their `impact_point` differs by exactly 8.00 m, Drone3's spawn
  offset, so `impact_point` is spawn-relative while kinematics is not.
- The contact is timestamped **t+14 s of flight** — during the climb, before
  `set_altitude` could have completed.
- Drone1's `land` then had to descend **60 m at 2 m/s**. It never arrived:
  `moveToZAsync` gave up against the collision contact, `landAsync` returned,
  control was released, and the drone stayed at 60 m with
  `completed: true`. `landed_on_ground: false` was the only field that caught
  it — a 103.1 s flight against 44–55 s for the other three.
- `SeparationMonitor` reported `min sep 4.0 m` at **t+15.9 s**, two seconds
  *after* the contact. That 4.0 m is the post-collision separation, not spawn
  spacing, and the monitor reported no proximity event for a collision the
  physics engine recorded.

**Fix:** three call sites anchored to the measured ground, the way `land`
already was — `take_off`'s climb to cruise, `set_altitude`, and `fly_to`'s z.
`arm()` sets `ground_z` before `take_off()` runs, so the ordering already
holds. A side effect: `MAX_ALTITUDE = -120`, commented "roughly the legal
ceiling", previously permitted 149 m AGL and now means 120 m.

**Consequence for the data.** The **execution** column of all 30 recorded runs
is invalid: flight times, ground contact, and the vertical staggering that is
M09's and M10's only separation were all measured 29.25 m above the commanded
regime. The **planning** results are untouched — 21/21 exact-sequence correct,
the M08 ambiguity finding, and every latency were produced before the simulator
was involved. This is the Block A split again, for the same kind of reason, and
re-flying costs about a minute a run.

**Two things remain unexplained**, and deliberately so rather than by
inference. Drone3 was at 60 m when even the broken frame puts its commanded
−18 at 47.65 m; and the separation monitor missed a real collision. Both need
an altitude trace across all four drones rather than one row of summary data,
and the fix moves the entire altitude regime (cruise 37.5 → 8 m, targets
59/53/47/41 → 30/24/18/12), so deriving them from pre-fix data would answer a
question that no longer applies.

### 2026-10-06 — control was being released in mid air again

The first re-flight after the altitude fix put a drone on the ground by dropping
it. Watched live: Drone1 fell from 22 m to the terrain in three seconds with
`api=False`. M01 run 2 of that block ended at **9.32 m AGL**,
`landed_on_ground: false`, after 15.9 s; run 1 of the same block landed cleanly
in 63.5 s. Same plan, same `ground_z`.

`_land_and_release`'s own docstring describes this exact failure from the first
real flight — *"M01 took off, flew its leg, held position, and then fell when
control was released"* — so it is a regression of a defect this harness was
written to prevent.

**Cause: `_is_airborne()` trusted AirSim's `LandedState`.** Measured with the
aircraft hovering at **29.43 m above the terrain**: `landed_state = 0`, which is
`Landed`. `_is_airborne` returns `landed_state != 0`, so teardown skipped the
landing and released control at altitude. The field is correct at rest on the
ground and correct during a climb, and wrong for a motionless hover — which is
precisely how a plan without a final `land` ends, because the harness issues
`hoverAsync` before teardown.

Fixed by making height authoritative and keeping `LandedState` only as a
tiebreak below the margin. The redundant-descent problem that motivated the
field is already handled by `skip_landing`, which the caller passes when the
plan's own last step was a successful `land`, so nothing is reintroduced.

#### Two further findings from the same investigation

**`arm()` can latch a ground reference 29 m in the air, and flag it settled.**
After `client.reset()` the aircraft is placed at the player start, about 29 m
above the terrain. Usually it falls, and the settle loop waits correctly — the
traced M01 shows the fall from 29.16 m to 0.00 m between t+3.9 s and t+9.4 s,
after which `ground_z` reads 29.25. But it does not always fall: observed
motionless at that height with zero velocity, where the settle loop sees
stillness on its first comparison and the agent printed **`armed, ground z =
-0.18`** with no `[DID NOT SETTLE]` flag. Stillness is not proof of ground
contact, and `ground_settled: true` in the records attests to nothing. A
controlled `landAsync` *is* deterministic — measured bringing the aircraft from
29.43 m to exactly 0.00 m AGL — and that was the intended fix until this file's
own 2026-09-29 note ruled it out: **this build has no terrain collision**, so
`landAsync` cannot wait for a touchdown and would descend through the ground
wherever no mesh happens to stop it. The clean landing measured above was at the
player start, where `SM_seaM` provides a surface; that does not generalise, and
arming first also hands SimpleFlight a falling aircraft to catch, which is the
2026-09-29 failure exactly.

So the flight behaviour is left alone and the **silence** is fixed instead. The
ground under a given drone is a session constant, because `reset_world` returns
every vehicle to the same pose. The first `arm()` for a drone records it; every
later one is checked against it, and a disagreement beyond 2 m raises
`GroundReferenceError` so the run is refused and recorded as a failure rather
than flown against a wrong ground. The plan is already recorded by then, so
nothing measurable is lost. Nine tests pin it, including the two historical
failures: a true 29.25 followed by `-0.18`, and the 2026-09-29 readings of
12.07/12.17/12.12 and Block A's 10.87–11.02.

Verified in flight, two M01 repeats establishing then checking the reference:
`ground_z 29.25` both times, `final x` 20.23 and 20.22, both landed at 1.21 m,
both 21.7 s. Identical repeats, which is what the altitude fix was for.

**The surface at the player start is not recognised as ground.** The aircraft
rests on `SM_seaM`, which lowercases to `sm_seam` and matches none of
`GROUND_OBJECTS = ("terrain", "ground", "landscape", "road", "sidewalk")`. So
the `landed_on_ground` contact fallback cannot fire at the spawn point — it
worked for M05 only because that mission ends over `Town10HD_Terrain_Ground`.
The flag therefore rests entirely on a height test against `ground_z`, with no
independent check, and a collision with that mesh would score as an *obstacle*
collision rather than ground contact. Left unchanged pending a decision on
whether to name a map-specific mesh in a general predicate.

#### What the altitude fix did, measured

Retracting a claim made earlier the same day: the altitude fix was reported here
as having broken horizontal flight, on the strength of two records showing
`final x = -0.05`. That was wrong. The velocity leg is unaffected by altitude —
**+14.32 m at 8 m AGL against +14.31 m at 37.5 m** — and a traced M01 through
the real runner flies correctly end to end: cruise settles at 8.30 m, the leg
carries x from 0.06 to 20.31 at 4.86 m/s, `final x = 20.23`, landed, **21.7 s**
against the pre-fix 42.2 s for the same 20.46 m of travel. Half the time for the
same mission, because the climb is 8 m rather than 37.5 m.

The two zero-displacement runs are real but **not reproducible** on this code
and no cause is claimed for them. Their block is kept as a diagnostic, and the
re-flight runs with a position trace attached so a recurrence is captured rather
than reconstructed.

### 2026-10-06 — M09 and M10 re-flown; two measurement defects found by the new fields

Phase 1 is flown: 30 runs, 42 drone-plans, altitudes correct to 0.13 m,
everything landed. The two fields added before these runs — the altitude each
step reached, and separation per pair — each caught something within three
flights of existing.

#### `fly_backward` climbs 14.6 m

M10's four drones are staggered 30/24/18/12 m, and all four reached their
commanded altitude to within 0.13 m. Then their velocity legs moved them:

| Drone | Direction | Asked | Reached | After the leg |
|---|---|---|---|---|
| Drone1 | forward | 30.0 | 30.11 | 32.43 (+2.3) |
| Drone2 | right | 24.0 | 24.13 | 25.96 (+1.8) |
| **Drone3** | **backward** | 18.0 | 18.12 | **32.74 (+14.6)** |
| Drone4 | left | 12.0 | 12.13 | 14.03 (+1.9) |

Consistent across all three runs: 32.74, 32.80, 33.53. Drone3 ends up inside
Drone1's 30.1–32.4 m band while flying backward along −x through where Drone1 is
holding, and a 6 m vertical stagger cannot survive a 14.6 m excursion.

> **Corrected later the same day.** This was read as `fly_backward` intrinsically
> climbing, and it is not: flown on one drone, a backward leg drifts **+1.24 m**
> against a forward leg's +1.40 m. The 14.6 m is real and reproducible but belongs
> to the four-drone context, not to the primitive. See the correction entry below;
> the paragraphs that follow here are superseded by it.

This also settles the question left open earlier today. Drone3 was measured at
roughly 60 m in the pre-fix M10 when even the broken altitude frame put its
commanded −18 at 47.65 m, and no cause was claimed. 47.65 + 14.6 ≈ 62 m. The
excursion was always there; it was invisible because nothing recorded the
altitude a step reached.

Cause: `_velocity` passes `vz = 0.0` to `moveByVelocityBodyFrameAsync`, which
commands zero vertical *velocity* and holds no altitude, so the error is whatever
the controller's attitude leaves behind — and backward flight pitches the
airframe the opposite way, giving a much larger one. The fix is
`moveByVelocityZBodyFrameAsync`, which takes a z to hold. Not applied yet: it
changes how every leg in the study is flown, so it belongs at the start of a
block rather than the end of one.

#### A collision can only be seen if the flight fails to land

All three M10 runs record `collision: false`. The physics engine disagrees: a
position trace polling `simGetCollisionInfo` at 10 Hz caught Drone1 and Drone3 in
contact in two of the three runs, with penetration up to **0.152 m**, about 14 s
into each flight.

`collisions()` is read **once, after teardown**, and AirSim returns only the most
recent collision. Every flight that lands ends touching the ground, and that
contact overwrites whatever happened earlier. So a successful flight can never
report a mid-flight collision, and the only reason the pre-fix M10 recorded this
same Drone1/Drone3 contact is that the flight never landed — nothing came after
it.

**Every "zero obstacle collisions" claim in this project is therefore unverified,
including the 24 single-drone runs flown earlier today.** Collisions need
polling, exactly as proximity does, and for the same reason: the end state does
not contain them. `SeparationMonitor` is the obvious place.

#### Still unexplained, and sharper than before

At the instant of that contact, both drones' world poses are **7.54 m apart** —
`per_pair_min_m` for Drone1–Drone3, timestamped 14.3 s, which matches the
collision. The frame explanation is ruled out: `simGetVehiclePose` and
`kinematics_estimated` were measured agreeing to 0.00 m on all four drones
simultaneously, in both x and z. The altitude data shows the two drones *were*
level with each other (32.4 and 32.74 m), so the 7.54 m is horizontal.

Two measurements that cannot both be right, and no claim about which. What is
new is that `impact_point` is reported in a spawn-relative frame while `position`
is not — the pre-fix M10 had the two drones reporting the same contact 8.00 m
apart, exactly Drone3's spawn offset — so any reconciliation has to start by not
mixing the two.

### 2026-10-06 — collisions are polled now; the altitude-hold fix failed

Two changes attempted. One works and is kept; one does not and was reverted.

#### Kept: `SeparationMonitor` polls collisions, and contacts are classified

Collisions are now read every 0.1 s during the flight, each distinct event once,
instead of once after teardown. Verified on M10 against a collision known to be
there: the poll caught **Drone1 and Drone3 in contact at t+17.03 s with 0.25 m of
penetration**, in the same run whose per-flight record says `collision: false`.
That is the defect reproduced and then made visible.

The monitor now also runs for **single-drone** missions. Proximity needs two
drones; collisions need one, and a single-drone mission was previously unpolled —
so the 24 single-drone runs flown earlier today cannot support a collision claim
either. It also always gets its own connection now, rather than sharing the
flight's client when there is one drone, which would have put a 10 Hz poll on the
same msgpack-rpc socket as the flight commands. That is this file's oldest open
question and not something to discover through a rare failure.

The first version of this counted **14 "obstacle collisions" in one clean M10
run**, which is worse than the silence it replaced. "Not ground" turned out to
mean four different things:

| Kind | Example observed | Counts against a flight? |
|---|---|---|
| ground | `Town10HD_Terrain_GroundNode_1088`, `SM_seaM` | no |
| drone | `Drone1`, `Drone3` | the thing M09/M10 measure |
| camera | `SpectatorPawn_2147444257` | no — an artifact of watching |
| obstacle | a building, vehicle, tree | **yes** |

`SM_seaM` is named as ground deliberately. It is what the aircraft rests on at
Town10HD's player start — measured sitting on it at 0.00 m AGL with the physics
engine reporting contact — so treating it as an obstacle would make every landing
a crash. Naming a map mesh in a general predicate is unlovely; the alternative is
worse. The spectator pawn is the free camera, which the drones genuinely collide
with: 0.14 m of penetration against it mid-mission, meaning nothing about flight.

Re-scored with those categories, that M10 run has **zero obstacle collisions, six
drone-contact events and seven ground contacts** — which is both true and useful,
where 14 was neither. Nine tests pin the classification against the exact names
observed.

#### Reverted: holding altitude with `moveByVelocityZBodyFrameAsync`

The obvious fix for the 14.6 m backward-leg climb is to fly the leg at a held z
rather than at vz = 0, so `_velocity` was changed to read the current z and pass
it to `moveByVelocityZBodyFrameAsync`.

**It did not work, and it broke landing.** Flown on M10:

- Drone3 still climbed about 13 m, reaching **31.42 m** against a commanded 18 —
  so the z was not held in any useful sense.
- The run then hung. Drone3 was left at 31.42 m with control still enabled,
  stuck in `land`; Drone1 was released at **31.18 m** and fell, at 16.4 m/s when
  sampled. The 38 s mission had not finished after five minutes and was killed.

Reverted to `moveByVelocityBodyFrameAsync` with vz = 0, which at least completes
and lands. The drift remains an open defect, documented at the call site so the
next attempt does not repeat this one. Whatever holds altitude through a backward
leg on this build, it is not that call used this way.

Worth noting what the landing failure says: Drone1's plan ended with a successful
`land` step, so teardown trusted it and skipped its own landing — `skip_landing`
is passed precisely then. The height-authoritative `_is_airborne` fix cannot help
there, because it is never consulted. A `land` step that returns without landing
defeats it, and that is the same shape as the original M10 failure.

### 2026-10-06 — correction: `fly_backward` does not intrinsically climb

Earlier today this log attributed M10's Drone1/Drone3 collision to `fly_backward`
climbing 14.6 m, and called the collision "a consequence of this, not of
multi-drone flight". **That explanation is withdrawn.** It was inferred from
four drones flying at once and never tested on one.

Measured directly, one drone, no model, the same 5 s leg from 18 m AGL — M10's
Drone3 — with each method flown back to back:

| Method | Drift | Travelled |
|---|---|---|
| A `moveByVelocityBodyFrameAsync` vz = 0 — what the agent flies | **+1.24 m** | 15.57 m |
| B `moveByVelocityZBodyFrameAsync` holding z | +0.40 m | 14.36 m |
| C `moveByVelocityAsync` world frame, vz = 0 | +1.83 m | 20.93 m |
| **D `moveByVelocityZAsync` world frame, holding z** | **+0.16 m** | **23.58 m** |
| E `moveToPositionAsync` 25 m back | +0.89 m | 26.62 m |
| F forward, for comparison | +1.40 m | 19.44 m |

**A backward leg drifts +1.24 m and a forward leg +1.40 m.** Backward is, if
anything, slightly better. The 14.6 m climb is real — it was recorded three times
in a row, 32.74, 32.80 and 33.53 against a commanded 18 — but it is **not a
property of the primitive**, so it belongs to the four-drone context and its
cause is unknown.

What changed between the two measurements is worth listing rather than guessing
between: four drones instead of one; four flight threads issuing commands
concurrently; a collision occurring during the same leg; and, in the agent but
not in this test, **no settle between `set_altitude` and the leg that follows
it** — `take_off` sleeps for `TAKEOFF_SETTLE` but `set_altitude` does not, so a
leg can begin while the aircraft is still moving vertically, and `vz = 0` does
not arrest momentum it inherits. That last one is testable and cheap, and is the
first thing to try.

This also reopens the collision. The claim that it followed from the climb is
gone, so the 7.54 m separation at the moment of a 0.25 m interpenetration is once
more entirely unexplained, with the frame explanation still ruled out by direct
measurement.

#### A better primitive, separately

Method **D** is better on both axes than what the agent flies: **+0.16 m of
drift against +1.24 m**, and **23.58 m travelled against 15.57 m** for a leg
asking for 25. Body-frame velocity under-travels badly — A reaches 62% of the
commanded distance — which has gone unnoticed because nothing ever scored
displacement either.

Not adopted today. It is a change to how every leg in the study is flown, it
moves from body frame to world frame (equivalent only because nothing in this
agent yaws, which the call site documents), and the last change made to this
function on the strength of a good argument hung the simulator. It belongs at the
start of a block, after the no-settle hypothesis is tested, not at the end of a
session.

### 2026-10-06 — M10 reproduces without the model, and the settle hypothesis is wrong

#### The settle hypothesis is insufficient

Recorded earlier today as the first thing to try: `set_altitude` has no settle
after it where `take_off` does, so a leg can begin while the aircraft is still
climbing, and `vz = 0` does not arrest inherited momentum. Tested on one drone,
same backward leg from 18 m:

| | vz at leg start | Drift |
|---|---|---|
| no settle | **−4.17 m/s** | +1.85 m |
| 3 s settle | −0.00 m/s | +1.06 m |

Real, and **0.8 m of the 14 m**. Inherited momentum is worth a metre at most, so
it is not the explanation. Kept as a small correctness improvement worth making
on its own merits, not as the fix.

#### M10 reproduces with four drones and no model

The same four-drone geometry flown through `fly_plans` with hand-built
`PlanRecord`s — no Ollama, no GPU, no tunnel:

```
Drone1 fly_straight   reached 30.11  after leg 32.71  drift  2.60  landed
Drone2 fly_right      reached 24.13  after leg 25.96  drift  1.83  landed
Drone3 fly_backward   reached 18.12  after leg 32.18  drift 14.06  landed
Drone4 fly_left       reached 12.13  after leg 14.03  drift  1.90  landed
Drone1<->Drone3 contact at t+17.01, penetration 0.075
per-pair min Drone1-Drone3: 7.54 m
```

Against the model-driven runs: Drone3 14.06 against 14.6, and the Drone1–Drone3
minimum **7.54 m against 7.54 and 7.55**, to the centimetre. **The defect is
deterministic and the language model has nothing to do with it.**

That matters more than it sounds. Every bisection from here — two drones instead
of four, Drone3 flying forward instead of backward, Drone1 removed — costs a
minute of simulator time and no cluster allocation at all. The investigation was
gated on a GPU job and is not any more.

#### The contradiction, stated precisely

Three numbers from one deterministic run that cannot all be true:

1. **Geometry says they separate.** Drone1 flies forward (+x) from x = 0;
   Drone3 flies backward (−x) from x = 8. They move *apart*. Four seconds into
   legs that start around t+13, Drone1 is near x = +16 and Drone3 near x = −8:
   roughly 24 m apart.
2. **The monitor says 7.54 m**, from `simGetVehiclePose` in the world frame,
   sampled at 10 Hz, timestamped 14.3 s.
3. **The physics engine says they are touching**, 0.075–0.25 m of
   interpenetration, at t+17.0.

No claim about which is wrong. What is ruled out by measurement:
`simGetVehiclePose` and `kinematics_estimated` agree to 0.00 m on all four drones
in x and z, so it is not that frame confusion; and `impact_point` is
spawn-relative while `position` is not, which is a trap rather than an
explanation.

Two cheap tests that would discriminate, neither run yet: log all four drones'
world x through the legs and see whether Drone1 and Drone3 ever occupy the same
point; and fly Drone3 forward instead of backward in the same four-drone layout,
to see whether the 14 m drift follows the *direction* or the *drone*.

### Pending — 1.3

Write the agent, then 24 scored runs plus M09/M10. Restore `settings.json` after
the multi-drone missions, or the single-drone missions become invalid.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-09-24 | New repository rather than building on the external clone | It is another author's repo with a published tag; a personal repo avoids rewriting anything of theirs |
| 2026-09-24 | **Reimplement the baseline; use no external agent code** | No licence means no right to redistribute or derive. Phase 20 publishes an artifact |
| 2026-09-24 | Purge history rather than delete going forward | History is published too; a deletion commit leaves the code retrievable |
| 2026-09-24 | Drop the tag until the agent exists | A tag named `open-loop-baseline` on a commit with no baseline is a false record |
| 2026-09-24 | Logging is built into the agent, not patched in | A measurement step that can be skipped will be skipped, and the fields cannot be reconstructed afterwards |
| 2026-09-24 | Commit email is the GitHub noreply address | Account blocks pushes exposing a private email; noreply keeps it private and still attributes |
| 2026-09-24 | Repository kept **private** for now | Publication is a Phase 20 decision, taken deliberately rather than by default |

## Open questions

- **One AirSim client shared across threads.** `DroneRunner` threads share a
  single `MultirotorClient`. `msgpack-rpc-python` multiplexes one socket and is
  not documented as thread-safe, so this is a plausible source of rare failures
  under multi-drone load. Settle it at the first M09/M10 flight test — either
  observe it working reliably, or give each thread its own client. Do not settle
  it by assertion either way.
- **Does CARLA synchronous mode gate AirSim physics?** Both plugins share one
  UE4 tick loop, so it plausibly does, but the two APIs have no shared notion of
  time and this has not been tested. It decides whether deterministic replay of
  *flight* is possible at all, which Phase 10 depends on. Test: world in
  synchronous mode, issue a velocity command, check whether the drone moves
  without `world.tick()`.
- **Absolute paths in the docs.** `SETUP.md` and `CONTROLS.md` quote this
  machine's paths (`D:\Research\...`, `D:\AllSetups\...`). A student on another
  machine meets them immediately, and the exit criterion is explicitly about
  someone else. Decide whether they become placeholders before the exit test.
- ~~**Which licence** this repository carries.~~ **Settled 2026-10-06: MIT**,
  held by the FICS Research Group, matching the parent repository. Possible only
  because the baseline was reimplemented — had the external code remained, the
  choice would not have been ours to make.
