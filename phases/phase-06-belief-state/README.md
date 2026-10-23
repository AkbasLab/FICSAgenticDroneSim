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

**Met:** on the mock, 2026-10-23 — 1340 of 1340 decisions, in 40 flights,
logged complete, correct and without a leak · **Evidence:**
[`evidence/exit-criterion-2026-10-23.md`](evidence/exit-criterion-2026-10-23.md).
The optional live flight (step 6) is not yet flown.

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
| The boundary, hardened | `agentic_uav/control/action_executor.py` (`SkillHandle`), `agentic_uav/agents/drone_agent.py`, `tests/test_sensing.py` | **Done** 2026-10-22; goldens unedited; Phase 5's decisions unchanged |
| Assumptions, recorded by the policy | `agentic_uav/agents/rule_policy.py` | **Done** 2026-10-23; goldens unedited; Phase 5's decisions unchanged |
| The knowledge log and the exit | `agentic_uav/experiments/knowledge.py`, `agentic_uav/experiments/single_agent.py` (`fly_agents_on_mock`), `configs/scenarios/search_pair_001.toml`, `scripts/knowledge_exit.py`, `results/`, `evidence/` | **Done** 2026-10-23; exit met on the mock |
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

### 2026-10-22 — step 3: the boundary, hardened (6.2)

**Where the agent could reach the simulator.** A walk of a flying agent's
ordinary attributes and containers (`search S3`, 30 s in, 493 objects) found
exactly one path to a simulator object: `agent.executor.runner.vehicle`, the
mock adapter, and through it the world. It was the one found while planning.
Nothing else the agent held — brief, sensors, belief, policy, clock, trace —
led anywhere.

**The fix: the agent holds a handle, not the executor**
(`control/action_executor.py`). `ActionExecutor.handle()` returns a
`SkillHandle`: the clock and six plain functions — `start`, `abort`,
`current`, `history`, `is_busy` (and a `busy` property), `wait` — built like
`core.sensing.Sensors`, so no attribute leads to the runner (a bound method's
`__self__` would have). `DroneAgent` turns an executor it is given into its
handle and keeps only that; every caller is unchanged. The same walk of the
agent now finds nothing (402 objects).

**The source check refuses the ways round an import ban**
(`tests/test_sensing.py`, applied to every module in `agents/` and to
`core/sensing.py` and `core/team.py`):

* any dunder attribute (`__closure__`, `__self__`, `__globals__`, …): a
  closure or a bound method is how a bundle of functions could lead back;
* the introspection modules `gc`, `inspect`, `ctypes`, `sys`, `importlib`,
  `builtins`;
* the dynamic built-ins `getattr`, `setattr`, `delattr`, `vars`, `globals`,
  `locals`, `eval`, `exec`, `compile`, `__import__`, `breakpoint`.

None of the agent code used any of them. Thirteen new breaches, one per way,
are each caught, so the check cannot pass vacuously.

**A runtime check beside the source check.** `ground_truth_reached(root)`
walks ordinary attributes, lists, tuples, sets and dicts, and reports any
world, scenario, adapter, target, runner, observer or monitor it meets. A
test flies the rule agent 30 s into its search and requires the walk to find
nothing; the same walk from the raw executor finds the runner, and a
simulator object hidden in each kind of container is found, so the walk can
see what it is looking for. What it deliberately does not follow: closures
and other dunder attributes, which the source check forbids agent code to
touch.

**What is still true, and stated rather than hidden:** Python cannot make an
object unreachable. The sensor and handle functions close over the world and
the executor; code that read `__closure__` would get there. The boundary is
that no agent code may, and two tests — one of the source, one of the
running object — make sure it does not.

**Phase 5's decisions still did not move:** its exit re-run (`agentic_uav`
digest `bd3ccb44b2b4dd19`, not kept), on all 25 flights, identical to the run
of record. The real-time live-path test (`AUV_SLOW_TESTS`), which builds the
agent on a live-style executor with a connection per skill, passes with the
handle.

**Tests: 4 new, in `tests/test_sensing.py`:** the handle is functions and the
clock; the handle does what the executor does (start, wait with and without a
limit, busy, abort, history, current); a flying agent reaches nothing of the
simulator; and the walk looks inside containers; plus thirteen more breaches in the
existing check. Also removed while writing it: a skip for `from __future__`
imports that could never matter.

**Mutations: 16, all caught.** The first pass caught 14. Two were untested:
the handle's `wait` ignoring its time limit (nothing called it with one), and
the walk skipping lists (no simulator object sat in one). Each is tested now.
Mutated files were restored from the text read just before, never from git.

**The goldens did not move.** `record_golden.py --check` matches all four.
595 tests pass, 17 skipped; audit clean.

### 2026-10-23 — step 4: assumptions, recorded by the policy

**What the rule policy takes to be true without checking it**, now recorded
in the belief's `assumptions` block where it starts to rely on each
(`agents/rule_policy.py`):

