# Phase 8 — Implement decentralized task allocation without an LLM

**Stage:** 3 · The team · **Vault note:** `AUV-08 — Decentralized Task Allocation`
**Started:** 2026-11-04 · **Completed:** —

> Until now each drone was told its sector. Phase 8 tells the team its
> mission and nobody anything more: the drones divide the work between
> themselves, over Phase 7's messages, by a deterministic contract-net --
> announce, bid, claim, acknowledge, report progress, hold a lease. It comes
> before any LLM touches coordination (AUV-08), so that whatever the LLM later
> adds can be told apart from what the protocol already does. Recovery from a
> lost drone (Phase 9) and degraded links (Phase 10) are built on its leases.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **8.1** Represent work as explicit tasks — `MissionTask` with id, type, region, priority, capabilities, deadline, status, assignee, lease expiry
- [ ] **8.2** Implement a contract-net-style protocol — announce → bid → exchange → claim → acknowledge → progress → lease expiry → re-announce
- [ ] **8.3** Compute bids deterministically — distance, battery, workload, communication risk, capability mismatch; **vehicle ID as tie-breaker**
- [ ] **8.4** Add task leases — renewed through progress messages; on expiry the task returns to the pool
- [ ] **8.5** Prevent duplicate claims — version numbers, lowest valid bid, lower agent ID, losers release, **all corrections logged**

## Exit criterion

> Four drones receive **one team mission**, divide the sectors **without a
> central assignment**, complete the work, and resolve simultaneous claims
> deterministically.

**Met:** no · **Evidence:** —

Planned evidence: the four canonical agents on `search_relay_001`, seeds
1–20, each seed flown deliberating and contested (simultaneous claims made to
happen), every claim traced to the bids behind it, every sector held by one
drone once conflicts settle, and each flight flown twice to show it is
deterministic. Optionally, two drones dividing two sectors in CarlaAir.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Tasks and the task book (8.1) | `agentic_uav/coordination/tasks.py` | **Done** 2026-11-04; goldens unedited |
| Deterministic bids and their manifest (8.3) | `agentic_uav/coordination/bids.py`, `configs/allocation/default.toml` | step 2 |
| The contract-net protocol (8.2, 8.4, 8.5) | `agentic_uav/coordination/contract_net.py`, `agentic_uav/core/messages.py` | step 3 |
| Agents that allocate | `agentic_uav/agents/`, `agentic_uav/experiments/` | step 4 |
| The exit | `agentic_uav/experiments/`, `scripts/`, `results/`, `evidence/` | step 5 |
| Optional live flight; close | `results/`, `evidence/` | step 6 |

## Plan

Approved 2026-11-04 with all six recommendations, after it had been shown in
full; the user asked for the whole plan to be carried out, each step
committed, and to be asked before anything is pushed. Each step lands as its
own commit; the four Phase 2 goldens must pass unedited after every step, and
Phases 5–7's runs of record must still reproduce.

1. **Tasks (8.1).** A new package, `agentic_uav/coordination/`, inside the
   agents' boundary. `tasks.py`: `MissionTask` -- AUV-08's fields (id, type,
   region, priority, capabilities, deadline, status, assignee, lease expiry)
   plus a version number -- and `tasks_from_brief`, turning the canonical
   mission's four sectors into four `SEARCH_SECTOR` tasks. Each agent keeps a
   **task book**, its own view, changed only by its own acts and the messages
   it receives.
2. **Bids (8.3).** `coordination/bids.py`: w_d·D + w_b·B + w_l·L + w_c·C +
   w_r·R from the agent's own belief, every term recorded with the bid;
   weights in a manifest, `configs/allocation/default.toml`, recorded with
   every run. Lowest wins; vehicle ID breaks ties.
3. **The protocol, as pure logic (8.2, 8.4, 8.5).** Payload schemas for the six
   `TASK_*` types; `coordination/contract_net.py`: announce, bid, exchange,
   claim, acknowledge, progress, lease, release, re-announce; duplicate claims
   settled by AUV-08's rules (version, lowest valid bid, lower ID), losers
   releasing, every correction logged. Tested on scripted message sequences --
   a lost bid, a simultaneous claim, a lease running out, a stale version --
   with no flight at all.
4. **Agents that allocate.** A team policy: the rule policy taking its sector
   from the protocol instead of `assign()`; task messages that change its book
   become `MESSAGE` events (the first time that trigger is raised). Four
   agents on the mock, one mission, nobody told a sector.
5. **The exit.** Four agents on `search_relay_001`, seeds 1–20, each seed flown
   **deliberating** (a bid window long enough to hear every bid) and
   **contested** (every drone claims at once, before any bid can arrive, so
   simultaneous claims happen on every seed). Checks: met (AUV-05's mission
   success); no central assignment (no agent told a sector; every claim
   traced to the bids its claimant had heard); every sector held by exactly
   one drone once conflicts settle; simultaneous claims resolved by the rules
   -- the same winners every run, losers released, every correction logged;
   leases renewed throughout; deterministic (each seed flown twice,
   identical); known exactly, as before. Phase 4's fixed assignment
   (192.1 s) beside it, for comparison, not as a pass condition. Evidence
   generated from the record.
