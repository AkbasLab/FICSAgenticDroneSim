# Phase 6 — Create a structured belief state for every drone

**Stage:** 2 · One agent · **Vault note:** `AUV-06 — The Persistent Agent Loop`
**Started:** 2026-10-22 · **Completed:** —

> Before drones talk to each other, each must hold what it believes in a form
> that can be read back: about itself, its mission, the map, its team and its
> link, what it is assuming, and how old each piece is. AUV-06: "Do not use the
> LLM conversation transcript as the primary memory." Phase 7's messages,
> Phase 10's degraded links and Phase 16's trace inspection all land in it.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **6.1** Define the belief-state schema — `self`, `mission`, `local_map`, `team`, `communication`, `assumptions`
- [ ] **6.2** Distinguish truth from belief — ground truth to the simulator and evaluator **only**; agent belief from local sensing and received messages **only**
- [ ] **6.3** Handle stale information — every teammate record carries timestamp, age, confidence, source, expiration

## Exit criterion

> The experiment logger can show, for each decision, **exactly what the agent
> knew and what it did not know**.

**Met:** no · **Evidence:** —

Planned evidence: a knowledge log for every decision of the single agent's 20
exit seeds, and of a two-drone run of two independent agents: what each knew
(every field with its age and source), what it marked unknown, and — joined
afterwards, outside the agent — the truth gap: targets present but not yet
seen, and where teammates really were.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The full belief schema | `agentic_uav/agents/belief_state.py` | **Done** 2026-10-22; goldens unedited; Phase 5's decisions unchanged |
| Stale information: teammate records | `agentic_uav/core/team.py`, `agentic_uav/agents/belief_state.py` | **Done** 2026-10-22; goldens unedited; Phase 5's decisions unchanged |
| The boundary, hardened | `agentic_uav/agents/`, `tests/` | step 3 |
| Assumptions, recorded by the policy | `agentic_uav/agents/rule_policy.py` | step 4 |
| The knowledge log and the exit | `agentic_uav/experiments/`, `scripts/`, `results/`, `evidence/` | step 5 |
| Optional live flight; close | `results/`, `evidence/` | step 6 |

## Plan

Approved 2026-10-22 with all five recommendations. Each step lands as its own
commit after the user's go-ahead; the four Phase 2 goldens must still pass
unedited, and Phase 5's decisions must not change.

1. **The record and the full schema (6.1).** The `team`, `communication` and
   `assumptions` blocks added to Phase 5's belief. `self` gains velocity and
   heading (estimated from its own positions) and health (from its own skill
   results); `local_map` gains the restricted zones from the brief. Phase 5's
   exit re-run: decisions and reports identical.
2. **Stale information (6.3).** A teammate record carries timestamp, age,
   confidence, source and expiration; an intake, `receive(report)`; expired
   records kept but never treated as current.
3. **The boundary, hardened (6.2).** Found while planning: the agent holds
   the executor, whose runner holds the adapter, which holds the mock world,
   so `agent.executor.runner.vehicle` leads to ground truth. The agent gets a
   narrow executor handle (`start`, `abort`, `current`, `busy`, `wait`); the
   static check also bans dunder escapes (`__closure__`, `__self__`,
   `__globals__`, …) and `gc`, `inspect`, `ctypes` in `agents/`; a runtime
   test walks the agent's attributes and must reach no world, scenario or
   adapter.
4. **Assumptions.** The rule policy records what each decision assumed:
   statement, evidence, timestamp, confidence.
5. **The knowledge log (the exit).** For each decision: what the agent knew,
   with each field's age and source; what it marked unknown; and the truth
   gap, computed afterwards outside the agent. The single agent's 20 seeds,
   plus a two-drone run of two independent agents (no messaging yet).
   Evidence generated from the records.
6. **An optional live flight with the knowledge log; the close.**

**The five recommendations:**

1. The team block gets its intake and staleness now, fed only by tests. The
   network that fills it is Phase 7's; faking messages here would hollow out
   Phase 7's exit ("team beliefs update only on delivery").
