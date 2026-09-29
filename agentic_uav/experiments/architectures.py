"""The architectures under comparison, selected by configuration (Phase 13).

Four architectures plus a historical baseline, plus ablations, all built by
**one** function from **one** spec. That is the exit criterion, and it is a
scientific requirement rather than a tidiness preference: four separate programs
would differ from each other in a hundred incidental ways, and any measured
difference could be attributed to any of them. Here the only thing that varies
between two runs is the fields of the spec.

    A  centralized      one controller assigns all work
    B  independent      pre-assigned tasks, local replanning, no negotiation
    C  decentralized    contract-net, leases, roles - deterministic throughout
    D  agentic          C, with an LLM making the high-level decisions
    E  open loop        the Phase 1-2 preflight action list, for context

Everything else is held constant by construction: the same scenario, the same
skills, the same executor, the same sensor model, the same network model, and
the same runtime-safety guardian. `test_architectures.py` asserts this rather
than trusting it - the shared-component check is the one that protects every
number the paper will report.

The axis each comparison isolates:

    A vs C   centralized vs decentralized decision-making
    B vs C   the value of coordinating at all
    C vs D   the contribution of LLM reasoning, holding architecture fixed
    D vs D-  ablations: which part of D is doing the work
"""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from ..agents.comms_estimator import CommsEstimator
from ..agents.persistent_agent import PersistentAgent
from ..agents.safety_guardian import SafetyGuardian, SafetyLimits
from ..agents.search_policy import SearchAgentPolicy
from ..coordination.bidding import BidWeights
from ..coordination.comms_conditions import condition as comms_condition
from ..coordination.fleet_controller import (
    CONTROLLER_ID, CentralAssignmentClient, CentralizedPolicy, FleetController)
from ..coordination.message_bus import MessageBus
from ..coordination.network_model import NetworkModel
from ..coordination.role_manager import FixedRoleManager, RoleManager
from ..coordination.roles import HealthMonitor
from ..coordination.task_allocator import (
    DEFAULT_BID_WINDOW_S, DEFAULT_LEASE_S, TaskAllocator)
from ..coordination.tasks import TaskBoard, tasks_from_scenario
from ..simulator.ground_truth import GroundTruth, SensorModel

#: A lease long enough to outlast any skill. Phase 9 established that the lease
#: must exceed the longest sweep (~70 s) or healthy drones lose work mid-flight.
LEASE_DISABLED_S = 1e9          # "no leases" = a lease that never expires


@dataclass(frozen=True)
class ArchitectureSpec:
    """Everything that distinguishes one architecture from another."""
    key: str
    name: str
    description: str

    #: "centralized" | "none" | "contract_net"
    coordination: str = "contract_net"
    #: "rule" | "llm" | "open_loop"
    policy: str = "rule"

    # --- ablation switches (all default to the full system) ---
    persistent_memory: bool = True      # the LLM agent's own decision history
    task_leases: bool = True            # lease expiry allows reclaiming work
    dynamic_roles: bool = True          # role changes in response to failures
    force_perfect_comms: bool = False   # override the condition with nominal
    comms_health_in_bids: bool = True   # the C term of the cost model
    llm_enabled: bool = True            # False = D with the fallback policy

    #: informal note for the results table
    ablation_of: Optional[str] = None

    def label(self):
        return f"{self.key}  {self.name}"

    def as_dict(self):
        return {"key": self.key, "name": self.name,
                "coordination": self.coordination, "policy": self.policy,
                "persistent_memory": self.persistent_memory,
                "task_leases": self.task_leases,
                "dynamic_roles": self.dynamic_roles,
                "force_perfect_comms": self.force_perfect_comms,
                "comms_health_in_bids": self.comms_health_in_bids,
                "llm_enabled": self.llm_enabled,
                "ablation_of": self.ablation_of}


# --- the registry --------------------------------------------------------

A = ArchitectureSpec(
    "A", "Centralized fleet controller",
    "One controller holds the fleet view and assigns every task. State reports "
    "and commands cross the same degraded link; drones that lose contact fall "
    "back to a local rule.",
    coordination="centralized", policy="rule")

