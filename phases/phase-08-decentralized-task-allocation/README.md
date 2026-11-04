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

**Met:** on the mock, 2026-11-04 — 20 of 20 seeds passed all seven checks, each seed flown deliberating and
contested and each way twice (80 flights, every message delivered) · **Evidence:**
[`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md).
The optional live flight (step 6) is not yet flown.

Planned evidence: the four canonical agents on `search_relay_001`, seeds
1–20, each seed flown deliberating and contested (simultaneous claims made to
happen), every claim traced to the bids behind it, every sector held by one
drone once conflicts settle, and each flight flown twice to show it is
deterministic. Optionally, two drones dividing two sectors in CarlaAir.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Tasks and the task book (8.1) | `agentic_uav/coordination/tasks.py` | **Done** 2026-11-04; goldens unedited |
| Deterministic bids and their manifest (8.3) | `agentic_uav/coordination/bids.py`, `configs/allocation/default.toml`, `agentic_uav/experiments/allocation.py` | **Done** 2026-11-04; goldens unedited |
| The contract-net protocol (8.2, 8.4, 8.5) | `agentic_uav/coordination/contract_net.py`, `agentic_uav/core/messages.py` | **Done** 2026-11-04; goldens unedited; Phase 7 reproduces |
| Agents that allocate | `agentic_uav/agents/team_policy.py`, `agentic_uav/agents/drone_agent.py` (coordinator), `agentic_uav/experiments/allocation.py` (`fly_team_on_mock`), `agentic_uav/simulator/message_bus.py` (tie order) | **Done** 2026-11-04; goldens unedited; Phases 5–7 reproduce |
| The exit | `agentic_uav/experiments/allocation_exit.py`, `scripts/allocation_exit.py`, `results/`, `evidence/` | **Done** 2026-11-04; exit met on the mock |
| The live path (6) | `agentic_uav/experiments/allocation.py` (`fly_team_live`), `agentic_uav/experiments/allocation_exit.py` (`live_checks`), `scripts/allocation_exit.py --sim airsim` | **Done** 2026-11-04; real-time dry run on the mock passes |
| Optional live flight; close | `results/`, `evidence/` | the close; the live flight not flown |

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

### 2026-11-04 — step 2: deterministic bids, and the manifest (8.3)

**`coordination/bids.py`**: `bid_for(task, bidder, brief, weights)`, AUV-08's
w_d·D + w_b·B + w_l·L + w_c·C + w_r·R, **in seconds until the drone would
finish the task**, every term kept on the bid with the detail behind it
(metres to the task, through it and home, the battery it would cost and
leave, the time left). A `Bidder` is what the drone believes of itself --
position, battery, home, time left, height, speed, committed work,
capabilities -- and nothing more.

* **D** -- to the task's first lane and through its lanes, at the drone's
  speed. **The lanes are the rule policy's own**: `search_lanes` makes the
  same calls in the same order, and a test pins them equal for every sector
  at every drone's height, so the drone that "wins" is the one that would
  finish soonest by the path it will really fly.
* **B** -- the task and the way home costed with the brief's battery model;
  short of the reserve plus the policy's 2 % margin, **not eligible**;
  otherwise 0. The deadline gates the same way, with the policy's landing
  allowance.
* **L** -- seconds already committed; 0 for a free drone (one task at a time).
* **C** -- seconds of the task's lanes beyond the base's radio range, sampled
  every metre: logged, **weighted 0** until Phase 10.
* **R** -- a missing capability makes it **not eligible**; otherwise 0.
* **`rank`**: lowest value first, the vehicle id breaking ties; values are
  compared to the microsecond, so no float noise decides a tie; an
  ineligible bid is never ranked.

**The manifest**, `configs/allocation/default.toml`, fixed today before any
run: w_d = w_b = w_l = w_r = 1, w_c = 0; a bid window of 1 s, progress every
2 s, a lease of 10 s. `experiments/allocation.py` reads it strictly -- every key
required, none unknown, numbers only -- outside the boundary, and hands the
agents an `AllocationConfig`; every run will record it.

**What the bids say at the start of the canonical mission.** From the pads
(x 0, 4, 8, 12): S2 108.0–108.8 s, S1 113.5–114.3, S4 126.8–127.6, S3
129.4–130.3; Drone4, nearest, bids lowest on all four. So a greedy reading of
the full table would give Drone4 S2, Drone3 S1, Drone2 S4, Drone1 S3 -- not
the hand assignment (Drone *i* to S*i*) every earlier phase flew. Whether
the flights agree is step 4's to show.

**Tests: 19, in `tests/test_bids.py`:** a bid costs the policy's lanes; every
term kept and summed; D the seconds to the task and through it (slower costs
more, though not exactly twice -- the lanes depend on the speed); the battery
costed with the way home, eligible with just enough and not with a little
less; each weight weighing its term; nearer bids lower; L the committed work;
C logged and not weighed, S1 only partly beyond the radio; not eligible on
battery, deadline or capability; the same inputs the same bid; the JSON;
lowest wins and the id breaks ties, to the microsecond; an ineligible bid
never ranked; the manifest, typos refused not defaulted, bad values refused,
a manifest by path.

**Mutations: 21, all caught.** The first pass caught 16; the five survivors
were test gaps -- the way home left out of the battery cost, w_d ignored, the
tie rounding (my tie test had the two values the wrong way round), the
radio-range sampling, a bool taken for a number. A first test of mine also
assumed half the speed costs exactly twice the time; the lanes themselves
change with the speed.

**The goldens did not move.** `record_golden.py --check` matches all four.
798 tests pass, 24 skipped; audit clean.

### 2026-11-04 — step 3: the contract-net, as pure logic (8.2, 8.4, 8.5)

**The messages** (`core/messages.py`). Payload schemas for the six `TASK_*`
types: an announcement (task, version, why), a **bid with its five terms**, a
claim (`TASK_AWARD`) **with its bid** -- so a conflict can be settled from the
claims alone -- an acknowledgement naming the holder, a release (why), a
completion. A version is an integer from 1, a progress a fraction, text not
empty. **A holder's progress rides on `STATUS_UPDATE`** as an optional group --
task, version, progress -- that comes all together or not at all, so a drone
holding nothing, and every Phase 7 agent, sends the status update it always
did. Phase 7's two schemas are unchanged, and **its exit and gate re-run
identical** to their records.

**`coordination/contract_net.py`: one drone's side of the protocol**, with no
clock, no bus and no other drone -- messages in, messages to send out:

| AUV-08's step | What carries it |
|---|---|
| an unassigned task is announced | the brief announces the mission's; `TASK_ANNOUNCEMENT` one returned to the pool |
| eligible drones compute a bid | `bids.bid_for`, from the drone's own belief |
| bids are exchanged | `TASK_BID`, every term |
| the best bidder claims | `TASK_AWARD` |
| others acknowledge | `TASK_ACCEPT` |
| the winner reports progress | `STATUS_UPDATE`'s task group, every 2 s |
| the lease expires if reports stop | each drone, from its own book |
| an expired or released task is announced again | `TASK_ANNOUNCEMENT`, one version on |

* **Who claims what.** A drone holding nothing bids for every open task it
  has not bid for and starts its bid window. When the window has passed it
  reads the bids it has heard -- for open tasks, from drones holding nothing
  -- lowest first, ids breaking ties, and gives each task to the best bidder
  not yet given one; if that gives it a task, it claims it. Every drone that
  heard the same bids gives the same answer. **With a window of 0
  (contested), every drone claims at once on its own bids alone.**
* **Duplicate claims, by AUV-08's rules**: a claim for an older version is
  refused; the lowest bid wins; equal bids, the lower id; the losers release
  and bid again for what is left; **every losing claim is logged in every
  book**, the winner's own included, once.
* **Leases.** A claim starts its lease; each progress report renews it from
  when it was sent. A drone that sees a teammate's lease run out reopens the
  task one version on and announces it. A drone that comes back to find its
  task gone learns it from the newer version, and is free again.
* **Endings.** `complete` (the task done, heard by all), `release` (a holder
  that cannot finish gives it back, one version on, and bids for nothing
  more), `stop`. A claim never heard is learned from the holder's progress.
  `idle`: holding nothing, and no open task it could bid a value for.
* **Every claim keeps the bids its claimant had heard** (`claims_made`), so
  the record can trace it.

**A defect of my first version, found by the contested test.** It settled
each claim the moment it arrived, so four simultaneous claims for S2 were
settled one by one: Drone1's book logged "Drone2 displaced Drone1", then
"Drone3 displaced Drone2", then "Drone4 displaced Drone3", and two losers
released naming the wrong winner. The holder came out right; the corrections
log -- rule 5, part of the record -- did not. **A tick's claims are now settled
together, at the start of the next tick**, and every book logs each losing
claim against the true winner.

**Tests: 24 in `tests/test_contract_net.py`, 5 more in `tests/test_messages.py`.**
Drones exchange real messages over a small wire in the test -- what one says
at a tick the others hear at the next, unless the test drops it:

* *deliberating*: every drone gets one task, nobody assigning them -- Drone4
  S2, Drone3 S1, Drone2 S4, Drone1 S3, the greedy reading of step 2's bids;
  every book agrees; 16 bids at 0 s, 4 claims at 1 s, no conflicts; every
  claim made on every bid; each acknowledged by the other three; the lease
  running from the claim, the first report a period on; progress renewing
  every lease over a minute;
* *contested*: all four claim S2 at once; every book logs Drone1–3's claims
  lost to Drone4's by the lowest bid, once; three releases naming Drone4; the
  losers claim again and the same division results; run twice, identical;
* the rules: **equal bids go to the lower id**; **a lost bid makes a conflict
  and the rules settle it**; a claim for an old version refused and logged;
  each losing claim logged once, however late it comes;
* leases: **a silent holder loses its task to the pool** -- announced at
  version 2 within a lease and a tick of its last report; the returned task
  goes to a drone that comes free; the silent one learns it lost it;
* endings: complete, give up, a claim learned from its progress, idle, every
  out a valid message, the JSON; and the schemas: each task message, refused
  for its reasons, progress on a status update, the group all or nothing, a
  heartbeat taking none.

My own test errors along the way, each against what the protocol rightly
did: a bid expected after a give-up when every other drone was busy, a
progress report expected inside 3 s, a lease measured from an acknowledgement
rather than a report, and a silent drone expected to stay free when, free and
still the best bidder, it rightly claimed the new version.

**Mutations: 34, all caught.** The first pass caught 30 of 35. Four survivors
were test gaps -- a losing claim logged more than once, the lease from the
settling rather than the claim, the first report at the claim, an
eligible-but-waiting drone called idle -- closed by the tests above. The
fifth, a released claim dropped from the table, changed nothing (the winner's
always outranks it, and the next version has a fresh table): the line was
dead, and is gone.

**The goldens did not move.** `record_golden.py --check` matches all four.
827 tests pass, 24 skipped; audit clean.

### 2026-11-04 — step 4: agents that allocate

**The agent loop** (`agents/drone_agent.py`) takes an optional **coordinator**
and a new instruction, **`assign_team()`: the team mission, and no task**.
Each tick, after taking in what arrived, it hands the coordinator the task
messages (`TASK_*`, and status updates carrying a holder's progress), sends
what the coordinator says, and turns its news -- a task claimed, lost, nothing
left -- into **`MESSAGE` events, the first time that trigger is raised**. Every
message still counts toward the link estimates; only heartbeats and status
updates make teammate records. Without a coordinator the agent is exactly
Phase 7's.

**The team policy** (`agents/team_policy.py`) is the rule policy, flying as
it always did once it holds a task -- the policy's sector set-up is now one
method, `_prepare`, so it can be handed a sector by the protocol -- with what
is new around it: take off at once on the team mission (the claims settle in
the first seconds of the climb); airborne, go to the task it holds, or hold
in 5 s slices waiting for one, or go home with nothing left; a task lost to a
better claim, drop it; a search done, complete it so all hear; a shortfall or
a give-up, **give the task back** (release) and go home. Flight decisions are
made from the protocol's state, not from the order its news arrived.

**`fly_team_on_mock`** (`experiments/allocation.py`): every drone on the
roster an agent told the team mission, talking, nobody told a sector; each
drone's book, corrections and claims come back with the flight.

**The first flights failed, and the cause is a finding, not a typo.** On the
canonical 100 m radio a drone searching a far sector is out of everyone's
reach for most of its search: its progress reports go unheard, its 10 s
lease runs out while it is still working, and a teammate that has finished
claims the "returned" task and searches it again -- S1 and S4 searched twice,
two drones holding for ever on stale bids, one crash. The plan had said the
flights "only confirm no lease expires under perfect comms", assuming every
message arrives. **The user decided (2026-11-04): the exit flies with every
message delivered** -- the protocol under perfect communication, as the plan
meant -- and one 100 m flight is recorded beside it as a finding; partitions,
and leases under them, are Phase 10's subject.

**Three defects found by flying it, fixed:**

* **A task a teammate completed left its holder crashing.** It went on
  reporting progress on a finished task. Now a completion heard for its own
  task frees it ("lost: completed by …").
* **Stale bids could leave a drone waiting for ever.** A bid heard from a
  drone that then became busy (its claim unheard) or went home kept winning
  the free drone's reading of the table. **A bid now counts only while its
  message is current** (its 10 s time to live), and a drone still waiting
  bids again when its own lapses (`BID_TTL_S`).
* **Two contested flights logged their books in different orders.** Same
  claims, corrections, decisions and division -- but progress reports sent at
  one simulated instant by different drones reached an inbox in thread order.
  **The bus now reads an inbox oldest first, ties by sender, then sequence**
  (`simulator/message_bus.py`); Phase 7's agents, one record per teammate,
  never noticed.

**And one boundary catch.** The team policy first called
`super().__init__` -- a dunder the agents' boundary check refuses. The rule
policy's set-up is now its own method, `_setup`, which both call.

**With every message delivered, on seeds 1–20, deliberating and contested:
all 40 flights met, each sector searched exactly once** -- Drone1 S3, Drone2
S4, Drone3 S1, Drone4 S2, the greedy reading of step 2's bids -- **188.0 s**
against Phase 4's hand assignment at 192.1 s; in every contested flight each
book logs the same three settled conflicts; no lease ran out.

**Phases 5–7 reproduce**, re-run after every change above: Phase 5's exit,
Phase 6's knowledge exit, Phase 7's exit and gate, identical.

**Tests: 27 in `tests/test_team_policy.py`; 2 more in
`tests/test_contract_net.py`, 1 in `tests/test_message_bus.py`.** Flights:
the mission met and the work divided; nobody told a sector; each drone
flying the task it claimed; every book agreeing; no conflict, no lease run
out; the task messages on the record; every decision known exactly; no
slower than the hand assignment; contested -- the same division, every book
logging the conflict by the rules, the losers flying their second claim,
deterministic; and the 100 m radio, kept visible. The policy, one reaction
at a time: the team mission taking off; nothing for it, no take-off; no task,
hold; a claim while waiting; searched with nothing left, complete and home;
searched with work left, wait; a shortfall giving the task back; a task lost
in flight; a second task costed as a trip out to it; nothing left sending a
waiting drone home at once; no estimate on lanes it no longer has; progress
along its lanes; a plain task, Phase 5's; the wiring refused without
coordinator or comms. And a bid counting only while current, a task
completed by a teammate freeing its holder, the inbox's tie order.

**Mutations: 27, all caught.** The first pass caught 22; the five survivors
were test gaps -- a second task costed from the wrong stage, the "nothing
left" news (without it a waiting drone still goes home, a hold later), the
guard that keeps a drone that lost its task from being costed on lanes it no
longer has (removed, it crashes), the progress fraction, the completed-by-a-
teammate fix -- each closed by a test above.

**The goldens did not move.** `record_golden.py --check` matches all four.
857 tests pass, 24 skipped; audit clean.

### 2026-11-04 — step 5: the exit, met on the mock

**`experiments/allocation_exit.py`**: each seed flown **deliberating** (the
manifest's 1 s bid window) and **contested** (no window: every drone claims
at once on its own bids, before any other can arrive), **each twice**, every
message delivered. **Seven checks**, each shown able to fail:

| Check | What it requires |
|---|---|
| met | both flights complete the mission, every drone ending its part itself |
| no central assignment | every drone told the team mission and nothing more; every claim resting on its own bid and the bids it had heard (deliberating: every drone's); the task flown the last it claimed |
| one holder each | every sector searched, each by exactly one drone; every book agreeing at the end |
| conflicts resolved by the rules | contested: at least one simultaneous claim, each settled for the lowest bid (the lower id on a tie), every book logging the same corrections, every loser releasing; deliberating: none |
| leases renewed | no lease run out; every holder reporting from claim to completion with no gap over a period and a tick |
| deterministic | each way flown twice: the same books, division and decisions |
| known exactly | Phase 6's knowledge log passes every decision |

**The run of record** (`results/allocation-exit-20261104-085636-exit`, at
`60496ea` with the step-5 files uncommitted, `agentic_uav` digest
`f85f583549e02b62`, 80 flights, 198.7 s): **20 of 20 seeds passed every
check.**

* **The same division on every seed** -- Drone1 S3, Drone2 S4, Drone3 S1,
  Drone4 S2 -- the greedy reading of step 2's bids: the targets move with the
  seed, the bids do not. Every claim in seed 17 traced to the bids heard,
  each of the 16 matching the bids recomputed from the pads.
* **Every contested flight: four simultaneous claims for S2 at 0 s**, each
  drone on its own bid; Drone4's lowest (107.975 s); every book logging the
  same three losing claims by the lowest valid bid at 0.5 s; the three
  losers releasing at 0.5 s and claiming S3, S4, S1 the same tick -- the same
  division as deliberating.
* **No lease ran out**: every holder's lease renewed in its teammates' books
  at most 2.0 s apart, from its claim to its completion (60–70 renewals each).
* **188.0 s every flight**, against Phase 4's hand assignment at 192.1 s --
  beside it, not a pass condition. 4,410 decisions known exactly.
* **Deterministic**: each way flown twice gave the same books, division and
  decisions, on every seed.

**Beside the exit, the finding** (the run's header, `finding_100m`): the
scenario's own 100 m radio, one flight -- met, but **8 searches of 4 sectors
and 20 lease expiries**, the first at 51 s: a far-sector holder out of
everyone's reach, its lease run out mid-search, its sector searched again.

**Evidence:** [`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md),
generated from the record: every seed's checks; seed 17's bids, claims,
conflict, corrections, releases, second claims and lease renewals; the 100 m
finding. A first version measured "widest gap" across every status update
of the flight (10 s, the periodic ones before and after holding); it now
measures what the check does, a holder's renewals while it holds.

