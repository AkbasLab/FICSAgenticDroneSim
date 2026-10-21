"""Running experiments: the mission runner, the agent log, provenance.

Moved here in Phase 2 step 5 from `scripts/run_missions.py` (now the runner's
command line) and `baseline/open_loop_agent.py`. The runner plans through a
`MissionPlanner` and flies through the AirSim adapter, so nothing in this
package calls AirSim or Ollama directly. `tests/golden/runner.json`, recorded
before the move, pins what it prints, writes and flies.
"""
