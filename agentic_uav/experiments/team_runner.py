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
            adapter=adapter_factory(vehicle.vehicle_id),
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


def run_team(agents, tasks, bus, max_total_steps=400) -> TeamRunReport:
    """Step agents in simulated-time order until they all finish."""
    for a in agents:
        a.start(tasks[a.vehicle_id])

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
