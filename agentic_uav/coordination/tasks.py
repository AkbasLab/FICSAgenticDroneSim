"""Work represented as explicit, first-class tasks (Phase 8.1).

Until now a drone was *handed* a sector. From Phase 8 the mission is a set of
tasks and the team works out who does what, with no central assignment. That
requires the work itself to be an object agents can announce, bid on, claim,
release and complete - not a parameter baked into a script.

Two pieces live here:

  MissionTask - one unit of work, carrying everything needed to arbitrate it:
                a version number (so stale claims can be detected), a lease
                (so a silent drone loses its task), and the winning bid (so a
                duplicate claim can be resolved deterministically).

  TaskBoard   - one agent's *local* view of the task set. Every agent has its
                own; they are updated only by delivered messages, so two agents
                can legitimately disagree for a while. Reconciling that
                disagreement is the protocol's job, not the board's.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class TaskType(str, Enum):
    SEARCH_SECTOR = "search_sector"
    MAINTAIN_RELAY = "maintain_relay"
    INSPECT_TARGET = "inspect_target"
    RETURN_TO_BASE = "return_to_base"


class TaskStatus(str, Enum):
    UNASSIGNED = "unassigned"     # nobody holds it
    CLAIMED = "claimed"           # someone has claimed it, lease running
    IN_PROGRESS = "in_progress"   # claimant has reported progress
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class MissionTask:
    task_id: str
    task_type: TaskType
    region: Any = None                       # Rect for a sector, Position3D for a point
    priority: int = 1                        # higher runs first
    required_capabilities: Set[str] = field(default_factory=set)
    deadline: Optional[float] = None
    status: TaskStatus = TaskStatus.UNASSIGNED
    assigned_agent: Optional[str] = None
    lease_expires_at: Optional[float] = None

    # arbitration metadata
    version: int = 0                         # bumped on every state change
    winning_bid: Optional[float] = None      # the bid the claim was won with

    # --- lease ---

    def lease_expired(self, now) -> bool:
        if self.status not in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS):
            return False
        if self.lease_expires_at is None:
            return False
        return now >= self.lease_expires_at

    def is_open(self, now) -> bool:
        """Available to bid on: unheld, or held by someone who went silent."""
        if self.status in (TaskStatus.COMPLETE, TaskStatus.FAILED):
            return False
        if self.status is TaskStatus.UNASSIGNED:
            return True
        return self.lease_expired(now)

    def held_by(self, vehicle_id, now) -> bool:
        return (self.assigned_agent == vehicle_id
                and self.status in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS)
                and not self.lease_expired(now))

    # --- state transitions ---
    #
    # `version` is a Lamport clock, not a local counter. Every agent keeps its
    # own copy of a task, so a plain `+= 1` would produce incomparable numbers -
    # Drone1's "v3" and Drone2's "v3" would be unrelated, and version comparison
    # across agents would be meaningless (and actively harmful, since a stale
    # claim could out-rank a newer one). Bumping to `max(seen) + 1` instead makes
    # versions globally ordered: a strictly higher version really is newer
    # information, and two genuinely simultaneous claims land on the *same*
    # version, which is exactly the case the conflict rules are there to settle.

    def bump(self, seen_version=0):
        self.version = max(self.version, seen_version) + 1
        return self.version

    def claim(self, vehicle_id, bid, now, lease_s, seen_version=0):
        self.assigned_agent = vehicle_id
        self.winning_bid = bid
        self.status = TaskStatus.CLAIMED
        self.lease_expires_at = now + lease_s
        self.bump(seen_version)

    def renew(self, now, lease_s):
        """Lease renewal is not new information about *ownership*, so it must not
        bump the version - otherwise a holder would out-rank rivals simply by
        reporting progress often."""
        self.status = TaskStatus.IN_PROGRESS
        self.lease_expires_at = now + lease_s

    def release(self, now=None, seen_version=0):
        self.assigned_agent = None
        self.winning_bid = None
        self.status = TaskStatus.UNASSIGNED
        self.lease_expires_at = None
        self.bump(seen_version)

    def complete(self, seen_version=0):
        self.status = TaskStatus.COMPLETE
        self.lease_expires_at = None
        self.bump(seen_version)

    # --- wire format ---

    def to_payload(self):
        r = self.region
        region = None
        if r is not None:
            if hasattr(r, "min_x"):
                region = {"rect": [r.min_x, r.min_y, r.max_x, r.max_y]}
            elif hasattr(r, "x"):
                region = {"point": [r.x, r.y, r.z]}
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "region": region,
            "priority": self.priority,
            "required_capabilities": sorted(self.required_capabilities),
            "deadline": self.deadline,
            "status": self.status.value,
            "assigned_agent": self.assigned_agent,
            "lease_expires_at": self.lease_expires_at,
            "version": self.version,
            "winning_bid": self.winning_bid,
        }

    @staticmethod
    def from_payload(p):
        from ..core.geometry import Rect
        from ..core.models import Position3D
        region = None
        rp = p.get("region")
        if rp:
            if "rect" in rp:
                region = Rect(*rp["rect"])
            elif "point" in rp:
                region = Position3D(*rp["point"])
        t = MissionTask(
            task_id=p["task_id"], task_type=TaskType(p["task_type"]),
            region=region, priority=p.get("priority", 1),
            required_capabilities=set(p.get("required_capabilities") or []),
            deadline=p.get("deadline"),
            status=TaskStatus(p.get("status", "unassigned")),
            assigned_agent=p.get("assigned_agent"),
            lease_expires_at=p.get("lease_expires_at"),
            version=p.get("version", 0), winning_bid=p.get("winning_bid"))
        return t


class TaskBoard:
    """One agent's local view of the mission's tasks."""

    def __init__(self, tasks=None):
        self.tasks: Dict[str, MissionTask] = {}
        for t in (tasks or []):
            self.tasks[t.task_id] = t

    def add(self, task):
        self.tasks[task.task_id] = task

    def get(self, task_id):
        return self.tasks.get(task_id)

    def all(self):
        return list(self.tasks.values())

    def open_tasks(self, now, capabilities=None):
        """Tasks available to bid on, best first (priority, then id for determinism)."""
        out = [t for t in self.tasks.values() if t.is_open(now)]
        if capabilities is not None:
            out = [t for t in out if t.required_capabilities <= set(capabilities)]
        return sorted(out, key=lambda t: (-t.priority, t.task_id))

    def held_by(self, vehicle_id, now):
        return [t for t in self.tasks.values() if t.held_by(vehicle_id, now)]

    def incomplete(self):
        return [t for t in self.tasks.values()
                if t.status not in (TaskStatus.COMPLETE, TaskStatus.FAILED)]

    def all_complete(self):
        return all(t.status is TaskStatus.COMPLETE for t in self.tasks.values())

    def expire_leases(self, now):
        """Return tasks whose holder went silent; they become open again (8.4)."""
        expired = []
        for t in self.tasks.values():
            if t.lease_expired(now):
                expired.append(t)
        return expired

    def merge(self, incoming: MissionTask):
        """Fold a task record received from a peer into the local view.

        A higher version always wins - it is strictly newer information. Equal
        versions with different claimants is the genuine conflict case, and is
        resolved by the allocator's rules, not here.
        """
        mine = self.tasks.get(incoming.task_id)
        if mine is None:
            self.tasks[incoming.task_id] = incoming
            return "added"
        if incoming.version > mine.version:
            self.tasks[incoming.task_id] = incoming
            return "updated"
        if incoming.version < mine.version:
            return "ignored_stale"
        if incoming.assigned_agent != mine.assigned_agent:
            return "conflict"
        return "same"

    def summary(self, now):
        out = {}
        for t in sorted(self.tasks.values(), key=lambda x: x.task_id):
            holder = t.assigned_agent or "-"
            flag = " (lease expired)" if t.lease_expired(now) else ""
            out[t.task_id] = f"{t.status.value}/{holder}{flag}"
        return out


def tasks_from_scenario(scenario, include_relay=True):
    """Build the mission's task set from a scenario file (8.1's example list)."""
    tasks = []
    for s in scenario.sectors:
        tasks.append(MissionTask(
            task_id=f"SEARCH_SECTOR_{s.sector_id}",
            task_type=TaskType.SEARCH_SECTOR, region=s.footprint,
            priority=2, required_capabilities={"search"},
            deadline=scenario.mission.deadline_s))
    if include_relay:
        base = scenario.base.position
        from ..core.models import Position3D
        tasks.append(MissionTask(
            task_id="MAINTAIN_RELAY_POINT_R1",
            task_type=TaskType.MAINTAIN_RELAY,
            region=Position3D(base.x, base.y + 30.0, -8.0),
            priority=1, required_capabilities={"relay"},
            deadline=scenario.mission.deadline_s))
    return tasks
