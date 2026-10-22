# Phase 5 — Replace one-shot planning with a persistent single-drone agent

**Stage:** 2 · One agent · **Vault note:** `AUV-06 — The Persistent Agent Loop`
**Started:** 2026-10-21 · **Completed:** —

> Before any team, and before any LLM: one drone that is given a task, not
> a list of actions, and works out each next step itself — noticing when a
> skill succeeds or fails, when it sees a target, when its battery runs
> down — and decides what to do about it. AUV-06: "Do not move directly from
> static plans to multi-agent LLM negotiation. First build one reliable
> closed-loop agent."

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **5.1** Implement the agent lifecycle — Observe → Update belief → Select objective → Choose skill → Validate → Execute → Verify
- [ ] **5.2** Make replanning event-driven — nine triggers; **low-level motion must never depend on LLM response time**
- [ ] **5.3** Implement a deterministic policy first — accept a task, navigate, search, report, return home, react to low battery, recover from a failed skill

## Exit criterion

> One deterministic persistent agent completes a search task **without
> receiving a complete preflight action list**, recognises success or
> failure, and decides what to do next.

**Met:** on the mock, 2026-10-21 — 20 of 20 seeds completed from the task
alone; 5 of 5 kinds of trouble recognised and answered as fixed beforehand ·
**Evidence:** [`evidence/exit-criterion-2026-10-21.md`](evidence/exit-criterion-2026-10-21.md).
The optional live run (step 6) is not yet flown.

Planned evidence: the rule-based agent, given only a search task, completing
it on the mock across 20 seeds, judged by Phase 4's evaluator. Then the same
agent under injected trouble — a failed navigation skill, a battery running
low, a target sighted mid-search — with its decision trace showing what
triggered each decision and what it chose. Optionally, a small live run.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Sensing behind the truth/belief boundary | `agentic_uav/core/sensing.py`, `agentic_uav/simulator/sensing.py` | **Done** 2026-10-21; goldens unedited |
| A non-blocking action executor | `agentic_uav/control/action_executor.py` | **Done** 2026-10-21; goldens unedited |
| Events, a minimal belief, and the agent loop | `agentic_uav/core/events.py`, `agentic_uav/agents/` | **Done** 2026-10-21; goldens unedited |
| The rule-based policy | `agentic_uav/agents/rule_policy.py` | **Done** 2026-10-21; goldens unedited |
| The exit: nominal and injected-trouble runs | `configs/scenarios/search_single_001.toml`, `agentic_uav/experiments/single_agent.py`, `scripts/single_agent_exit.py`, `results/`, `evidence/` | **Done** 2026-10-21; exit met on the mock |
| Optional live run; close | `results/`, `evidence/` | step 6 |

## Plan

Approved 2026-10-21 with all five recommendations. Each step lands as its own
commit after the user's go-ahead; the four Phase 2 goldens must still pass
unedited. Module names follow AUV-03's tree (`agents/drone_agent.py`,
`agents/belief_state.py`, `agents/rule_policy.py`, `core/events.py`,
`control/action_executor.py`).

1. **Sensing behind the boundary.** What a drone can know while it flies:
   its own position and whether it is airborne, its own battery, the targets
   it has itself sighted (Phase 4's detection rule, applied as the flight
   goes), and whether it can reach the base by radio. Agent-facing types in
   `core`; the mock's implementation on the simulator side, computed from the
   world's exact trace up to the present instant.
2. **A non-blocking action executor.** One skill at a time on its own
   thread, with its status readable at any moment and an abort, so the agent
   can react while a skill is still flying.
3. **Events, a minimal belief, and the agent loop.** AUV-06's nine replanning
   triggers as events (the team and network ones defined, raised from Phase 7
   on), plus a slow periodic check. The lifecycle — Observe, Update belief,
   Select objective, Choose skill, Validate, Execute, Verify — run only when
   an event fires. A belief holding AUV-06's first three blocks (self,
   mission, local map). A validation step with basic checks (zones, reserve,
   altitude); the guardian proper is Phase 11. A trace of every decision.
