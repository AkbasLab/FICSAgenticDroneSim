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
| Goldens: runner (10 cases), fly_chat (4 sessions) | [`tests/golden/`](../../tests/golden/) | **Recorded** from step 4 (`5f9ac56`), before the runner and sandbox moved |
| Regression test | [`tests/test_golden.py`](../../tests/test_golden.py) | **Passing**, all four goldens |
| `VehicleAdapter` + `SceneAdapter`, core types, AirSim adapter | [`agentic_uav/core/`](../../agentic_uav/core/), [`agentic_uav/simulator/`](../../agentic_uav/simulator/) | **Done** 2026-10-20 |
| Adapter tests, expectations taken from the goldens | [`tests/test_adapter.py`](../../tests/test_adapter.py) | **Passing**, 23 tests |
| Execution on the adapter | [`agentic_uav/control/`](../../agentic_uav/control/), [`simulator/scenario_manager.py`](../../agentic_uav/simulator/scenario_manager.py) | **Done** 2026-10-20; goldens pass unedited |
| `MissionPlanner` + Ollama and replay planners | [`agentic_uav/planners/`](../../agentic_uav/planners/), [`core/protocol.py`](../../agentic_uav/core/protocol.py) | **Done** 2026-10-20; goldens pass unedited |
| Planner tests | [`tests/test_planners.py`](../../tests/test_planners.py) | **Passing**, 8 tests |
| Runner, agent log, provenance moved; settings.json helpers moved | [`agentic_uav/experiments/`](../../agentic_uav/experiments/), [`simulator/airsim_settings.py`](../../agentic_uav/simulator/airsim_settings.py) | **Done** 2026-10-20; goldens pass unedited |
| Sandbox on the adapter and the planner | [`tools/fly_chat.py`](../../tools/fly_chat.py) | **Done** 2026-10-20; goldens pass unedited |
| Experiment and sandbox tests | [`tests/test_experiments.py`](../../tests/test_experiments.py), [`tests/test_fly_chat.py`](../../tests/test_fly_chat.py) | **Passing**, 11 + 2 tests |

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
   command line, so every documented command keeps working. Done; see the
   record. The monitor had already moved, with execution, in step 3; the
   sandbox moved onto the adapter in this step too.
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

### 2026-10-20 — the runner, the agent log and the sandbox moved onto the adapters; the goldens pass unedited

**Pinned first, again.** The execution and planning goldens stop at
`fly_plans` and `plan_for`. Nothing recorded what the runner does around
them: the preflight refusals, row construction, scoring, the summary, the
console, the agent log, the code snapshot. Nor anything of the sandbox. So
two more goldens came before any code moved, both recorded from the step 4
code:

* **`runner.json`, 10 cases**: whole `scripts/run_missions.py` invocations,
  each case one simulator session. The protocol series in one session (M01–M08,
  M09, M10, then M01 again, refused), plan-only, `--model`/`--option`/`--block`
  overrides with no server version, four drones declared, a rejected plan plus
  a dead endpoint mid-series, a stuck landing, a drone appearing mid-series
  (the `STOPPED at` path), a model not served, an endpoint down, and two bad
  arguments. Compared per invocation: exit code, console, result rows,
  summary, agent-log records, the code snapshot's shape, every AirSim call.
  The replies are v6's own, from its three files, so no model runs.
* **`fly_chat.json`, 4 sessions**: scripted input through every sandbox
  command, both departures from the study (the prompt addendum and hovering),
  a startup speed, two and four drones, `:drones 1` with four in the scene, end
  of input, a model not served. Compared: console, every request the model
  received, every AirSim call.

