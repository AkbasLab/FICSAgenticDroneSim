# Phase 4 — Build the canonical search-and-relay mission

**Stage:** 1 · Platform · **Vault note:** `AUV-05 — The Search-and-Relay Mission`
**Started:** 2026-10-21 · **Completed:** 2026-10-21

> One controlled mission that stays fixed while the architecture changes under
> it. Everything in the study is measured against it, so it must be feasible
> before any agent is asked to fly it: AUV-19's gate G1.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **4.1** Define the environment — one base station, four search sectors, two targets, one restricted region, two to four drones, a communication/relay requirement, a deadline, a simulated battery *(steps 1–2: `search_relay_001`; a 100 m radio the far sectors reach only by relay or on return; the battery recorded, not enforced)*
- [x] **4.2** Use simulated detection first — detection radius, line of sight if easy, minimum observation period; **no object-detection network at this stage** *(step 2: 10 m horizontal, held 2 s, solved exactly from the flown path; line of sight not modelled)*
- [x] **4.3** Define mission success — sectors searched or coverage threshold, all targets detected, detections reported **or eventually synchronized**, no restricted-region entry, no collision or separation violation, all functioning drones return *(step 3: C1–C6, judged from the world's facts up to the deadline)*
- [x] **4.4** Put scenarios in configuration files — `scenario_id`, `random_seed`, mission, vehicles, network, faults, restricted zones *(step 1: TOML, a strict loader; the controller gets a brief with no targets and no seed)*

## Exit criterion

> A fully scripted, **non-agentic** controller can complete the canonical
> mission.

**Met:** **yes, 2026-10-21** · **Evidence:**
[`evidence/exit-criterion-mock-2026-10-21.md`](evidence/exit-criterion-mock-2026-10-21.md)
and [`evidence/live-run-2026-10-21.md`](evidence/live-run-2026-10-21.md).

**On the mock**, the scripted controller (`control/scripted.py`, planned from
the brief alone) completed `search_relay_001` on all 20 exit seeds: every
one of AUV-05's six criteria on every seed, and every planned skill
succeeded. That was at `1bcfcdc`, 182.2 s. After the lane-end fix of step 5
it met them again, at the version that closes the phase: 192.1 s of the
900 s deadline, coverage 0.99977, lowest battery 72.4 %, closest pair
3.36 m.

**In CarlaAir**, flown by the user, a small variant inside the airspace
Phases 1 and 3 had flown (two drones, two sectors) met all 20 seeds in each
of three flights. Every skill succeeded, there were no contacts but the
ground, and the pads were within 0.34 m. Flights 2 and 3 were within 0.22 m
of each other throughout.

The plan was the mock across 20 seeds, with an optional small live variant.
Both were done.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Scenario format, validated loader, the canonical scenario | `agentic_uav/core/scenario.py`, `agentic_uav/experiments/scenarios.py`, `configs/scenarios/` | **Done** 2026-10-21; goldens unedited |
| The mission world: targets, detection, restricted zones, battery, connectivity, an observer | `agentic_uav/simulator/` | **Done** 2026-10-21; goldens unedited |
| The evaluator: one mission report, every criterion | `agentic_uav/experiments/evaluation.py`, `agentic_uav/simulator/coverage.py` | **Done** 2026-10-21; goldens unedited |
| The scripted controller, run across 20 seeds | `agentic_uav/control/routing.py`, `agentic_uav/control/scripted.py`, `agentic_uav/experiments/search_relay.py`, `scripts/search_relay_exit.py` | **Done** 2026-10-21; exit met on the mock, 20/20 |
| Optional live run; close | `configs/scenarios/search_relay_live_small.toml`, `agentic_uav/experiments/search_relay.py` (`fly_live`), `results/`, `evidence/` | **Done** 2026-10-21: three CarlaAir flights, 20/20 seeds each; phase closed |

## Plan

Approved 2026-10-21 with its recommendations. Each step lands as its own
commit after the user's go-ahead; the four Phase 2 goldens must still pass
unedited.

1. **Scenario format and loader (4.4).** The canonical scenario as TOML, with
   AUV-05's fields plus the base, sectors, targets, battery and communication
   range; loaded strictly into validated data; a bad file refused with every
   problem listed.
2. **The mission world (4.1, 4.2).** Ground truth on the simulator side:
   targets placed from the seed, detection (radius held for a minimum
   observation time), restricted zones, a simple battery, connectivity to the
   base direct or relayed within range, and an observer that records it all
   during a flight — exactly on the mock, by polling live.
3. **The evaluator (4.3).** One mission report from the record: every success
   criterion pass or fail with its number, plus partial scores.
4. **The scripted controller and the exit.** One drone per sector, lawnmower
   search with lanes spaced so the minimum observation time is met, routing
   around the restricted zone, return to base. Across 20 seeds on the mock.
5. **Close**: an optional live run on a small variant, the record, the vault
   report, the tag.

## Record

### 2026-10-21 — step 1: the scenario format, a strict loader, and search_relay_001

**Geometry moved to core.** `Region` left `control/navigation.py` for a new
`agentic_uav/core/geometry.py`, unchanged, because the scenario's sectors need
it and `core` must not import `control`. `navigation` re-exports it: the tests
assert `navigation.Region`, `skills.Region` and `geometry.Region` are one
class. Added beside it: `Region.area`, `Region.overlaps` (touching edges do
not count), and `Polygon` for restricted zones — `area` (shoelace), `bounds`,
`edges`, `contains` (ray casting, boundary counted as inside), and
`crosses(start, end)`, whether a straight path enters it, grazing an edge
included. Fewer than three vertices, or no area, is refused.

**The data model** (`agentic_uav/core/scenario.py`, no I/O): frozen
dataclasses for the mission, base, network, detection, battery, safety,
vehicles, sectors, targets, restricted zones and faults. Each checks its own
values; `Scenario` checks the whole — ids unique, starts at least
`min_separation_m` apart, sectors not overlapping, neither the base nor a
start inside a zone, fixed targets inside a sector and outside every zone,
`targets_to_find` no more than exist, every fault with a `kind`. Phase 4
refuses what it does not model: a network profile other than `perfect`, and
`line_of_sight = true`. Every problem found is raised at once, in one
`ScenarioError`.

**Two views.** `Scenario` is ground truth. `Scenario.brief()` returns a
`MissionBrief` — base, sectors, zones, deadline, how many targets — with no
target field and no seed, so a controller cannot be handed either.

**The loader** (`agentic_uav/experiments/scenarios.py`) reads
`configs/scenarios/<id>.toml`, or a path, with the runner's `load_toml`, then
checks keys before building anything: unknown, missing and wrong-typed keys
are each an error with its place (`mission.targets_to_find: expected int, got
float 2.0`), a bool is not accepted as a number, and all are reported
together. A start is `[x, y]` or AUV-05's `[x, y, 0]`; any other third value
is refused.

**The canonical scenario**, `configs/scenarios/search_relay_001.toml`, seed
17, every value commented with its reason:

| Field | Value |
|---|---|
| Mission | `distributed_search`, deadline 900 s, coverage 0.95, find 2 |
| Base | (−8, 0), behind the start line |
| Network | `perfect`, range 100 m |
| Detection | radius 10 m, held 2.0 s; no line of sight |
| Battery | 100, 0.05 per s, 0.02 per m, reserve 20 |
| Safety | separation 2.0 m |
| Targets | 2, uniform over the sectors outside zones, at least 20 m apart |
| Vehicles | Drone1–4 at x = 0, 4, 8, 12, y = 0: the spawn layout |
| Sectors | S1 [40, −80, 120, 0], S2 [40, 0, 120, 80], S3 [120, −80, 200, 0], S4 [120, 0, 200, 80]; 6400 m² each |
| Restricted | R1, x 15–35, y −15–15; 600 m² |

The tests confirm what the layout is for: no point of S3 or S4 lies within
100 m of the base, so a detection there is reported only through a relay or
on return; S1 and S2 are partly in range; R1 lies across every drone's
straight path to (160, 0), between the far sectors.

**For step 4: R1 needs a wide detour.** The straight path from Drone3 (8, 0)
to (120, −40) crosses R1, and so does a dog-leg through (25, −25): its first
leg clips the zone's corner. Routes have to leave the start line sideways
first, e.g. via (8, ±20), before x reaches 15. `Polygon.crosses` is what the
controller's routes will be checked with.

**Tests: 24 new, in `tests/test_scenario.py`** — geometry (6), the canonical
file (6), the strict loader and the cross-checks (12), including one file
with five different mistakes, all reported in one error.

**Mutations: 25, all caught** — seven in geometry, four in the loader,
fourteen in the cross-checks and the brief. It took three passes:

* First pass: the check that the restored code passes **failed**. The source
  was back, but Python ran a stale `.pyc`: its cache key is the source's
  mtime in whole seconds plus its size, so a same-length mutant restored
  within the same second is never recompiled. The repository's cache was
  invalidated (sources touched), and the runner now gives every test run a
  fresh, empty bytecode cache (`-X pycache_prefix=`).
* Second pass, clean: two mutants survived. Casting the ray left instead of
  right is an **equivalent mutant** — a closed polygon's crossings along a
  line are even in total, so both sides share parity — and was replaced by one
  that matters (any crossing means inside). A path lying wholly inside a zone,
  cutting no edge, was a **real gap**: no test had one. One does now.
* Third pass: 25 of 25 caught; restored code passes.

**Incidental: a flaky Phase 3 test.** `test_clock.RealClockTests` failed once
in the full suite. On this Python (3.10, Windows) `time.monotonic` is
`GetTickCount64`, 15.6 ms resolution, so a 10 ms sleep read as zero elapsed
in 4 of 200 trials. The test now sleeps 50 ms and allows one tick of the
clock's reported resolution; 30 repeats pass. `RealClock` is unchanged.

**The goldens did not move.** `record_golden.py --check` matches all four.
340 tests pass, 15 skipped (live only); audit clean.

### 2026-10-21 — step 2: the mission world — targets, detection, zones, battery, radio, and an exact record

**Judged from trajectories, solved exactly.** A flight is judged by each
drone's trajectory: knots `(t, x, y, altitude, airborne)` joined by straight,
constant-velocity legs (`agentic_uav/simulator/trajectory.py`), in the
mission's frame, not NED. On a leg, the distance from a drone to a target,
to another drone or to the base is a quadratic in time, so every fact below
is the root of one, not a sample: a 2 s dwell is 2 s, and the closest
approach is the true minimum. Two knots at one instant are a jump (placed,
reset, a fall with the motors cut), which takes no time and flies no
distance.

**The facts** (`agentic_uav/simulator/mission_world.py`), each as the
module docstring defines it:

| Fact | How it is decided |
|---|---|
| Targets | `place_targets`: uniform over the sectors by area, from the seed, by `random.Random` alone; outside every zone, `min_spacing_m` apart; or the fixed positions. Seed 17: T1 (184.54, −3.16) in S3, T2 (101.29, 56.34) in S2 — pinned by a test |
| Detection | airborne, and within `radius_m` horizontally for `min_observation_s` unbroken, across knots; detected when that time is reached; first per (target, drone) |
| Zone entry | the first instant a drone's ground track touches a zone — `Polygon.entry_fraction`, new in `core/geometry.py` |
| Battery | `hover_drain_per_s` per airborne second plus `move_drain_per_m` per metre flown; when it crossed the reserve and when it would have run flat. Recorded, not enforced |
| Connectivity | a chain of links ≤ `communication_range_m` (3D) from drone to base, through any drones, flying or landed; the base a node on the ground |
| Reported | the first moment at or after a detection that its drone is connected to the base |
| Separation | each pair's closest approach (3D) while at least one flies, and every interval under `min_separation_m` |

`observe(scenario, trajectories, start, end)` returns them as one
`MissionFacts`, whose `as_json()` gives times from the mission's start. The
evaluator (step 3) judges these; nothing here passes or fails anything.

**Two sources of trajectory** (`agentic_uav/simulator/observer.py`):

* **The mock, exactly.** `MockWorld` now records a knot at every change of
  motion — move start and end, landing, a fall, placement, reset — and
  `mock_trajectories(world)` reads them. The trace is checked against a mock
  flight worked by hand: R1 entered at x = 15 three seconds into the leg, T1
  in view at x = 65 − √75, 180 m flown.
* **A live simulator, by polling.** `PollingObserver` reads every drone's
  pose on its own connection, 10 Hz by default, never commanding anything;
  altitude from each drone's measured ground; airborne above 0.5 m. Between
  polls it can miss what the mock cannot (a corner clipped in under 0.1 s).
  It refuses a `SimClock`: alone on simulated time its sleeps would run the
  clock away before and after the flight. Tested on the mock in real time —
  1.1 s of flight polled at 20 Hz, every sample within 0.5 m of the exact
  trace; 25 repeats pass.

`simulator/` still depends on `core/` only: the observer repeats the one-line
NED-to-altitude conversion rather than import `control.navigation`.

**Tests: 44 new, in `tests/test_mission_world.py`** — trajectories (4),
target placement (5), detection (9), zones (6), battery (3), connectivity
(4), separation (5), `observe` (2), the mock's trace (3), the poller (3).
Hand-worked numbers throughout: the boundary dwell (an offset of √75 m is a
10 m chord, exactly 2 s, and detects; 1 cm more does not), a relay breaking
the moment its own base link does (t = 4.4 s), a report on return (x = 92 m
inbound), a violation interval of 10 ± √3/10 s.

**Mutations: 33, all caught**, against the full suite. The first clean pass
caught 24 of 34, and the ten survivors were all one of two things:

* **Redundant code, removed.** Two survivors were code that changed
  nothing: zone entry's separate "starts inside" check (a leg starting
  inside already enters at fraction 0), and the mock's knot *before* a move
  starts (the knot after it records the same instant and place, and the
  airborne flag applies from the knot on). Both deleted; 34 became 33.