| Key | Statement | Evidence it records | When |
|---|---|---|---|
| `battery_model` | the brief's battery model holds | the brief's drain rates, uncalibrated | an accepted task |
| `hazards` | the brief's zones are all the hazards, 2 m clear is safe | the zones listed; no hazard sensed | an accepted task |
| `reporting` | what it sees reaches the base on the way home — or, if home is out of range, that it may never | home's distance from the base against its radio | an accepted task |
| `teammates` | separation is not its concern | alone on the roster; or who is on it, unheard; or whose reports are current | every decision |
| `speed` | the drone keeps making v m/s for the rest | planned (and why not yet measured), or made good over t s, capped or floored | every estimate |
| `fits` | the battery and the time cover the rest of the task | percent and seconds needed against those left | every estimate that fits; dropped when it does not |
| `retry` | the failure was passing | the failure, and which retry | a retry; dropped on success or when the stage is given up |

* **Confidences are the policy's own, fixed per kind of evidence**
  (`CONFIDENCE`: the brief 0.8, a planned number 0.5, a measured one 0.9,
  alone 1.0, unheard teammates 0.5, a retry 0.5), and not calibrated. `fits`
  is held no more confidently than the speed it was costed at.
* **An unchanged assumption keeps its time**, so its age says how long it has
  been held. In the slow-battery trouble, the drone turned back at 59.5 s on
  a `fits` it had held for 19.5 s: about 62 % needed, from the check at 40 s,
  costed at 2.50 m/s measured over 20 s of search. The next decision no
  longer holds `fits`.
* **It changes no decision.** Phase 5's exit re-run (`agentic_uav` digest
  `71cb73c48559b233`, not kept), on all 25 flights: decisions, events,
  verdicts, actions and reports identical to the run of record.

**Tests: 10, in `tests/test_rule_policy.py` (`AssumptionTests`):** what an
accepted task takes from the brief; a home beyond the radio; teammates
unheard, then heard; an unknown task assuming nothing; the speed planned,
too early to measure, measured, capped and floored; `fits` held, then
dropped for battery and for time; a retry assumed and let go on success and
on give-up; an unchanged assumption keeping its time; and, in a real
slow-battery flight, what the turning-back decision rested on.

**Mutations: 20, all caught.** The first pass caught 19. The survivor: the
short-of-time test never held `fits` before the shortfall, so dropping it
could not be seen; it now checks `fits` is held first. Also: the first run
stopped at its fourth mutant, whose target text I had written with a blank
line the file does not have; the file was untouched, and the rest ran after
every target was checked to occur exactly once.

**The goldens did not move.** `record_golden.py --check` matches all four.
605 tests pass, 17 skipped; audit clean.

### 2026-10-23 — step 5: the knowledge log, and the exit met on the mock

**The logger** (`agentic_uav/experiments/knowledge.py`) sits on the
experiments side of the boundary: it reads a flight's ground truth (`Truth`:
the trajectories, the targets from the seed, the radio links solved exactly,
each drone's detections) and joins it to the belief each decision was made
on. Nothing it computes reaches an agent. For each decision:

* **Known:** every field of the snapshot, by walking it, with its source —
  sensing now, an estimate from its own positions, the brief, its own
  executor, its own decisions, a teammate report, an assumption — and its age
  where it has one (sightings, assumptions, teammate records).
* **Unknown, as the agent records it:** fields held as "unknown" (with why:
  velocity before two readings, heading when hovering, the link's latency,
  loss and peers until Phase 7), teammates never heard, expired teammate
  records, where the targets it has not found are, and sectors it has not
  searched.
* **The truth gap:** each target it has not seen — where, in which sector,
  and when this drone will first see it, if ever — and each teammate's true
  position against what it believed.

**Three checks on every decision:** *complete* (the six blocks; every field
has a known source), *correct* (position, battery and base link match the
truth at that instant within 0.01 m and 0.01 %, since the snapshot rounds;
its sightings are exactly what this drone had detected), and *no leak* (no
unseen target's id or position, no teammate's true position, anywhere in what
it knew).

**Two public facts added to the belief,** so the agent's own record can say
what it does not know: `mission.constraints` now carries the brief's
`targets_to_find` and its sectors. "Where 2 more targets are" and "S2 not
searched" are then the agent's own knowledge of its ignorance, not the
logger's. Phase 5's decisions did not move (exit re-run, digest
`7bb546fe63088f65`: identical on all 25 flights).

**Two independent agents** (`fly_agents_on_mock`, `search_pair_001`: the
canonical mission cut to Drone1, Drone2, S1 and S2, every other value
unchanged, tested). One rule agent per drone, each told only its task,
Drone1 "search S1" at 12 m and Drone2 "search S2" at 16 m, Phase 4's height
spacing; they share the clock and the airspace and hear nothing of each
other. 20 of 20 seeds met, deterministic. In seed 17 they came within
3.25 m of each other at 148 s, on the way home, each holding the other as
"never heard": their heights kept them apart, not anything either knew.
That is the gap Phase 7 onwards exists to close.

