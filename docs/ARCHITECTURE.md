# Architecture

## Flow of one mission

```
operator instruction
      │
      ▼
 AgentContext ──► MissionPlanner.decide() ──► AgentDecision (list of SkillCommands)
                                                     │
                                                     ▼
                                   ActionExecutor.run(vehicle_id, decision)
                                                     │  (arm_takeoff → plan steps → stop)
                                                     ▼
                                   VehicleAdapter.execute_skill(...)
                                          │                     │
                                   AirSimVehicleAdapter    MockVehicleAdapter
                                   (real flight)           (records skills)
```

`experiments/runner.py` builds one `DroneAgent` per drone, plans them all up
front, then executes concurrently (one thread per drone) - the open-loop
baseline behavior.

## How this maps to the baseline

| Baseline (flat scripts) | Now |
|---|---|
| `interpret_user_prompt` in each `*_airsim_agent.py` | `planners/*_planner.py` behind `MissionPlanner` |
| `check_task_list` / schema / prompt | `planners/base_planner.py` (shared) |
| `AgenticAirSimDrone.execute_*` (AirSim calls) | `simulator/airsim_adapter.py` behind `VehicleAdapter` |
| `execute_mission` loop | `control/action_executor.py` |
| `Multiple.py` threaded swarm + `main()` | `experiments/runner.py` |
| `update_airsim_settings` / `runtime_spawn_swarm` | `simulator/scenario_manager.py` |
| flight constants, landing profile | `control/navigation.py` + adapter |

Flight behavior (velocities, fixed-heading strafing, ground-level recording,
fast-then-gentle landing, plan validation) is unchanged - the same missions
produce the same actions. The behavior-preservation test checks this with the
mock adapter.

## What's intentionally still a stub

`coordination/` (message bus, network model, task allocator, roles),
`agents/belief_state.py`, fault handling, `experiments/metrics.py` and
`batch_runner.py`. These are where the next phase - decentralized persistent
agents that communicate, allocate tasks, and stay operational under
communication degradation and agent loss - will be built.