4. **The rule-based policy (5.3)**: accept a search task, route to the
   sector, search it, report, return home, react to low battery, recover from
   a failed skill.
5. **The exit.** A single-agent scenario; the agent given only its task,
   across 20 seeds on the mock; then injected trouble, one kind at a time.
6. **Close**: an optional live run, the record, the vault report, the tag.

## Record

### 2026-10-21 — the plan, written down after it was approved

The plan above was approved before its text had been shown: the message
proposing it ended at the question, and the plan itself never reached the
screen. It was written into this record first thing in step 1, and the user
was told so in the same message, so it can still be read and changed.

### 2026-10-21 — step 1: sensing behind the truth/belief boundary

**What a drone can know, as types** (`agentic_uav/core/sensing.py`):

* `OwnState`: time, x, y, altitude above the measured ground, and airborne.
* `Sighting`: label, x, y, and when it was made.
* `Sensors`: the bundle an agent is handed. It is a drone name and five
  functions of the present instant: `now`, `own_state`, `battery`,
  `sightings` and `base_link`.

The types live in `core`, so the agent side and the simulator side can both
use them while `simulator/` still depends on `core` alone.

**How the mock builds them** (`agentic_uav/simulator/sensing.py`,
`mock_sensors(world, scenario, drone, start)`). Each reading is Phase 4's own
rule, applied to the world's exact trace up to the present instant:

* **own state**: the drone's position at this instant, and its landed flag;
* **battery**: `mission_world.battery` over the drone's path since `start`;
* **sightings**: `mission_world.detections` over the drone's **own** path
  only, so a target another drone held is not this one's sighting. Each
  carries the target's label and exact position (Phase 4 has no perception
  error), and nothing about targets not yet seen, nor how many exist;
* **base link**: the radio graph at this instant (every scenario drone plus
  the base, links within range in 3D), and whether it joins this drone to
  the base.

**`mock_trajectories(..., until_now=True)`** adds a knot at the present
instant, where the drone is now. Mid-move, the trace's last knot is where the
move began, so a reading taken in flight needs it. The trace and the present
position are read under one lock, at one instant.

**The boundary, in code** (decision 2 of the plan):

* **The bundle is bare.** `Sensors` holds only a name and plain functions.
  The world sits in their closures, so no attribute leads to it. `now` is a
  function rather than the clock's bound method, whose `__self__` would have
  led back to a world object; that was changed during this step, and a test
  checks every field.
* **`agentic_uav/agents/` exists now**, with only its docstring stating the
  rule. A test reads every module in it and refuses:
  * any import from `agentic_uav.simulator` or `agentic_uav.experiments`;
  * the names `Scenario`, `TargetSpec`, `place_targets`, `MockWorld`;
  * any read of `.random_seed`.

  The same check is fed five files that break the rule, so it cannot pass
  vacuously. `core/sensing.py` is held to it too.

**Readings mid-skill agree with the evaluator.** A test flies a drone on one
thread while a second thread, on the same simulated clock, reads its sensors
every 0.5 s across four skills. At every reading:

* the position is where the trajectory was at that instant;
* the battery equals Phase 4's battery over [start, now], and only falls;
* a sighting appears exactly once its detection time has passed, and not
  before;
* the base link equals Phase 4's `Connectivity` at that instant, and is both
  true and false during the flight.

Other tests cover a sighting being one drone's own, the base reached through
a second drone (150 m out, through one at 70 m) and not without it, the
scenario's drones only, and counting from the moment asked.

**Tests: 15, in `tests/test_sensing.py`. Mutations: 12, all caught on the
first pass**: the first knot for the position, the path stopping at the last
knot, the battery from time zero, every drone's sightings, a sighting
without position, no relays, the range doubled, any drone accepted, missing
drones accepted, the clock's bound method handed out, the present never
added, and the present always airborne.

**A slip of mine, again:** a test edit sent through a shell heredoc lost its
`\n` escapes and broke the file before anything ran. Fixed with the editor.
Python source no longer goes through heredocs.

