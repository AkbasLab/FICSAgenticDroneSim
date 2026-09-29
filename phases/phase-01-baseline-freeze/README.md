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

### 2026-09-28 — a per-drone camera view, and what it revealed about cameras

M09 is the first mission where the drones do different things at the same time,
and one third-person viewport cannot show both. `tools/drone_view.py` pulls the
`front_center` image for each drone over the API and lays the tiles side by
side, captioned with name, X, Y and altitude.

Building it surfaced a constraint worth recording: **runtime-spawned drones
have no cameras.** `simAddVehicle` creates a flyable vehicle, which is why the
interactive drone count works at all, but it does not attach the `Cameras`
block that `settings.json` declares. A drone added at runtime can fly, be
posed, report state and collide; it cannot be seen from. So a mission that is
to be watched per drone needs its roster **declared before launch**:

    python tools/write_roster.py 2      # then restart the simulator

That is not a workaround being reintroduced. Flying N drones still needs no
roster edit; only *watching* them does. The distinction is now in
`docs/CONTROLS.md` §7 rather than in someone's memory.

The viewer is deliberately outside the experiment. It records nothing and
scores nothing, and the baseline agent never reads an image — it is blind by
design, which is the control condition. The one real cost is measured, not
waved away: a 1280×960 capture per drone per frame over RPC, on a machine
already at ~93% of 4 GB of VRAM, hence 5 fps by default rather than 30. If a
flight's timing moves when the viewer is running, that is a confound and the
viewer comes off, not the frame rate up.

**Considered and rejected:** AirSim's `SubWindows` settings key, which would
render sub-views inside the simulator window itself and cost no RPC. Our
`docs/carlaair/` reference set does not document it for this build, and an
untested settings key is exactly what killed the simulator silently a few days
ago. The documented `simGetImages` path was taken instead. `SubWindows` remains
worth testing later, deliberately and not on the eve of a scored run.

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

- ~~**One AirSim client shared across threads.**~~ **Settled 2026-09-28 by
  flying it.** Not a rare failure under load — it failed immediately and
  totally, `RuntimeError: IOLoop is already running` and `BufferError:
  Existing exports of data`, with neither drone leaving the ground. Each thread
  now opens its own connection. See the multi-drone entry above.
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
- **Which licence** this repository carries, now that it is free to choose one.
  Settled in `AUV-21` before Phase 20.
