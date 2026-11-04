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
| Roles and their triggers (9.1) | `agentic_uav/coordination/roles.py`, `agentic_uav/core/messages.py` (`ROLE_CHANGE`) | **Done** 2026-11-04; goldens unedited |
| Recovery behaviour (9.3); stopping an agent | `agentic_uav/agents/recovery_policy.py`, `agentic_uav/agents/team_policy.py` (hooks), `agentic_uav/coordination/` (abandoned, finished), `agentic_uav/experiments/recovery.py` (`fly_recovery_on_mock`) | **Done** 2026-11-04; goldens unedited; Phases 5–8 reproduce |
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

### 2026-11-04 — step 2: roles, and what changes them (9.1)

**`coordination/roles.py`**: the three roles, each a pure function of the
drone's own belief -- what its contract-net says it holds, what its failure
detector says of its teammates:

| Role | When | Does |
|---|---|---|
| SCOUT | it holds a task | searches it |
| RELAY | it is free, and a teammate is UNREACHABLE but not FAILED | bridges toward it: holds half way from the base to the teammate's last known position (`relay_point`) |
| RESERVE | it is free, and nothing calls for a relay | stays available for a returned task |

**A task in hand outranks a relay, a relay outranks waiting**: a scout does
not drop its task to relay; free, it may (9.3: "a scout may become a relay if
connectivity is lost"). A drone starts a RESERVE -- told the mission, holding
nothing yet. `RoleKeeper` logs only changes, each with why, and each is
announced in a **`ROLE_CHANGE`** message (a new schema: role, previous, why).

**AUV-09's six triggers, and how each is taken:** remaining tasks (a claim
makes a scout; finished, a reserve); loss of a teammate (its task comes back
through the lease, a reserve bids, a scout again); communication topology (an
unreachable, not failed, teammate makes a free drone a relay; RECOVERED or
FAILED ends it); battery (a drone that can bid for nothing goes home, the
policy's own checks); number of active drones (through the above); a
high-priority target -- **not yet**.

**One part of the plan narrowed, said here.** The plan gave RELAY a second
trigger, "the base out of reach with sightings unreported". Building it showed
it needs a teammate's sightings, and no message carries one yet
(`TARGET_FOUND` has no schema) -- the same reason the high-priority-target
trigger waits. Both are left for the phase that gives sightings a message.
And under Phase 9's network an UNREACHABLE teammate is a stopped one on its
way to FAILED, so a free drone may start to bridge toward it for those twenty
seconds; whether that happens in flight is counted in the exit, not assumed
away.

**Tests: 10, in `tests/test_roles.py`:** the three roles; a task makes a
scout; a task outranks a relay; free with a teammate unreachable, a relay
(the names sorted); free and nothing calling, a reserve; where a relay holds;
the keeper starting a reserve and logging only changes; its JSON; the
`ROLE_CHANGE` message, refused without why, with an empty or no role; roles
inside the boundary.

**Mutations: 10, all caught.** The first pass caught 9; the survivor was a
role allowed to be none, closed by a test.

**The goldens did not move.** 914 tests pass, 26 skipped; audit clean.

### 2026-11-04 — step 3: recovery, and stopping a drone (9.3)

**`agents/recovery_policy.py`**: Phase 8's team policy with a failure
detector, a role and the recovery behaviour -- a new policy, so Phase 8's
flights are untouched (the team policy gained two hooks, `_team_setup` and
`_nothing_open`, its behaviour unchanged and its run of record identical):

* **Its own failure detector and role**, updated every tick; the ladder in its
  belief; every role change announced (`ROLE_CHANGE`) and every one heard
  recorded.
* **RESERVE**: with nothing open but teammates still at work, it holds where
  it is instead of going home -- as long as it could still do one of their
  tasks (its own bid would be eligible) -- and bids for anything returned.
  Phase 8 went home.
* **RELAY**: free, with a teammate unreachable, it flies half way from the
  base to where that teammate was last heard and holds.
* **REPRIORITIZING** (9.3, step 6): an open task that no drone could still
  finish before the deadline -- not it, not a teammate that is not FAILED, from
  where each was last known (a teammate's battery is not on the record, so
  for it only the deadline counts: an optimistic estimate) -- is **ABANDONED**
  in its book (a new task status; `ContractNet.abandon`), and the drones go
  home with the partial result rather than chase it. A later claim may take
  an abandoned task back.

**The recovery itself is Phase 8's**: the stopped drone's lease runs out, its
task returns to the pool one version on, a reserve claims it and becomes a
scout again. **No command is given to anyone after the team mission.**

**Stopping a drone** (`experiments/recovery.fly_recovery_on_mock`, `stop`):
from outside, at a set time -- its agent stops deciding and talking, its
running skill is aborted, the drone holds where it is. No agent code knows
about it. The judge is told which drones were stopped (AUV-05's C6: "all
functioning drones return safely").

**Two flaws found by flying it, fixed:**

* **A false alarm at every landing.** A drone that had landed and ended its
  part fell silent for good, and its teammates climbed it up the ladder --
  and free drones set off to "relay" toward it. A drone that finishes says so
  (its last status: stage "done"); **the detector no longer watches a
  teammate that has reported its part done**, and shows it "finished".
* **The flight's records in thread order.** Drones were listed in the order
  their threads happened to run; they follow the roster now.

**On the mock, every message delivered:**

| Flight | Detected (every survivor) | Reassigned | Result |
|---|---|---|---|
| no stop | no ladder moved | -- | met, 194.1 s (reserves wait for the team; Phase 8 188.0) |
| Drone1 stopped at 60 s | suspected 63.5, unreachable 70.5, failed 90.5 | S3 to Drone4, a reserve since 118.5 s, claimed at 119.6 | met, 309.1 s |
| Drone3 stopped at 60 s | the same | S1 to Drone4 | met, 309.1 s |
| Drone1 stopped, deadline 250 s | the same | S3 abandoned in every survivor's book at 69.0 s, nobody chasing it | not met: S3 0.387 covered -- the partial result, as intended |

**Tests: 21 in `tests/test_recovery_policy.py`; 1 more each in
`tests/test_health.py`, `tests/test_tasks.py`, `tests/test_contract_net.py`.**
No stop: met, the work divided as in Phase 8, no false alarm, finished drones
shown finished, each a scout then a reserve and no relay, reserves at a cost.
A stop: the mission continuing and met, every survivor detecting it at the
thresholds, its task returning to a reserve, no new command, role changes
announced, `met` needing every survivor to end its part, and a stop being only
a stop (no decision after it, its skill aborted, the drone holding). The
deadline cut: the task abandoned in every book, nobody chasing it, every
survivor ending its part before the deadline, the result partial and said so.
The policy's reasoning: nobody can (and a teammate that could keeping the
task, unless it has failed); a reserve staying while teammates work and it
could help, going home when it could not; a relay flying half way and then
holding; the ladder in the belief; a plain task still Phase 5's. And a
finished teammate unwatched; abandoned only from open, a claim taking it back;
the protocol's `abandon`.

**Mutations: 28, all caught.** The first pass caught 27 of 29; one survivor was
a dead guard (removed), the other `met` not needing every survivor to finish,
closed by a test.

**Phases 5–8 reproduce**; the goldens did not move. 938 tests pass, 26
skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **Recovery is a new policy on the team policy, not a change to it** | Phase 8's drones go home when nothing is open; a reserve that stays is new behaviour, and Phase 8's record must stay as it was |
| 2026-11-04 | **A teammate that reported its part done is not watched** | A landed drone falls silent for good; treating that as a failure is the false alarm AUV-09 warns of |
| 2026-11-04 | **A drone is stopped from outside; the judge is told, no agent is** | The thesis is that the team notices on its own; only the experiment and the evaluator may know which drone was stopped |
| 2026-11-04 | **A role is a pure function of what the drone holds and hears** | Roles then result from the agents' interactions and nothing else, which is 9.4's fourth condition |
| 2026-11-04 | **RELAY triggers on an unreachable teammate only, for now** | Its second trigger, and a high-priority target, need a teammate's sightings in a message, which none carries yet |
| 2026-11-04 | **Health is read from silence alone, at 3, 10 and 30 s** | A drone cannot see a teammate stop, only stop hearing it; three missed heartbeats, a lease, and three leases keep one missed message from ever counting as a failure |
| 2026-11-04 | **The ladder shows in the belief only for a drone with a detector** | Every earlier agent's snapshot, and every run of record built on it, stays exactly as it was |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
