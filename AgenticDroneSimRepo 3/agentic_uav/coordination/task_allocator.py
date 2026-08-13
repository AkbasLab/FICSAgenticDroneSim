"""Dynamic task allocation among agents. Placeholder for the next phase.

Will assign mission sub-tasks to drones and reassign unfinished work when an
agent fails or drops out. The baseline gives each drone a fixed instruction, so
there is nothing to allocate yet.
"""


class TaskAllocator:
    def allocate(self, mission, agents):
        raise NotImplementedError("task allocation is part of the next phase")
