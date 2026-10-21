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

**Met:** no · **Evidence:** —

Planned evidence: the rule-based agent, given only a search task, completing
it on the mock across 20 seeds, judged by Phase 4's evaluator. Then the same
agent under injected trouble — a failed navigation skill, a battery running
low, a target sighted mid-search — with its decision trace showing what
triggered each decision and what it chose. Optionally, a small live run.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Sensing behind the truth/belief boundary | `agentic_uav/core/sensing.py`, `agentic_uav/simulator/sensing.py` | **Done** 2026-10-21; goldens unedited |
| A non-blocking action executor | `agentic_uav/control/action_executor.py` | step 2 |
| Events, a minimal belief, and the agent loop | `agentic_uav/core/events.py`, `agentic_uav/agents/` | step 3 |
| The rule-based policy | `agentic_uav/agents/rule_policy.py` | step 4 |
| The exit: nominal and injected-trouble runs; optional live; close | `configs/scenarios/`, `scripts/`, `results/`, `evidence/` | steps 5–6 |

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
465 tests pass, 16 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-21 | **Skills run on their own thread, abortable; the agent watches** | Event-driven replanning needs events while a skill is still flying: a target sighted mid-search, a battery crossing its threshold mid-leg. A blocking skill call would make the agent deaf until the skill ended, and AUV-06 says low-level motion must never wait on the decision-maker. Phase 3's `request_abort` already exists for this |
| 2026-10-21 | **The truth/belief boundary is enforced now, in code and in tests** | It is objective 6.2, but it is cheapest before any agent code exists. Agent code imports nothing that holds ground truth (no scenario, no world, no targets), and what it is handed exposes nothing that leads back to them. AUV-06: "Enforce it in code, not by convention" |
| 2026-10-21 | **Phase 5's belief is minimal: self, mission, local map** | The lifecycle needs a belief to update. The team and communication blocks, assumptions, staleness and the "what it knew" logger are Phase 6's objectives; building them now would fix their shape before the team exists to shape them. A per-decision trace starts now regardless |
| 2026-10-21 | **The task is given, the plan is not** | The agent receives the brief's public facts it needs (its sector, the zones, the base, its own battery model) and one task, "search this sector". Every skill it flies, it chose. That is the exit criterion's "without receiving a complete preflight action list" |
| 2026-10-21 | **The exit is on the mock, judged by Phase 4's evaluator; live is optional** | As Phase 4: the mock runs seeds and injected faults exactly and repeatably; a small live run inside the flown airspace can follow |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
