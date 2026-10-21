"""The agents: a drone that decides its own next step (AUV-06, Phases 5 and 6).

THE BOUNDARY (AUV-06, 6.2), enforced by `tests/test_sensing.py`: nothing in
this package may import the simulator or the experiments packages, nor the
scenario's ground-truth types (`Scenario`, `TargetSpec`). An agent knows the
world only through `core.sensing.Sensors` and the public brief
(`core.scenario.MissionBrief` and its parts). If it could read the scenario
it would silently have perfect global information, and every resilience
result built on it would mean nothing.
"""
