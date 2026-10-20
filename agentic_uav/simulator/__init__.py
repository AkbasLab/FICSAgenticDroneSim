"""The only code that talks to a simulator (AUV-03, 2.2).

`adapter` defines what the rest of the project may ask of a simulator.
`airsim_adapter` implements it for CarlaAir's AirSim. A mock implementation
arrives in Phase 3, and swapping between them is a constructor argument.
"""

from .adapter import SceneAdapter, VehicleAdapter  # noqa: F401