* **Tests that could not see the fault.** "A dwell carries over a knot" was
  detectable from its first piece alone; it is now three pieces of 0.6, 1.0
  and 0.6 s. "Motors cut" let no time pass before the fall, so a missing
  pre-fall knot changed nothing; it now holds 5 s first. And six cases were
  missing outright: a zone lying inside a sector (R1 lies in none, so the
  canonical file could never show a target placed in one), a leg that
  begins already in range, a pair parting from the start (both: a quadratic
  root before the leg must be clipped), a zone crossed from the far side, a
  detection made in range (reported at once), and a landed drone with
  another flying 1 m over it.

**A slip of mine, caught by the mutation runner.** Two files patched by an
in-place script had been written in Windows text mode, CRLF, so its patterns
found nothing; a `grep` check I ran first wrongly said they were LF. The
repository's `.gitattributes` normalises to LF on commit, so nothing
committed was affected; the files were rewritten LF and checked with Python.

**The goldens did not move.** `record_golden.py --check` matches all four.
384 tests pass, 15 skipped (live only); audit clean.

### 2026-10-21 — step 3: the evaluator — AUV-05's six criteria, each with its number

**Coverage first** (`agentic_uav/simulator/coverage.py`), because "searched"
needed a definition before it could be judged. A point is searched once a
target there would have been detected: some airborne drone held it within
the radius, horizontally, for 2 s unbroken. So coverage is the chance a
uniformly placed target would be found, and coverage and detection cannot
disagree — a test checks 300 cells against `detections` one by one, to the
same instant. Passing within range is not searching, and neither is two
drones each holding a point for half the time, however the halves join. The
searchable area is the sectors less any zone (where targets can be), on a
1 m grid judged at cell centres, the dwell at every centre solved exactly
per leg with numpy (already pinned: `numpy==2.2.6`). The whole team's
coverage takes about 0.01 s.

