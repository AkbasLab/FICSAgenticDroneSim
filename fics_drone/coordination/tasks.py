"""One MissionTask per sector, and a per-agent TaskBoard - each agent keeps
its OWN local copy, updated only by messages it actually received, never by
reaching into another agent's board. That's what makes the version-conflict
bug FICS's own doc describes a real possibility here too, not something
designed away: two agents can each believe they won the same task if their
view of the bids differs.

version is a per-task Lamport clock (next = this task's own highest version
this agent has ever seen, +1), not a private per-agent counter - two
independent per-agent counters can both read "3" while meaning nothing in
common, which is exactly the bug FICS's own build hit and fixed.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from ..core.scenario import Scenario


class TaskStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETE = "complete"


@dataclass
class MissionTask:
    task_id: str
    sector_id: str
    status: TaskStatus = TaskStatus.OPEN
    assignee: Optional[str] = None
    winning_bid: Optional[float] = None
    version: int = 0
    lease_expires_at: Optional[float] = None  # structural only this phase - lease
    # expiry/reclaim on a gone-silent holder is real Phase 9 territory ("keep going
    # when something fails"), not this phase's exit criterion


def tasks_from_scenario(scenario: Scenario) -> Dict[str, MissionTask]:
    """One task per sector - this is shared mission structure every agent
    starts knowing (the team was briefed 'search these N sectors'), not
    secret ground truth like a target's position. Phase 6's wall is about
    targets, not about the task list itself."""
    return {f"search_{s.id}": MissionTask(task_id=f"search_{s.id}", sector_id=s.id)
            for s in scenario.sectors}


class TaskBoard:
    """One agent's own local view. apply_bid/apply_claim are the only ways
    it changes - both driven by messages, never by peeking at anyone else's
    board or the bus directly."""

    def __init__(self, scenario: Scenario):
        self.tasks: Dict[str, MissionTask] = tasks_from_scenario(scenario)
        self._bids: Dict[str, Dict[str, float]] = {tid: {} for tid in self.tasks}  # task_id -> {bidder: bid}

    def apply_bid(self, task_id: str, bidder: str, bid: float):
        self._bids.setdefault(task_id, {})[bidder] = bid

    def bids_for(self, task_id: str) -> Dict[str, float]:
        return dict(self._bids.get(task_id, {}))

    def apply_claim(self, task_id: str, claimant: str, bid: float, version: int,
                     now: Optional[float] = None, lease_s: Optional[float] = None) -> bool:
        """Lamport-clock acceptance rule: a higher version always wins; on a
        tie, the lower bid wins; on a further tie, the lower vehicle name
        wins. Returns True if this claim was accepted (the board changed).
        now/lease_s are optional so existing Phase 8 callers (pre-flight
        allocation, where lease tracking doesn't matter yet) don't need to
        change - a claim with no lease info just never expires until
        something sets one."""
        task = self.tasks[task_id]
        if task.status == TaskStatus.OPEN:
            accept = True
        else:
            # Higher version wins outright. On a tie, LOWER bid should win - but raw
            # tuple comparison on (version, bid, name) would make a HIGHER bid win a
            # tie instead, the opposite of the actual rule. Negate bid so "greater
            # key" correctly means "better claim" on every term.
            current = (task.version, -(task.winning_bid if task.winning_bid is not None else float("inf")),
                       task.assignee or "")
            incoming = (version, -bid, claimant)
            accept = incoming > current
        if accept:
            task.status = TaskStatus.CLAIMED
            task.assignee = claimant
            task.winning_bid = bid
            task.version = version
            if now is not None and lease_s is not None:
                task.lease_expires_at = now + lease_s
        return accept

    def next_version(self, task_id: str) -> int:
        return self.tasks[task_id].version + 1

    def mark_complete(self, task_id: str, agent_name: str) -> bool:
        """An agent that finishes its own sector marks it explicitly, rather
        than just going quiet - silence alone can't tell 'finished normally'
        from 'died', since both look identical to a teammate as 'stopped
        sending heartbeats'. A COMPLETE task is never offered up for reclaim,
        regardless of lease or health state."""
        task = self.tasks[task_id]
        if task.assignee == agent_name:
            task.status = TaskStatus.COMPLETE
            return True
        return False

    # --- Phase 9: lease, self-view vs others'-view, health short-circuit ---
    # FICS's own build hit three bugs here, all really one issue: the relationship
    # between lease duration and skill duration. Designed around all three from the
    # start rather than rediscovering them live:
    #   1. A drone must trust its OWN claim regardless of lease expiry - claimed_by()
    #      is lease-independent, for exactly this reason (an agent mid-sweep still
    #      considers itself the holder even if the lease clock is running low).
    #   2. Lease must exceed the longest skill (DEFAULT_LEASE_S=300.0 in
    #      task_allocator.py already satisfies this - the live build's longest
    #      measured sweep was ~218s).
    #   3. Health detection must be able to short-circuit the lease - waiting out a
    #      300s lease for a drone the team already knows is gone would mean most of
    #      the mission goes unsearched for no reason. release_if_failed() does this.

    def renew_lease(self, task_id: str, holder_name: str, now: float, lease_s: float):
        """The holder calls this periodically (same cadence as its own
        heartbeat) to keep its claim fresh from OTHER agents' point of view."""
        task = self.tasks[task_id]
        if task.assignee == holder_name:
            task.lease_expires_at = now + lease_s

    def claimed_by(self, agent_name: str) -> list:
        """Self-view: every task this agent believes it holds, regardless of
        lease expiry. An agent must never lose track of its own work just
        because a lease timer happened to lapse - FICS's bug #1."""
        return [tid for tid, t in self.tasks.items() if t.assignee == agent_name]

    def held_by(self, task_id: str, now: float) -> Optional[str]:
        """Others'-view: who - if anyone - currently holds this task, with
        lease expiry actually counting. Returns None (available to reclaim)
        if the lease has lapsed, even though the holder's OWN board (via
        claimed_by) still considers it theirs - that asymmetry is the whole
        point, not a bug."""
        task = self.tasks[task_id]
        if task.status != TaskStatus.CLAIMED:
            return None
        if task.lease_expires_at is not None and now > task.lease_expires_at:
            return None
        return task.assignee

    def release_if_failed(self, task_id: str, failed_agent: str) -> bool:
        """Short-circuits the lease: a task held by a teammate HealthMonitor
        has classified FAILED becomes available immediately, not after
        waiting out the full lease. Returns True if this task was actually
        released."""
        task = self.tasks[task_id]
        if task.assignee == failed_agent and task.status == TaskStatus.CLAIMED:
            task.status = TaskStatus.OPEN
            task.assignee = None
            task.winning_bid = None
            task.lease_expires_at = None
            # version is NOT reset - the Lamport clock must keep counting up, or a
            # later re-claim at a lower version could lose to a stale message still
            # in flight that references the old, higher version.
            return True
        return False

    def release(self, task_id: str, agent_name: str) -> Optional[int]:
        """The HOLDER gives its own unfinished task back. Returns the new Lamport version (one higher
        than anything seen), or None if this agent doesn't hold it or it is already complete. The
        version keeps counting up for the same reason release_if_failed's does: a later re-claim must
        beat any stale message still in flight that references the old claim."""
        task = self.tasks[task_id]
        if task.assignee != agent_name or task.status != TaskStatus.CLAIMED:
            return None
        task.version += 1
        task.status = TaskStatus.OPEN
        task.assignee = None
        task.winning_bid = None
        task.lease_expires_at = None
        return task.version

    def apply_release(self, task_id: str, sender: str, version: int) -> bool:
        """Another agent's TASK_RELEASE. Accepted only if the sender is who this board believes holds
        the task and the version is newer - a stale or forged release cannot free someone else's work."""
        task = self.tasks.get(task_id)
        if task is None or task.assignee != sender or task.status != TaskStatus.CLAIMED or version <= task.version:
            return False
        task.version = version
        task.status = TaskStatus.OPEN
        task.assignee = None
        task.winning_bid = None
        task.lease_expires_at = None
        return True

    def greedy_global_assignment(self, own_name: str, own_bids: Dict[str, float]) -> Dict[str, str]:
        """One-to-one, not one task independently winner-picked per task -
        the naive per-task version let a single drone be the cheapest
        bidder on MULTIPLE tasks at once, winning more than one while
        another drone won none and a sector went unclaimed by anyone.
        Since every bid is broadcast to everyone, every agent already has
        the SAME full bid matrix after the window closes - so every agent
        can run this exact greedy procedure independently (cheapest
        (task, bidder) pair first, remove both, repeat) and land on the
        same one-to-one result without any central coordinator."""
        entries = []
        for task_id in self.tasks:
            bids = self.bids_for(task_id)
            bids[own_name] = own_bids[task_id]
            for bidder, bid in bids.items():
                entries.append((bid, task_id, bidder))
        entries.sort(key=lambda e: (e[0], e[1], e[2]))  # bid, then deterministic tie-break

        assigned_task_to_bidder: Dict[str, str] = {}
        taken_bidders = set()
        for bid, task_id, bidder in entries:
            if task_id in assigned_task_to_bidder or bidder in taken_bidders:
                continue
            assigned_task_to_bidder[task_id] = bidder
            taken_bidders.add(bidder)
        return assigned_task_to_bidder
