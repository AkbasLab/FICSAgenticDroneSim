"""Agentic UAV coordination -- the research modules.

Built up during Phase 2 by moving the open-loop baseline
(`baseline/open_loop_agent.py`, frozen at the tag `v0.1-open-loop-baseline`)
into interchangeable parts, without changing what it does. The tree follows
`AUV-03 — Repository Architecture`:

    core/         plain data shared by everything: positions, vehicle state,
                  primitive commands and results, protocol constants, errors;
                  the real and simulated clocks
    simulator/    the only code that talks to a simulator, behind the
                  VehicleAdapter and SceneAdapter protocols: AirSim, and the
                  mock; AirSim's settings.json
    control/      the open-loop executor, the ground reference, contact
                  classification, the separation monitor; navigation and the
                  eleven mission-level skills (Phase 3)
    planners/     the MissionPlanner protocol: the plan language and its
                  validation, the prompt, the Ollama and replay planners
    experiments/  the mission runner, the agent log, provenance

Further packages (agents and coordination, in later phases) arrive with the
code they hold. They are not created empty. Behaviour is pinned by
`tests/test_golden.py`.
"""