B = ArchitectureSpec(
    "B", "Independent persistent agents",
    "Each drone is given a task up front and replans locally, but never "
    "negotiates or reassigns. Isolates the value of coordination itself.",
    coordination="none", policy="rule")

C = ArchitectureSpec(
    "C", "Deterministic decentralized agents",
    "Local beliefs, message exchange, deterministic bids, task leases, role "
    "rules and dynamic reassignment. No LLM anywhere.",
    coordination="contract_net", policy="rule")

D = ArchitectureSpec(
    "D", "Agentic decentralized agents",
    "Architecture C with an LLM making the high-level decisions, through the "
    "same beliefs, protocol, tool set and guardian.",
    coordination="contract_net", policy="llm")

E = ArchitectureSpec(
    "E", "Open-loop preflight baseline",
    "The original action-list system: a plan is produced before flight and "
    "executed without replanning. Historical context, not a serious baseline.",
    coordination="none", policy="open_loop")

#: The ablations named in 13's "Important ablations". Each is `replace()`d from
#: its parent, so an ablation cannot accidentally differ in a second respect.
ABLATIONS = [
    replace(D, key="D1", name="Agentic, no persistent memory",
            description="D with the agent's own decision history removed from "
                        "its context each turn.",
            persistent_memory=False, ablation_of="D"),
    replace(D, key="D2", name="Agentic, no task leases",
            description="D with leases that never expire, so work held by a "
                        "silent drone can never be reclaimed on timeout.",
            task_leases=False, ablation_of="D"),
    replace(D, key="D3", name="Agentic, no dynamic roles",
            description="D with role changes disabled; every drone keeps the "
                        "role it started with.",
            dynamic_roles=False, ablation_of="D"),
    replace(D, key="D4", name="Agentic, perfect communication",
            description="D with the degradation model forced to nominal, "
                        "isolating how much of D's behaviour is a response to "
                        "the link rather than to the mission.",
            force_perfect_comms=True, ablation_of="D"),
    replace(C, key="C1", name="Deterministic, with comms-health inputs",
            description="C with the communication-health term in the cost "
                        "model, matching the information available to D.",
            comms_health_in_bids=True, ablation_of="C"),
    replace(D, key="D5", name="Agentic, LLM replaced by fallback",
            description="D with the model disabled so every decision falls "
                        "through to the deterministic policy. Should reproduce "
                        "C; if it does not, C and D differ in something other "
                        "than the LLM and the comparison is confounded.",
            llm_enabled=False, ablation_of="D"),
]

MAIN = [A, B, C, D, E]
ALL: Dict[str, ArchitectureSpec] = {s.key: s for s in MAIN + ABLATIONS}


def spec(key) -> ArchitectureSpec:
    k = str(key).upper()
    if k not in ALL:
        raise KeyError(f"unknown architecture {key!r}; "
                       f"have {', '.join(sorted(ALL))}")
    return ALL[k]


# --- the one builder -----------------------------------------------------


@dataclass
class BuiltRun:
    """Everything a runner needs, whatever the architecture."""
    spec: ArchitectureSpec
    agents: List[Any]
    tasks: Dict[str, Any]
    bus: Any
    truth: Any
    controller: Optional[FleetController] = None
    policies: Dict[str, Any] = field(default_factory=dict)
    scenario: Any = None
    condition: Optional[str] = None
    seed: Optional[int] = None