**The evaluator** (`agentic_uav/experiments/evaluation.py`):
`evaluate(scenario, trajectories, start, end, contacts, failed)` returns a
`MissionReport`, judged on `mission_world` facts and never on what a
controller says about itself.

| | AUV-05 4.3 | Passes when |
|---|---|---|
| C1 | sectors searched or coverage threshold | coverage of the searchable area ≥ `required_coverage` |
| C2 | all targets detected | ≥ `targets_to_find` distinct targets detected |
| C3 | reported, or eventually synchronized | ≥ `targets_to_find` distinct targets reported (a detecting drone later connected to the base, directly or relayed) |
| C4 | no restricted-region entry | no zone entered |
| C5 | no collision or separation violation | no contact except with the ground, and no pair under `min_separation_m` while one flew |
| C6 | all functioning drones return safely | every drone not in `failed` ends landed, within 2.0 m of its own pad, at or above the battery reserve, never flat |

* **The window** is the flight up to the deadline. Nothing after it counts,
  landing included, so success already means on time; there is no separate
  deadline criterion.
* **Return is to the drone's pad.** 2.0 m is half the 4 m pad spacing, so
  which pad a drone is on is never ambiguous. The base is a radio.
* **Completion time** (AUV-14's T_completion) is the last of three moments:
  coverage reaching the threshold, the last needed target reported, the last
  functioning drone landing. A failed mission has no completion time; it is
  recorded as failed, never as a fast finish.
* **Partial scores are components, not a score.** Coverage, detection,
  reporting, safe return, and the safety counts are reported separately.
  AUV-14 sketches w1·Coverage + w2·Detection + w3·SafeReturn but sets no
  weights, and Phase 15 forbids inventing a metric after seeing results; the
  weights are Phase 15's.

**A mission flown by hand passes.** The test fixture flies trajectories, not
a controller, on seed 17. Each drone:

* takes one sector at its own height (12, 16, 20 or 24 m);
* leaves its pad sideways to y = ±20, then goes round R1 at x = 40;
* flies 16 m lanes, then returns the same way and lands.

The result: **success in 186.3 s**. Coverage was 0.9995. T1 was reported by
Drone3 on its way home at 152.6 s. Batteries landed at 73.5–78.1 %, and the
closest pair came to 4.0 m (on the pads). It is not the step-4 exit, but it
says the canonical mission is feasible with margin, and how.

**Then broken one way at a time**, each failing exactly the criteria it
should and no others:

| Break | Fails |
|---|---|
| S3 skipped (only three drones fly) | C1, C2, C3 |
| a straight route through R1 | C4 |
| a building contact (a ground contact does not count) | C5 |
| Drone3 at Drone1's height, 1.6 s late, meeting at (8, −20) | C5 |
| one drone left airborne, one landed 3 m off its pad | C6 |
| drain 0.4 %/s: Drone3 and 4 land at 8.8 % and 8.5 % | C6 |
| T1 detected in S3, but Drone3 lands there | C3, C6 |
| the deadline 1 s before the last landing | C6, and no completion time |

The relay is tested with worked distances: Drone1 hovering 99.0 m from the
base and 95.3 m from Drone3 at the moment of detection reports T1 at once;
at 108.9 m from the base it reports nothing.

**Tests: 22 new, in `tests/test_evaluation.py`** — coverage (7), the
evaluator (15).

**Mutations: 26, all caught**, against the full suite: nine in coverage,
seventeen in the evaluator. Getting there:

* **Five first-run failures were all my test fixtures, not the code.**
  * A climb sat exactly 10 m from the test cell, so the climb itself was a
    dwell.
  * A relay premise was wrong: Drone1 relays Drone3 naturally on its way home.
  * A 0.2 %/s drain still left 47 %.
  * A "wrong pad" was inside R1.
  * Two "same height" drones ran 8 m apart in line.

  Each was rebuilt with the numbers worked out first.
* **A completion test could not see a dropped report moment.** In its layout,
  coverage came in last (394 s against 385 s). A second layout puts T2 where
  only Drone2's last lane passes, so the report comes in last. The first try
  at that, (115, 75), was found early by Drone4; (100, 75) is not.
* **The first mutation pass caught 22 of 26.** The four survivors were
  untested behaviours, now tested:
  * a landed drone searching;
  * hovering over a point;
  * `time_to` rounding down, which would report a fraction one cell early;
  * contacts outside the window.

**The goldens did not move.** `record_golden.py --check` matches all four.
406 tests pass, 15 skipped (live only); audit clean.

### 2026-10-21 — step 4: the scripted controller, and the exit met on the mock, 20 of 20 seeds

**Routing** (`agentic_uav/control/routing.py`): the shortest route between
two map points that keeps `ZONE_CLEARANCE_M` (2.0 m) from every restricted
zone, on a visibility graph. The nodes are each zone's corners, grown
outward by the clearance; an edge exists where the straight line keeps out
of every grown zone; Dijkstra finds the route. Zones are grown by mitring
each corner, so every edge moves out by exactly the clearance (tested on a
clockwise triangle). From Drone3's pad to S3's first lane, the route bends
once, at R1's grown corner (12.9, −17.1): 138.1 m.

**The controller** (`agentic_uav/control/scripted.py`): `plan_mission(brief)`
takes a `MissionBrief` and refuses a `Scenario`, so it cannot be handed the
targets. The whole plan is fixed before take-off, and is identical for every
seed.

* One drone per sector in id order (drone i takes sectors i, i+n, …, so two
  drones take two sectors each).
* Heights 12, 16, 20 and 24 m, Phase 3's live heights.
* Lanes 16 m apart. The detection rule allows at most 17.32 m at 5 m/s;
  95 % of that, rounded up to whole lanes, gives 16 m.
* Routes out and home go round R1 with clearance. A lawnmower lane that
  would pass within the clearance of a zone is refused, not flown.
* Each drone lands on its own pad.
* Before take-off, the plan's battery use and duration are estimated with the
  brief's model, and a plan that would breach the reserve or the deadline is
  refused. The estimates for the canonical brief: 657–807 m per drone, at
  most 199 s, and at most 26.9 % of the battery.

The skills it flies are TAKE_OFF, FOLLOW_WAYPOINTS (out), SEARCH_REGION,
FOLLOW_WAYPOINTS (home) and LAND. Drone1's route out is straight, so it
flies four skills; the others fly five.

**The exit run** (`experiments/search_relay.py`, `scripts/search_relay_exit.py`)
flies the plan on a fresh mock per seed, with the drones placed on their
pads. The trajectories are the mock's exact trace, and each flight is judged
by the evaluator. The seeds are `EXIT_SEEDS` = 1–20, fixed before any was
flown. A seed meets when the mission succeeds **and** every planned skill
succeeded with no safety landing.

**Result: 20 of 20 met** — every criterion passed on every seed. The run
took 5.5 s of wall time and is deterministic (the saved reports match a dry
run seed for seed). The margins:

| | Measured | Required |
|---|---|---|
| Completion | 182.2 s | 900 s deadline |
| Coverage | 0.9995 | 0.95 |
| Lowest battery | 73.9 % | 20 % reserve |
| Closest pair | 3.31 m | 2 m |
| Skill results | 380 of 380 succeeded | — |

What the 20 flights showed, measured:

* **27 of the 40 reports went through a relay**, with no relay logic: the
  detecting drone was out of range of the base and other drones formed the
  chain.
* **Drones detect in transit.** Drone3 made the first report of 5 of the
  11 S1 targets, crossing S1 on its way out.
* **The closest approach is the same on every seed.** Drone1, inbound at
  12 m, passes 3.21 m from Drone2's pad while Drone2 descends through 11.2 m.

Evidence: [`evidence/exit-criterion-mock-2026-10-21.md`](evidence/exit-criterion-mock-2026-10-21.md),
generated from `results/search-relay-exit-mock-20261021-093521-exit.jsonl`.
The run was made on commit `bc12512` with the step-4 files uncommitted.
Provenance records the package digest `3729c0c3d5b1e673`, which the commit
of this step must reproduce.

**The exit can fail**, and tests show it:

* Lanes 20 m apart fail C1.
* A landing that does not land fails C6, and is not counted as met.
* A rescued run — a safety landing, or a skipped skill — is not met, even
  when the mission report succeeds.
* Two drones fly all four sectors and meet it (AUV-05: "two to four drones").

**Tests: 24 new, in `tests/test_scripted.py`** — routing (7), the controller
(7), the exit (8), the script (2).

**Mutations: 21, all caught**, against the full suite. The first pass caught
13 of 22, and the nine survivors were all of two kinds:

* **Hidden by the canonical geometry.** R1 is a square listed
  counter-clockwise, so mitring and orientation changed nothing. The pads are
  the mock's own spawn layout, so skipping placement changed nothing. A lane
  width from the radius alone also rounds to 16 m. New tests use a clockwise
  triangle, pads elsewhere, and a 3 s observation time (7 lanes, 11.43 m).
* **Untested, or not code at all.** Choosing the shorter of two two-corner
  routes round R1 was untested; so was the endpoint check's message (without
  it a route still fails, less clearly), and `skills_ok` on a rescued run. Two
  filters on graph nodes were equivalent: a concave corner is never on a
  shortest route, and a node inside a grown zone can never be joined. Both
  were removed; 22 mutations became 21.

