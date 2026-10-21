"""The only code that talks to a simulator (AUV-03, 2.2).

`adapter` defines what the rest of the project may ask of a simulator.
`airsim_adapter` implements it for CarlaAir's AirSim, and `mock_adapter`
(Phase 3) for a lightweight simulated world in simulated time. Swapping
between them is a constructor argument; `tests/test_adapter_contract.py`
holds both to the same promises.
"""

from .adapter import SceneAdapter, VehicleAdapter  # noqa: F401
