# Phase 2 — Refactor the repository into research modules

**Stage:** 1 · Platform · **Vault note:** `AUV-03 — Repository Architecture`
**Started:** 2026-10-20 · **Completed:** —

> Split the single-file open-loop agent into interchangeable planners, a
> vehicle adapter and an experiment layer, without changing anything it does.
> Until this is done, no second architecture and no mock simulator have
> anywhere to plug in.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **2.1** Separate planner logic from drone execution — one `MissionPlanner` protocol
- [ ] **2.2** Separate AirSim calls from agent logic — a `VehicleAdapter` protocol; the agent never calls arbitrary AirSim methods
- [ ] **2.3** Preserve current functionality — refactoring adds no new behaviour

## Exit criterion

> All original baseline examples run through the new modular structure
> **without changing their expected behaviour.**

**Met:** no · **Evidence:** `tests/test_golden.py` against `tests/golden/`,
recorded from `v0.1-open-loop-baseline` before any code moved. A live block,
flown by the user and compared with `v6-polled`, closes it.

AUV-03 calls this "a pure refactor with a behavioural regression test". The
goldens are that test. They pass today, against the untouched baseline, and
they must still pass, unedited, when the refactor is done.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Recording fake AirSim + virtual clock + scripted Ollama | [`tests/airsim_fake.py`](../../tests/airsim_fake.py) | **Done** 2026-10-20 |
| Golden recorder | [`tools/record_golden.py`](../../tools/record_golden.py) | **Done** 2026-10-20 |
| Goldens: execution (16 cases), planning (44 cases) | [`tests/golden/`](../../tests/golden/) | **Recorded** from `v0.1-open-loop-baseline` |
| Regression test | [`tests/test_golden.py`](../../tests/test_golden.py) | **Passing** against the baseline |
| `VehicleAdapter` + `SceneAdapter`, core types, AirSim adapter | [`agentic_uav/core/`](../../agentic_uav/core/), [`agentic_uav/simulator/`](../../agentic_uav/simulator/) | **Done** 2026-10-20; not yet used by the agent |
| Adapter tests, expectations taken from the goldens | [`tests/test_adapter.py`](../../tests/test_adapter.py) | **Passing**, 21 tests |
| Execution on the adapter | [`agentic_uav/control/`](../../agentic_uav/control/), [`simulator/scenario_manager.py`](../../agentic_uav/simulator/scenario_manager.py) | **Done** 2026-10-20; goldens pass unedited |
| `MissionPlanner` + Ollama and replay planners | [`agentic_uav/planners/`](../../agentic_uav/planners/), [`core/protocol.py`](../../agentic_uav/core/protocol.py) | **Done** 2026-10-20; goldens pass unedited |
| Planner tests | [`tests/test_planners.py`](../../tests/test_planners.py) | **Passing**, 8 tests |
| Runner and logging moved | `agentic_uav/experiments/` | Not started |

## Plan

Each step lands as its own commit, and the golden test must pass after every
one without the goldens being re-recorded.

1. **Recording harness and goldens.** Done; see the record.
2. **`VehicleAdapter` and core types** (`VehicleState`, `SkillCommand`,
   `SkillResult`), with an AirSim adapter that wraps exactly today's calls.
   Done; see the record.
3. **Move execution onto the adapter.** `DroneRunner`'s step dispatch becomes
   the executor. AirSim is touched only inside the adapter. Done; see the
   record.
4. **`MissionPlanner`**, with an Ollama planner (Llama and Mistral both run
   through it) and a replay planner that returns recorded replies. Done; see
   the record.
5. **Move the runner, monitor and logging into `agentic_uav/experiments/`.**
   `baseline/open_loop_agent.py` becomes a thin entry point with the same
   command line, so every documented command keeps working.
6. **Close:** docs, a live block flown by the user, compared with `v6-polled`.

## Record

### 2026-10-20 — behaviour pinned before anything moves

Nothing in the agent was touched. The harness records what the tagged baseline
does, so later steps can be checked against it.

**The fake.** `tests/airsim_fake.py` implements the 17 AirSim methods the agent
uses, with trivial physics: commands set positions, every drone rests on
ground z = 29.25, nothing drifts. It is not a simulator. Its only job is to
drive the real code down the same paths a flight does, deterministically.
Three things make it deterministic:

* calls are filed **per drone**, because every flight thread has its own
  connection and addresses only its own vehicle. Thread interleaving cannot
  change a drone's sequence;
* a **per-thread virtual clock** replaces `time` inside the agent, so settle
  loops, timeouts and `flight_seconds` come out identical every run, and a
  four-drone M10 runs in milliseconds;
* the **separation monitor is not recorded.** It polls on a real 10 Hz timer,
  so how many polls fit into a run depends on the machine.

