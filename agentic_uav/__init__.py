"""Agentic UAV coordination -- the research modules.

Built up during Phase 2 by moving the open-loop baseline
(`baseline/open_loop_agent.py`, frozen at the tag `v0.1-open-loop-baseline`)
into interchangeable parts, without changing what it does. The tree follows
`AUV-03 — Repository Architecture`:

    core/         plain data shared by everything: positions, vehicle state,
                  skill commands and results
    simulator/    the only code that talks to a simulator, behind the
                  VehicleAdapter and SceneAdapter protocols

Further packages (control, planners, experiments, and later agents and
coordination) arrive as the code they hold is moved. They are not created
empty. Behaviour is pinned by `tests/test_golden.py`.
"""