The harness grew to drive them: a whole-runner scripted Ollama that refuses an
unscripted instruction loudly (the planner catches every exception, so a gap
in the script would otherwise pass as the model's own failure), a scenario
runner whose world persists across invocations, a world that can grow an
intruder on its n-th reset, and a sandbox driver that feeds `input()`. Two of
its stand-ins were made faithful at the connection boundary: they confirm the
connection as the real `connect` does, and a per-drone stream does not record
the handshake, since it addresses no vehicle. Each change was checked against
the unmoved code first: the existing goldens stayed byte-identical.

**What is not compared, and why.** Only what differs between two runs of
identical code: timestamps, the output directory, the code digests and commit
(they change with every edit, by design), the separation monitor's figures,
which depend on a real 10 Hz timer racing virtual flight time, the order flight
threads finish in, and how two drones' console lines interleave. Each drone's
own lines keep their order. The digests' MEANING is pinned by unit tests
instead (below).

**Recorded twice, both times from the pre-move code.** The first recording
kept the monitor's sample counts and closest approach in 34 console lines.
Deterministic on this machine, but a slower one could take a second sample and
fail. Those figures were normalised and the goldens recorded again from
`5f9ac56`, exported with `git archive`, with only the new harness and recorder
laid over it. The second recording differs from the first in exactly those 34
lines and nothing else, and the agent and runner digests in its metadata are
step 4's. The moved code was then checked against it, unedited.

| Moved | To |
|---|---|
| `load_toml`, `score`, `snapshot_code`, `current_roster`, `series_conflicts`, `describe`, `fly_one`, `run_one`, `summarise`, `main` | `experiments/runner.py` |
| `LOG_PATH`, `log_record`, `log_execution` | `experiments/agent_log.py` |
| `file_digest`, `provenance`, `package_digest` | `experiments/provenance.py` |
| `documents_dir`, `vehicle_names`, `CAMERA_TEMPLATE`, `build_settings`, `write_settings` | `simulator/airsim_settings.py` |

Moved by script, as in steps 3 and 4. `scripts/run_missions.py` went from 704
lines to 42: the command line and re-exports, so `from run_missions import
score` and every documented command still work. Its `--help` is byte-identical
to step 4's. The agent went from 561 lines to 315. The settings helpers moved
because the runner reads the declared roster, and a package module importing
from `baseline/` would invert the dependency. Imports this step left unused
were pruned (`ctypes`, `json`, `time`), along with five unused since steps 3–4
(`math`, `threading`, `dataclass`, `field`, `Iterable`).

**The runner no longer takes the agent.** `run_one(planner, mission, model,
attempt, protocol)` plans through any `MissionPlanner`; `fly_one(planner,
scene, connect, ...)` resets through the scenario manager and flies through
the executor's `fly_plans`. Its own connection comes from
`AirSimAdapter.connect`, which confirms it as the old explicit
`confirmConnection` did, and the leftover-drone preflight reads
`scene.list_vehicles()`. A test now walks every module of `agentic_uav`:
AirSim is imported only by the AirSim adapter, Ollama only by the Ollama
planner and the endpoint check, and the baseline by nothing. Importing the
runner loads neither, so `--help` and a bad mission id still fail instantly.

**Provenance states the same agent.** Two paths were `__file__` in the agent:
the repository and the agent file itself. They are named explicitly now, so a
record still says `open_loop_agent.py` with that file's digest, plus one
digest over the package. The goldens cannot pin digests, so unit tests do:
the fields, the agent file's digest, the package digest recomputed
independently, and the agent log's path.

**The sandbox stopped rewriting the study.** `tools/fly_chat.py` made its two
departures and its speed by assigning `agent.SYSTEM_PROMPT`,
`agent.DroneRunner` and `agent.MOVE_SPEED`. Now it hands its prompt to an
`OllamaPlanner` and `HoverRunner` and the speed to `fly_plans`, the
parameters steps 3 and 4 added for it. `status`, `airborne` and `land_all` go
through the adapter. That needed one new method, `has_control`
(`isApiControlEnabled`), whose expected call is taken from the sandbox golden,
as are those of `land_all`'s take-control, land, release. A test runs a
session and checks the study's prompt, speed and runner are untouched
afterwards. The sandbox no longer imports `airsim` or the agent.

**Mutations, on the moved code.**

| Mutation | Runner cases failing (of 10) | Sandbox sessions failing (of 4) |
|---|---|---|
| `score` counts one extra step | 7 | — |
| `series_conflicts` never refuses | 1, the wrong-order series | — |
| `reset_world` skipped | 5 | — |
| `log_record` / `log_execution` silent | 7 / 5 | — |
| `current_roster` empty | 5 | — |
| a new key in `OLLAMA_OPTIONS` | 9 | — |
| `provenance` drops a field | 7 | — |
| snapshot misses `executor.py` | 7 | — |
| the speed retune leaves the prompt alone | — | 2 |
| sandbox addendum removed | — | 2 |
| study runner instead of `HoverRunner` | — | 1 |
| `release` does nothing | — | 2 |
| `has_control` always true | — | 3 |
| `LAND_TIMEOUT` changed | — | 1 |
| speed not passed to `fly_plans` | — | 2 |

Three mutations failed nothing, each for a reason: `num_ctx` in
`OLLAMA_OPTIONS` (the config sets it, so the default never reaches a run), a
`file_digest` returning `None`, and `build_settings` (digests are unpinned by
design and unit-tested instead; the runner never calls `build_settings`, which
`tests/test_settings.py` pins).

162 tests pass; `record_golden.py --check` matches all four goldens; audit
clean. The live block that closes the phase is step 6.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-20 | **Pin the runner and the sandbox as whole invocations before moving them** | The first two goldens stop at `fly_plans` and `plan_for`. Everything the runner does around them (refusals, scoring, the summary, the log, the snapshot) and everything the sandbox does was unpinned, and step 5 moves exactly that. |
| 2026-10-20 | **A golden is re-recorded only from the code it pins** | `runner.json` needed a second recording to drop timing-dependent monitor figures. Recording it from the moved code would have made the moved code its own reference. It was recorded from `5f9ac56`, and shown to differ from the first recording in those lines only. |
| 2026-10-20 | **The harness removes measurement noise, never behaviour** | Each normalisation names something that differs between two runs of identical code: clock, paths, digests, the monitor's 10 Hz race with virtual time, thread order. What the code decides, prints, writes or sends is compared exactly. |
| 2026-10-20 | **The sandbox passes its departures as arguments** | Rewriting the agent's globals made the sandbox's changes invisible at the call site and process-wide. Steps 3 and 4 had added the parameters for it; this step uses them. The agent's wrappers keep reading their globals, for any other caller. |
| 2026-10-20 | **settings.json helpers live beside the AirSim adapter** | The runner reads the declared roster. Leaving them in the agent would have had `agentic_uav` import `baseline/`, inverting the dependency. They are AirSim's file format, so `simulator/`. |
| 2026-10-20 | **`has_control` joins the `VehicleAdapter` protocol** | The sandbox's `:status` reads AirSim's API-control flag. Without it in the protocol the sandbox would reach past the adapter, which 2.2 forbids. One line for a mock to implement. |
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
- ~~**`run_missions.py` and `fly_chat.py` still call AirSim directly.**~~
  **Done in step 5**: both go through the adapter, and a test keeps every
  other module of `agentic_uav` from importing AirSim.
- **The runner prints `min sep Nonem` for every single-drone flight.**
  `describe()` checks that the monitor ran, not that there was a distance to
  report. The executor fixed the same mistake in its own line long ago. The
  console only; the rows are right. Pinned in `runner.json`, so fixing it is
  a deliberate change with a re-recording and a line here.
- **`:drones N` with fewer drones than the scene holds ends the sandbox.**
  `ensure_vehicles` refuses, correctly, with `ForeignVehicleError`, and
  nothing in `fly_chat.py` catches it. Pinned in `fly_chat.json`.
- **The sandbox's options claim to be the study's but are not.** Its comment
  says "the study's frozen options"; its `num_ctx` is 4096 against the
  protocol's 98304. Sandbox plans are not comparable anyway (the addendum), so
  the comment or the value should change; which is a decision for the study's
  owner.
- ~~**The local agent log held 90 records of scripted replies.**~~ **Removed
  2026-10-20, with the owner's go-ahead.** The first smoke test of the runner
  harness, at 14:38 that day, ran before the harness redirected the log, and
  appended 66 planning and 24 execution records to `runs/agent-log.jsonl`,
  each naming `llama3.3:70b`. They were the file's last 90 lines and the only
  records from 14:38; the 459 before them, real flights included, are
  untouched. The file is ignored by git, so nothing committed was affected.
  The untouched file is kept beside it as
  `runs/agent-log.backup-before-removing-90-scripted-records-20261020.jsonl`.
  The harness now redirects the log and raises if the real one changes.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
