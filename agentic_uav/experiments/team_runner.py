"""Run several persistent agents together over a shared message bus (Phase 7).

Agents are stepped in simulated-time order: whichever agent's clock is furthest
behind goes next. That makes the run a simple discrete-event simulation - agents
genuinely interleave, so a message sent by one at t=40s is available to another
whose clock has reached t=40s, and beliefs update mid-flight instead of after the
fact. It is also fully deterministic, so a run always replays identically.

Each agent still owns its own adapter (one AirSim client per vehicle) and its own
belief. Nothing here reaches into an agent's memory; the runner only calls
`step()` and reads the public report at the end.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from ..agents.objectives import SearchTask
from ..agents.persistent_agent import PersistentAgent
from ..coordination.message_bus import MessageBus
from ..simulator.ground_truth import GroundTruth, SensorModel


@dataclass
class TeamRunReport:
    agents: Dict[str, object] = field(default_factory=dict)   # vid -> AgentRunReport
    message_stats: dict = field(default_factory=dict)
    message_log: object = None
    bus: object = None
    total_steps: int = 0
    errors: dict = field(default_factory=dict)
    stopped: dict = field(default_factory=dict)   # vehicle_id -> time it was killed

    @property
    def all_completed(self):
        return all(r.completed for r in self.agents.values())

    @property
    def sectors_searched(self):
        out = []
        for r in self.agents.values():
            if r.sector_searched:
                out.append(r.task_id.replace("search_", ""))
        return sorted(out)

    @property
    def targets_found(self):
        found = set()
        for r in self.agents.values():
            found.update(r.detections)
        return sorted(found)


def build_team(scenario, adapter_factory, latency_s=0.0, loss_rate=0.0,
               rng=None, battery_s=None):
    """Create one agent per vehicle, all sharing one bus and one ground truth."""
    truth = GroundTruth(scenario)
    sensor = SensorModel(truth)
    bus = MessageBus(latency_s=latency_s, loss_rate=loss_rate, rng=rng)

    agents, tasks = [], {}
    for i, vehicle in enumerate(scenario.vehicles):
        sector = scenario.sectors[i % len(scenario.sectors)]
        agent = PersistentAgent(
            vehicle_id=vehicle.vehicle_id,
            adapter=_placed(adapter_factory(vehicle.vehicle_id),
                            vehicle.vehicle_id, vehicle.start),
            home=vehicle.start,
            battery_total_s=battery_s or vehicle.battery_s,
            cruise_altitude=sector.altitude,
            sensor=sensor,
            roster=truth.roster(),
            sector_ids=truth.sector_ids(),
            link=bus.register(vehicle.vehicle_id),
            message_log=bus.log)
        agent.belief.brief(scenario)
        agents.append(agent)
        tasks[vehicle.vehicle_id] = SearchTask(
            task_id=f"search_{sector.sector_id}", sector=sector,
            report_to=scenario.base.position)
    return agents, tasks, bus, truth


def build_allocating_team(scenario, adapter_factory, latency_s=0.0, loss_rate=0.0,
                          rng=None, battery_s=None, lease_s=None,
                          bid_window_s=None, capabilities=None,
                          heartbeat_interval_s=20.0, network=None, seed=None,
                          policy_factory=None, guardian_factory=None):
    """Phase 8: a team given the *mission*, with no sector assigned to anyone.

    Every agent gets the same task board and works out its own share through
    the contract-net protocol. Contrast with `build_team`, where the sectors are
    handed out up front by the experiment.

    Phase 12: `policy_factory(vehicle_id, allocator)` builds each agent's policy.
    It is called once per drone, so four agents get four *separate* policy
    objects - separate memory, separate decision history - even when those
    policies share one model process. That separation is the research property
    12.1 asks for, and building it here means every existing caller keeps the
    deterministic policy without changing a line.
    """
    from ..agents.comms_estimator import CommsEstimator
    from ..coordination.bidding import BidWeights
    from ..coordination.network_model import NetworkModel
    from ..coordination.role_manager import RoleManager
    from ..coordination.roles import HealthMonitor
    from ..coordination.task_allocator import (
        DEFAULT_BID_WINDOW_S, DEFAULT_LEASE_S, TaskAllocator)
    from ..coordination.tasks import TaskBoard, tasks_from_scenario

    truth = GroundTruth(scenario)
    sensor = SensorModel(truth)

    # Phase 10: a seeded NetworkModel, if a profile was given. The model can see
    # true positions (range and interference need them) because it is simulator
    # infrastructure - agents never hold it.
    net = None
    if network is not None:
        run_seed = scenario.random_seed if seed is None else seed
        net = NetworkModel(profile=network, seed=run_seed,
                           position_of=truth.true_position)
    bus = MessageBus(latency_s=latency_s, loss_rate=loss_rate, rng=rng,
                     network=net)
    mission_tasks = tasks_from_scenario(scenario, include_relay=False)

    agents = []
    for vehicle in scenario.vehicles:
        # each agent gets its OWN copy of the board - no shared state
        board = TaskBoard([MissionTaskCopy(t) for t in mission_tasks])
        link = bus.register(vehicle.vehicle_id)
        health = HealthMonitor(vehicle.vehicle_id,
                               heartbeat_interval_s=heartbeat_interval_s)
        roles = RoleManager(vehicle.vehicle_id, health)
        comms = CommsEstimator(vehicle.vehicle_id,
                               heartbeat_interval_s=heartbeat_interval_s)
        allocator = TaskAllocator(
            vehicle_id=vehicle.vehicle_id, board=board, link=link,
            weights=BidWeights(),
            capabilities=capabilities or {"search", "relay", "inspect"},
            lease_s=lease_s or DEFAULT_LEASE_S,
            bid_window_s=(DEFAULT_BID_WINDOW_S if bid_window_s is None
                          else bid_window_s),
            health=health)
        kwargs = {}
        if policy_factory is not None:
            kwargs["policy"] = policy_factory(vehicle.vehicle_id, allocator)
        if guardian_factory is not None:
            kwargs["guardian"] = guardian_factory(vehicle.vehicle_id)
        agent = PersistentAgent(
            vehicle_id=vehicle.vehicle_id,
            adapter=_placed(adapter_factory(vehicle.vehicle_id),
                            vehicle.vehicle_id, vehicle.start),
            home=vehicle.start,
            battery_total_s=battery_s or vehicle.battery_s,
            cruise_altitude=scenario.sectors[0].altitude,
            sensor=sensor, roster=truth.roster(), sector_ids=truth.sector_ids(),
            link=link, message_log=bus.log, allocator=allocator,
            health=health, role_manager=roles, comms=comms, max_steps=120,
            **kwargs)
        agent.belief.brief(scenario)
        agents.append(agent)

    # no tasks dict: every agent starts empty-handed and bids for work
    return agents, {v.vehicle_id: None for v in scenario.vehicles}, bus, truth


def _placed(adapter, vehicle_id, start):
    """Start a vehicle on its own pad when the adapter supports being told.

    The AirSim adapter does not - the simulator owns vehicle placement there,
    via settings.json - so this is feature-tested rather than assumed.
    """
    if start is not None and hasattr(adapter, "place"):
        adapter.place(vehicle_id, start)
    return adapter


def MissionTaskCopy(t):
    """A per-agent copy of a task, so boards can legitimately diverge."""
    import copy
    return copy.deepcopy(t)


def run_team(agents, tasks, bus, max_total_steps=400) -> TeamRunReport:
    """Step agents in simulated-time order until they all finish."""
    for a in agents:
        a.start(tasks.get(a.vehicle_id))

    active = list(agents)
    total = 0
    while active and total < max_total_steps:
        # whichever agent is furthest behind in sim time goes next
        agent = min(active, key=lambda a: a.belief.now)
        total += 1
        if not agent.step():
            active.remove(agent)

    return TeamRunReport(
        agents={a.vehicle_id: a.report() for a in agents},
        message_stats=bus.stats(), message_log=bus.log, bus=bus,
        total_steps=total)


def run_team_with_faults(agents, tasks, bus, stop_at=None,
                         max_total_steps=600) -> TeamRunReport:
    """Run the team, stopping chosen agents partway through (Phase 9 exit criterion).

    `stop_at` is {vehicle_id: sim_time_s}. When an agent's clock passes its time
    it is switched off completely - no flight, no sensing, no heartbeats. Its
    teammates are *not* told; they have to notice the silence, decide it is a
    failure rather than a comms glitch, reclaim its task and carry on. No human
    command is issued at any point after the mission starts.
    """
    stop_at = stop_at or {}
    for a in agents:
        a.start(tasks.get(a.vehicle_id))

    stopped_at = {}
    active = list(agents)
    total = 0
    while active and total < max_total_steps:
        agent = min(active, key=lambda a: a.belief.now)
        total += 1

        deadline = stop_at.get(agent.vehicle_id)
        if deadline is not None and agent.belief.now >= deadline and not agent.stopped:
            agent.stopped = True
            stopped_at[agent.vehicle_id] = agent.belief.now
            active.remove(agent)
            continue

        if not agent.step():
            active.remove(agent)

    report = TeamRunReport(
        agents={a.vehicle_id: a.report() for a in agents},
        message_stats=bus.stats(), message_log=bus.log, bus=bus,
        total_steps=total)
    report.stopped = stopped_at
    return report


def run_team_threaded(agents, tasks, bus) -> TeamRunReport:
    """Fly all agents at the same time, one thread each - for AirSim.

    `run_team` interleaves agents on a *simulated* clock, which is exact and
    deterministic but serialises real flight: with AirSim every skill blocks on
    `.join()`, so drone 1 would fly its whole sweep before drone 2 moved. Here
    each agent owns a thread and its own AirSim client, so the fleet genuinely
    flies concurrently and messages cross mid-flight. Thread ordering makes the
    run non-deterministic, so use this for the simulator and `run_team` for
    reproducible experiments.
    """
    import threading

    errors = {}

    def fly(agent):
        try:
            agent.start(tasks[agent.vehicle_id])
            while agent.step():
                pass
        except Exception as e:                      # keep one drone's failure local
            errors[agent.vehicle_id] = repr(e)

    threads = [threading.Thread(target=fly, args=(a,), name=a.vehicle_id,
                                daemon=True) for a in agents]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    report = TeamRunReport(
        agents={a.vehicle_id: a.report() for a in agents},
        message_stats=bus.stats(), message_log=bus.log, bus=bus,
        total_steps=sum(a.steps for a in agents))
    if errors:
        report.errors = errors
    return report