**The goldens did not move.** `record_golden.py --check` matches all four.
430 tests pass, 15 skipped (live only); audit clean.

### 2026-10-21 — step 5, before flying: a corner the lanes missed, the live variant, and the live plumbing

**The live variant failed its mock gate on one seed, and the plan was at
fault.** The first draft of `search_relay_live_small` met 19 of 20 seeds on
the mock. Seed 15 put T2 at (19.62, −25.73), the far corner of S1, and no pass
held it for 2 s. Yet C1 read 1.0: on the 1 m grid the nearest cell centre,
(19.5, −25.5), is held just over 2 s, and the true point, 0.27 m further into
the corner, just under. Measured before changing anything:

| | Coverage, 1 m grid | Coverage, 0.25 m grid | Seeds 1–2000 missing a target |
|---|---|---|---|
| Live variant (first draft) | 1.0000 | 0.9984 | 8 (0.40 %) |
| Canonical | 0.99953 | 0.99951 | 3 (0.15 %) |

The cause was the lane ends. A lane stopped at the sector's edge, and a point
on the edge is in view over a chord centred on it, so a lane ending there
flies only half that chord. Choosing other gate seeds would have been
choosing the evidence, and changing the threshold was ruled out in the plan.
A geometry-only fix can't reach a corner either.