**The run of record** (`results/knowledge-exit-20261023-095034-exit`, at
`8a5597f` with the step-5 files uncommitted, `agentic_uav` digest
`7bb546fe63088f65`): **40 of 40 flights met their tasks; 1340 of 1340
decisions passed all three checks** — 471 of the single agent's on seeds
1–20, 869 of the pair's. Every decision of every flight is in the record,
in full (7.3 MB): the claim is "for each decision", so none is sampled.

**Evidence:** [`evidence/exit-criterion-2026-10-23.md`](evidence/exit-criterion-2026-10-23.md),
generated from the record: every flight's counts; one decision in full (the
single agent about to search: what it knew by source, its assumptions, what
it recorded as unknown, and the two targets it had not seen, with when it
would); how the gap closed over that flight; and every decision of the pair
with what each believed of the other against where the other was.

**Two checks of mine were wrong at first, and the agent right each time:**

* **The flight's end.** The last decision, at the landing, failed
  "correct": the belief said the base link was up, the truth said not. The
  flight's last trajectory knot was at 187.49999999999963 s and the clock at
  187.5 s; `Truth` ended the radio picture at the knot. It now takes the
  end from the clock, as the evaluator does, and a test pins the case.
* **A velocity read as a position.** The pair's decision at 154.5 s failed
  "no leak" on every seed: Drone2, descending at `[0.0, 0.0, -1.0]` m/s,
  appeared to know Drone1's true position, over its pad at `[0.0, 0.0, 1.0]`.
  The leak check now leaves its own velocity out — a speed, not a place —
  and a test pins that exact decision. I first described the case as a
  velocity at rest; finding the actual match showed the descent, and the
  comment and test say so.

The completeness check also caught a gap of mine on its first run: the
three link qualities held as unknown had no source in the logger's map.

**Tests: 27, in `tests/test_knowledge.py`:** the pair scenario; the two
agents (each completes its task, its own height, neither ever hears the
other, deterministic, the roster enforced, met needs every agent to finish);
the single log (every decision passes; sources and ages; what it did not
know before searching; one target found, one to find; nothing unseen after;
the first sighting counted from the flight's start, with the whole flight
shifted 1000 s; the last decision at the flight's end; a logged entry read
back the same); the pair log (both pass; in time order across both; a
teammate never heard against where it was; the other's sector unknown; its
own velocity not a teammate's position; a teammate heard, then expired); each
check failing when broken; and the script. Also: `cls.run` in the new tests
shadowed `TestCase.run` again, caught at once and renamed.

**Mutations: 24, all caught.** The first pass caught 19. The five survivors
were test gaps: exactly one target found; an expired teammate record; the
first sighting counted from 0 rather than the flight's start (every mock
flight starts at 0 — the trap Phase 4 met, met the same way); the log's time
order; and a pair run met with one agent unfinished. Each is tested now.
Every target was checked to occur exactly once before the run.

**The goldens did not move.** `record_golden.py --check` matches all four.
632 tests pass, 17 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-22 | **What is not known is written as unknown, never as a default** | A zero latency or loss rate would claim a perfect link, and the knowledge log (step 5) must be able to say what the agent did not know |
| 2026-10-22 | **Velocity and heading are estimates from the drone's own positions, labelled as such** | Sensing gives position, not velocity; deriving it inside the belief keeps the boundary, and the label keeps a reader from taking it for a measurement |
| 2026-10-22 | **A teammate report's age counts from when it was true, and an expired record is kept but never current** | 6.3: "Agents must not treat an old position report as current." Relayed news arrives late, so its arrival time says nothing about its age; keeping the expired record lets the agent say what it last heard, which the knowledge log needs |
| 2026-10-22 | **Older news never replaces newer** | Under degraded links (Phase 10) delivery can be out of order; a late, older report must not roll the belief back |
| 2026-10-22 | **The agent holds a handle of plain functions, never the executor** | The executor's runner holds the adapter, and the mock adapter holds the world: ground truth one attribute chain away. A handle built like `Sensors` gives the agent everything it does with skills and nothing that leads further |
| 2026-10-22 | **The boundary is checked twice: in the source, and on the running agent** | Python cannot make an object unreachable, so the rule is that agent code may not reach through dunders, introspection or dynamic lookups (source check), and that nothing the agent holds through ordinary attributes is a simulator object (runtime walk) |
| 2026-10-23 | **The policy records its assumptions where it starts to rely on them; their confidences are fixed per kind of evidence, not calibrated** | 6.1's assumptions block exists so a reader can audit a decision. Fixed confidences say how much the policy leans on each without pretending to a calibration nothing here has done; an LLM policy (Phase 12) will have to state its own |
| 2026-10-23 | **The knowledge log lives on the experiments side and never reaches an agent** | It reads ground truth to show the gap; if any of it flowed back, the boundary it is there to show would be the first thing it broke |
| 2026-10-23 | **Every decision of every flight is kept in full** | The criterion is "for each decision"; a sample would show only that some were logged |
| 2026-10-23 | **The pair flies independent agents at Phase 4's heights, hearing nothing** | Without messages (Phase 7) a teammate can only be "never heard"; the heights keep them apart while neither knows of the other, which the log now shows |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
