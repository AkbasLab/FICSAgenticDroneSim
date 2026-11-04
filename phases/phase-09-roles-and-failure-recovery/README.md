# Phase 9 — Add dynamic roles and failure recovery

**Stage:** 3 · The team · **Vault note:** `AUV-09 — Roles and Controlled Emergence`
**Started:** 2026-11-04 · **Completed:** —

> Phase 8's drones divide one team mission between themselves; a drone that
> stops reporting loses its task to the pool when its lease runs out. But a
> Phase 8 drone that finishes goes straight home, so in a four-drone mission
> nobody is left to take a task that comes back. Phase 9 gives the drones
> roles -- scout, relay, reserve -- a way to tell from what they hear that a
> teammate is suspect, unreachable or failed, and the behaviour to recover:
> rebid, re-task, or lower the team's ambition when the whole mission can no
> longer be done. Its exit is the study's thesis in one sentence: a drone is
> stopped, and the rest carry on without a new human command.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **9.1** Begin with three roles — `SCOUT`, `RELAY`, `RESERVE`, with defined change triggers
- [ ] **9.2** Implement teammate-failure detection — `HEALTHY` → `SUSPECTED` → `UNREACHABLE` → `FAILED` → `RECOVERED`; **do not declare failure after one missed message**
- [ ] **9.3** Implement recovery behaviour — lease expires, tasks return to pool, drones rebid, reserve→scout, scout→relay, **objective reprioritized if full completion is no longer possible**
- [ ] **9.4** Define controlled emergence operationally — five conditions

## Exit criterion

> During a four-drone mission, one agent can be **intentionally stopped**.
> The remaining agents detect the disruption, reassign its task, and continue
> **without a new human command**.

**Met:** no · **Evidence:** —

Planned evidence: the four canonical drones on `search_relay_001`, seeds
1–20, each seed flown with no stop and with each drone stopped in turn
mid-search, the stopped flights flown twice; every survivor's failure ladder,
the stopped drone's task returned and searched by a survivor, the mission met,
no command after the start. Beside it, a reprioritization flight and the 9.4
report. Optionally, two drones in CarlaAir, one stopped.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Teammate-failure detection (9.2) | `agentic_uav/coordination/health.py`, `configs/recovery/default.toml`, `agentic_uav/experiments/recovery.py` | **Done** 2026-11-04; goldens unedited; Phases 5–8 reproduce |
| Roles and their triggers (9.1) | `agentic_uav/coordination/roles.py`, `agentic_uav/core/messages.py` | step 2 |
| Recovery behaviour (9.3); stopping an agent | `agentic_uav/agents/team_policy.py`, `agentic_uav/coordination/`, `agentic_uav/experiments/` | step 3 |
| The exit; reprioritization; 9.4 | `agentic_uav/experiments/`, `scripts/`, `results/`, `evidence/` | step 4 |
| Optional live flight; close | `results/`, `evidence/` | step 5 |

## Plan

Approved 2026-11-04 with all six recommendations, after it had been shown in
full; the user asked for the whole plan to be built, each step committed, and
to be asked before anything is pushed. The four Phase 2 goldens must pass
unedited after every step, and Phases 5–8's runs of record must still
reproduce.

1. **Failure detection (9.2).** `coordination/health.py`: a ladder per
   teammate -- HEALTHY → SUSPECTED → UNREACHABLE → FAILED → RECOVERED -- from
   messages heard only; thresholds in a manifest
   (`configs/recovery/default.toml`); every transition logged; the belief's
   team view showing each. Tested on scripted heartbeat sequences, including
   one missed heartbeat changing nothing.
2. **Roles (9.1).** `coordination/roles.py`: SCOUT, RELAY, RESERVE and their
   change triggers, as pure functions of the drone's own belief; a payload
   schema for `ROLE_CHANGE`; every change announced and logged.
3. **Recovery (9.3).** The team policy acts on its role: a reserve stays
   available and bids for returned tasks; a scout gives back what it cannot
   finish; a task nobody can still do is abandoned and the team returns its
   partial result. And the experiment's way to stop an agent from outside.
4. **The exit.** The four canonical drones, seeds 1–20; each seed flown with no
   stop and with each drone stopped in turn mid-search (at 60 s), the stopped
   flights flown twice. Checks: detected (every survivor's ladder climbs in
   order, at its thresholds, and never suspects a live drone); reassigned
   (the stopped drone's task returns and a survivor searches it to
   completion); continued (the mission met); no new human command (after the
   start, only the team mission); roles from interactions; deterministic;
   known exactly. Beside it, a reprioritization flight (a drone stopped and
   the deadline cut so its task cannot be redone) and the 9.4 report.
   Evidence generated from the record.
5. **An optional live flight -- two drones, Drone2 stopped mid-search, Drone1
   taking its sector after its own -- and the close.** Ask before tagging and
   pushing.

