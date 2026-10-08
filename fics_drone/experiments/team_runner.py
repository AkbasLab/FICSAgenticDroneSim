"""Runs all four agents together, each on its own thread and its own
AgentLink into one shared MessageBus - this is FICS's run_team_threaded(),
the real-time runner selected for --airsim. A fully deterministic
simulated-clock interleaver (FICS's other runner) isn't built here: this
repo's skills layer is inherently real-time (actual time.sleep polling
loops), so a sim-clock version would need a parallel non-real-time skill
execution path - a real rearchitecture, not something to invent cheaply
under this phase's scope. Threaded is the one mechanism this build has, and
it is the one FICS itself uses for live flight anyway.
"""

import threading
from typing import Dict, List, Optional

from ..agents.decision_log import DecisionLogger
from ..agents.persistent_agent import AgentReport, PersistentAgent
from ..coordination.message_bus import AgentLink, MessageBus
from ..coordination.roles import HealthMonitor
from ..coordination.task_allocator import TaskAllocator
from ..coordination.tasks import TaskBoard
from ..core.scenario import Scenario

DEFAULT_HEARTBEAT_INTERVAL_S = 15.0  # nominal cadence used only for HealthMonitor grading -
# HEARTBEATs are actually sent once per search leg (event-driven, not a fixed timer), so this
# is nothing more than a reasonable assumption about typical leg-to-leg spacing to grade silence
# against, same simplification FICS's own configurable --heartbeat period makes

# Belt-and-braces alongside PersistentAgent's own MAX_STEPS backstop: a genuine
# infinite-loop bug once made one drone's thread spin forever with no error, and the
# plain t.join() here waited on it silently with zero visibility. Generous (well above
# any real mission's ~300s battery budget), but bounded, and now at least reports which
# drone never finished instead of leaving the whole process looking hung with no clue why.
FLEET_JOIN_TIMEOUT_S = 600.0


def _join_all(threads, names):
    for t, name in zip(threads, names):
        t.join(timeout=FLEET_JOIN_TIMEOUT_S)
        if t.is_alive():
            print(f"WARNING: {name}'s thread did not finish within {FLEET_JOIN_TIMEOUT_S}s "
                  f"- abandoning it, continuing with whatever else completed")


def run_team_threaded(scenario: Scenario, adapters: Dict[str, object], bus: MessageBus = None,
                       loggers: Dict[str, DecisionLogger] = None,
                       comms_estimators: Dict[str, "CommsEstimator"] = None) -> Dict[str, AgentReport]:
    """Static assignment (scenario's own spec.sector), Phase 7 behavior -
    unchanged, still used where a fixed assignment is what's wanted. Phase 10
    uses this one (not run_team_with_allocation) for the comms study, on
    purpose: assignment stays fixed regardless of message loss, so a degraded
    bus tests Phase 7's messaging protocol in isolation rather than
    confounding it with Phase 8's contract-net bidding, which depends on
    messages of its own and would otherwise fail to even finish allocating
    under `severe` - a real, separate finding, not what Phase 10 is about."""
    bus = bus or MessageBus()
    reports: Dict[str, AgentReport] = {}
    agents: Dict[str, PersistentAgent] = {}

    for spec in scenario.drones:
        adapter = adapters[spec.name]
        link = AgentLink(bus, spec.name)
        logger = loggers.get(spec.name) if loggers else None
        estimator = comms_estimators.get(spec.name) if comms_estimators else None
        agents[spec.name] = PersistentAgent(adapter, scenario, spec.sector, spec.spawn_offset,
                                             spec.battery_s, logger=logger, drone_name=spec.name, link=link,
                                             comms_estimator=estimator)

    def fly_one(name):
        reports[name] = agents[name].run()

    threads = [threading.Thread(target=fly_one, args=(name,)) for name in agents]
    for t in threads:
        t.start()
    _join_all(threads, list(agents.keys()))

    return reports, agents, bus


def allocate_sectors_and_boards(scenario: Scenario, links: Dict[str, AgentLink]):
    """Phase 8's bidding round, plus (Phase 9) hands back each agent's own
    TaskBoard afterward instead of discarding it - that board is what makes
    dynamic reassignment possible later: each agent needs its OWN view of
    who holds what, kept alive from allocation through the whole mission,
    not rebuilt from scratch."""
    results: Dict[str, Optional[str]] = {}
    boards: Dict[str, TaskBoard] = {}

    def run_one(spec):
        allocator = TaskAllocator(links[spec.name], scenario, spec.name)
        # Pre-flight: no real position yet, so each drone bids from its own
        # spawn point at full battery - the only honest "current state" available
        # before anyone has taken off.
        results[spec.name] = allocator.allocate(world_position=spec.spawn_offset, battery_frac=1.0)
        boards[spec.name] = allocator.board

    threads = [threading.Thread(target=run_one, args=(spec,)) for spec in scenario.drones]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, boards


