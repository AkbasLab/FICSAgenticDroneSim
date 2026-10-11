# Evaluation metrics (Phase 15)

Every number this project reports is defined here, and every definition has a
tested implementation in `agentic_uav/experiments/evaluation.py`. The ordering
is the point: these definitions were fixed **before** the main experiments were
run. A metric chosen after seeing the results is not a measurement, it is a
decision about which story the results tell.

`tests/test_evaluation.py` checks the registry in `evaluation.py` against the
reported fields in both directions, so a number cannot enter the results
without a definition here, and a definition cannot be orphaned by a renamed
field.

**Units.** Distances in metres, times in simulated seconds, data in bytes.
Scores and rates are fractions in `[0, 1]`, never percentages.

---

## Three conventions that override convenience

**1. Unmeasured is `None`, never zero.** Reporting zero collisions for a run
that never tracked positions is a false claim, and it is the most dangerous
kind, because zero is the number a safe system would produce. Any metric the
run could not produce is `None` and is named in the `not_measured` field, so a
gap in instrumentation appears in the results table instead of appearing as a
favourable value. `SafetyCounts.clean()` returns `None` rather than `True` when
the hard safety counts were not measured.

**2. A failed mission has no completion time.** A run that does not reach the
terminal condition reports `completed=False` and `completion_time_s=None`, with
`timed_out` and the applicable cap recorded separately. If a timeout were
recorded as its elapsed clock, the mean completion time over a set of runs
would *improve* as more of them failed.

**3. Completion is a statement about the mission, not the run loop.** Defining
it as "the agent loop drained" was wrong in both directions: a team stalled in
a repeating objective drains nothing even if the work is finished, and a team
whose agents all exit mid-air drains cleanly having completed nothing. The
terminal condition is: every sector searched, and every surviving vehicle
landed.

---

## Primary metrics

The small set a comparison is argued from.

### 1. Mission completion

```
MissionScore = w1*Coverage + w2*TargetDetection + w3*SafeReturn
w1 = 0.5   w2 = 0.3   w3 = 0.2        (fixed in advance; must sum to 1)
```

The three components are always reported alongside the composite, because a
single score can conceal a run that searched everything and lost an aircraft.
A strict binary `strict_success` is reported as well: every criterion holds,
including that the safety counts were measured and clean.

| Component | Definition |
|---|---|
| `Coverage` | Fraction of required sectors covered to the scenario's `required_coverage` threshold **by a vehicle that actually flew it**. Sectors learned about from a peer's report do not count. |
| `TargetDetection` | Fraction of targets both detected **and** reported to base. Detection without a delivered report is not a completed objective. |
| `SafeReturn` | Fraction of vehicles not deliberately stopped by fault injection that landed at their own home pad. |

Unnormalised or negative weights raise rather than being silently rescaled,
since scores from two differently-weighted runs are not comparable.

### 2. Mission completion time

```
T_completion = t_mission_complete - t_mission_start
```

`None` for a run that did not complete, per convention 2 above.

### 3. Continuity retention

```
ContinuityRetention(c) = MissionScore(c) / MissionScore(nominal)
```

How much capability survives degradation, rather than raw performance under
degradation, which conflates survival with how good the architecture was to
begin with.

`None` when the nominal score is zero: an architecture that failed under
nominal conditions has no capability to retain, and `0/0` is not `1.0`. Values
above 1 are reported rather than clipped — degradation can suppress duplicated
work, and hiding that would hide a real result.

### 4. Recovery time

```
RecoveryTime            = t_replacement_task_accepted - t_failure
ProductiveResumption    = t_first_skill_flown_against_it - t_failure
```

Two numbers, because they answer different questions. Acceptance shows the
coordination mechanism noticed and reacted; the first skill actually flown
shows the team regained capability. A system can do the first quickly and the
second never, and reporting only acceptance would score that as fast recovery.

Acceptance by the lost vehicle does not count. Reassignment of a *different*
task does not count. Both are `None` when no fault was injected, or when
recovery did not occur within the run — which is a result, not a missing value,
and is never filled in with the run duration.

### 5. Safety

