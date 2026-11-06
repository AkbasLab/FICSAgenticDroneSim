# Phase 16 — Verification and software testing

**Stage:** 6 · Apparatus · **Vault note:** `AUV-15 — Testing and Verification`
**Started:** 2026-11-06 · **Completed:** 2026-11-06

> The phase that decides whether the schedule holds. Phase 16 mapped every test
> AUV-15 asks for to the tests that hold it, added its seven integration
> scenarios by name and a determinism suite, set up continuous integration, flew
> its five AirSim regression checks live, and showed — by planting defects and by
> the project's own history — that coordination and communication defects are
> found without launching CarlaAir.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **16.1** Unit tests — task cost, tie breaking, lease expiration, serialization, expiration, packet-loss sampling, latency scheduling, role transitions, belief aging, geofence, battery, invalid LLM output (`docs/TESTING.md`, each mapped to named tests, checked)
- [x] **16.2** Integration tests using the mock adapter — the seven named scenarios (`tests/test_integration_mock.py`)
- [x] **16.3** AirSim regression tests — the five (`scripts/airsim_regression.py`), **flown live, all passed**
- [x] **16.4** Determinism tests — network events, target placement, injected faults, deterministic policies (`tests/test_determinism.py`)
- [x] **16.5** Continuous integration — every test that needs no simulator, on each pull request and push to `SC` (`.github/workflows/tests.yml`)
- [x] ✅ **Exit:** most coordination and communication defects can be discovered without launching CARLA-Air

## Exit criterion

> Most coordination and communication defects can be discovered without launching CARLA-Air.