**Tests: 21, in `tests/test_allocation_exit.py`:** every check passes on a real
seed; the flights are what they say, each flown again rather than reused; and
each check failing on that seed altered to break it -- a drone told a sector,
a claim not on its own bid, a deliberate claim without every bid (and the
exit holding the deliberating flight to every bid), flying what it did not
last claim, a sector searched twice, books that disagree, a contested flight
that contested nothing, a deliberating flight with a conflict, a conflict
logged for the wrong winner, a loser that never let go, a lease run out, a
holder gone quiet, two flights that differ, a belief that is wrong, one
failing check failing the seed; the 100 m finding; the script writing its
record, and a failing seed failing the run.

**Mutations: 23, all caught.** The first pass caught 20; the three survivors
were test gaps -- the "flown again" flight being the first one reused, the
exit not holding deliberating claims to every bid, the run's verdict not
following its seeds -- each closed by a test above.

**The goldens did not move.** `record_golden.py --check` matches all four.
878 tests pass, 24 skipped; audit clean.

### 2026-11-04 — step 6: the live path

**`fly_team_live`** (`experiments/allocation.py`): Phase 7's live path with the
team policy -- reset; Drone2 spawned at runtime; both at rest; the poller and
the separation monitor; one agent per drone on its own thread on the real
clock, each skill on its own connection, sensors from the poller; **every
message delivered**, the exit's network. Each drone is told the team mission
and nothing more. It comes back as a `LiveAllocationFlight`, and `as_run`
makes it the exit's `AllocationRun`, so the checks apply unchanged.