def build(spec_or_key, scenario, adapter_factory, condition=None, seed=None,
          backend=None, battery_s=None, heartbeat_interval_s=20.0,
          bid_window_s=None, max_steps=160) -> BuiltRun:
    """Construct a runnable team for any architecture.

    The shared components are created once, above the branch: the same ground
    truth, the same sensor model, the same network model, the same guardian
    limits. Only `coordination` and `policy` are allowed to change what gets
    built, and each one touches exactly one object in the agent.
    """
    sp = spec_or_key if isinstance(spec_or_key, ArchitectureSpec) \
        else spec(spec_or_key)

    # --- held constant across every architecture --------------------------
    truth = GroundTruth(scenario)
    sensor = SensorModel(truth)
    limits = SafetyLimits.from_scenario(scenario)
    run_seed = scenario.random_seed if seed is None else seed

    effective_condition = "nominal" if sp.force_perfect_comms else condition
    profile = comms_condition(effective_condition) if effective_condition else None
    net = NetworkModel(profile=profile, seed=run_seed,
                       position_of=truth.true_position) if profile else None
    bus = MessageBus(network=net)

    mission_tasks = tasks_from_scenario(scenario, include_relay=False)
    weights = BidWeights() if sp.comms_health_in_bids \
        else BidWeights(w_comms=0.0)

    agents, tasks, policies = [], {}, {}
    controller = None

    if sp.coordination == "centralized":
        controller = FleetController(
            link=bus.register(CONTROLLER_ID), scenario=scenario,
            tasks=[_copy_task(t) for t in mission_tasks], weights=weights)

    for i, vehicle in enumerate(scenario.vehicles):
        vid = vehicle.vehicle_id
        link = bus.register(vid)
        health = HealthMonitor(vid, heartbeat_interval_s=heartbeat_interval_s)
        comms = CommsEstimator(vid, heartbeat_interval_s=heartbeat_interval_s)

        # --- the coordination object: the single axis A/B/C differ on -----
        allocator = None
        if sp.coordination == "centralized":
            allocator = CentralAssignmentClient(vid, link, scenario)
        elif sp.coordination == "contract_net":
            allocator = TaskAllocator(
                vehicle_id=vid, board=TaskBoard([_copy_task(t)
                                                 for t in mission_tasks]),
                link=link, weights=weights,
                capabilities={"search", "relay", "inspect"},
                lease_s=LEASE_DISABLED_S if not sp.task_leases
                        else DEFAULT_LEASE_S,
                bid_window_s=(DEFAULT_BID_WINDOW_S if bid_window_s is None
                              else bid_window_s),
                health=health)

        # --- the policy object: the single axis C/D differ on -------------
        policy = _make_policy(sp, vid, limits, allocator, backend)
        if policy is not None:
            policies[vid] = policy

        agent = PersistentAgent(
            vehicle_id=vid,
            adapter=_placed(adapter_factory(vid), vid, vehicle.start),
            policy=policy,
            guardian=SafetyGuardian(limits=limits),
            home=vehicle.start,
            battery_total_s=battery_s or vehicle.battery_s,
            cruise_altitude=scenario.sectors[0].altitude,
            sensor=sensor, roster=truth.roster(), sector_ids=truth.sector_ids(),
            link=link, message_log=bus.log, allocator=allocator,
            health=health,
            role_manager=(RoleManager(vid, health) if sp.dynamic_roles
                          else FixedRoleManager(vid, health)),
            comms=comms, max_steps=max_steps)
        agent.belief.brief(scenario)
        agents.append(agent)

        # B and E start with a sector in hand and never renegotiate.
        if sp.coordination == "none":
            tasks[vid] = _initial_task(scenario, i)
        else:
            tasks[vid] = None

    return BuiltRun(spec=sp, agents=agents, tasks=tasks, bus=bus, truth=truth,
                    controller=controller, policies=policies,
                    scenario=scenario, condition=effective_condition,
                    seed=run_seed)


