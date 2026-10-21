# Phase 3 — Complete the deterministic flight-skill layer

**Stage:** 1 · Platform · **Vault note:** `AUV-04 — Flight Skills and the Mock Simulator`
**Started:** 2026-10-20 · **Completed:** 2026-10-21

> Give every later agent a reliable toolbox: eleven mission-level skills with
> formal contracts and structured results, heading and waypoint navigation, and
> a mock simulator to run them without CarlaAir. Until this exists, an agent
> can only print, never recognise that something failed and decide what next.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **3.1** Define high-level skills — `TAKE_OFF` `GO_TO_WAYPOINT` `FOLLOW_WAYPOINTS` `SEARCH_REGION` `INSPECT_POINT` `HOLD_POSITION` `RENDEZVOUS` `ACT_AS_RELAY` `RETURN_HOME` `LAND` `EMERGENCY_HOLD` *(step 3; relay and rendezvous geometric until Phases 7 and 9, as decided)*
- [x] **3.2** Add heading and waypoint navigation — turn to heading, 3D waypoint, waypoint list, cancel movement, stop and hold, reached-within-tolerance *(steps 1–3; turning and cancelling from a second connection checked live)*
- [x] **3.3** Give every skill a formal contract — parameters, preconditions, success, failure, timeout, abort behaviour, expected state change *(step 3; all seven clauses for all eleven, as data, checked by a test)*
- [x] **3.4** Add a lightweight mock simulator — `MockVehicleAdapter` for unit tests, communication testing, task-allocation testing, rapid debugging, CI *(step 4; held to the same contract as AirSim)*

## Exit criterion

> A deterministic script makes four drones take off, navigate to distinct
> waypoints, hold, return and land — and **each skill returns a structured
> result rather than merely printing output.**

**Met:** **yes, 2026-10-21** · **Evidence:**
[`evidence/exit-criterion-2026-10-21.md`](evidence/exit-criterion-2026-10-21.md).

The same script and plan, `scripts/four_drone_skills.py` at `5738760`, flown
twice: **live in CarlaAir by the user** — 20 of 20 skills succeeded, each a
structured `SkillResult`, closest approach 4.0 m, no drone contacts, every
drone landed at home, 46 s — and **on the mock**, with the same outcome in
36 s of simulated time. The mock run is also a test, on every run
(`tests/test_exit_script.py`). Before the live flight the live adapter
contract passed 14 of 14 in CarlaAir, including a move cancelled from a
second connection.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Primitives renamed `Primitive*`; turn, cancel and heading in the adapter | `agentic_uav/core/models.py`, `agentic_uav/simulator/` | **Done** 2026-10-20; Phase 2 goldens pass unedited |
| NED conversion, heading, tolerance, coverage paths; a clock | `agentic_uav/control/navigation.py`, `agentic_uav/core/clock.py` | **Done** 2026-10-20 |
| The eleven skills and their contracts | `agentic_uav/control/skills.py` | **Done** 2026-10-20 |
| `MockVehicleAdapter`, and one contract suite for every adapter | `agentic_uav/simulator/mock_adapter.py`, `tests/test_adapter_contract.py` | **Done** 2026-10-20 |
| The four-drone exit script | `scripts/four_drone_skills.py`, `agentic_uav/experiments/team_flight.py` | **Done** 2026-10-20; exit criterion met on the mock |
| Live flight of the exit script; close | [`results/`](results/), [`evidence/`](evidence/) | **Done** 2026-10-21; exit criterion met live |

## Plan

Approved 2026-10-20, with its three recommendations. Each step lands as its
own commit after the user's go-ahead, and the four Phase 2 goldens must pass
unedited after every step: Phase 3 adds a layer, it does not change the
baseline.

1. **Extend the adapter for 3.2.** Turn-to-heading and cancel as primitives,
   heading in the vehicle state. The primitives renamed `PrimitiveKind`,
   `PrimitiveCommand`, `PrimitiveResult`, and the adapter's `execute_skill`
   renamed `execute_primitive`, so the names AUV-04 gives the mission skills
   are free for them.
2. **Navigation and a clock.** Every NED sign conversion in one tested module
   (metres above ground in, NED z out); heading maths; the within-tolerance
   check; lawnmower paths for search regions. A clock with a real and a
   simulated implementation.
