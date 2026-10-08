"""Runs several drones at once. Sits one level above the adapters: each
adapter's execute() stays blocking and single-drone, and this is the only
place threads exist.

All planning happens up front, one drone at a time, on the calling thread -
so a bad plan for any drone aborts before anyone takes off, and the shared
planner is never touched from two threads.
"""

import threading
from typing import Dict

from ..core.enums import ActionType
from ..core.interfaces import MissionPlanner, VehicleAdapter


class FleetController:
    def __init__(self, planner: MissionPlanner, adapters: Dict[str, VehicleAdapter]):
        self.planner = planner
        self.adapters = adapters
        self.landed = set()

    def _run_parallel(self, jobs):
        """jobs: {drone_name: zero-arg callable}. One thread each; waits for all,
        then raises if any thread failed (the others are not interrupted)."""
        errors = {}

        def wrap(name, fn):
            try:
                fn()
            except Exception as e:  # surface it after every thread has finished
                errors[name] = e

        threads = [threading.Thread(target=wrap, args=(n, fn)) for n, fn in jobs.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            detail = "; ".join(f"{n}: {e}" for n, e in errors.items())
            raise RuntimeError(f"drone(s) failed: {detail}")

    def takeoff_all(self):
        self._run_parallel({n: a.connect_and_takeoff for n, a in self.adapters.items()})

    def run(self, instructions: Dict[str, str]):
        """instructions: {drone_name: instruction text}. Raises ValueError for an
        unknown/landed drone and PlanError for a bad plan - in both cases before
        any drone moves."""
        for name in instructions:
            if name not in self.adapters:
                raise ValueError(f"unknown drone '{name}'")
            if name in self.landed:
                raise ValueError(f"'{name}' has already landed")

        plans = {name: self.planner.plan(text) for name, text in instructions.items()}

        self._run_parallel({n: (lambda a=self.adapters[n], c=cmds: a.execute(c))
                            for n, cmds in plans.items()})

        for name, cmds in plans.items():
            if any(c.action == ActionType.LAND.value for c in cmds):
                self.landed.add(name)

    def land_all(self):
        self._run_parallel({n: a.land for n, a in self.adapters.items()
                            if n not in self.landed})
        self.landed.update(self.adapters)

    @property
    def all_landed(self):
        return len(self.landed) == len(self.adapters)