**`allocation_exit.py --sim airsim`** flies the live variant's pair
(`search_relay_live_small`, S1 and S2), deliberating, and holds it to **six
checks** -- met, no central assignment, one holder each, no conflict, leases
renewed (a report may come a tick later than on the mock: the real clock's
tick), known exactly within one observed poll of flight -- since determinism
needs a second flight. The mock twin is flown beside it with all seven. The
verdict reads **"Live flight"**, never "Exit criterion".

**The real-time dry run** (the mock standing in for AirSim, 38.3 s): Drone2
spawned at runtime, both finished, each at its own height, **all six checks
passed**. The pair divided the two sectors themselves, **Drone1 S2, Drone2 S1**
-- the bids from pads 4 m apart, at 12 and 16 m.

**Tests: 14, in `tests/test_allocation_live.py`** (2 real time, behind
`AUV_SLOW_TESTS`): the path refusing pads off the spawn layout; a live flight
as a run the checks apply to, both sectors divided, a claim without every
bid failing it, its record; the script's
live record -- six checks for the flight, seven for its twin, the verdict the
flight's and following the checks, a flight that did not finish not met; live
options only live; and, in real time on the mock, the live path and the
script whole.

**Mutations: 16, all caught** -- 11 by the fast tests and 5 (the bus's
range, both drones at one height, the grounds lost, the live slack, the live
tolerance dropped) only by the real-time tests, run for them. The first pass
left one survivor, the live checks ignoring no-central-assignment; the test
for it is above.