def _make_policy(sp, vehicle_id, limits, allocator, backend):
    """The policy slot. `None` means the agent's own default rule policy."""
    if sp.policy == "rule":
        # A's drones wait for orders instead of bidding; everything else about
        # the policy - and every command it builds - is the shared rule policy.
        return CentralizedPolicy() if sp.coordination == "centralized" else None
    if sp.policy == "open_loop":
        from .open_loop import OpenLoopPolicy
        return OpenLoopPolicy()
    if sp.policy == "llm":
        from ..agents.llm_policy import LLMAgentPolicy
        if not sp.llm_enabled:
            # the ablation: keep every other part of D, remove only the model
            from ..agents.llm_backends import ScriptedBackend
            from ..agents.llm_backends import BackendError
            backend = ScriptedBackend(answers=[], default=None)
        if backend is None:
            raise ValueError("architecture D needs a backend; pass backend=...")
        return LLMAgentPolicy(
            backend, vehicle_id, safety_limits=limits, allocator=allocator,
            timeout_s=None, memory_turns=6 if sp.persistent_memory else 0)
    raise ValueError(f"unknown policy {sp.policy!r}")


def _initial_task(scenario, index):
    from ..agents.objectives import SearchTask
    sector = scenario.sectors[index % len(scenario.sectors)]
    return SearchTask(task_id=f"SEARCH_SECTOR_{sector.sector_id}",
                      sector=sector, report_to=scenario.base.position)


def _copy_task(t):
    """Each participant gets its own copy of the board - never a shared object."""
    from ..coordination.tasks import MissionTask
    return MissionTask(
        task_id=t.task_id, task_type=t.task_type, region=t.region,
        priority=t.priority, required_capabilities=set(t.required_capabilities),
        deadline=t.deadline)


def _placed(adapter, vehicle_id, start):
    if start is not None and hasattr(adapter, "place"):
        adapter.place(vehicle_id, start)
    return adapter


# --- running any architecture -------------------------------------------


@dataclass
class RunResult:
    """One run of one architecture under one condition and seed."""
    spec: ArchitectureSpec
    condition: Optional[str]
    seed: int
    sectors_searched: int
    sectors_total: int
    coverage: float
    all_landed: bool
    drones_home: int
    targets_found: int
    targets_total: int
    duplicated_sectors: int
    mission_time_s: float
    total_steps: int
    messages_sent: int
    messages_delivered: int
    delivery_rate: float
    guardian_interventions: int
    stopped: List[str] = field(default_factory=list)
    llm: Optional[Dict[str, Any]] = None
    controller: Optional[Dict[str, Any]] = None

    def as_row(self):
        d = {"architecture": self.spec.key, "name": self.spec.name,
             "condition": self.condition or "none", "seed": self.seed,
             "stopped": ",".join(self.stopped) or "-",
             "sectors_searched": self.sectors_searched,
             "coverage": round(self.coverage, 4),
             "all_landed": self.all_landed, "drones_home": self.drones_home,
             "targets_found": self.targets_found,
             "duplicated_sectors": self.duplicated_sectors,
             "mission_time_s": round(self.mission_time_s, 1),
             "total_steps": self.total_steps,
             "delivery_rate": round(self.delivery_rate, 4),
             "guardian_interventions": self.guardian_interventions}
        if self.llm:
            d["llm_fallback_rate"] = self.llm.get("fallback_rate")
            d["llm_turns"] = self.llm.get("turns")
        if self.controller:
            d["assignments_sent"] = self.controller.get("assignments_sent")
            d["reassignments"] = self.controller.get("reassignments")
        return d