6. **An optional live flight, and the close.** Two drones dividing S1 and S2
   live, on the variant's 20 m radio, flown by the user on Windows, no Vega.
   Then the record, ledger, index, vault. Ask before tagging and pushing.

**The six recommendations:**

1. **Tasks from the brief.** Four `SEARCH_SECTOR` tasks, identical in every
   book at the start: that is the "one team mission". Relay and inspection
   types are named but not generated -- this mission has neither -- and
   `RETURN_TO_BASE` is what a drone does with nothing left, not a task to
   allocate.
2. **A bid is the expected seconds until this drone would finish the task.**
   D the travel time to it and through it, L the work it has already
   committed to, B making it ineligible if it could not finish and get home
   with its reserve plus margin, C (communication risk) computed and logged
   but weighted 0 under perfect comms until Phase 10, R ineligible on a
   capability mismatch. Weights fixed before any run; never tuned after one.
3. **The six types:** `TASK_ANNOUNCEMENT` for a task returned to the pool (the
   brief announces the first four), `TASK_BID`, `TASK_AWARD` the winner's
   claim, `TASK_ACCEPT` the others' acknowledgement, `TASK_RELEASE`,
   `TASK_COMPLETE`. **Progress rides on `STATUS_UPDATE`** every 2 s while a
   drone holds a task -- its fields present only then, so Phase 7's agents and
   records are unchanged. **Lease 10 s.**
4. **One task at a time per drone;** on finishing, it bids for what is left or
   goes home.
5. **Simultaneous claims are made to happen** (contested flights), so the
   conflict rules are exercised on every seed, not left to chance.
6. **Lease expiry is shown at the protocol level** (step 3's tests); the
   flights only confirm no lease expires under perfect comms. A drone that
   stops is Phase 9's exit, not flown here.

## Record

### 2026-11-04 — the plan, shown before it was approved

The plan above was written out in full in the message that asked for its
approval, and approved with all six recommendations. The user asked for the
entire plan to be done and committed, and to be asked before pushing. No
Vega: the agents are rule-based until Phase 12.

### 2026-11-04 — step 1: tasks, and each agent's own book (8.1)

**`agentic_uav/coordination/`**, a new package, inside the agents' boundary:
its `__init__` says so, and the agents' source check now runs over it too
(`tests/test_tasks.py`). No shared book, and no agent reads another's.

* **`MissionTask`: AUV-08's fields, and a version.** Id, type, region,
  priority, required capabilities, deadline, status (open, claimed,
  complete), assignee, lease expiry -- validated, so an open task has no
  assignee or lease, a claimed one has both, a complete one keeps who did it
  and has no lease. What can happen to a task is a method each: claimed
  (a lease from the claim's time), renewed, completed, and **reopened: back
  in the pool one version on**, so a claim for the old version can be told
  from one for the new (8.5, rule 1). A complete task cannot be claimed or
  reopened; only a claimed one is renewed or completed.
* **The team mission, from the brief.** `tasks_from_brief`: one open
  `SEARCH_SECTOR` task per sector, in the brief's order, version 1, the
  brief's deadline, needing the `search` capability every drone has. Every
  agent derives the same four from the same brief. **The id is the task as
  the rule policy already reads it, "search S1"** -- so a claimed task can be
  handed to the policy as it stands.
* **The types AUV-08 names** -- search, relay point, inspection, return to
  base -- all four named; this mission generates only searches.
* **The task book**, one agent's view: it takes a task as the latest word on
  it, **refuses an older version**, ignores a non-change, and logs every
  change -- when, before, after, why -- so the record can show how each view
  came to be.

**Tests: 18, in `tests/test_tasks.py`:** AUV-08's fields; the types; a claim,
a renewal, completion; back in the pool one version on; what a task cannot
become; seventeen malformed tasks refused; the JSON; one open search per
sector in order, the same for every agent, ids the policy reads, only
searches; the book starting as the mission, a change taken and logged, older
news never replacing newer, no change not logged, an unknown task or a task
twice refused, its JSON; and the package passing the boundary check.

**Mutations: 17, all caught.** The first pass caught 15 of 16; the survivor was
a guard whose refusal the validation behind it would have made anyway, so a
test now asks for the guard's own reason. One assertion was added before the
pass, for a holder filter no test yet exercised.

**The goldens did not move.** `record_golden.py --check` matches all four.
779 tests pass, 24 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **A task carries a version, one higher each time it returns to the pool** | AUV-08's first conflict rule compares versions; without one a late claim for a task that has since been released and re-claimed would look current |
| 2026-11-04 | **The task id is the policy's own task string, "search S1"** | A claimed task goes to the rule policy as it stands: allocation decides which sector, the Phase 5 policy flies it |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