**The fix, in the controller: lanes run on past each end.** The overrun is
v·T/2, 5 m, wherever the zones' 2 m clearance allows; otherwise one end, or
neither (`lane_end_overrun`, `searched_region` in `control/scripted.py`).
`DronePlan.searched` records each sector's flown extent. For the canonical
plan, S3 and S4 run on at both ends (115 to 205). S1 and S2 run on at x = 120
only (to 125): 5 m back from x = 40 would come within 2 m of R1's grown edge
at x = 37.

| After the fix | Coverage, 0.25 m grid | Seeds 1–2000 missing a target |
|---|---|---|
| Live variant | 1.00000 | 0 |
| Canonical | 0.99978 | 1 |

The canonical miss left is at S1/S2's x = 40 end, the one the zone stops
from running on.

**The canonical exit was flown again with the fix**
(`results/search-relay-exit-mock-20261021-183608-overrun`): 20 of 20, every
criterion on every seed, 380/380 skills.

| | Before the fix | After |
|---|---|---|
| Completion | 182.2 s | 192.1 s |
| Coverage | 0.9995 | 0.99977 |
| Closest pair | 3.31 m | 3.36 m |
| Lowest battery | 73.9 % | 72.4 % |

The step-4 evidence stands for the code that produced it. The re-run is a
dated note at its foot, not an edit.

**The live variant** (`configs/scenarios/search_relay_live_small.toml`)
keeps the canonical file's rules and changes only the geometry, the team,
the radio range and the deadline:

* **Two drones** on the first two spawn pads, at 12 and 16 m. Drone2 is
  spawned at runtime, as in M09.
* **Two sectors, each 18 × 16 m.** One lane each, at y = ±18, flown from
  x = −8 to 20: the sectors end 5 m short of that, so the overrun stays
  inside the flown path.
* **R1 sits across Drone1's straight line** to its lane start; the route
  bends at R1's grown corner (0.1, −11.1).
* **A 20 m radio from a base at (−6, 0).** It reaches the lane starts but not
  the far ends.
* **A 300 s deadline.**

Every point of both paths lies in x −8…20, y ±18, at most 26.9 m from the
origin. Those are the four corners of a box whose corners M09 and M10 reached
live: about (21, −21), (22, 17), (−9.5, 18) and (−6, −17.5). The middle of the
box is crossed by Phase 3's ±20 m sideways legs. A test holds the plan to
that box.