3. **The eleven skills and their contracts**, written once against the
   protocol, each returning AUV-04's four-state `SkillResult`.
4. **`MockVehicleAdapter`**: a constant-speed point mass in simulated time,
   with separation and collision checks and injectable faults. One contract
   test suite run against every adapter.
5. **The exit script**: four drones take off, go to distinct waypoints, hold,
   return and land, every `SkillResult` to JSONL; mock or AirSim by flag. The
   mock run becomes a test.
6. **Close**: the same script flown live in CarlaAir by the user, which also
   settles what only the real simulator can (whether `cancelLastTask` works
   from a second connection, whether a yaw command holds); the record, the
   vault report, the tag.

## Record

### 2026-10-20 — step 1: the adapter gains heading, turning and cancelling; the Phase 2 goldens pass unedited

**The rename.** The Phase 2 primitives became `PrimitiveKind`,
`PrimitiveCommand`, `PrimitiveResult`, and the adapter's `execute_skill`
became `execute_primitive`: 83 word-boundary replacements by script across
seven files (`core/models.py`, `core/__init__.py`, `control/executor.py`,
`simulator/adapter.py`, `simulator/airsim_adapter.py`, `tests/test_adapter.py`,
`tools/fly_chat.py`), counted per file. One overreach fixed by hand: the
adapter's docstring briefly claimed AUV-03 sketches `execute_primitive`; it
says `execute_skill`, and the docstring now says so and why. Docstrings that
said "skill" for a primitive now say primitive.

**The additions (3.2), none of which the baseline calls:**

| Addition | AirSim call | Notes |
|---|---|---|
| `VehicleState.yaw_deg` | none new — read from the same `getMultirotorState` | AirSim's convention: degrees, 0 = +x (north), positive towards +y (east), −180..180. `yaw_degrees(w, x, y, z)` is the yaw term of AirSim's own `to_eularian_angles` |
| `PrimitiveKind.ROTATE_TO_YAW`, `PrimitiveCommand.rotate_to_yaw(yaw_deg, timeout, margin_deg)` | `rotateToYawAsync(yaw, [timeout_sec], [margin], vehicle_name).join()` | omitted arguments left to AirSim's defaults (unbounded, 5°), as the baseline does for every other primitive |
| `VehicleAdapter.cancel(vehicle_id)` | `cancelLastTask(vehicle_name)` | does not brake: the caller follows with `stop`. Meant for another thread, on its own connection; whether CarlaAir honours that is checked live in step 6 |

Signatures checked against the installed `airsim` package's source
(`rotateToYawAsync(yaw, timeout_sec=3e+38, margin=5, vehicle_name='')`,
`cancelLastTask(vehicle_name='')`).

**The fake** (`tests/airsim_fake.py`) gained a heading per vehicle, a
yaw-only orientation quaternion in `getMultirotorState`, and
`rotateToYawAsync` and `cancelLastTask`, recorded with AirSim's defaults as
its other methods are. 17 methods now.

**Tests: 7 new, in `tests/test_adapter.py`.** The new calls' expectations
come from AirSim's API, since no baseline flight makes them; a test asserts
exactly that, over every recorded golden. The heading conversion is checked
against AirSim's own `to_eularian_angles` at seven orientations, with pitch
and roll present, including −45.59°, the spawn heading Phase 1 measured.

**Mutations:** heading sign flipped — caught by 2 tests (the read-back, and
six of the seven angles against AirSim); heading in radians — the same 2;
`cancel` a no-op — 1; the margin dropped from `rotate_to_yaw` — 1.

**The goldens did not move.** `record_golden.py --check` matches all four
after the rename and after the additions. 169 tests pass; audit clean.

### 2026-10-20 — step 2: navigation, and a clock with one shared simulated timeline

Two new modules, both pure enough to test without a simulator.