**Met:** yes, 2026-11-06. **Planted defects:** 37 realistic coordination and communication defects, fixed before
their first run, each planted alone — **36 of 37 discovered on the first run (97.3 %), 37 of 37 in the run of
record** after a test was added for the one missed; the bar was 90 %. **The project's history:** of its coordination
and communication defects, **28 of 29 (96.6 %)** were found without the simulator; of all its code defects, 55 of
60 (91.7 %). · **Evidence:** [`evidence/exit-criterion-2026-11-06.md`](evidence/exit-criterion-2026-11-06.md),
[`evidence/defect-history-2026-11-06.md`](evidence/defect-history-2026-11-06.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The map of 16.1, 16.2, 16.4 to tests, and its check | `docs/TESTING.md`, `tests/test_traceability.py` | **Done** |
| The seven integration scenarios | `tests/test_integration_mock.py` | **Done**; 17 s together |
| Determinism | `tests/test_determinism.py` | **Done** |
| Continuous integration | `.github/workflows/tests.yml`, `requirements-ci.txt` | **Done**; tried on clean Linux and Windows environments |
| The AirSim regression set | `scripts/airsim_regression.py`, `tests/test_airsim_regression.py`, `results/` | **Done**; five live flights |
| The exit | `tests/planted_defects.py`, `scripts/testing_exit.py`, `results/`, `evidence/` | **Done**; exit met |

## Plan

Approved 2026-11-06 ("Approve, build it all"), shown in full first, with two of the user's choices: **CI goes live
on the lab's repository**, and **the live flights are flown this phase**. Steps: the map; the seven scenarios;
determinism; CI, tried first; the regression set and its dry run; the exit (planted defects and history); the live
flights; close, pushing and tagging.

## Record

### 2026-11-06 — the map, the scenarios, determinism

* **The map.** Every one of AUV-15's twelve unit-test items, seven scenarios and the determinism items names its
  tests in `docs/TESTING.md`; `tests/test_traceability.py` finds each named test in its file, so a rename fails a
  test. Most were already there — the suite held about 1,340 tests — and the map made it visible.
* **The seven scenarios**, one mock flight each. The sixth was new ground: nothing had tested a relay failing.
  Roles are worked out from each drone's own view, so a handover should follow on its own; probing stop times found
  the flight that shows it — Drone3 stopped at 100 s, Drone4 relays toward it from 118.5 s and is itself stopped at
  119 s, still the relay; Drone2 takes the role at 136.0 s, Drone1 at 138.5 s, and the mission is met. The fifth
  (delayed claims) flies, as Phase 8 does, with unlimited radio, so the conflict is the only difference.
* **Determinism**: five runs flown twice; the run directory, network events, targets, injected faults, policies and
  a replayed model's output all repeat, and another seed changes them.

### 2026-11-06 — continuous integration, tried before it went live

The workflow was tried on clean environments before it could run on the lab's repository, and the trials found three
things:

1. **The `airsim` package was missing** from the first CI requirements. No test starts a simulator, but the fake
   simulator and the goldens use AirSim's own types. Added, with what it imports — and not the OpenCV it lists
   and never imports; it is built against those (`--no-deps --no-build-isolation`), since its setup imports itself.
2. **A model call's latency is timed on the wall clock**, so "the same run, byte for byte" failed on a loaded Linux
   machine (a replay's 0.000 s became 0.001 s). The comparisons — the determinism test and Phase 14's batch check —
   now set that one field aside, and a test shows nothing else is set aside.
3. **The recorded goldens pin Windows paths** (`<OUT>\file`), and goldens are never re-recorded. CI therefore runs on
   **Windows**, as the project is developed and flown; on Linux the suite passes but for those path strings.

Python 3.10 throughout: AirSim's `tornado` 4.5.3 runs on nothing newer than 3.11 (seen on WSL's 3.14).

### 2026-11-06 — the five AirSim regression checks, flown live

Flown by the user in CarlaAir (Town10HD), one at a time, the simulator relaunched and the scene checked (Drone1
alone, API control off) before each:

| Check | Result | As flown |
|---|---|---|
| single-waypoint | **passed** | mission met, 38.8 s; every skill succeeded; the twin met too |
| return-home | **passed** | the injected fault struck; the drone retried and recovered; met; the twin's 11 decisions exactly |
| pair-apart | **passed** | the twin's division (Drone1 S2, Drone2 S1); six live checks |
| reassign | **passed** | stop detected, task reassigned in flight, keep-out kept; **the mission not met**: S1 81.9 % covered (the keep-out's cost, as Phase 9's re-fly), Drone1 landed 2.1 m from its pad |
| four-search | **passed** | four drones, 20 of 20 skills; closest pairs 4.0 m. A four-drone *search* is flown on the mock only: the surveyed airspace holds the two-sector live layout |

### 2026-11-06 — the exit

* **Planted defects** (`tests/planted_defects.py`): 37 — the bus (range, delay, rate limit, partitions, losses,
  latency, early reads, stale reads, order, shared copies), the network model, message expiry and schemas, leases,
  bids, the bid window, ties, the health ladder, roles, recovery, the keep-out and teammates' records ageing. The
  first run, during the phase, missed one (a drone re-announcing its own task by its own lease); a test was added;
  the run of record (`results/testing-exit-20261106-141341-exit`, at `f144d24`, clean) discovers all 37.
* **History** (`evidence/defect-history-2026-11-06.md`): every code defect in the phase reports, classed by what found
  it, row by row. The five found live were about CarlaAir itself (its timing, landed heights, drones falling after
  placement, a printout) and one coordination defect — the survivor sent beneath a stopped teammate in Phase 9.

### 2026-11-06 — close

**Phase 16 is complete.** The suite passes on the laptop and on a clean Windows environment as CI builds it.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-06 | **A checked map, rather than new tests for everything already tested** | Most of 16.1 existed; the map shows it and keeps it true |
| 2026-11-06 | **The exit measured two ways: planted defects (bar 90 %, fixed first) and the project's history** | One is controlled, the other real |
| 2026-11-06 | **CI on Windows, Python 3.10** | The goldens pin Windows output and are never re-recorded; AirSim's tornado needs ≤ 3.11 |
| 2026-11-06 | **A model call's latency set aside when comparing runs** | It is wall-clock time, the run's own, like its manifest's |
| 2026-11-06 | **`four-search` as four drones flying together** | Town10HD's surveyed airspace holds two sectors; nothing avoids its buildings |
| 2026-11-06 | **The reassignment flight recorded as flown: the check passed, the mission not met** | The user's standing rule: record live results as they are |

## Open questions

1. **A four-drone live search** needs more of Town10HD's airspace surveyed.
2. **A live model's residual variability** (docs/TESTING.md's protocol) is measured with the first live-model batch.
3. **Coverage against the keep-out** in small sectors (Phase 9's open question) showed again in `reassign`.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
