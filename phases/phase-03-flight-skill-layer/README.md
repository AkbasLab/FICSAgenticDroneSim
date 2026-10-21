# Phase 3 — Complete the deterministic flight-skill layer

**Stage:** 1 · Platform · **Vault note:** `AUV-04 — Flight Skills and the Mock Simulator`
**Started:** 2026-10-20 · **Completed:** —

> Give every later agent a reliable toolbox: eleven mission-level skills with
> formal contracts and structured results, heading and waypoint navigation, and
> a mock simulator to run them without CarlaAir. Until this exists, an agent
> can only print, never recognise that something failed and decide what next.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **3.1** Define high-level skills — `TAKE_OFF` `GO_TO_WAYPOINT` `FOLLOW_WAYPOINTS` `SEARCH_REGION` `INSPECT_POINT` `HOLD_POSITION` `RENDEZVOUS` `ACT_AS_RELAY` `RETURN_HOME` `LAND` `EMERGENCY_HOLD`
- [ ] **3.2** Add heading and waypoint navigation — turn to heading, 3D waypoint, waypoint list, cancel movement, stop and hold, reached-within-tolerance
- [ ] **3.3** Give every skill a formal contract — parameters, preconditions, success, failure, timeout, abort behaviour, expected state change
- [ ] **3.4** Add a lightweight mock simulator — `MockVehicleAdapter` for unit tests, communication testing, task-allocation testing, rapid debugging, CI

## Exit criterion

> A deterministic script makes four drones take off, navigate to distinct
> waypoints, hold, return and land — and **each skill returns a structured
> result rather than merely printing output.**

**Met:** no · **Evidence:** —

Planned evidence: the exit script's structured results from the mock (a test,
on every run) and from one live CarlaAir flight of the same script, flown by
the user.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Primitives renamed `Primitive*`; turn, cancel and heading in the adapter | `agentic_uav/core/models.py`, `agentic_uav/simulator/` | **Done** 2026-10-20; Phase 2 goldens pass unedited |
| NED conversion, heading, tolerance, coverage paths; a clock | `agentic_uav/control/navigation.py`, `agentic_uav/core/clock.py` | **Done** 2026-10-20 |
| The eleven skills and their contracts | `agentic_uav/control/skills.py` | **Done** 2026-10-20 |
| `MockVehicleAdapter`, and one contract suite for every adapter | `agentic_uav/simulator/mock_adapter.py`, `tests/` | step 4 |
| The four-drone exit script | `scripts/` | step 5 |
| Live flight of the exit script; close | `results/`, `evidence/` | step 6 |

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
| 2026-10-20 | **`ACT_AS_RELAY` and `RENDEZVOUS` are geometric in Phase 3** | Go to a point and hold (until a deadline, for rendezvous). What makes them relay and rendezvous — messages — arrives in Phases 7 and 9. |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
