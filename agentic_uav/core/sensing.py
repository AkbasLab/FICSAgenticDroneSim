"""What one drone can know while it flies: the agent's side of the truth/belief boundary.

    sensors.own_state()      # where am I, am I flying
    sensors.battery()        # my battery, percent
    sensors.sightings()      # the targets I have seen
    sensors.base_link()      # can I reach the base by radio, now

AUV-06, 6.2: "Ground truth — available only to the simulator and evaluator.
Agent belief — based only on local sensing and received messages." This
module is the local-sensing half of that sentence. It defines what a sensor
reading IS; the simulator side builds the readings (`simulator/sensing.py`),
and the agent is handed only the `Sensors` bundle.

WHAT EACH READING MEANS, and why each is local:

* OWN STATE: the drone's position in the mission's frame (x, y, altitude
  above its measured ground) and whether it is airborne. A drone knows where
  it is.
* BATTERY: the drone's own meter, in percent, by the scenario's battery
  model (Phase 4: linear, uncalibrated). A drone knows its own charge.
* SIGHTINGS: the targets THIS drone has detected, by Phase 4's rule (within
  the radius, horizontally, for the minimum observation time), and where.
  Nothing about targets it has not seen, nor how many there are. The label
  is the target's id, as a perception system would tag what it found; the
  position is exact, since Phase 4 has no perception error (AUV-05, 4.2).
* BASE LINK: whether the drone's radio reaches the base right now, directly
  or through other drones. A radio knows whether it has a link; where the
  others are is not part of the reading.

THE BUNDLE IS DELIBERATELY BARE. `Sensors` is a set of functions and
nothing else: no world, no scenario, no simulator object to reach through.
What builds the functions closes over the world; the agent holds only the
functions. Python cannot make the world unreachable from a closure, but no
attribute of the bundle leads to it, and a test walks every attribute to
make sure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class OwnState:
    t: float                  # the clock's time of the reading
    x: float
    y: float
    altitude_m: float         # above the drone's measured ground
    airborne: bool


@dataclass(frozen=True)
class Sighting:
    """A target this drone has detected: its label, where, and when."""

    label: str
    x: float
    y: float
    at: float                 # when the minimum observation time was reached


@dataclass(frozen=True)
class Sensors:
    """One drone's readings, as functions of the present instant. Nothing else."""

    drone: str
    now: Callable[[], float]
    own_state: Callable[[], OwnState]
    battery: Callable[[], float]
    sightings: Callable[[], tuple[Sighting, ...]]
    base_link: Callable[[], bool]