def run(built: BuiltRun, max_total_steps=600, stop_at=None) -> RunResult:
    """Step a built team to completion.

    Identical scheduling for every architecture - whichever agent is furthest
    behind on the simulated clock goes next - so two architectures cannot differ
    because one was stepped more often. Architecture A additionally ticks its
    controller, which is the only structural difference in the loop and is
    unavoidable: a centralized system has a component that is not a drone.
    """
    agents, tasks = built.agents, built.tasks
    for a in agents:
        a.start(tasks.get(a.vehicle_id))

    # Fault injection is how this study gets a question worth asking. With four
    # drones, four sectors and nobody failing, an architecture that never
    # coordinates finishes as fast as one that does - B is optimal by
    # construction, and the comparison measures nothing. Killing a drone
    # mid-mission is what forces the surviving work to be noticed and reassigned.
    stop_at = dict(stop_at or {})
    stopped = set()

    active, total = list(agents), 0
    while active and total < max_total_steps:
        agent = min(active, key=lambda a: a.belief.now)
        # Evaluated against each drone's *own* clock, not the fleet minimum: a
        # kill time compared against the slowest agent never fires for a drone
        # that has raced ahead. Faults therefore land on skill boundaries - a
        # drone part-way through a 70 s sweep finishes it and then stops, since
        # simulated time advances one whole skill at a time. Pick kill times
        # before the sweep starts if the intent is to prevent the work.
        for a in agents:
            when = stop_at.get(a.vehicle_id)
            if when is not None and a.vehicle_id not in stopped \
                    and a.belief.now >= when:
                a.stopped = True
                stopped.add(a.vehicle_id)
        if built.controller is not None:
            # The controller is a continuously running process, so its clock is
            # global simulated time - approximated by the fleet's leading edge,
            # not by the agent that happens to be furthest behind. Ticking it at
            # the minimum clock froze its heartbeat cadence behind the slowest
            # drone, and drones that had raced ahead concluded they were
            # disconnected and started duplicating work.
            built.controller.tick(max(a.belief.now for a in built.agents))
        total += 1
        if not agent.step():
            active.remove(agent)

    return _measure(built, total, stopped=stopped)


def _measure(built: BuiltRun, total_steps, stopped=()) -> RunResult:
    from ..experiments.llm_log import combined_stats

    scenario, truth = built.scenario, built.truth
    reports = {a.vehicle_id: a.report() for a in built.agents}

    # Coverage must count sectors that were actually *flown*, not sectors a
    # drone has merely heard about. `local_map.searched_ids` includes regions
    # learned from a teammate's TASK_COMPLETE, so using it counted gossip as
    # work and reported every sector as duplicated. `by_vehicle` is what
    # separates the two.
    flown = {}                                   # sector_id -> {vehicle_ids}
    for a in built.agents:
        for r in a.belief.local_map.searched_regions:
            if r.by_vehicle == a.vehicle_id:
                flown.setdefault(r.region_id, set()).add(a.vehicle_id)

    sector_ids = {s.sector_id for s in scenario.sectors}
    searched = set(flown) & sector_ids
    duplicated = sum(1 for sid in searched if len(flown[sid]) > 1)

    found = set()
    for a in built.agents:
        found.update(a.belief.detections)

    stats = built.bus.stats()
    llm = None
    if built.policies:
        logs = [p.log for p in built.policies.values() if hasattr(p, "log")]
        if logs:
            llm = combined_stats(logs)

    survivors = [a for a in built.agents if a.vehicle_id not in set(stopped)]
    return RunResult(
        spec=built.spec, condition=built.condition, seed=built.seed,
        stopped=sorted(stopped),
        sectors_searched=len(searched), sectors_total=len(sector_ids),
        coverage=len(searched) / max(1, len(sector_ids)),
        all_landed=all(reports[a.vehicle_id].landed for a in survivors),
        drones_home=sum(1 for a in survivors
                        if reports[a.vehicle_id].landed
                        and reports[a.vehicle_id].returned_home),
        targets_found=len(found), targets_total=len(scenario.targets),
        duplicated_sectors=duplicated,
        mission_time_s=max((a.belief.now for a in built.agents), default=0.0),
        total_steps=total_steps,
        messages_sent=stats.get("sent", 0),
        messages_delivered=stats.get("delivered", 0),
        delivery_rate=stats.get("delivery_rate", 0.0),
        guardian_interventions=sum(len(a.guardian_log.interventions())
                                   for a in built.agents),
        llm=llm,
        controller=built.controller.stats() if built.controller else None)


def run_architecture(key, scenario, adapter_factory, condition=None, seed=None,
                     backend=None, stop_at=None, max_total_steps=600,
                     **kw) -> RunResult:
    """Build and run in one call - the usual entry point."""
    built = build(key, scenario, adapter_factory, condition=condition,
                  seed=seed, backend=backend, **kw)
    return run(built, max_total_steps=max_total_steps, stop_at=stop_at)
