"""Runs one mission: build agents, plan, then execute concurrently.

This is the new home of what the baseline split between main() and
Multiple.py. It preserves the open-loop flow exactly:
  1. every drone gets its own instruction,
  2. all planning happens up front (before anything flies),
  3. the drones then execute their plans concurrently, one thread each.

Inter-agent communication, shared missions and replanning are NOT here yet -
that is the next phase. This runner is the baseline behavior expressed through
the new architecture.
"""

import threading

from ..agents.drone_agent import DroneAgent
from .logger import get_logger

log = get_logger(__name__)


def run_mission(adapter, planner_factory, drone_instructions, concurrent=True):
    """
    adapter:            a VehicleAdapter (real or mock)
    planner_factory:    zero-arg callable returning a fresh MissionPlanner
    drone_instructions: dict {vehicle_id: instruction_string}
    """
    agents = {vid: DroneAgent(vid, planner_factory(), adapter)
              for vid in drone_instructions}

    # 1 + 2: plan everything before any drone takes off.
    for vid, instruction in drone_instructions.items():
        decision = agents[vid].plan(instruction)
        actions = [c.action for c in decision.plan]
        log.info("%s planned (%s): %s", vid, decision.source, actions)

    # 3: execute. Concurrent = one thread per drone (like the baseline swarm).
    results = {}
    if concurrent and len(agents) > 1:
        threads = []
        lock = threading.Lock()

        def worker(vid):
            try:
                r = agents[vid].execute()
            except Exception as e:  # one drone failing shouldn't stop the others
                log.error("%s failed: %s", vid, e)
                r = e
            with lock:
                results[vid] = r

        for vid in agents:
            t = threading.Thread(target=worker, args=(vid,), name=f"thread-{vid}")
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
    else:
        for vid in agents:
            try:
                results[vid] = agents[vid].execute()
            except Exception as e:
                log.error("%s failed: %s", vid, e)
                results[vid] = e

    return results