2. Latency, loss and connected peers are **unknown** until Phase 7, never
   zero. Only base reachability comes from sensing.
3. Estimates are labelled as estimates, with their source.
4. "Did not know" has two parts: the unknowns the agent itself records, and
   the truth gap computed after the run, which the agent never sees.
5. The executor handle and the dunder ban close the gap above, as part of 6.2.

## Record

### 2026-10-22 — the plan, approved before it was shown

The plan above was approved before its text had reached the screen: the
message proposing it ended at the question, and the plan existed only in my
working notes. It is the third time (the Phase 5 plan and its step 6 were the
others). The user was told at once, the plan was shown in full in the next
message and written here before any code, so it can still be read and changed.
From now on the plan text goes in the message before the question.

### 2026-10-22 — step 1: the full belief schema (6.1)

**The six blocks** (`agentic_uav/agents/belief_state.py`, schema version 2;
Phase 5's three blocks were version 1):

| Block | Holds | From |
|---|---|---|
| `self` | position, **velocity**, **heading**, battery, **health**, current skill and task, home, base link | readings; velocity and heading **estimated** from its own successive positions and labelled so; health from its own skill results |
| `mission` | id, objective, **constraints**, deadline, progress | the brief (zones, reserve, separation, deadline); its own decisions |
| `local_map` | searched regions, observed and reported targets, known hazards, **restricted zones** | readings; the brief |
| `team` | one entry per teammate on the brief's roster, each "never heard" | the brief's roster; filled from Phase 7 |
| `communication` | base reachable, and for how long; latency, loss rate, connected peers | sensing for the base; the rest **unknown** until Phase 7 |
| `assumptions` | key, statement, evidence, age, confidence; a newer one replaces the older by key | the agent's own decisions (the rule policy records them in step 4) |

* **Unknown is said, not zeroed.** The snapshot writes `"unknown"` for
  velocity and heading before they can be estimated, for heading when slower
  than 0.2 m/s, and for latency, loss rate and connected peers. A zero would
  claim a perfect link.
* **Health counts each ended skill once.** Failed and timed-out skills count;
  the agent's own aborts do not. `degraded` is set by a failure and cleared
  by the next skill that ends well. The observation now carries the latest
  skill's name (`last_skill`), so health can say which skill failed.
* **Velocity from a repeated instant** is left as it was rather than divided
  by zero.

**Phase 5's decisions did not move.** Its exit re-run with the new belief
(`agentic_uav` digest `2252d677e3c846e6`, not kept): on all 25 flights the
decisions, events, verdicts, actions, skills and mission reports are
identical to the run of record `single-agent-exit-20261021-215820-exit`; only
the belief snapshots grew. A test now holds seed 17 to that record.

**Tests: 16, in `tests/test_belief_state.py`:** the six blocks and plain
data; motion unknown until two readings, then estimated (4 m/s along +x,
heading 0; 3 m/s along −y climbing 2 m/s, heading 270); heading unknown when
hovering; no estimate from a repeated instant; health through success,
failure seen twice, abort, timeout and recovery; constraints and zones from
the brief; the roster without itself; the unknowns; the base link and how
long it has held; assumptions replaced, aged, dropped, and confidence kept
in [0, 1]; in a real fault-once flight, health degraded when it retried and
recovered by the search; motion in flight never above the planned speed; and
seed 17 deciding as Phase 5's record.

**Mutations: 20, all caught on the first pass, against the full suite: the velocity's division by time, the heading floor, a repeated instant, the heading's wrap to 0-360, counting a skill twice, timeouts not counted, aborts counted, degraded never clearing, the failure's time, itself on its own roster, unknown written as 0, the link's age and state not updated, an older assumption kept, any confidence accepted, the reserve, the assumption's age, dropping one never held, the zones left out, and the skill's name not passed.**

**The goldens did not move.** `record_golden.py --check` matches all four.
582 tests pass, 17 skipped; audit clean.

### 2026-10-22 — step 2: stale information (6.3)

**What can be told about a teammate** (`agentic_uav/core/team.py`): a
`TeamReport` — the teammate, `at` (when the news was TRUE at its source),
`source` (`message`, `relay` or `base`), `confidence` (0..1, the source's),
`ttl_s` (how long after `at` it may be treated as current; 10 s by default
until Phase 7 sets heartbeat periods), and the content: position, role,
task, status, any of which may be absent. It is the received-messages half of
6.2's boundary, beside `core/sensing.py`, and like it needs nothing from the
simulator (tested). Phase 7's network will deliver these; until then only
tests do, so in every flight the team block stays "never heard".

**What the belief does with one** (`BeliefState.receive(report, now)`,
returning whether it was kept and why):

* **A record carries all five of 6.3:** the report's timestamp, its age now,
  its source, its confidence now, and when it expires (`at + ttl_s`).
* **Age counts from when the news was true, not from when it arrived.** A
  report relayed 7 s late is 7 s old on arrival.
* **Confidence falls linearly with age**, from the source's own value to zero
  at expiry, and stays at zero.
* **An expired record is kept, never current.** The agent can still say what
  it last heard and when; `current_teammates()` leaves it out, and the
  snapshot marks it `current: false`. The tick on which a record expires
  reports it once (`changes["team_expired"]`); fresh news clears that, and
  a later expiry is reported again.
* **Older news never replaces newer.** A report no newer than the one held is
  refused: delivery out of order (Phase 10) cannot roll a belief back.
* **Refused, with the reason:** a report about itself, about a drone not on
  the roster, or dated in the future.

The snapshot shows each teammate as "never heard" or as position, role,
task, status (each "unknown" if absent), source, age, time since receipt,
confidence, time to expiry, and whether it is current.

**Phase 5's decisions still did not move:** its exit re-run (`agentic_uav`
digest `f5a910e23aee77d8`, not kept), on all 25 flights, gave decisions,
events, verdicts, actions and reports identical to the run of record.

**Tests: 9 new, in `tests/test_belief_state.py`:** all five fields on a
record; age from the source's time, for a relayed report; confidence
falling to zero and staying there; an expired record kept but never current;
expiry reported once, and again after fresh news expires; out-of-order news;
the three refusals; a malformed report; and `core/team.py` needing nothing
from the simulator. Also fixed: the boundary check left the file it parsed
open (a `ResourceWarning`), now closed.

**Mutations: 22, all caught.** The first pass caught 21. The survivor: the
snapshot could have called every record's source "message", because the only
test that read the snapshot used a direct message. A relayed report's
snapshot is now checked too.

**A slip of mine, caught before it cost anything.** Checking that the new
test killed the survivor, I restored the mutated `belief_state.py` with
`git checkout`, which put back the last COMMITTED version and silently
dropped step 2's uncommitted work in that file. A copy taken just before the
mutation restored it, identical, and the full suite passed. Mutations are
reverted from the copy taken before them, never from git.

**The goldens did not move.** `record_golden.py --check` matches all four.
591 tests pass, 17 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-22 | **What is not known is written as unknown, never as a default** | A zero latency or loss rate would claim a perfect link, and the knowledge log (step 5) must be able to say what the agent did not know |
| 2026-10-22 | **Velocity and heading are estimates from the drone's own positions, labelled as such** | Sensing gives position, not velocity; deriving it inside the belief keeps the boundary, and the label keeps a reader from taking it for a measurement |
| 2026-10-22 | **A teammate report's age counts from when it was true, and an expired record is kept but never current** | 6.3: "Agents must not treat an old position report as current." Relayed news arrives late, so its arrival time says nothing about its age; keeping the expired record lets the agent say what it last heard, which the knowledge log needs |
| 2026-10-22 | **Older news never replaces newer** | Under degraded links (Phase 10) delivery can be out of order; a late, older report must not roll the belief back |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