**The goldens did not move.** `record_golden.py --check` matches all four.
465 tests pass, 16 skipped; audit clean. Committed as `5a2e89f`.

### 2026-10-21 — step 2: the action executor — a skill flies on its own thread while the agent watches

**`ActionExecutor`** (`agentic_uav/control/action_executor.py`) runs one
drone's skills one at a time, each on its own thread.

* **`start(command)`** returns at once with an `Execution`: serial, command,
  start time, and then the result, or the error if the skill's thread itself
  raised. A second start while one runs is refused (`ExecutorBusy`): to
  change course, abort, then start.
* **`current()`**, **`history()`** and **`busy`** are readable at any moment.
* **`abort()`** stops the running skill through Phase 3's
  `SkillRunner.request_abort`, so the drone holds where it is. It records
  `abort_requested`, and returns False when nothing is running. Live, pass
  `abort_via`, an adapter on the agent's own connection.
* **`wait(timeout_s)`** sleeps on the clock in 0.1 s slices until the skill
  ends; **`close()`** joins the thread, from outside the simulated timeline.

**Built for the shared simulated clock:**

* **The skill's thread joins the timeline before `start` returns.**
  Otherwise the agent could fall asleep first and time would jump with
  nothing flying.
* **A waiting agent sleeps on the clock rather than blocking on the
  thread**, because a participant that blocks stops time for everyone.

On a real clock the same code runs unchanged; a test flies a short leg with
the mock in real time, and `start` returns in under 0.2 s.

**One change to Phase 3's `SkillRunner`.** `run` cleared any pending abort as
it began. An abort asked for between `start` returning and the skill's thread
reaching `run` would be silently lost, and on the simulated clock that window
is real. `run` now takes `clear_abort` (default True, as before), and
`clear_abort()` is public. The executor clears once, before the thread
starts, and runs with `clear_abort=False`. Every existing caller is
unchanged, and so are the goldens.

**The agent notices an ending within one slice.** Through the executor, a
skill flies exactly as when called directly: the same outcomes, durations and
final positions, tested across five skills. The one difference is that each
next skill starts up to 0.1 s after the last ended, because `wait` checks
every 0.1 s. That is the agent's reaction time, during which the drone
holds. The first version of that test expected identical start times and
failed on exactly this; it now asserts the bound. Waking the agent at the
exact instant would need a new kind of sleep in `SimClock`, not worth 0.1 s.

**Tests: 15, in `tests/test_action_executor.py`**, stable over repeated runs:

* starting and watching mid-skill;
* the same flight as direct calls;
* determinism;
* an abort mid-leg stops within a tick and holds;
* an abort the instant a skill starts (20 runs, then forced);
* nothing to abort, before and after a skill;
* the skill after an aborted one runs;
* one at a time; `wait` giving up; a raising thread recorded, not lost;
* `SkillRunner`'s `clear_abort`;
* real time.

**Mutations: 10, all caught.** The first pass caught 6. Three of the four
survivors were races the tests never forced:

* **`start` not waiting for the thread to join.** In practice the thread
  joins in time anyway. A clock whose participants pause before joining now
  forces it.
* **An instant abort being cleared away.** The thread usually cleared first.
  A runner that pauses before running now makes the abort certain to arrive
  first.
* **A stale abort killing the next skill at birth.** This is a real bug if
  the guard goes, and no test had started a skill after an aborted one.

The fourth: `abort()` returning True after a skill had already ended, which
no test had covered.

**The goldens did not move.** `record_golden.py --check` matches all four.
480 tests pass, 16 skipped; audit clean. Committed as `06d20aa`.

### 2026-10-21 — step 3: events, the minimal belief, and the agent loop

**Events** (`agentic_uav/core/events.py`): `Trigger` and `Event(trigger, at,
detail)`.

* **Raised in Phase 5:**
  * task assigned;
  * skill succeeded;
  * skill failed (failed or timed out);
  * target detected;
  * communication changed (for one drone, its base link coming or going);
  * battery threshold;
  * guard rejected.