Collisions, separation violations, restricted-zone entries, emergency
fallbacks, unsafe proposals, guardian interventions, and the minimum observed
separation for context (no violations at a 3 m minimum reads very differently
at 3.1 m than at 40 m).

Violations are **episode-counted, not sample-counted**: a drone that sits
inside a no-fly zone has committed one violation, not one per sample.
Per-sample counting would make the number depend on the sampling rate, and
`tests/test_evaluation.py` asserts the count is unchanged at four times the
resolution.

A collision is separation below `COLLISION_RADIUS_M = 1.0`, distinct from
violating the scenario's commanded minimum. The simulated vehicles are points,
so this is a modelling threshold and not an airframe dimension.

### 6. Communication overhead

Messages sent and delivered, bytes transmitted, duplicates, expired messages,
link drops, and messages (and bytes) per completed task.

The per-task ratios are `None` when nothing completed. Zero completed tasks
with hundreds of messages sent is not "efficient", and dividing by zero to get
infinity would sort that run as the worst rather than the undefined one.

Duplicate-message counting is not implemented in the bus, so it is reported as
unmeasured rather than as zero.

---

## Diagnostic metrics

Diagnostics explain a primary result; they never decide which architecture won.
They answer "why" once the primary metrics have said "which". A test asserts no
field is both primary and diagnostic.

Area searched, duplicate search, task reassignments, orphaned tasks, role
changes, role oscillations, stale-message decisions, invalid LLM outputs, LLM
latency (mean and max), LLM calls, fallback-policy use and rate, tokens
consumed, energy used, distance travelled, conflicting task claims.

A **role oscillation** is a return to the role a vehicle just left, counted
because a team that thrashes between roles can look identical to a stable one
on any end-of-run metric.

`conflicting_task_claims` is `None`, not 0, for architectures with no
allocator: a centralized or non-coordinating architecture cannot have a claim
conflict, and zero would invite the reading that it avoided them.

### Coordination efficiency

```
CoordinationEfficiency = UniqueProductiveWork / TotalWork
```

For area search, newly searched cells over all cells searched including
repeats. A team that searches the same sector twice scores 0.5 even though its
coverage is perfect — this is the measure that separates "the work got done"
from "the work got divided". `None` when no work was performed, because 0/0 is
undefined and 1.0 would rank an idle team as perfectly coordinated.

---

## Where the safety numbers come from

Separation, collisions, restricted-zone entries and distance travelled are
geometric facts about where the vehicles went, and cannot be recovered from the
decision logs. They are computed from the **flown track**, recorded by the
adapter: one sample per leg endpoint.

The adapter is the only component that knows where a vehicle actually is and
when, which makes it the only honest place to record this. One sample per leg
endpoint is both the finest available resolution and exactly the right one: the
mock moves in a straight line at constant speed between endpoints, so a
position interpolated inside a leg is a position the vehicle really occupied.

Sampling from the agent loop instead — the first implementation — was wrong in
the dangerous direction. Simulated time advances one whole skill at a time, so
a 70 s area sweep appeared as two samples 70 s apart; interpolating across it
drew a straight line through a lawnmower pattern, placed two drones on the same
invented point, and reported **ten collisions in a run that had none**. An
adapter that records no track contributes nothing rather than a coarse
approximation, so a metric computed from these is either right or absent.

---

## A limitation this work surfaced

The runtime guardian's `separation` check compares the **destination waypoint**
against **believed** peer positions, skipping records it considers stale. Three
consequences follow, and `tests/test_evaluation.py` pins all three so they stay
visible:

1. Only the endpoint is checked, so two crossing paths with distant endpoints
   are each approved. Measured: two drones passing within 1.88 m under a 3 m
   minimum, with zero guardian interventions.
2. With no fresh peer positions the check returns `passed=True`. The pass is
   vacuous — it means "nothing known", not "separation assured".
3. The check therefore weakens precisely when communication is worst, which is
   when the risk is highest.

Fleet-level separation assurance does not follow from per-command, per-agent
separation checking on believed positions. Two commands each safe in isolation
can be unsafe together. This is a design finding rather than a defect to patch
quietly, and it belongs in the write-up.