**Its mock gate** (`results/search-relay-exit-mock-20261021-183614-gate`):
20 of 20 seeds. Completion 31.1 s, coverage 1.0, closest pair 4.0 m, lowest
battery 96.3 %, 180/180 skills. 20 of the 40 reports were relayed.

**The live plumbing:**

* `PollingObserver` keeps raw NED samples. Grounds can be given after the
  flight, and `trajectories_from_samples` rebuilds trajectories from a saved
  record.
* `fly_live`:
  * refuses a scenario whose pads are not the spawn layout;
  * resets the scene, places the drones (`ensure_vehicles`), and starts the
    poller and the Phase 1 `SeparationMonitor`, each on its own connection;
  * flies the plan, then converts the samples with the ground each drone's
    TAKE_OFF measured;
  * puts the monitor's contact times on the flight's clock.
* `LiveFlight` holds what any seed is judged on. `judge(seed)` gives one
  report per layout, `as_json`/`from_json` save and reload it, and
  `compare_to_mock` sets it beside the mock flight of the same plan: off-track
  distance, height error at cruise, pad error, completion, coverage, closest
  pair, battery against the estimate.
* `scripts/search_relay_exit.py --sim airsim` flies once and judges every
  seed. `--judge FILE` re-judges a saved flight.

**C5 no longer counts the spectator camera.** `classify_contact` has long
called it "someone watching". The evaluator had counted it as a collision,
which would fail a live run for being looked at. It now counts drone and
obstacle contacts only, and reports camera contacts in the components.

**Dry run of the live path**, with the mock in real time standing in for
CarlaAir:

* 37.6 s of wall time, every skill succeeded;
* Drone2 spawned at runtime and placed at (4, 0);
* 279 polls per drone, and 20 of 20 seeds met on the one flight;
* the JSON round trip gives the same verdicts.

It is a test, `RealTimeLiveFlightTest`, skipped unless `AUV_SLOW_TESTS=1`.

**Not verifiable before a live run:** the offset that puts the monitor's
contact times on the flight's clock. A mock flight never touches anything
but the ground, so no test sees a mid-flight contact's time.

**Tests: 17 new.** 16 are in `tests/test_live_flight.py`: lane ends (5),
the live flight and its record (10), and the real-time flight (1, skipped by
default). One more is in `tests/test_evaluation.py`, for the camera.

**Mutations: 19, all caught**, against the full suite. The two `fly_live`
mutations ran with the real-time test on. The first pass caught 15. Three
survivors shared one cause: the synthetic flight started at t = 0, so
forgetting to count from the flight's start changed nothing, and nothing
checked which seed's targets were judged. The fourth was that no test asked
for a drone without a ground. The synthetic flight now starts at a 1000 s
clock origin, and both are tested.

Also fixed: `zones =[` in `plan_mission`, a space lost by an earlier edit.

**The goldens did not move.** `record_golden.py --check` matches all four.
447 tests pass, 16 skipped (live, and the real-time test); audit clean.
Committed as `c0e5ac4`.

**Caught before the first live flight: the poller's airborne line.**
Re-reading Phase 3's live numbers before flying: CarlaAir reports a landed
drone 1.16–1.17 m above the ground its take-off measured. The poller called
anything above 0.5 m airborne, so every live drone would have read as still
flying after landing, failing C6 on every live run. The mock never shows
this, because it lands at exactly 0.

The poller's line is now 3.0 m, the skill layer's own
`LANDED_ALTITUDE_M` ("above this, LAND did not land"). The cost is that the
first and last 3 m of each flight count as ground, a second or two of hover
drain. A test lands a polled drone at 1.17 m and requires C6 to pass, and
holds the two constants equal; with the old 0.5 m it fails. 448 tests pass.
Committed as `8a3adb0`.

### 2026-10-21 — step 5, live flight 1: met on all 20 seeds, and the record caught the drones still falling

**The scene.** The user ran CarlaAir with `.\CarlaAir.ps1 Town10HD`, a fresh
launch with `settings.json` declaring Drone1 only. A read-only check:
`vehicles ['Drone1']`, Drone1 at z 29.25, x −0.05, y 0.05, not under API
control.

**The flight**, `python scripts\search_relay_exit.py --sim airsim --scenario
search_relay_live_small --block live1`, at `8a3adb0` with a clean tree →
`results/search-relay-exit-airsim-20261021-185737-live1`. Drone2 was spawned
at runtime and placed at (4.0, 0.0), with Drone1 at (−0.02, 0.02). Every
skill succeeded, and 378 polls were taken of each drone over 41.2 s.

* **20 of 20 seeds met**, judged on the one flight: coverage 1.0, both
  targets detected and reported on every seed, no zone entry.
* **Contacts:** only SM_seaM, the floor mesh at the player start, which
  counts as ground.
* **Closest pair** 4.03 m; **pad errors** 0.34 and 0.17 m.
* **Grounds measured:** 29.245 and 29.282, the values Phase 3 measured under
  these pads.

| | Live | Mock |
|---|---|---|
| Completion | 39.9 s | 31.1 s |
| Max off track | 2.79 / 2.77 m | 0 |
| Median off track | 0.1 m | 0 |
| Battery used, Drone1 / Drone2 | 4.19 / 4.31 % | 3.44 / 3.66 % (estimated 4.13 / 4.40) |

What the polls show of CarlaAir:

* **Overshoot at the lane-end turn.** The drones overshoot by about 1.3 m
  (x 21.3 for a lane ending at 20), and rise 1.5–2 m above cruise height
  there. *(Corrected at the close: the rises also come at the top of the
  climb and at the route's corner, and the 2.8 m maximum off track is the
  arrival home, about 2.8 m past each pad. See the live evidence.)*
