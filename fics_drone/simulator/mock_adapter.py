"""Simulator-free VehicleAdapter: records what it was asked to do, flies nothing.

Position is fake and test-controlled: `reachable` decides whether
start_move_to() "arrives" instantly (so a skill's polling loop sees success)
or leaves position unchanged (so it times out). `position_sequence`, when
given, overrides get_position() to return one value per call - lets a test
script an exact sequence (e.g. drift appearing on the 3rd poll) without
racing real time. `speed` is a plain settable attribute (default 0.0, i.e.
already stopped) - set it before a call to simulate "still moving fast".
"""

import time

from ..core.interfaces import VehicleAdapter


class MockVehicleAdapter(VehicleAdapter):
    def __init__(self, vehicle_name="MockDrone", step_delay=0.0,
                 start_position=(0.0, 0.0, 0.0), reachable=True,
                 position_sequence=None):
        self.vehicle_name = vehicle_name
        self.step_delay = step_delay  # lets tests prove drones overlap in time
        self.log = []                 # ("takeoff"|"execute"|"land"|"move_to"|"hover", detail)
        self.start_time = None
        self.end_time = None
        self._position = start_position
        self.reachable = reachable
        self._position_sequence = list(position_sequence) if position_sequence else None
        self.speed = 0.0

    def connect_and_takeoff(self):
        self.log.append(("takeoff", None))

    def execute(self, commands):
        self.start_time = time.monotonic()
        self.log.append(("execute", [c.action for c in commands]))
        time.sleep(self.step_delay)
        self.end_time = time.monotonic()

    def land(self):
        self.log.append(("land", None))

    def get_position(self):
        if self._position_sequence:
            if len(self._position_sequence) > 1:
                return self._position_sequence.pop(0)
            return self._position_sequence[0]  # hold the last value once exhausted
        return self._position

    def start_move_to(self, x, y, z):
        self.log.append(("move_to", (x, y, z)))
        if self.reachable:
            self._position = (x, y, z)

    def start_hover(self):
        self.log.append(("hover", None))

    def get_speed(self):
        return self.speed
