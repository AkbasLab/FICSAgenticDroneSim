# Phase Documentation
## Phase 1 — Natural-language flight planning (open-loop baseline)
Goal: an operator types a plain-English instruction; a language model turns it into a validated sequence of flight actions; the drone executes it in simulation.

Environment. Set up CARLA-Air v0.1.7 (CARLA 0.9.16 + AirSim 1.8.1 in one Unreal 4.26 process) on Windows from scratch — conda environment, the AirSim Python client, Ollama for local models, and API access for the cloud model. Verified against Town10HD with a working test flight.

Action vocabulary. Nine low-level primitives the planner is allowed to emit: arm_takeoff, fly_to, fly_straight, fly_backward, fly_left, fly_right, hover, set_altitude, land. Every plan is validated against this list and its required parameters before anything flies — the model cannot invent an action or omit an argument.

Planners. Four interchangeable implementations behind one interface: Google Gemini (cloud), Llama 3.1 8B and Mistral-Nemo 12B (local, via Ollama on CPU), and a deterministic keyword-based rule policy used as a control condition and for testing without a model.

The main technical problem. The local models silently collapsed multi-step instructions into a single action — "fly forward, turn left, then land" would return only one step. Diagnosing it as an output-format problem rather than a reasoning problem was the key step: constraining generation with a JSON schema ({"plan": [...]}) fixed it, and both local models then produced correct multi-step plans.

Landing. AirSim's drone doesn't collide with CARLA's ground, so naive landing either flew through the terrain or stopped in mid-air. Solved by recording ground level before takeoff, descending fast to 4 m above it, settling, then a slow final approach and disarm.

Benchmarking. An automated comparison of the models on plan correctness, consistency across repeated runs, and latency, on both a standard and a deliberately harder instruction set, with the harder set showing a genuine separation between the two local models.

What it produced: a working end-to-end pipeline (English → validated plan → real flight), reproducibility documentation, and a version-tagged baseline that the later phases were built on without changing its flight behavior, verified by the 4 behavior-preservation tests that still pass today.
