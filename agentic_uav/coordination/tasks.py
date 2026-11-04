"""The work, as explicit tasks (AUV-08, 8.1), and each agent's own view of them.

    tasks = tasks_from_brief(brief)          # the team mission: one SEARCH_SECTOR per sector
    book = TaskBook("Drone2", tasks)         # Drone2's own view, changed only by what it does and hears
    book.update(book.get("search S1").claimed("Drone1", at=1.0, lease_s=10.0), at=1.5, why="Drone1#3 claimed it")

A `MissionTask` is AUV-08's, field for field -- id, type, region, priority,
required capabilities, deadline, status, assignee, lease expiry -- and one
more: a VERSION. A task that returns to the pool (released, or its lease run
out) comes back with its version one higher, so a claim made for the old
version can be told from one made for the new (8.5, rule 1).

ONE TEAM MISSION. `tasks_from_brief` turns the brief's sectors into one
`SEARCH_SECTOR` task each, in the brief's order, every one open at version 1.
Every agent derives the same tasks from the same brief: that is the team
mission, and nobody's assignment. The task id is the task as the rule policy
already reads it, "search S1".

THE TYPES. AUV-08 names search, relay, inspection and return-to-base work.
This mission generates only the first: it has no relay point and no target to
inspect, and going home is what a drone does with nothing left, not work to
divide. The others are named, so a later mission can generate them.

THE TASK BOOK is one agent's view of every task: what it believes each one's
status, holder, lease and version are. It is changed by the agent's own acts
and by the messages it receives -- by nothing else -- and it never takes an
older version over a newer one. Every change is logged, with when and why,
so the record can show how each agent's view came to be what it was.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from ..core.geometry import Region
from ..core.scenario import MissionBrief


class TaskType(str, Enum):
    SEARCH_SECTOR = "search_sector"
    MAINTAIN_RELAY_POINT = "maintain_relay_point"     # named; no mission generates it yet
    INSPECT_TARGET = "inspect_target"                 # named; no mission generates it yet
    RETURN_TO_BASE = "return_to_base"                 # named; what a drone does with nothing left


class TaskStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETE = "complete"
    ABANDONED = "abandoned"            # Phase 9: no drone can still do it; the team goes home without it


SEARCH = "search"                         # the capability a sector search needs
DEFAULT_CAPABILITIES = frozenset({SEARCH})          # every drone so far: one camera, the same airframe
SEARCH_PRIORITY = 1


@dataclass(frozen=True)
class MissionTask:
    task_id: str
    task_type: TaskType
    region: Region
    priority: int
    required_capabilities: frozenset[str]
    deadline: float | None                 # seconds from the mission's start; None for none
    status: TaskStatus = TaskStatus.OPEN
    assigned_agent: str | None = None
    lease_expires_at: float | None = None
    version: int = 1

    def __post_init__(self) -> None:
        problems = self.problems()
        if problems:
            raise ValueError(f"not a valid task {self.task_id!r}: " + "; ".join(problems))

    def problems(self) -> list[str]:
        p: list[str] = []
        if not isinstance(self.task_id, str) or not self.task_id:
            p.append("task_id must be a non-empty string")
        if not isinstance(self.task_type, TaskType):
            p.append(f"unknown task type {self.task_type!r}")
        if not isinstance(self.region, Region):
            p.append(f"region must be a Region, got {self.region!r}")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool) or self.priority < 0:
            p.append(f"priority must be an integer from 0, got {self.priority!r}")
        if not isinstance(self.required_capabilities, frozenset):
            p.append("required_capabilities must be a frozenset")
        if self.deadline is not None and not self.deadline > 0:
            p.append(f"deadline must be positive or None, got {self.deadline!r}")
        if not isinstance(self.status, TaskStatus):
            p.append(f"unknown status {self.status!r}")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            p.append(f"version must be an integer from 1, got {self.version!r}")
        if self.status is TaskStatus.OPEN and (self.assigned_agent is not None or self.lease_expires_at is not None):
            p.append("an open task has no assignee and no lease")
        if self.status is TaskStatus.CLAIMED and (not self.assigned_agent or self.lease_expires_at is None):
            p.append("a claimed task has an assignee and a lease")
        if self.status is TaskStatus.COMPLETE and (not self.assigned_agent or self.lease_expires_at is not None):
            p.append("a complete task keeps who did it, and has no lease")
        if self.status is TaskStatus.ABANDONED and (self.assigned_agent is not None or self.lease_expires_at is not None):
            p.append("an abandoned task has no assignee and no lease")
        return p

    # ------------------------------------------------------- what can happen

    def claimed(self, agent: str, at: float, lease_s: float) -> "MissionTask":
        if self.status is TaskStatus.COMPLETE:
            raise ValueError(f"{self.task_id} is complete: it cannot be claimed")
        return replace(self, status=TaskStatus.CLAIMED, assigned_agent=agent, lease_expires_at=at + lease_s)

    def renewed(self, at: float, lease_s: float) -> "MissionTask":
        if self.status is not TaskStatus.CLAIMED:
            raise ValueError(f"{self.task_id} is {self.status.value}: only a claimed task's lease is renewed")
        return replace(self, lease_expires_at=at + lease_s)

    def reopened(self) -> "MissionTask":
        """Back in the pool, one version on: a claim for the old version no longer counts."""
        if self.status is TaskStatus.COMPLETE:
            raise ValueError(f"{self.task_id} is complete: it does not return to the pool")
        return replace(self, status=TaskStatus.OPEN, assigned_agent=None, lease_expires_at=None,
                       version=self.version + 1)

    def completed(self) -> "MissionTask":
        if self.status is not TaskStatus.CLAIMED:
            raise ValueError(f"{self.task_id} is {self.status.value}: only a claimed task is completed")
        return replace(self, status=TaskStatus.COMPLETE, lease_expires_at=None)

    def abandoned(self) -> "MissionTask":
        """Given up by the team: nobody can still do it (Phase 9, 9.3). A later claim may take it back."""
        if self.status is not TaskStatus.OPEN:
            raise ValueError(f"{self.task_id} is {self.status.value}: only an open task is abandoned")
        return replace(self, status=TaskStatus.ABANDONED)

    def lease_expired(self, now: float) -> bool:
        return self.status is TaskStatus.CLAIMED and now >= self.lease_expires_at

    def as_json(self) -> dict[str, Any]:
        r = self.region
        return {"task_id": self.task_id, "task_type": self.task_type.value,
                "region": [r.x_min, r.y_min, r.x_max, r.y_max], "priority": self.priority,
                "required_capabilities": sorted(self.required_capabilities), "deadline": self.deadline,
                "status": self.status.value, "assigned_agent": self.assigned_agent,
                "lease_expires_at": None if self.lease_expires_at is None else round(self.lease_expires_at, 3),
                "version": self.version}


def tasks_from_brief(brief: MissionBrief) -> tuple[MissionTask, ...]:
    """The team mission: one open SEARCH_SECTOR task per sector, in the brief's order."""
    return tuple(MissionTask(f"search {s.id}", TaskType.SEARCH_SECTOR, s.region, SEARCH_PRIORITY,
                             frozenset({SEARCH}), brief.mission.deadline_s)
                 for s in brief.sectors)