**The goldens.** Execution: every distinct plan set in the recorded results,
13 in all, covering all ten missions and every model reply that differed (three
M08 variants, two M04). Plus three synthetic cases: a stuck landing, a stuck
landing on M10's Drone3 only, and leftover drones in the scene. Planning: all
38 distinct (instruction, reply, model, options) combinations on record, plus
six synthetic error paths: unparseable JSON, unknown action, duration over the
limit, positive z (normalised), empty plan, unreachable endpoint. Each case
stores its inputs, so the test replays from the golden alone.

**Proved able to fail.** Three in-memory mutations: flight speed 5.0 → 4.9 m/s
broke all 15 cases that fly. One word of the system prompt broke all 44
planning cases. The landing threshold 3 → 9 m broke exactly the two
stuck-landing cases, the only ones it reaches. Restored, everything passed
again. Recorded twice from scratch, the two recordings were identical.

### 2026-10-20 — the adapter, built from the goldens

`agentic_uav/` now exists with two packages. Nothing in the agent uses them
yet; that is step 3.

* **`core/models.py`**: `Position`, `VehicleState`, `CollisionInfo`,
  `SkillKind`, `SkillCommand`, `SkillResult`. Plain frozen dataclasses,
  coordinates left in AirSim's NED, because converting to "height above
  ground" needs the measured ground and hiding that sign is how Phase 1's
  altitudes came out 29 m wrong.
* **`simulator/adapter.py`**: two protocols. `VehicleAdapter` has AUV-03's
  `get_state`, `execute_skill` and `stop`, plus the four things the baseline
  actually does: `get_pose`, the ground-truth pose it records where a flight
  ended from, distinct from the state estimate; `get_collision`; and
  `take_control` and `release`. `SceneAdapter`: `confirm_connection`,
  `reset`, `list_vehicles`, `add_vehicle`, `place_vehicle`.
* **`simulator/airsim_adapter.py`**: `AirSimAdapter` implements both on one
  connection. Every method is the baseline's call or pair of calls: same
  arguments, same order, `.join()` where it joined, default timeouts left
  out where the baseline left them out, exceptions passed through untouched.

**Skills are primitive by design**: take off, move to z, velocity, hover, move
to position, land. The baseline's decisions stay out of the adapter: braking
with a hover after a velocity leg, altitudes relative to the measured ground,
and verifying that `land` landed. So moving execution onto the adapter in step
3 cannot move a decision with it.

**Tested against the evidence, not against expectations.** `tests/test_adapter.py`
takes each expected call from `tests/golden/execution.json`: what the tagged
baseline sent for takeoff, the cruise climb, the landing descent, a velocity
leg, `fly_to`, `land`, arm, release, the three reads, and M10's spawn and
placement of three drones. It then asserts the adapter sends exactly that.
21 tests, all passing.

**One limit of the fake, recorded rather than hidden.** It fills in AirSim's
default timeout when a call omits it (20 s for takeoff, unbounded for moves),
so a test cannot tell "omitted" from "passed the default". In AirSim the two
are the same call. The adapter omits them exactly where the baseline did.

### 2026-10-20 — execution moved onto the adapter; the goldens pass unedited

Everything that flies left `baseline/open_loop_agent.py`, which went from
2,021 lines to about 970:

| Moved | To |
|---|---|
| `DroneRunner`, `fly_plans`, the flight constants | `agentic_uav/control/executor.py` |
| the session ground reference and its guards | `agentic_uav/control/ground.py` |
| `is_ground`, `classify_contact`, `landing_contact` | `agentic_uav/control/contacts.py` |
| `SeparationMonitor` | `agentic_uav/control/monitor.py` |
| `reset_world`, `ensure_vehicles`, the leftover-drone check | `agentic_uav/simulator/scenario_manager.py` |
| `PlanError` | `agentic_uav/core/errors.py` |

**Moved by script, not by hand.** Each block was cut by line range, with its
first and last line asserted. The only edits were the client-to-adapter
substitutions, each asserted to occur exactly as often as expected. Comments
and docstrings, which are this project's record of why each line exists, moved
word for word. The one exception: `DroneRunner`'s docstring no longer calls
the client "SHARED", which had been wrong since the per-thread fix.

**The agent keeps its interface.** It re-exports every moved name, and
`reset_world`, `ensure_vehicles` and `fly_plans` remain as thin wrappers that
take a raw AirSim client. So `run_missions.py`, `fly_chat.py` and the existing
tests run unchanged. `connect()` and `main()` now open their connection
through the adapter, and the agent imports AirSim nowhere.