**`agentic_uav/control/navigation.py`** — the skill layer's only sign
handling, as AUV-04 asks. Above it, a mission speaks map metres and
**altitude above the ground, positive up**; below it, NED. Every conversion
takes the measured ground as an argument, because NED's zero is not the
ground (Town10HD's is z = +29.25) and the ground differs per drone (29.25,
29.28, 27.29 under M10's spawns).

| Name | What |
|---|---|
| `altitude_to_z(altitude_m, ground_z)`, `z_to_altitude` | the conversion; a negative altitude is refused |
| `Waypoint(x, y, altitude_m)` | the mission's point; no `z` field — the only way to NED is `to_position(ground_z)` |
| `horizontal_distance`, `distance`, `reached(current, target, tolerance_m, vertical_tolerance_m=None)` | 3.2's reached-within-tolerance, as a sphere or a cylinder |
| `normalise_heading`, `heading_to`, `heading_error` | AirSim's heading convention, (−180, 180], shortest signed turn |
| `standoff_point(target, origin, radius_m)` | where to stand to inspect a point |
| `Region`, `lawnmower(region, spacing_m, altitude_m)` | boustrophedon coverage of a rectangle; every point within `spacing/2` of a leg |
| `travel_time(distance_m, speed_mps)` | the floor for any timeout |

**`agentic_uav/core/clock.py`** — `Clock` (`now`, `sleep`), `RealClock`
(monotonic, for AirSim) and `SimClock`. The mock's drones will fly in their
own threads, as real flights do, and a separation check needs their positions
at one instant, so `SimClock` gives them one timeline: threads that fly
together enter `participate()`, a sleeping participant waits until every
participant sleeps, and time then jumps to the earliest wake-up. Time never
passes while a participant computes, so a run's simulated times do not depend
on the machine. Whether model thinking time should be charged to simulated
time (AUV-19's question) is left to Phase 12: this clock charges nothing
unless a caller sleeps for it.

**Tests: 34 new** (`tests/test_navigation.py` 21, `tests/test_clock.py` 13),
pinned to Phase 1's measured numbers (12 m → z 17.25, 30 m → z −0.75 over
29.25). The clock's shared timeline is checked with four threads of uneven
sleeps, 20 repeated runs giving identical wake times, a participant computing
in real time while another sleeps (simulated time stays at 0), and a
participant leaving.

One test of mine was wrong: a point placed "exactly" 0.5 m away
(10.3 − 10 is 0.3000000000000007) failed the 0.5 m tolerance. A test on an
exact floating-point boundary proves nothing; it now uses a point clearly
inside.

**Mutations** (failures counted with sub-tests): altitude sign flipped — 28;
NED z sent as minus the altitude, Phase 1's own bug — 23; heading axes
swapped — 2; headings normalised to [−180, 180) — 5; tolerance ignoring
height — 2; coverage legs a spacing in from the edge — 19; the clock
advancing without waiting for every participant — 3; jumping to the latest
wake-up instead of the earliest — 3.

The four Phase 2 goldens match unedited. 203 tests pass; audit clean.

### 2026-10-20 — step 3: the eleven skills, their contracts, and SkillResult

**`agentic_uav/control/skills.py`**, written once against `VehicleAdapter`, so
the same skills fly AirSim or the mock. It reaches the simulator only through
primitives, measures time only on a `Clock`, converts heights only through
`navigation`.

| Piece | What |
|---|---|
| `SkillName` | the eleven: `TAKE_OFF` `GO_TO_WAYPOINT` `FOLLOW_WAYPOINTS` `SEARCH_REGION` `INSPECT_POINT` `HOLD_POSITION` `RENDEZVOUS` `ACT_AS_RELAY` `RETURN_HOME` `LAND` `EMERGENCY_HOLD` |
| `SkillStatus` | AUV-04's four states: success, failed, aborted, timeout |
| `ErrorCode` | `PRECONDITION_FAILED` `NOT_REACHED` `HEADING_NOT_REACHED` `TIMEOUT` `LATE` `LANDING_FAILED` `ABORTED` `SIMULATOR_ERROR` |
| `SkillResult` | skill, vehicle, status, `started_at`, `ended_at`, final position (NED) and altitude above the ground, final heading, error code, message, skill-specific details (legs of a list, coverage of a search, drift during a hold); `as_json()` |
| one `…Command` per skill | AUV-04's `GoToWaypointCommand(waypoint, speed_mps, tolerance_m, timeout_s)` and ten more, validated when built: an impossible command is refused before any drone moves |
| `CONTRACTS` | per skill: parameters, preconditions, success, failure, timeout, abort behaviour, expected state change — as data, so a test checks all eleven are complete |
| `SkillRunner(vehicle, vehicle_id, clock, ground_z, home)` | runs one skill at a time for one drone; never raises for a flight; `request_abort(via)` from another thread |

**Phase 1's lessons, kept.** `TAKE_OFF` measures the ground with the drone
uncontrolled and at rest, and refuses to measure one already under control —
an armed drone is held wherever it is, which once made a run 17 m wrong.
`LAND` descends at 2 m/s to the remembered ground and verifies; a landing
that did not land keeps control, because releasing an airborne drone cuts its
motors. Defaults match the measured baseline: 5 m/s, take-off to 8 m, landed
within 3 m.

**Abort.** `request_abort` sets a flag and cancels the movement (on the
calling thread's own adapter, for AirSim). The skill then holds position and
returns `aborted`. An abort targets the skill in progress; a stale request
does not abort the next one. `EMERGENCY_HOLD` is the same as a skill:
cancel, then brake.

**Relay and rendezvous** are geometric, as decided: go and hold; a rendezvous
reached after `arrive_by` is `LATE` and does not hold.

**Tests: 39 new**, `tests/test_skills.py`, on the real `AirSimAdapter` over
the recording fake, with a `SimClock`. Every skill's success path and the
state it leaves; every failure clause made to happen — refused precondition,
stopping short, running out of time, heading not reached, a simulator error
reported word for word, a leg failing mid-list, partial search coverage, a
late rendezvous, a landing that does not land, an abort mid-move and one from
another thread mid-hold. Every height checked as the AirSim call it became
(30 m → `moveToZAsync(-0.75)`).

**Mutations, each caught:** control taken before measuring the ground — 29
failing; arrival never checked — 4; timeouts reported as failures — 2; a
landing released while airborne — 3; abort not holding — 1; abort ignored —
2; airborne precondition skipped — 1; emergency hold not cancelling — 1;
waypoint altitude sent as −altitude — 6; heading not checked — 1; rendezvous
never late — 1.

The four Phase 2 goldens match unedited. 242 tests pass; audit clean.

### 2026-10-20 — step 4: the MockVehicleAdapter, and one contract for every adapter

**`agentic_uav/simulator/mock_adapter.py`**: `MockWorld` (the shared scene)
and `MockVehicleAdapter` (both protocols, one per thread like AirSim's).

| Model | |
|---|---|
| motion | a point moving in straight lines at the commanded speed; no acceleration, wind or drift; turns at 90°/s; take-off lifts 3 m at 1.5 m/s, landing descends at 1 m/s |
| time | every motion takes simulated time on the world's `SimClock`, so timeouts, holds and team timing mean something, and minutes of flight take milliseconds |
| determinism | motion is stored as segments (from, to, start, end), so where a drone is at the current simulated instant is exact, whichever thread asks first |
| contacts | two drones closer than 0.8 m touch: both record a collision with the other, by name; every pair's minimum separation is kept |
| copies AirSim | NED with the ground at +29.25 by default; `add_vehicle` ignores its pose and spawns at the player start, `place_vehicle` then sets x and y; `reset` removes nothing; releasing an airborne drone drops it; landing is a contact with `MockGround`, classified as ground |
| differs, on purpose | the ground is solid: a move below it stops there and records a ground contact, so a sign error shows up instead of a drone underground |
| faults | per drone: a landing that does not descend, moves that make no progress, a primitive that raises, a slower drone |

One flaw found and fixed while testing: a finished move ended at
49.99999999999988 instead of 50, because a hundred 0.1 s ticks do not sum to
10.0 exactly. A move that runs its full course now ends exactly on its target.

**`tests/test_adapter_contract.py` — one contract, every adapter.** Fourteen
promises the skill layer relies on (the protocols; starting on the ground
uncontrolled; control and release; cancel with nothing moving; take-off,
moves, turns, hover, landing; reset; spawn ignoring the pose, then placing;
the skills flying end to end), written once in `AdapterContract` and run by:

* `AirSimOverFakeContract` — the real `AirSimAdapter` over the recording fake;
* `MockContract` — the mock, plus the scenario manager's spawn-and-place
  running on it;
* `LiveAirSimContract` — the real `AirSimAdapter` against a running CarlaAir,
  skipped unless `AUV_LIVE_AIRSIM=1`. It flies Drone1, with tolerances (1 m,
  5°), and is part of step 6's live check.

**`tests/test_mock_adapter.py`, 20 tests:** motion time is distance over
speed, take-off, climb and turn times, a timeout stopping a drone part way,
body-frame velocity after a turn, solid ground, a release dropping the drone,
landing contact, each fault giving the right skill result (stuck landing →
`LANDING_FAILED` with control kept, stalled → `TIMEOUT` at 15.0 s, raising →
`SIMULATOR_ERROR`, half speed → twice the time), and no real time passing (a
400 s search flown in well under a second). Then teams, one thread per drone
on one timeline: four drones flying take-off, waypoint, hold, home and land
concurrently; the same flight five times with identical results, separations
and contacts; two drones swapping places touching, classified as a drone
contact; two flying parallel 4 m apart not touching, minimum separation
exactly 4.0 m; an abort from a controller thread on its own adapter stopping
a drone 15 m into a 50 m leg, after 3 s at 5 m/s.

**Mutations:** contacts never recorded — 3; ground not solid — 1; cancel
ignored — 1; release not dropping an airborne drone — 1; spawning at the
requested pose — 1; motion taking no simulated time — 11; velocity ignoring
heading — 1. (A first "ground not solid" mutation patched a constant already
bound as a default argument and so changed nothing; it was redone on the
clamp itself.)

The four Phase 2 goldens match unedited. 305 tests pass, 14 of them the live
contract, skipped; audit clean.

### 2026-10-20 — step 5: the four-drone exit script, met on the mock

**`agentic_uav/experiments/team_flight.py`**: `exit_plan()`, the fixed plan,
and `fly_team(missions, connect, clock)`, which flies any such plan with one
thread and one adapter per drone, all on one clock (the world's `SimClock`,
every thread a participant, or real time for AirSim), keeping every
`SkillResult`. A drone whose skill does not succeed runs `EMERGENCY_HOLD` and
`LAND`, and its remaining skills are recorded as skipped: no drone is left
flying because a script stopped. `verdict()` checks the exit criterion.

**`scripts/four_drone_skills.py`**: `--sim mock` (default) or `--sim
airsim`. Resets the scene, spawns and places Drone2–4 through
`ensure_vehicles` (on both backends: it gained an optional `settle`, so the
mock waits in simulated time; the default is the real-time wait it always
had, and the goldens did not move), flies the plan, and writes a JSONL (a
header with provenance, layout, separation and the verdict, then one row per
skill: the command and its full result) and a Markdown summary. Exit code 0
only if every skill succeeded. On AirSim the separation monitor Phase 1 built
polls at 10 Hz during the flight; on the mock the world measures separation
and contacts exactly.

**The plan.** Four drones spawned 4 m apart along +x climb to 12, 16, 20 and
24 m, fly 20 m straight out sideways — Drone1 and Drone3 to −y, Drone2 and
Drone4 to +y — turn to face the way they went (±90°), hold 5 s, fly home at
their own height and land: the kind of legs M09 and M10 flew safely in
Phase 1. **A first version was unsafe and was changed:** it fanned the drones
forward, and Drone1, at 12 m, passed 2.4 m sideways from Drone2 while Drone2
was still climbing — 3.5 m apart on the mock, and in CarlaAir's different
timing exactly the crossing that made M10's contact. Now no tracks cross, and
every pair's closest approach is the 4 m spawn spacing.

**On the mock: exit criterion met.** 20 of 20 skills succeeded, each a
structured result; 37.5 s of simulated flight; every pair at least 4.0 m
apart; no drone contacts; every drone landed at home.

**Tests: 10 new**, `tests/test_exit_script.py`: the plan's shape (four
drones, five skills, distinct waypoints, 4 m altitude steps, alternating
sides); the script's own `main` on the mock, its outputs and verdict;
separation; every drone ending on the ground; four identical runs; a stalled
drone timing out mid-plan and then holding and landing while the other three
finish; a stuck landing failing the verdict; and `--sim airsim` against the
recording fake — the scene, the monitor and one connection per drone thread,
the waypoints sent as NED. **Mutations, each caught:** no hold-and-land after
a failure — 1; verdict always met — 2; all drones at one altitude — 1; the
old crossing plan — 2.

**One more live-only check, for step 6**: in `LiveAirSimContract`, a move on
one connection cancelled from a second — the open question of whether
`request_abort` works in CarlaAir.

The four Phase 2 goldens match unedited. 316 tests pass, 15 live ones
skipped; audit clean.

### 2026-10-21 — step 6: live in CarlaAir; the exit criterion is met

Flown by the user, step by step, after midnight. No model runs in Phase 3, so
no Vega job.

**Before flying, one fix to the live test.** `LiveAirSimContract` waited a
fixed 4 s after each reset for the falling drone to land, then read the
ground. Phase 1 had found a fixed wait reads the drone in mid-air (18 m
wrong once), so it was replaced, before any live run, by the executor's
settle loop: sample until the drone stops moving, at most 15 s.

**The scene.** `.\CarlaAir.ps1 Town10HD`, fresh, `settings.json` declaring
Drone1 only. A read-only check: one vehicle, on the ground at z = 29.25,
uncontrolled, heading **−45.6°** — Phase 1 measured the spawn heading as
−45.59°, so step 1's heading reading is right in CarlaAir.

**The live adapter contract**, `AUV_LIVE_AIRSIM=1 python
tests\test_adapter_contract.py -v LiveAirSimContract`: **15 tests in 178.5 s,
OK, 1 skipped by design** (spawning a test drone would leave it in the scene).
The two questions only CarlaAir could answer:

* **Cancelling from a second connection works.** A 60 m move running on one
  connection was cancelled 4 s in by `cancelLastTask` on a third; the move
  returned early and the drone stopped well short. So
  `SkillRunner.request_abort(via=...)` works as designed.
* **Turning holds.** 90°, −135° and 0°, each within 5°.

Every other promise held live: start on the ground uncontrolled, control and
release, take-off, moves, hover, landing, reset, the skills end to end. The
run printed `ResourceWarning: unclosed socket` repeatedly: every AirSim
connection in this project is opened and never closed. Harmless at this
scale; noted below.

**The exit script, live**: `python scripts\four_drone_skills.py --sim airsim
--block live` → `four-drone-skills-airsim-20261021-005707-live`. Drone2–4
spawned at runtime and placed 4 m apart. **20 of 20 skills succeeded**, each
a structured result; the four drones flew 46 s together; closest approaches
4.03, 8.02, 12.02, 4.0, 8.0 and 4.0 m over 420 monitor samples; **no drone
contacts**; every drone landed at home. **Exit criterion: MET.** The mock run
of the same script was saved beside it (`…-005853-mock`): 20 of 20, 36 s
simulated, closest approach exactly the 4 m spacing.

**What the live numbers say**

* **TAKE_OFF measured the grounds Phase 1 knew**: 29.245, 29.282, 29.281 and
  27.29 under the four spawns — Phase 1 recorded 29.25, 29.28 and 27.29 across
  M10's. Measuring at rest and uncontrolled works in CarlaAir.
* **A landed drone reads 1.16–1.17 m above its take-off ground** (z 28.07
  over 29.245; Drone4 26.12 over 27.29). v6's landed drones read the same
  (28.04–28.12, and 26.12), so it is CarlaAir's own behaviour, not this
  layer's. It is why `LAND` keeps the baseline's 3 m threshold: a 1 m one
  would have failed every live landing.
* **Headings ended at ±87.6° for ±90° asked**: AirSim's `rotateToYawAsync`
  returns once inside its default 5° margin, which the skill also accepts.
* **Heights crept 0.2–0.5 m above target over the legs** (12.24 after
  take-off, 12.52 after the waypoint, 13.01 after returning home, for 12 m
  asked): constant-height moves in CarlaAir end slightly high. All within the
  1 m tolerance.
* **Live take-off took 11.5–13.9 s**, the mock's 7.1–9.5 s; waypoint legs
  7.9–8.0 s live against 5.0 s: the mock has no acceleration, so its timings
  are lower bounds.

The scene now holds Drone2–4 until the simulator restarts; restart before any
single-drone mission (the runner would refuse anyway).

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-20 | **The Phase 2 primitives become `PrimitiveKind`, `PrimitiveCommand`, `PrimitiveResult`, and `execute_skill` becomes `execute_primitive`** | AUV-04 names the mission skills' types `SkillCommand` and `SkillResult`. Two layers each with a "skill result" would be read wrongly. The adapter runs primitives; the skill layer runs skills. A mechanical rename, proved behaviour-free by the goldens. |
| 2026-10-20 | **Exit evidence is the mock run and one live CarlaAir flight** | The criterion says "a deterministic script", not "in the mock". A live flight shows the skills on the real platform, not only against a model of it. No model runs in Phase 3, so no Vega job. |
| 2026-10-20 | **The mock is a constant-speed point mass, with separation and collisions** | AUV-04 asks for a lightweight mock for coordination questions. Acceleration and wind would cost more than they tell; the coordination phases do need separation and contact. |
| 2026-10-20 | **Above the navigation module, altitude is metres above the ground, positive; below it, NED** | AUV-04's coordinate trap, and Phase 1's two-week altitude error. One module converts, always against a measured ground, and a mission's `Waypoint` has no `z` to misuse. |
| 2026-10-20 | **Simulated time is one timeline, advanced only when every flying thread waits** | Drones fly in their own threads; comparing their positions needs one instant. Advancing only when all wait makes simulated times independent of machine speed. |
| 2026-10-20 | **A skill never raises for a flight; it returns a status** | AUV-04: an agent must recognise failure and decide what next. Every way a flight goes wrong — including a primitive raising — comes back as a `SkillResult` with an error code, and the simulator's own message kept word for word. Only an impossible command (refused at construction) or a non-command raises. |
| 2026-10-20 | **Contracts are data beside the code that keeps them** | So the contract a skill promises and the contract a reader sees cannot drift apart, and a test can require all seven clauses for all eleven skills. |
| 2026-10-20 | **The mock copies AirSim where code depends on it, and differs only where a difference makes errors visible** | Spawning that ignores the pose, a reset that removes nothing, a release that drops an airborne drone: code written on the mock must behave the same on AirSim. The one deliberate difference, solid ground, turns a silent sign error into a recorded contact. |
| 2026-10-20 | **Every adapter runs one contract suite** | The skills are written once; they fly the same everywhere only if every adapter keeps the same promises. A live variant runs the same promises against CarlaAir. |
| 2026-10-20 | **The exit plan's tracks never cross** | The first plan let Drone1 pass 2.4 m from a still-climbing Drone2; safe on the mock's timing, and exactly M10's contact in CarlaAir's. Straight out sideways, alternating, keeps every pair at least the 4 m spawn spacing whatever the timing. |
| 2026-10-21 | **The live contract runs before the live exit flight** | It flies Drone1 only, so it runs on a fresh scene before Drone2–4 are spawned, and it answers the questions only CarlaAir can (cancel from a second connection, turning) before the exit run depends on them. |
| 2026-10-20 | **`ACT_AS_RELAY` and `RENDEZVOUS` are geometric in Phase 3** | Go to a point and hold (until a deadline, for rendezvous). What makes them relay and rendezvous — messages — arrives in Phases 7 and 9. |

## Open questions

- **The baseline's executor still reads real time.** `control/executor.py`
  uses the `time` module directly (settle loops, `TAKEOFF_SETTLE`), so the
  open-loop baseline cannot fly the mock in simulated time; only the skill
  layer can. Making the executor clock-aware is a behaviour-neutral change the
  goldens could prove, but nothing in Phase 3 needs it.
- **The mock is a point mass.** No acceleration, wind or drift; constant
  speed. Fine for coordination questions; anything about flight dynamics
  belongs in AirSim, as AUV-19 recommends. Measured live: real take-offs are
  about 4.5 s slower and 20 m legs about 3 s slower than the mock's, so mock
  timings are lower bounds.
- **Constant-height moves end slightly high in CarlaAir** (0.2–0.5 m per
  leg, cumulative over a sequence). Within tolerance for Phase 3's plans; a
  long sequence could drift out of a tight tolerance.
- **A landed drone reads about 1.17 m above its take-off ground in CarlaAir**,
  as it did in Phase 1. The 3 m landing threshold absorbs it; a tighter
  landing check would need to know why.
- **AirSim connections are never closed** (`ResourceWarning: unclosed
  socket`). Every test and flight opens fresh ones. Harmless so far; a long
  experiment opening thousands might exhaust sockets.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