@dataclass(frozen=True)
class BookEntry:
    """One change to an agent's view of one task."""

    at: float
    task_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    why: str

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "task_id": self.task_id, "before": self.before, "after": self.after,
                "why": self.why}


def _state(task: MissionTask) -> dict[str, Any]:
    return {"status": task.status.value, "assigned_agent": task.assigned_agent, "version": task.version,
            "lease_expires_at": None if task.lease_expires_at is None else round(task.lease_expires_at, 3)}


class TaskBook:
    """One agent's own view of the team's tasks."""

    def __init__(self, owner: str, tasks: Iterable[MissionTask]) -> None:
        self.owner = owner
        self._tasks: dict[str, MissionTask] = {}
        self.log: list[BookEntry] = []
        for t in tasks:
            if t.task_id in self._tasks:
                raise ValueError(f"task {t.task_id!r} given twice")
            self._tasks[t.task_id] = t

    def get(self, task_id: str) -> MissionTask:
        return self._tasks[task_id]

    def knows(self, task_id: str) -> bool:
        return task_id in self._tasks

    def tasks(self) -> tuple[MissionTask, ...]:
        return tuple(self._tasks.values())

    def open(self) -> tuple[MissionTask, ...]:
        return tuple(t for t in self._tasks.values() if t.status is TaskStatus.OPEN)

    def held_by(self, agent: str) -> tuple[MissionTask, ...]:
        return tuple(t for t in self._tasks.values() if t.status is TaskStatus.CLAIMED and t.assigned_agent == agent)

    def update(self, task: MissionTask, at: float, why: str) -> bool:
        """Take `task` as the latest word on it; refuse an older version. True if the view changed."""
        old = self._tasks.get(task.task_id)
        if old is None:
            raise KeyError(f"{self.owner} has no task {task.task_id!r}")
        if task.version < old.version:
            return False
        if _state(task) == _state(old):
            return False
        self._tasks[task.task_id] = task
        self.log.append(BookEntry(at, task.task_id, _state(old), _state(task), why))
        return True

    def as_json(self) -> dict[str, Any]:
        return {"owner": self.owner, "tasks": [t.as_json() for t in self._tasks.values()]}