* **Two more that complete the picture:** the agent's own abort completing,
  and AUV-06's slow periodic check.
* **Defined for later phases:** a message changing mission state (Phase 7)
  and a teammate failing (Phase 9). `RAISED_IN_PHASE_5` says which is which.

**The belief** (`agentic_uav/agents/belief_state.py`) holds AUV-06's first
three blocks:

| Block | Holds |
|---|---|
| `self` | position, airborne, battery, home, base link, current skill, current task |
| `mission` | id, objective, absolute deadline, reserve, progress |
| `local_map` | searched regions, observed targets, known hazards, targets reported |

* **Every field comes from a sensor reading, the agent's own executor or
  decisions, or the public brief.** "Reported" means seen while the base
  link was up: the agent's belief, not the evaluator's fact.
* **`update(observation)`** returns what changed: new sightings, the base
  link, the battery.
* **`snapshot()`** is plain data for the trace.

**Decisions** (`agentic_uav/agents/decision.py`) come in four kinds: START a
skill (replacing any running one), ABORT, CONTINUE, FINISH. Each carries an
objective (the lifecycle's "Select objective"), a command ("Choose skill")
and a reason. `Policy` is the protocol every policy will implement, rule now
and LLM in Phase 12.

**Validation** (`agentic_uav/agents/validation.py`) applies two hard rules
that need only the belief; the guardian proper is Phase 11:

* **No restricted zone.** The skill's ground track, from where the drone is
  through its waypoints (a search's whole lawnmower), must not touch a zone.
* **Home on what is left.** After flying the skill and then straight home,
  the battery, by the brief's model, must stay at or above the reserve.

Going home, landing and holding are always allowed: refusing them would be
worse than the risk.

**The loop** (`agentic_uav/agents/drone_agent.py`), `DroneAgent(brief,
sensors, executor, policy)`:

1. **Every 0.5 s tick** it observes (sensors plus its own executor) and
   updates its belief.
2. **It decides only when an event fired.** The periodic check (10 s by
   default) fires only when nothing else has.
3. **The policy proposes, and the validation step checks.** A refused
   decision is fed back to the policy as GUARD_REJECTED, up to three times
   more; after the fourth refusal the agent stops whatever is flying and
   holds.
4. **An accepted START replaces any running skill** (abort, wait, start).
   The agent watches only its latest skill, so a replaced skill's ending is
   never false news.
5. **Every decision goes into `agent.trace`:** time, events, the belief as
   it stood BEFORE the decision, the decision, the verdict, and what the
   agent then did.

**Tests: 20, in `tests/test_drone_agent.py`**, driven by small scripted test
policies (the rule-based policy is step 4):

* **Gating.** A task, then exactly one decision per skill ending: five
  decisions over more than 40 observations.
* **The periodic check** fires every 10 s in a quiet 25 s hold, and never
  alongside other news.
* **The trace holds the belief from before each decision.**
* **Each event fires once at the right moment:**
  * a sighting, used to stop a leg mid-flight;
  * battery levels, each once as it is crossed;
  * the base link lost at 100 m and regained;
  * a failed skill, with its error code and message.
* **A new START replaces a running leg** without false news.
* **A refusal is fed back and the agent asks again.** Refused every time
  while flying, it stops the leg and holds.
* **The battery rule** worked through (9 % out and back, from 25 %).
* **The way home is never refused**, from 150 m out on 21 %.
* **A search's lanes are checked.**
* **Belief updates and reports.**
* **Motion goes on while the agent thinks.** In real time, a policy taking
  0.3 s to decide mid-leg: the drone flew on more than 2 m meanwhile.

**A finding: an abort during TAKE_OFF's settle is reported as success.**
TAKE_OFF waits 3 s for the drone to settle with a plain sleep, so an abort
asked for then goes unseen and the skill ends in success, with the drone
already holding at height. An agent asking to abort there hears
"succeeded". A test pins the behaviour, so changing it is a decision rather
than an accident. Phase 3's skill is unchanged.

**Mutations: 19, all caught.** The first pass caught 16 of 20:

* **One was equivalent and its code was removed.** A set suppressing a
  replaced skill's abort could never matter, because the agent never sees a
  replaced skill end.
* **Three were test gaps, now tested:**
  * the periodic check riding along with other news;
  * repeated refusals while a skill flies;
  * the way home from far out.

  The last needed two attempts. My first version started the belief out
  there, which made that spot its home, so going home cost nothing.

**The goldens did not move.** `record_golden.py --check` matches all four.
500 tests pass, 16 skipped; audit clean. Committed as `d47a928`.

### 2026-10-21 — step 4: the rule-based policy

**`RulePolicy`** (`agentic_uav/agents/rule_policy.py`) is AUV-06 5.3's
deterministic agent, and AUV-13's Architecture C. Told `"search S1"` and
nothing else, it chooses each skill when the last has ended (or sooner, if
something happens), from the belief as it stands then.

**Its stages:** ready → taking off → to the sector (skipped when the first
lane is in a straight, clear line) → searching → going home → landing →
done. The geometry is Phase 4's: routes keep 2 m from zones, and lanes are
spaced by the detection rule and run past the sector ends.

* **Report.** The base stands by the pads, so the way home passes into radio
  range, and whatever the drone saw is reported on the way back.
* **Low battery and the deadline.** It checks before starting the outbound
  work, then at every battery level crossed and every periodic check while
  that work is ahead. It costs the rest of the transit, the rest of the
  search, and the route home, using the brief's model. If that leaves less
  than the reserve plus 2 %, or more time than is left, it drops the search
  and goes home at once.
* **A failed skill.** It re-plans from where the drone is and tries the
  stage again, up to twice. Then:
  * an unreachable sector or an unfinishable search sends it home;
  * a way home that keeps failing ends in landing where it is;
  * a take-off or landing that keeps failing ends the task.
* **A refused decision.** Refused outbound work means going home; a refused
  way home means landing where it is.

It records its stage, sector, retries, and any reason it gave up in the
belief's mission progress, so the trace shows them.

**Flown on the mock, judged by Phase 4's evaluator**, single-drone,
single-sector versions of the canonical mission:

| Run | What the agent did | Verdict |
|---|---|---|
| "search S1" | took off, searched, flew home, landed: 4 skills, each chosen on the event before it | success, 155.5 s |
| "search S3", beyond R1 and the radio | routed round R1, searched, reported both targets only once back in range | success, 187.5 s |
| a fault that strikes once, in the search | retried the search | success |
| a fault that strikes once, in the transit | re-planned from where it was | success |
| a fault that never clears | two retries, gave up the search, landed: its reason in the trace | C1–C3 fail, home safe |
| half speed, battery sized for full | at a periodic check, 53.2 % left against 31.6 % needed, dropped the search half done and flew home | C6 passes, landed on 37.8 %; coverage 0.53 |
| half speed, ample battery, deadline for full speed | turned back on the periodic check alone: "short of time" | C6 passes |
| a deadline it cannot meet | did not begin the search; landed | C6 passes |
| battery too low to start | did not begin; landed | C6 passes |
| a task it does not know | refused without flying | — |

**Three changes made along the way:**

* **Validation kept the way home out of zones.** Step 3's first version
  waived both rules for the way home, and traced no path for RETURN_HOME at
  all, so a straight line home through a zone would have passed. Now the
  battery rule alone is waived (for going home, landing and holding, and
  any route ending at home); the zone rule has no exceptions. Two tests:
  RETURN_HOME through R1 is refused, and a route home on a low battery is
  allowed.
* **The low-battery estimate measures progress by position.** A first
  version measured search progress by time at the nominal 5 m/s. A drone
  slower than planned, which is exactly when the battery runs short, would
  have looked further along than it was. Now it uses where the drone is on
  its lanes (`remaining_along`), tested on its own and through the slow
  drone.
* **The mock gained a passing fault.** `MockFaults.raise_times` raises a set
  number of times, then works, so recovery can be tested; `raise_on` only
  ever fails. It has its own test.

**Also found while choosing the test conditions:** the first short-deadline
run started a search it could never finish, and turned back only at the
first periodic check. The policy now checks before starting outbound work as
well.

**A serious slip in my own tests, caught by a mutation.** A helper in
`BranchTests` was named `fail`, which shadows `unittest.TestCase.fail`.
Every `assertEqual` calls that method to report a failure, so the helper
returned a value instead of raising, and **every assertion in that class
passed whatever the code did**. A mutation surviving against a test that
plainly covered it is what showed it. The helper is now `failed_event`.
`tests/test_suite_hygiene.py` checks every test class in the suite for a
shadowed TestCase method, and checks that it can see one; none other
exists.

**Tests:**

| File | Tests |
|---|---|
| `tests/test_rule_policy.py` | 21: nominal, recovery, low battery and deadline, refusal, the give-up branches, per-stage retries, the position-based estimate, `remaining_along` |
| `tests/test_drone_agent.py` | 1 more, for validation |
| `tests/test_mock_adapter.py` | 1 more, the passing fault |
| `tests/test_suite_hygiene.py` | 2 |

**Mutations: 17, all caught.** The first pass caught 12; of its five
survivors:

* **One was the shadowed `fail`.**
* **Four were test gaps:**
  * a task with an unknown verb and a known sector;
  * retries never reset between stages;
  * the deadline seen only by the periodic check;
  * the estimate counting the whole search as still ahead.

**The goldens did not move.** `record_golden.py --check` matches all four.
525 tests pass, 16 skipped; audit clean. Committed as `cbb3913`.

### 2026-10-21 — step 5: the exit, met on the mock

**The task's scenario** (`configs/scenarios/search_single_001.toml`) is
`search_relay_001` cut to one drone and the far sector S3, every other value
unchanged (a test holds it to that). Reaching S3 means routing round R1;
searching it is out of the base's radio; what is found there is reported
only on the way home.

**The exit runs** (`agentic_uav/experiments/single_agent.py`,
`scripts/single_agent_exit.py`) give the agent the brief and the words
`"search S3"`, nothing more. They fly it on a fresh mock per run, and judge
it with Phase 4's evaluator. The criterion's parts are each a check:

* **Completes a search task:** the mission report succeeds (all six of
  AUV-05's criteria) and the agent itself decided it was finished.
* **Without a preflight action list:** every skill was a START decision
  made in answer to an event (`chosen_as_it_went`, read from the trace).
* **Recognises success or failure, and decides:** five kinds of trouble,
  each with what the agent must do written into `TROUBLES` before any was
  flown. A trouble is met when the agent did that, ended the task itself,
  decided something after every failed skill (`decided_after_every_failure`),
  and came home safe.

**Choosing the trouble conditions found a flaw in the policy.** The
conditions were calibrated so that at the planned speed the task always
fits, and only the trouble breaks it. At half speed on a 0.2 %/s battery,
the agent turned back with 37.4 % left, estimating 15.8 % to get home, and
**landed on 18.0 %, under the 20 % reserve**. Its estimate costed the time
aloft at the planned 5 m/s; at half speed every metre costs twice the hover
drain. The estimate now uses the speed the drone is actually **making good**
on its search: measured by position along the path from where the search
began (so the fly-out to the first lane counts as progress), after 10 s,
and never above the planned speed. The same drone now turns back early and
lands on 65.7 %. The deadline estimate uses the same speed. A regression
test reproduces the original case, and another tests the measurement,
including the cap.

**The run of record**
(`results/single-agent-exit-20261021-215820-exit`), at `cbb3913` with the
step-5 files uncommitted (`agentic_uav` digest `218ab87329156ed8`), took
4.3 s for 25 flights.

* **Nominal, seeds 1–20: 20 of 20 met.** Each flew the same five skills,
  each chosen when the last ended: take off; route round R1; search S3; fly
  home, reporting both targets once back in range at 161.0 s; land. Every
  run completed in 187.5 s with coverage 1.0, and 72.9 % of the battery left.
* **Trouble: 5 of 5 met their checks:**

| Trouble | What the agent did |
|---|---|
| a fault once, in the transit | retried from where it was; mission success |
| a fault for good | three transit attempts, gave up, landed on its pad, with the reason in the trace |
| half speed, 0.25 %/s | turned back 59.5 s in, still on the fly-out to its first lane, having measured that it could not finish; landed on 64.5 % |
| half speed, 260 s deadline | turned back "short of time"; landed inside the deadline |
| 0.5 %/s | did not begin the search; landed |

The planned evidence named "a target sighted mid-search" among the
troubles. It is not a separate run: every nominal run's trace has the
TARGET_DETECTED events, and the rule policy carries on through them by
design. Reporting is the way home.

**Evidence:** [`evidence/exit-criterion-2026-10-21.md`](evidence/exit-criterion-2026-10-21.md),
generated from the record, with the decision traces of seed 17 and of two
troubles: each decision, its events, what the agent knew, and what it did.

**A second shadowed TestCase name**, caught loudly this time.
`cls.run = fly_agent_on_mock(...)` in the new tests replaced `TestCase.run`,
which the runner then tried to call. It is renamed `flight`, and the hygiene
test now also checks names assigned in a test class and attributes set on
`self` or `cls`. It looks only at real test classes, since fake runners in
the tests rightly have a `run` of their own, and it is shown to catch the
`cls.run` case.

**Tests: 16 new** — `tests/test_single_agent_exit.py` (14: the scenario, the
nominal run and its record, the troubles, negative controls showing each
check can fail, including a real run cut short by a 10 s deadline, the
script) and 2 in `tests/test_rule_policy.py`.

**Mutations: 13, all caught.** The first pass caught 11. Two were untested:

* coming home safe, since no negative control had a run where C6 failed;
* the cap on the speed made good, since the mock never flies faster than
  planned.

Step 4's 17 mutations were re-run against the changed policy: all caught.

**The goldens did not move.** `record_golden.py --check` matches all four.
541 tests pass, 16 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-21 | **Skills run on their own thread, abortable; the agent watches** | Event-driven replanning needs events while a skill is still flying: a target sighted mid-search, a battery crossing its threshold mid-leg. A blocking skill call would make the agent deaf until the skill ended, and AUV-06 says low-level motion must never wait on the decision-maker. Phase 3's `request_abort` already exists for this |
| 2026-10-21 | **The truth/belief boundary is enforced now, in code and in tests** | It is objective 6.2, but it is cheapest before any agent code exists. Agent code imports nothing that holds ground truth (no scenario, no world, no targets), and what it is handed exposes nothing that leads back to them. AUV-06: "Enforce it in code, not by convention" |
| 2026-10-21 | **Phase 5's belief is minimal: self, mission, local map** | The lifecycle needs a belief to update. The team and communication blocks, assumptions, staleness and the "what it knew" logger are Phase 6's objectives; building them now would fix their shape before the team exists to shape them. A per-decision trace starts now regardless |
| 2026-10-21 | **The task is given, the plan is not** | The agent receives the brief's public facts it needs (its sector, the zones, the base, its own battery model) and one task, "search this sector". Every skill it flies, it chose. That is the exit criterion's "without receiving a complete preflight action list" |
| 2026-10-21 | **The task is S3, the far sector; troubles are fixed in code, with their expectations, before flying** | S3 needs everything a single agent does: routing round a zone, searching out of radio range, reporting on return. Writing each trouble's expected answer before running it is what keeps "recognises and decides" a test rather than a description. |
| 2026-10-21 | **Cost what remains at the speed the drone makes good, never above the plan** | Time aloft is charged per second, so a slow drone pays more per metre; the planned speed brought one home under its reserve. Capped at the plan, so the estimate can only be conservative. |
| 2026-10-21 | **The exit is on the mock, judged by Phase 4's evaluator; live is optional** | As Phase 4: the mock runs seeds and injected faults exactly and repeatably; a small live run inside the flown airspace can follow |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