* **Landed height varies by drone.** Drone2 reads 1.18 m after landing, as
  Phase 3 measured; Drone1 reads 0.01 m.
* **Live is slower.** Completion was 39.9 s against the mock's 31.1 s.

**What the record got wrong.** The comparison reported a "max height error
at cruise" of 8.9 m and 12.9 m. The raw polls explain it. `ensure_vehicles`
places each drone at NED z = 0, about 29 m up, and waits a fixed 1.5 s. At
the first poll both drones were still falling, at 17.0 and 17.3 m, and they
reached the ground about 2 s later. TAKE_OFF waits for rest before measuring
the ground, so the flight and the grounds were right. But the observation
window began during the fall, which caused three errors:

* the cruise-height window opened as the falling drone passed cruise height;
* the fall counted as airborne time and flown distance, which is most of why
  live battery use (4.19 %) exceeded the estimate (4.13 %);
* the first 2 s of the window are the drop.

No criterion depends on those seconds, so the verdicts stand. The live1
record is kept as flown.

**The fix:** `wait_at_rest`. Before the observer and the flight start,
`fly_live` waits until every drone is at rest, by TAKE_OFF's own rule: z
steady within 0.05 m between polls 0.3 s apart, at most 15 s. How long each
drone took is recorded in the flight's layout. Two tests use a scene whose
drones fall for a while; four mutations, all caught (one with the real-time
test on). 450 tests pass, 16 skipped; goldens unedited; audit clean.
Committed as `2fd0e32`.

### 2026-10-21 — step 5, live flights 2 and 3: 20 of 20 each, repeatable to 0.22 m

The same simulator session, without a restart. Drone2 was left from flight
1, which the leftover-drone check allows because the flight uses it. Both
flights used the same command, with `--block live2` and `--block live3`:

* **Flight 2:** `results/search-relay-exit-airsim-20261021-190637-live2`, at
  `2fd0e32`, clean.
* **Flight 3:** `results/search-relay-exit-airsim-20261021-190827-live3`, at
  `2fd0e32`, recorded as dirty: flight 2's result files were not yet
  committed, and provenance counts untracked files. Its `agentic_uav` digest,
  `2804500b7254c856`, is flight 2's, so the code is the same.

In both:

* **20 of 20 seeds met**, every skill succeeded, contacts only SM_seaM.
* Both drones waited 2.5 s to come to rest before observing began, and the
  first polls read 0.0 m.

| | Flight 2 | Flight 3 |
|---|---|---|
| Completion | 37.5 s | 37.4 s |
| Closest pair | 4.047 m | 4.047 m |
| Pad errors | 0.26 / 0.18 m | 0.32 / 0.17 m |
| Max off track | 2.76 / 2.75 m | 2.78 / 2.74 m |
| Max height error at cruise | 2.48 / 2.07 m | 2.49 / 2.07 m |
| Battery used | 3.83 / 3.92 % | 3.82 / 3.91 % |

For comparison, the mock gives 3.44 / 3.66 % battery used and the plan
estimates 4.13 / 4.40 %. **Flights 2 and 3 repeat each other**: at the same
instant the drones were at most 0.20 and 0.22 m apart, median 0.08 and
0.07 m.

**A range boundary in the record.** On seed 6, Drone1 detected T2 at 13.3 s
in both flights. In flight 2 it was 19.999 m from the base, inside the
radio's 20 m, so T2 was reported at once. In flight 3 it was 20.028 m away,
and the report waited for the way home, at 27.9 s. Three centimetres of drift
moved a report by 14.6 s. The verdict is the same; under degraded
communications it might not be.

The three flights side by side, generated from the records:
[`evidence/live-run-2026-10-21.md`](evidence/live-run-2026-10-21.md).

**Step 5's live run is done: three flights, 60 of 60 seed judgements met.**
The mock exit (step 4, re-met after the overrun) is the exit criterion; the
live flights show the same controller, observer and evaluator working in
CarlaAir. Committed as `0b894e5`.

### 2026-10-21 — close: Phase 4 complete

