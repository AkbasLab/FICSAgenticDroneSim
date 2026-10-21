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
| NED conversion, heading, tolerance, coverage paths; a clock | `agentic_uav/control/navigation.py`, `agentic_uav/core/clock.py` | step 2 |
| The eleven skills and their contracts | `agentic_uav/control/skills.py` | step 3 |
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

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-20 | **The Phase 2 primitives become `PrimitiveKind`, `PrimitiveCommand`, `PrimitiveResult`, and `execute_skill` becomes `execute_primitive`** | AUV-04 names the mission skills' types `SkillCommand` and `SkillResult`. Two layers each with a "skill result" would be read wrongly. The adapter runs primitives; the skill layer runs skills. A mechanical rename, proved behaviour-free by the goldens. |
| 2026-10-20 | **Exit evidence is the mock run and one live CarlaAir flight** | The criterion says "a deterministic script", not "in the mock". A live flight shows the skills on the real platform, not only against a model of it. No model runs in Phase 3, so no Vega job. |
| 2026-10-20 | **The mock is a constant-speed point mass, with separation and collisions** | AUV-04 asks for a lightweight mock for coordination questions. Acceleration and wind would cost more than they tell; the coordination phases do need separation and contact. |
| 2026-10-20 | **`ACT_AS_RELAY` and `RENDEZVOUS` are geometric in Phase 3** | Go to a point and hold (until a deadline, for rendezvous). What makes them relay and rendezvous — messages — arrives in Phases 7 and 9. |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
