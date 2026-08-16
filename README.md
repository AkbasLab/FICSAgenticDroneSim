# AgenticDroneSimRepo

A multi-agent UAV simulation framework. An operator gives drones instructions,
a planner turns each into a validated sequence of flight actions, and the drones
execute in a CARLA-Air / AirSim simulator.

This repo is the restructured successor to the flat-script open-loop baseline
(tagged `v0.1-open-loop-baseline` in the original repo). This version keeps the
**same flight behavior** but organizes it behind clean interfaces so the next
phase - persistent agents, peer communication, task allocation, fault tolerance -
can be built on top.

## The two interfaces everything is built around

- **`MissionPlanner`** (`agentic_uav/planners/base_planner.py`)
  `decide(context: AgentContext) -> AgentDecision`.
  Implemented by Gemini, Llama, Mistral, and a deterministic rule policy - the
  agent doesn't know or care which it holds.

- **`VehicleAdapter`** (`agentic_uav/core/models.py`)
  `get_state`, `execute_skill`, `stop`.
  Agents never call AirSim directly. Implemented by `AirSimVehicleAdapter`
  (real sim) and `MockVehicleAdapter` (no sim, used by the tests).

## Layout

```
agentic_uav/
  core/          data types (models), enums, clock, events
  simulator/     VehicleAdapter impls (airsim, mock), scenario setup
  control/       skills, action executor, navigation constants, safety (stub)
  agents/        drone agent, rule policy, belief state (stub), fallbacks (stub)
  coordination/  message bus, network model, task allocation, roles  (all stubs)
  planners/      MissionPlanner interface + gemini/llama/mistral/rule
  experiments/   mission runner, scripted mission controller, metrics, logging
configs/         missions / networks / vehicles / experiments
scripts/         run_single_mission.py, run_canonical_mission.py, run_batch (stub)
tests/           behavior-preservation test (mock adapter)
docs/
```

Modules marked *(stub)* are placeholders for the next phase (communication,
faults, roles, metrics). The refactor added structure, not new behavior.

## High-level skills (Phase 3)

The agent's main interface is a set of mission-oriented skills, not low-level
directional commands. Each skill has a typed command (its parameters) and a
formal contract (preconditions, success/failure, timeout, abort behavior,
expected state change), and returns a structured `SkillResult`
(`success | failed | aborted | timeout`, timing, final position, error code).

Skills: `TAKE_OFF`, `GO_TO_WAYPOINT`, `FOLLOW_WAYPOINTS`, `SEARCH_REGION`,
`INSPECT_POINT`, `HOLD_POSITION`, `RENDEZVOUS`, `ACT_AS_RELAY`, `RETURN_HOME`,
`LAND`, `EMERGENCY_HOLD` (defined in `agentic_uav/control/skills.py`, executed by
`control/skill_executor.py`, built on waypoint + heading navigation in the
adapters).

Run the exit-criterion demo (4 drones take off, go to distinct waypoints, hold,
return, land) with no simulator needed:

```
python scripts/phase3_demo.py            # deterministic, on the kinematic mock
python scripts/phase3_demo.py --adapter airsim   # fly it for real
```

Skill unit tests (no sim, no LLM): `python tests/test_skills.py`

## The canonical mission (Phase 4)

A single fixed scenario, `configs/missions/search_relay_001.yaml`, defines the
world every later experiment runs against: a base station, four rectangular
search sectors, two targets, one restricted no-fly region, four drones with a
battery budget, a comms/relay range, and a mission deadline. The scenario is
declarative so it stays stable while the coordination architecture changes
around it.

- **Simulated detection** (`simulator/target_model.py`) is purely geometric -
  a target is "found" when a drone's path stays within its detection radius long
  enough. Deliberately **no neural network**, so a mission failure is attributable
  to coordination / comms / control, not perception.
- **Mission evaluation** (`experiments/metrics.py`) scores a run against all the
  Phase 4.3 success criteria: sector coverage, targets detected *and reported to
  base*, no restricted-zone entry, no separation violation, battery and deadline
  respected, and every drone returned safely.
- **Exit criterion** - a fully scripted, *non-agentic* controller
  (`experiments/mission_runner.py`) statically assigns one sector per drone and
  flies the fixed sequence `TAKE_OFF -> SEARCH_REGION -> RETURN_HOME -> LAND`.
  It completes the canonical mission, which is the baseline the coordinated
  architecture has to beat.

```
python scripts/run_canonical_mission.py           # deterministic, on the mock
python scripts/run_canonical_mission.py --airsim  # fly it for real
python tests/test_mission.py                       # mission + evaluator tests
```

## Persistent closed-loop agent (Phase 5)

Instead of planning a whole mission up front, one drone runs a persistent loop:

```
observe -> update belief -> select objective -> choose skill
        -> validate -> execute -> verify
```

It is handed a *task* ("search sector S1 and report"), **not** an action list,
and decides one skill at a time, reacting to what happens. Replanning is
event-driven (`agents/objectives.py`): it re-decides only on events - a skill
finished, a target was seen, the battery crossed a threshold, a safety guard
fired - never in a busy loop. A deterministic policy (`agents/search_policy.py`)
is built first as a debugging tool and research baseline, ahead of any LLM. A
separate `Guardian` (`agents/guardian.py`) gets the last word on every command
so an unsafe action never reaches the vehicle.

It handles the required reactions: accept a task, navigate to and search the
sector, report completion, return home, **react to low battery** (stop extending
the mission and land safely), and **recover from a failed navigation skill**
(retry, then give up safely).

```
python scripts/run_persistent_agent.py                 # completes the task
python scripts/run_persistent_agent.py --battery 8      # low-battery safe abort
python tests/test_persistent_agent.py                   # 5 tests
```

Exit criterion: one deterministic persistent agent completes a search task with
no preflight action list, recognizing success/failure and deciding what to do
next. The `agents/coordination/` stubs (messaging, roles, task allocation) are
where the multi-agent phase plugs into this same loop.

## Quick start

Run a mission with no simulator and no LLM (fast, deterministic):
```
python scripts/run_single_mission.py --planner rule --adapter mock --drones 1
```

Verify behavior preservation:
```
python tests/test_behavior_preservation.py
```

Fly for real (simulator running, models pulled - see docs/ARCHITECTURE.md and the
baseline SETUP guide):
```
python scripts/run_single_mission.py --planner gemini
python scripts/run_single_mission.py --planner mistral --drones 2
```

Planners: `gemini | llama | mistral | rule`. Adapters: `airsim | mock`.