**The six recommendations:**

1. **The network is Phase 8's: every message delivered.** Silence can then
   only mean a stopped drone; telling a partition from a failure needs a
   network that partitions -- Phase 10. The ladder keeps UNREACHABLE and
   FAILED apart anyway (by time), so Phase 10 can act on the difference.
2. **Thresholds from the 1 s heartbeat:** SUSPECTED after 3 s of silence (the
   heartbeat's lifetime: three missed), UNREACHABLE after 10 s (a lease: its
   task returns to the pool at the same moment), FAILED after 30 s; RECOVERED
   on any message after SUSPECTED or worse, then HEALTHY.
3. **Stopping an agent from outside, at a set time:** it stops deciding and
   talking, its running skill is aborted, the drone holds where it is -- a
   companion computer dying while the autopilot holds. No agent code knows
   about it.
4. **Roles.** SCOUT: holds a task. RESERVE: no task while teammates still work
   -- it holds where it finished, bids for anything returned, and goes home
   when its book shows every task complete or its battery or time say so
   (Phase 8 sent it straight home). RELAY: role, triggers (a teammate
   UNREACHABLE but not FAILED, or the base out of reach with sightings
   unreported) and positioning behaviour built and tested at the policy
   level; under Phase 9's network it never triggers in flight -- Phase 10 is
   where it does.
5. **Reprioritization (9.3, step 6):** a task every current bid for which is
   ineligible (battery or deadline) for a bid window is ABANDONED in every book
   (a new status), and the team goes home with what it has -- shown in the
   trouble flight, not the exit.
6. **9.4, honestly:** the five conditions each checked (code-level tests and
   per-flight traces), and two of AUV-19's proxies reported, not claimed: the
   assignment's distance from one-drone-per-sector (Phase 8: all four
   differ, 188.0 s against 192.1), and allocation divergence across seeds
   (zero for these deterministic agents -- said so).

## Record

### 2026-11-04 — the plan, shown before it was approved

The plan above was written out in full in the message that asked for its
approval, and approved with all six recommendations; the user asked for the
whole plan to be built. Phase 8's optional live flight is left for the user to
fly later. No Vega: the agents are rule-based until Phase 12.

### 2026-11-04 — step 1: teammate-failure detection (9.2)

**`coordination/health.py`**: a `FailureDetector` per drone, one ladder per
teammate -- HEALTHY → SUSPECTED → UNREACHABLE → FAILED, and RECOVERED when
heard again. **It is built only from silence**: how long the drone has heard
nothing at all from that teammate, read from the belief's own record of every
arrival (`BeliefState.links`, Phase 7's). A drone cannot see a teammate stop,
only stop hearing it.

* **The thresholds** (`configs/recovery/default.toml`, fixed before any run,
  read strictly by `experiments/recovery.py`): SUSPECTED at 3 s of silence --
  three heartbeats missed, a heartbeat's own lifetime -- UNREACHABLE at 10 s,
  the moment a silent holder's lease lets its task return to the pool, FAILED
  at 30 s. **One missed heartbeat changes nothing.**
* **Rungs crossed in order, each logged** -- when, from what, to what, after
  how long a silence -- even when a tick skipped one.
* **RECOVERED** when a teammate on SUSPECTED or worse is heard again,
  reintegrated rather than treated as a stranger; HEALTHY again once heard
  steadily for the SUSPECTED interval; silent again, it climbs from the
  bottom. A teammate never heard climbs from the start of the flight.
* **The belief shows it**: `communication.teammate_health`, present only for a
  drone that has a detector, so every earlier snapshot -- and every earlier
  run of record -- is exactly as it was; the knowledge log knows its source
  ("its own failure detector, from what it heard").

**Tests: 14, in `tests/test_health.py`:** one missed heartbeat changing
nothing; each rung at its threshold and not before (8, 15 and 35 s for a
teammate silent from 5 s), the others never suspected; a skipped tick
crossing every rung in order; recovering and then healthy; silent again,
climbing from the bottom; never heard, climbing from the start; the owner not
on its own ladder; the JSON; the manifest, thresholds that must rise, a typo
refused; the belief showing the ladder only with a detector; the knowledge
log's source; the detector inside the boundary.

**Mutations: 17, all caught on the first pass.**

**Phases 5–8 reproduce** -- Phase 5's exit, Phase 6's knowledge exit, Phase 7's
exit and gate, Phase 8's exit, all identical. **The goldens did not move.**
904 tests pass, 26 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **Health is read from silence alone, at 3, 10 and 30 s** | A drone cannot see a teammate stop, only stop hearing it; three missed heartbeats, a lease, and three leases keep one missed message from ever counting as a failure |
| 2026-11-04 | **The ladder shows in the belief only for a drone with a detector** | Every earlier agent's snapshot, and every run of record built on it, stays exactly as it was |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
