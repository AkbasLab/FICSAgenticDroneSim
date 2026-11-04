"""Coordination: how drones divide a team mission between themselves (AUV-08, Phase 8).

    tasks.py          the work as explicit tasks, and each agent's own task book
    bids.py           what a drone would bid for a task, term by term
    contract_net.py   announce, bid, claim, acknowledge, progress, lease, release

THE BOUNDARY is the agents' (`agents/__init__.py`), enforced by the same test
(`tests/test_sensing.py`): nothing here may import the simulator or the
experiments, nor the scenario's ground truth. An agent's task book is built
from the public brief and from the messages it was delivered, and from
nothing else -- there is no shared book, and no agent reads another's. If one
could, the allocation would be centralized in all but name.
"""