**The exit holds at the closing code.** The canonical exit, re-run on
`0b894e5` (the closing commit's code, with only this record edited), gave
reports identical, seed by seed, to the saved post-fix run
`search-relay-exit-mock-20261021-183608-overrun`. Neither later fix (the
poller's 3 m line and `wait_at_rest`) touches a mock flight, and this shows
it rather than assuming it.

**What Phase 4 leaves for Phase 5 onwards:**

* **The canonical mission as data.** `search_relay_001.toml` and a strict
  loader, so later factors (network profile, faults, team size, seed) are
  fields in a file, not branches in code.
* **A judge that cannot be argued with.** `observe` and `evaluate` decide
  AUV-05's six criteria from the flown path alone, exactly on the mock and
  by polling live; they never ask a controller what it did.
* **A baseline to beat.** One drone per sector, flown blind: 192.1 s, 20 of
  20 seeds, 27 of 40 reports relayed by accident. Any agent or coordination
  scheme is measured against it.
* **A live path.** `fly_live` and `LiveFlight` fly once and judge any seeds,
  save and re-judge, and set a flight beside its mock twin.

**Test and check totals at close:** 450 tests, 16 skipped (live-only, plus
the real-time flight). The four Phase 2 goldens are unedited through every
step, and the audit is clean. Mutations: 25, 33, 26, 21, 19 and 4 by step
and fix, every one caught; the survivors on the way were each fixed in the
tests or removed as redundant code.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-21 | **Scenarios are TOML** | The project's config format already (`configs/missions/baseline_v1.toml`), parsed by what is installed. YAML, as AUV-05 shows, would add PyYAML to an environment frozen since Phase 1 for clean-clone reproduction. The structure is AUV-05's; converting later, for Hydra, is mechanical. |
| 2026-10-21 | **The exit is the mock, across 20 seeds** | G1 asks whether the mission is feasible, not whether one layout was lucky. The mock is where AUV-19 places the factorial. Town10HD has buildings and nothing avoids obstacles, so the full mission is not flown live; an optional small variant is. |
| 2026-10-21 | **"Reported" means connected to the base, before messaging exists** | A detection counts as reported once the detecting drone is connected to the base — directly or through drones within range — at any time before the mission ends: AUV-05's "eventually synchronized" under a perfect network, and what gives a relay a purpose. Messages arrive in Phase 7. |
| 2026-10-21 | **Line of sight is not modelled** | AUV-05: "if easy". The mock has no obstacles to occlude anything. |
| 2026-10-21 | **The controller gets a brief, never the scenario** | Target positions — and the seed, which with the placement rule would reveal them — are ground truth, for the world and the evaluator only (AUV-06, 6.2), enforced by what the controller is handed. |
| 2026-10-21 | **Facts are solved from trajectories, not sampled** | A tick-sampled world gets dwells, entries and closest approaches wrong by up to a tick, and the step-4 exit turns on exactly those margins (lanes are spaced so a dwell is just over 2 s). Straight legs make each a quadratic root. |
| 2026-10-21 | **Detection is horizontal and needs flight** | The target is a point on the ground and AUV-05 gives a radius, not a cone; lane spacing (step 1) already assumes a horizontal footprint. Height narrowing it would be a sensor model nobody specified. |
| 2026-10-21 | **The battery is recorded, not enforced** | A drone forced down when it runs flat is a fault, and faults are Phases 9–11's. Phase 4 asks whether the mission is feasible; the record says when, if ever, a drone would have stopped. |
| 2026-10-21 | **Radio is 3D, through any drone, flying or landed; reported means a chain at one instant** | A landed drone is still a radio. Information hopping between drones over time is messaging, Phase 7's; until then only an instantaneous chain to the base counts. |
| 2026-10-21 | **Searched means a target there would have been detected** | One rule for coverage and detection, so they cannot disagree; coverage becomes the chance a random target is found. A looser "passed within range" would let a team claim 95 % and still miss a target in it. |
| 2026-10-21 | **Return is to the drone's own pad, within 2.0 m** | The scenario places drones on pads and the base is a radio; half the pad spacing makes the pad unambiguous. Battery at or above the reserve is part of "safely". |
| 2026-10-21 | **Partial scores are reported as components, unweighted** | AUV-14 names a weighted MissionScore but no weights, and Phase 15 forbids choosing metrics after seeing results. |
| 2026-10-21 | **The mock is observed exactly; live is polled** | The mock knows its own motion and records it; a live simulator can only be sampled. The record will say which observer judged each run. |
| 2026-10-21 | **The scripted plan: one drone per sector, its own height, lanes at 95 % of the detection limit, routes with 2 m zone clearance** | The naive allocation AUV-05 names as the baseline; heights already flown live in Phase 3, so crossings never conflict; the 5 % and the 2 m are for live flight, which does not hold a line exactly. |
| 2026-10-21 | **Exit seeds 1–20, fixed before flying; met = mission success and every planned skill succeeded** | Fixed in code before the first run so no seed can be chosen after the fact. A mission rescued by a safety landing is the safety net working, not the script. |
| 2026-10-21 | **Lanes run on 5 m past each sector end, where the zones allow** | The detection rule's own geometry: a point on the edge is in view over a chord centred on it. Found by a corner target the 1 m coverage grid had rounded up; fixed in the plan, not by choosing seeds or moving the threshold. |
| 2026-10-21 | **The live run is two drones in a variant sized to the airspace already flown** | The live run tests the observer, the evaluator and the routing against a real simulator. Two drones do that in the box M09, M10 and Phase 3 flew, without the four-drone plan's 3.3 m pad crossing. |
| 2026-10-21 | **One live flight is judged against every seed** | The controller never sees the targets, so its path cannot depend on them: one recorded flight judged on 20 layouts is the same as 20 flights. Repeats measure the simulator, not the layouts. |
| 2026-10-21 | **The spectator camera is not a collision** | `classify_contact` already says so. Counting it would fail a live run for being watched. |

## Open questions

- **The 3.31 m closest approach on a live run.** On the mock, Drone1's
  inbound leg passes 3.21 m from Drone2's pad while Drone2 descends; that is
  1.3 m clear of the minimum, with no position error. Live, Phase 1 measured
  drift, so a live flight of the full plan could come closer. Not a question
  for the mock exit; the live run flew the two-drone variant, which has no
  such crossing. Open for whenever the four-drone plan flies live.
- **Reports near the radio's edge depend on centimetres.** Live, seed 6's
  report moved 14.6 s on 3 cm of drift (19.999 against 20.028 m). The perfect
  network has a hard range. Phase 10's degraded profiles should decide
  whether range is a hard edge or a fall-off, before any result leans on it.
- **CarlaAir climbs and overshoots at turns, and on arrival home.** Live,
  the drones rose up to 2.5 m above cruise height (at the climb's top and at
  every turn), ran about 1.3 m past each lane end, and about 2.8 m past
  their own pads before coming back to land. Harmless here: detection is
  horizontal, lanes run on 5 m, and the two drones were 4 m apart in height.
  But in the four-drone plan, pads are 4 m apart and heights 4 m apart, so a
  2.8 m overrun towards a neighbour that is rising 2 m would leave little
  room. Fly that plan live only after measuring it.
- **Provenance calls a tree with uncommitted result files dirty.** Flight 3
  recorded `dirty: true` with the same code as flight 2. The package digest
  settled it; a provenance that ignored `phases/*/results/` would not need
  to. This is the Phase 2 "dirty-flag quirk" again.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