def allocate_sectors(scenario: Scenario, links: Dict[str, AgentLink]) -> Dict[str, Optional[str]]:
    """Phase 8 exit criterion only needs the assignment - kept as its own
    function so existing Phase 8 tests/callers don't need to change."""
    assignment, _ = allocate_sectors_and_boards(scenario, links)
    return assignment


def run_team_with_allocation(scenario: Scenario, adapters: Dict[str, object], bus: MessageBus = None,
                              loggers: Dict[str, DecisionLogger] = None,
                              comms_estimators: Dict[str, "CommsEstimator"] = None):
    """Phase 8 exit criterion: the team divides sectors itself, no central
    assignment - then flies using whatever each drone actually won.

    Phase 10: `bus` carrying a NetworkModel degrades delivery; passing
    `comms_estimators` gives each agent its own CommsEstimator, fed every
    delivered message, so a caller (run_comms_study.py) can read back each
    agent's own inferred view of link quality after the run."""
    bus = bus or MessageBus()
    links = {spec.name: AgentLink(bus, spec.name) for spec in scenario.drones}

    assignment = allocate_sectors(scenario, links)

    reports: Dict[str, AgentReport] = {}
    agents: Dict[str, PersistentAgent] = {}
    for spec in scenario.drones:
        sector_id = assignment.get(spec.name)
        if sector_id is None:
            continue  # didn't win anything - nothing to fly
        logger = loggers.get(spec.name) if loggers else None
        estimator = comms_estimators.get(spec.name) if comms_estimators else None
        agents[spec.name] = PersistentAgent(adapters[spec.name], scenario, sector_id, spec.spawn_offset,
                                             spec.battery_s, logger=logger, drone_name=spec.name,
                                             link=links[spec.name], comms_estimator=estimator)

    def fly_one(name):
        reports[name] = agents[name].run()

    threads = [threading.Thread(target=fly_one, args=(name,)) for name in agents]
    for t in threads:
        t.start()
    _join_all(threads, list(agents.keys()))

    return reports, agents, bus, assignment


def run_team_with_faults(scenario: Scenario, adapters: Dict[str, object], bus: MessageBus = None,
                          loggers: Dict[str, DecisionLogger] = None, kill_name: str = None,
                          kill_at_s: float = None, heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
                          policy_factory=None):
    """Phase 9 exit criterion: one drone is switched off mid-mission - no
    flight, no sensing, no heartbeats, nobody told. The survivors detect the
    silence, reclaim its sector, and finish. Same allocate-then-fly shape as
    run_team_with_allocation, but keeps each agent's TaskBoard alive into the
    flight phase and gives every agent a shared-shape HealthMonitor, so
    PersistentAgent's own _check_for_orphans logic actually has something to
    work with.

    Phase 12: `policy_factory(drone_name)` returns that drone's OWN policy object
    (e.g. an LLMAgentPolicy over one shared backend); None keeps the deterministic
    default, so every earlier caller is unchanged."""
    bus = bus or MessageBus()
    links = {spec.name: AgentLink(bus, spec.name) for spec in scenario.drones}

    assignment, boards = allocate_sectors_and_boards(scenario, links)

    reports: Dict[str, AgentReport] = {}
    agents: Dict[str, PersistentAgent] = {}
    for spec in scenario.drones:
        sector_id = assignment.get(spec.name)
        if sector_id is None:
            continue
        logger = loggers.get(spec.name) if loggers else None
        this_kill_at_s = kill_at_s if spec.name == kill_name else None
        agents[spec.name] = PersistentAgent(
            adapters[spec.name], scenario, sector_id, spec.spawn_offset, spec.battery_s,
            logger=logger, drone_name=spec.name, link=links[spec.name],
            task_board=boards[spec.name], health_monitor=HealthMonitor(heartbeat_interval_s),
            kill_at_s=this_kill_at_s,
            policy=policy_factory(spec.name) if policy_factory else None)

    def fly_one(name):
        reports[name] = agents[name].run()

    threads = [threading.Thread(target=fly_one, args=(name,)) for name in agents]
    for t in threads:
        t.start()
    _join_all(threads, list(agents.keys()))

    return reports, agents, bus, assignment