**The goldens did not move.** `record_golden.py --check` matches all four.
890 tests pass, 26 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **Each seed is flown deliberating and contested, each twice** | Conflicts must happen to be resolved, so the contested flight makes them; flying each twice is what "deterministically" is checked against |
| 2026-11-04 | **The exit flies with every message delivered; the 100 m radio is a finding beside it** | The user's decision: on the canonical radio far-sector holders go silent, leases expire mid-search and sectors are searched twice -- partitions are Phase 10's subject, and the exit is the protocol under perfect communication |
| 2026-11-04 | **A bid counts only while its message is current** | A bid from a drone that has since become busy or gone home must stop counting, or a free drone can wait for ever; a message's own time to live is the measure |
| 2026-11-04 | **An inbox is read oldest first, ties by sender then sequence** | Thread order decided the order of one instant's messages; a book logging in that order differed run to run |
| 2026-11-04 | **A tick's claims are settled together, at the next tick** | Claims made at one instant are one conflict; settled one by one they leave a log of displacements that never happened |
| 2026-11-04 | **Every losing claim is logged in every book, once** | Rule 5 asks for all corrections; logging only where a book's holder changed would leave the winner's own book silent about the conflict it won |
| 2026-11-04 | **Progress rides on STATUS_UPDATE as an all-or-nothing group** | No type of the thirteen is a progress report; a group present only for a holder leaves every Phase 7 message, and record, as it was |
| 2026-11-04 | **A bid costs the rule policy's own lanes, pinned by a test** | A bid that costs a different path from the one flown would let the wrong drone win; equality is checked for every sector and height |
| 2026-11-04 | **Battery, deadline and capability gate eligibility rather than add a penalty** | A penalty would need a price for running out; there is none worth paying, so an unable drone simply does not bid a value |
| 2026-11-04 | **A task carries a version, one higher each time it returns to the pool** | AUV-08's first conflict rule compares versions; without one a late claim for a task that has since been released and re-claimed would look current |
| 2026-11-04 | **The task id is the policy's own task string, "search S1"** | A claimed task goes to the rule policy as it stands: allocation decides which sector, the Phase 5 policy flies it |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
