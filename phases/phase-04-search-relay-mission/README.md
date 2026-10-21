# Phase 4 — Build the canonical search-and-relay mission

**Stage:** 1 · Platform · **Vault note:** `AUV-05 — The Search-and-Relay Mission`
**Started:** 2026-10-21 · **Completed:** —

> One controlled mission that stays fixed while the architecture changes under
> it. Everything in the study is measured against it, so it must be feasible
> before any agent is asked to fly it: AUV-19's gate G1.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **4.1** Define the environment — one base station, four search sectors, two targets, one restricted region, two to four drones, a communication/relay requirement, a deadline, a simulated battery
- [ ] **4.2** Use simulated detection first — detection radius, line of sight if easy, minimum observation period; **no object-detection network at this stage**
- [ ] **4.3** Define mission success — sectors searched or coverage threshold, all targets detected, detections reported **or eventually synchronized**, no restricted-region entry, no collision or separation violation, all functioning drones return
- [ ] **4.4** Put scenarios in configuration files — `scenario_id`, `random_seed`, mission, vehicles, network, faults, restricted zones

## Exit criterion

> A fully scripted, **non-agentic** controller can complete the canonical
> mission.

**Met:** no · **Evidence:** —

Planned evidence: the scripted controller completing the canonical scenario on
the mock across 20 seeds (target layouts), every success criterion passed.
Optionally, the same controller in CarlaAir on a small variant inside the
airspace Phase 1 flew.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Scenario format, validated loader, the canonical scenario | `agentic_uav/core/scenario.py`, `agentic_uav/experiments/scenarios.py`, `configs/scenarios/` | **Done** 2026-10-21; goldens unedited |
| The mission world: targets, detection, restricted zones, battery, connectivity, an observer | `agentic_uav/simulator/` | step 2 |
| The evaluator: one mission report, every criterion | `agentic_uav/experiments/` | step 3 |
| The scripted controller, run across 20 seeds | `agentic_uav/control/`, `scripts/` | step 4 |
| Optional live run; close | `results/`, `evidence/` | step 5 |

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

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-21 | **Scenarios are TOML** | The project's config format already (`configs/missions/baseline_v1.toml`), parsed by what is installed. YAML, as AUV-05 shows, would add PyYAML to an environment frozen since Phase 1 for clean-clone reproduction. The structure is AUV-05's; converting later, for Hydra, is mechanical. |
| 2026-10-21 | **The exit is the mock, across 20 seeds** | G1 asks whether the mission is feasible, not whether one layout was lucky. The mock is where AUV-19 places the factorial. Town10HD has buildings and nothing avoids obstacles, so the full mission is not flown live; an optional small variant is. |
| 2026-10-21 | **"Reported" means connected to the base, before messaging exists** | A detection counts as reported once the detecting drone is connected to the base — directly or through drones within range — at any time before the mission ends: AUV-05's "eventually synchronized" under a perfect network, and what gives a relay a purpose. Messages arrive in Phase 7. |
| 2026-10-21 | **Line of sight is not modelled** | AUV-05: "if easy". The mock has no obstacles to occlude anything. |
| 2026-10-21 | **The controller gets a brief, never the scenario** | Target positions — and the seed, which with the placement rule would reveal them — are ground truth, for the world and the evaluator only (AUV-06, 6.2), enforced by what the controller is handed. |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