**The sandbox's monkey-patching had to keep working.** `tools/fly_chat.py`
changes the flight speed by assigning `agent.MOVE_SPEED`, and swaps in its own
runner by assigning `agent.DroneRunner`. Moving the code naively would have
silently disconnected both: the sandbox would have flown at 5 m/s whatever was
typed. So `DroneRunner` takes `speed` as a parameter, and `fly_plans` takes
`runner_class` and `speed`. The agent's wrapper reads both from its own module
at call time.

**Only the harness's patch points changed, never the goldens.** Connections
now come from `AirSimAdapter.connect`, and the clock is read in the new
modules, so `tests/airsim_fake.py` patches those as well. `git diff
tests/golden` is empty, and `tools/record_golden.py --check` reports the
goldens match.

**Proved to be testing the new code.** Mutations aimed at the moved code:

| Mutation | Cases failing |
|---|---|
| `agent.MOVE_SPEED` 5.0 → 4.9 (the sandbox's speed path) | 15, every case that flies |
| `executor.LANDED_AGL_MAX` 3 → 9 | 2, the stuck landings |
| `agent.DroneRunner` replaced by a hold-position runner (the sandbox's path) | 7, exactly the plans without `land` |
| `AirSimAdapter.stop` made a no-op | 12 |

**The code snapshot follows the code.** `run_missions.snapshot_code` archived
`open_loop_agent.py`, the runner and the config. After this step that would be
a thin entry point, not the code that flew. It now archives every
`agentic_uav` module too, 16 files, and `provenance()` records
`agentic_uav_sha256`, one digest over the package. This is an addition to the
record, not a behaviour change, so the goldens do not cover it. It was checked
directly.

**Still calling AirSim directly, by design for now:** `run_missions.py` (its
connection and the leftover-drone preflight) and `fly_chat.py`'s status and
land-all helpers. Both move in step 5.

### 2026-10-20 — planning moved behind the MissionPlanner; the goldens pass unedited

Everything that plans left the agent, which went from 971 lines to about 560.
It is now an entry point: re-exports, three thin wrappers, settings,
logging, provenance and `main`.

| Moved | To |
|---|---|
| `ACTIONS`, `PLAN_SCHEMA`, `validate`, the duration and altitude limits | `planners/plan_schema.py` |
| `SYSTEM_PROMPT`, `EXAMPLES`, `build_messages` | `planners/prompt.py` |
| `MODEL`, `OLLAMA_ENDPOINT`, `normalise_endpoint`, `is_transport_error`, `server_version`, `check_endpoint` | `planners/endpoint.py` |
| `OLLAMA_OPTIONS`, `plan_for` | `planners/ollama_planner.py`, plus `OllamaPlanner` |
| `PlanRecord` | `planners/base_planner.py`, beside the `MissionPlanner` protocol |
| `MOVE_SPEED`, `CRUISE_ALTITUDE` | `core/protocol.py`, out of the executor |

Moved by script as in step 3: blocks cut by asserted line range, then only the
substitutions the move needed. The comments moved word for word, with one
exception: `OLLAMA_OPTIONS` said the config asks for 131072 context on two
H100s, superseded the same day by 98304 on one.

**`MissionPlanner.plan(instruction, drone) → PlanRecord`** never raises for a
bad plan or an unreachable model. It returns a record that says so. Two
implementations:

* **`OllamaPlanner`** — `plan_for` with model, endpoint, options and system
  prompt fixed. Llama and Mistral both run through it.
* **`ReplayPlanner`** — recorded replies through the SAME `json.loads` and
  `validate`, with no model. Built from a dict or a results file, it refuses
  conflicting recorded replies and never invents a plan for an unrecorded
  request. Checked against every reply in the planning goldens: identical
  plan, notes, error and raw text for all 43.

**The sandbox's prompt patching kept working.** `tools/fly_chat.py` rewrites
`agent.SYSTEM_PROMPT` for its speed setting and its addendum. `build_messages`
and `plan_for` now take a `system_prompt`, and the agent's `plan_for` wrapper
passes the agent's current one at call time. Tested directly.

**Shared constants have one home.** The prompt tells the model the speed and
the executor flies it. The validator defaults `fly_to`'s z to cruise and the
executor climbs to it. Both constants now live in `core/protocol.py`, so a
planner never imports from the flight-control package and the two can never
disagree.

**Harness unchanged.** The scripted Ollama is installed in `sys.modules`, and
`plan_for` still imports `ollama` at call time, so it reaches the moved code
with no new patch point. `git diff tests/golden` is empty.

**Mutations on the moved code, planning goldens:**

| Mutation | Cases failing |
|---|---|
| `agent.SYSTEM_PROMPT` edited (the sandbox's path) | 44 |
| one worked example dropped | 44 |
| `PLAN_SCHEMA` `minItems` 1 → 2 | 44 |
| `MAX_DURATION` 60 → 600 | 1, the too-long-duration case |

**A step 3 slip, caught by a new check.** A scan for names used but never
defined found `fly_plans`' inner `run(record: PlanRecord)` annotating with a
name the executor never imports. It never failed, because annotations are not
evaluated there, but it is now typed `Any`. Every module passes the scan.

Also run: the agent's real command line, plan-only, against an unreachable
endpoint. Planning went through the new planner, the transport failure was
recorded, and nothing armed. 144 tests pass; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-20 | **Protocol constants live in `core/protocol.py`** | The speed and cruise altitude are told to the model by the planner and flown by the executor. One definition keeps them equal, and keeps planners independent of the control package. |
| 2026-10-20 | **The system prompt is a parameter of the planner** | The sandbox depends on replacing it. A module constant inside `agentic_uav` would silently ignore that. |
| 2026-10-20 | **`ReplayPlanner` reuses the planner's validation and refuses ambiguity** | A replayed plan must be the plan the model produced, not an approximation. Conflicting recorded replies, or a request never recorded, are errors rather than guesses. |
| 2026-10-20 | **Move code by script with asserted boundaries, not by retyping** | 900 lines carrying the project's reasoning in their comments. A script that asserts each block's first and last line, and each substitution's count, either moves them exactly or stops. Retyping risks a silent change that the goldens might not reach, for example in a comment-adjacent constant. |
| 2026-10-20 | **Speed and runner class are parameters of the executor** | The sandbox depends on replacing them, and a module constant read inside `agentic_uav` would silently ignore its replacement. Parameters make the dependency visible, and the study passes the defaults. |
| 2026-10-20 | **The agent keeps thin wrappers that take a raw client** | Changing the runner, the sandbox and the tests in the same step as moving the code would mix two kinds of change. They move to adapters in step 5, on their own. |
| 2026-10-20 | **Skills are simulator primitives; the agent's decisions stay in the agent** | A `fly_straight` skill that braked, or a `land` that verified itself, would carry baseline decisions into the adapter, where a mock in Phase 3 would have to copy them or silently differ. Primitive skills keep one place for each decision. |
| 2026-10-20 | **The adapter protocol is wider than AUV-03's sketch, and says so** | The baseline reads a ground-truth pose, collisions, and hands control over and back. Leaving those out of the protocol would mean the agent reaching past it to AirSim, which is what 2.2 forbids. |
| 2026-10-20 | **Scene management is its own protocol** | Resetting the world and spawning vehicles belong to the scenario, not to a drone. A flight thread never needs them; the runner does. |
| 2026-10-20 | **Pin behaviour with a recording fake before moving any code** | AUV-03 asks for "a behavioural regression test". A live flight cannot be that test: it needs the simulator and Vega, takes an hour, and varies by centimetres. Recorded call sequences compare exactly, in under a second, on any machine. The live block stays, as the final check rather than the only one. |
| 2026-10-20 | **One simulator connection per vehicle, not one shared** | AUV-03 says the AirSim RPC server is "hostile to concurrent clients", so one adapter should own the connection. Phase 1 measured the opposite: a *shared* client fails (`IOLoop is already running`, `BufferError`), and one connection per thread works on every flight since. The adapter follows the measurement. |
| 2026-10-20 | **`MissionPlanner.plan(instruction)` now; `decide(context)` waits for Phase 5** | The baseline plans once, open loop. AUV-03's `decide(context) -> AgentDecision` belongs to a persistent agent that consults the world, and making the baseline fit it would add behaviour, which 2.3 forbids. The persistent agent brings `decide` when it exists. |
| 2026-10-20 | **No Gemini planner** | It was excluded from the frozen baseline (API key, off-machine, moving tag) and its code went with the third-party purge. Llama and Mistral both run through Ollama, so one Ollama planner serves both. |
| 2026-10-20 | **`baseline/open_loop_agent.py` becomes a thin entry point, not a frozen copy** | The exit criterion is that the baseline runs *through* the new structure. A second, untouched copy would prove nothing about the new one. The original is preserved by the tag `v0.1-open-loop-baseline`, and the goldens tie the two together. |

## Open questions

- **Which module owns teardown?** `_land_and_release` is half execution, half
  safety policy. Phase 2 moves it with execution, unchanged. Whether it
  becomes part of the `safety_guardian` is a Phase 3 or Phase 16 question.
- ~~**The `DroneRunner` docstring still calls the client SHARED.**~~
  **Corrected in step 3**, when the class moved.
- **`run_missions.py` and `fly_chat.py` still call AirSim directly** for
  connection setup, the leftover-drone preflight and the sandbox's status and
  land-all helpers. Step 5.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
