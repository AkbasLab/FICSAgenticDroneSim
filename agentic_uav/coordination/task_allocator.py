"""Decentralized contract-net task allocation (Phase 8.2, 8.4, 8.5).

There is no auctioneer. Every drone runs an identical copy of this allocator
against its own local task board, and the team converges on a division of work
through messages alone. The cycle:

  1. an agent that sees an open task announces it            TASK_ANNOUNCEMENT
  2. eligible agents compute a bid from their own belief     TASK_BID
  3. bids are exchanged
  4. each agent decides locally who won; the winner claims   TASK_AWARD
  5. others record the claim (and drop their own if they lost) TASK_ACCEPT
  6. the holder reports progress, renewing its lease         TASK_ACCEPT (renew)
  7. a lease that stops being renewed expires
  8. the expired task is announced again and re-bid          TASK_RELEASE

Because bids are deterministic (see bidding.py) and conflicts are resolved by a
fixed rule, two agents that have seen the same messages always reach the same
answer. Two agents that have seen *different* messages may disagree - that is
expected in a decentralized system, and step 5's conflict rules exist precisely
to converge them afterwards.

Conflict resolution (8.5), applied in order:
  1. higher task version wins (strictly newer information)
  2. otherwise the lower valid bid wins
  3. otherwise the lower vehicle ID wins
  4. the loser releases the task
  5. every correction is logged
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .bidding import Bid, BidWeights, best_bid, compute_bid
from .protocols import MessageType
from .tasks import MissionTask, TaskStatus

DEFAULT_LEASE_S = 120.0        # a holder must report within this or lose the task
DEFAULT_BID_WINDOW_S = 5.0     # how long to collect rival bids before claiming


@dataclass
class ConflictRecord:
    """One duplicate-claim resolution, kept for the audit trail (8.5)."""
    at_time_s: float
    task_id: str
    incumbent: Optional[str]
    challenger: Optional[str]
    winner: Optional[str]
    rule: str                 # which rule decided it
    detail: str = ""

    def to_dict(self):
        return {"t": round(self.at_time_s, 2), "task": self.task_id,
                "incumbent": self.incumbent, "challenger": self.challenger,
                "winner": self.winner, "rule": self.rule, "detail": self.detail}


class TaskAllocator:
    """One agent's half of the protocol. Every agent runs its own."""

    def __init__(self, vehicle_id, board, link=None, weights=None,
                 capabilities=None, lease_s=DEFAULT_LEASE_S,
                 bid_window_s=DEFAULT_BID_WINDOW_S, max_concurrent=1):
        self.vehicle_id = vehicle_id
        self.board = board
        self.link = link
        self.weights = weights or BidWeights()
        self.capabilities = set(capabilities or {"search", "relay", "inspect"})
        self.lease_s = lease_s
        self.bid_window_s = bid_window_s
        self.max_concurrent = max_concurrent

        # task_id -> {vehicle_id: Bid}   (only bids this agent has actually heard)
        self.bids: Dict[str, Dict[str, Bid]] = {}
        self.bid_opened_at: Dict[str, float] = {}
        self.announced: Dict[str, float] = {}
        self.conflicts: List[ConflictRecord] = []
        self.events: List[str] = []
        # highest task version this agent has ever seen, per task - feeds the
        # Lamport bump so our claims are ordered against everyone else's
        self.seen_version: Dict[str, int] = {}

    # --- helpers ---

    def _note_version(self, task):
        tid = task.task_id
        self.seen_version[tid] = max(self.seen_version.get(tid, 0), task.version)

    def _log(self, text):
        self.events.append(text)

    def _send(self, mtype, payload, belief, ttl_s=180.0):
        if self.link is None:
            return None
        return self.link.send(mtype, payload=payload, now=belief.now,
                              mission_id=belief.mission.mission_id, ttl_s=ttl_s)

    def my_tasks(self, now):
        return self.board.held_by(self.vehicle_id, now)

    def has_capacity(self, now):
        return len(self.my_tasks(now)) < self.max_concurrent

    # --- inbound messages ---

    def on_message(self, msg, belief):
        """Fold one delivered message into the local board. Returns True if the
        agent's own allocation state changed (so the agent knows to re-decide)."""
        p = msg.payload or {}
        t = msg.message_type
        changed = False

        if t is MessageType.TASK_ANNOUNCEMENT:
            for tp in p.get("tasks", []):
                incoming = MissionTask.from_payload(tp)
                self._note_version(incoming)
                result = self.board.merge(incoming)
                if result in ("added", "updated"):
                    changed = True
                elif result == "conflict":
                    changed |= self._resolve_conflict(incoming, msg.sender_id, belief)

        elif t is MessageType.TASK_BID:
            bid = Bid.from_payload(msg.sender_id, p)
            self.bids.setdefault(bid.task_id, {})[msg.sender_id] = bid
            self.bid_opened_at.setdefault(bid.task_id, msg.timestamp)
            changed = True

        elif t is MessageType.TASK_AWARD:
            incoming = MissionTask.from_payload(p["task"])
            self._note_version(incoming)
            local = self.board.get(incoming.task_id)
            if local is None:
                self.board.add(incoming)
                changed = True
            elif incoming.version > local.version:
                # somebody else claimed it with newer information
                if local.assigned_agent == self.vehicle_id:
                    self._log(f"t={belief.now:.0f} lost {incoming.task_id} to "
                              f"{incoming.assigned_agent} (newer version)")
                self.board.merge(incoming)
                changed = True
            elif incoming.assigned_agent != local.assigned_agent:
                changed |= self._resolve_conflict(incoming, msg.sender_id, belief)

        elif t is MessageType.TASK_ACCEPT:      # progress report / lease renewal
            tid = p.get("task_id")
            local = self.board.get(tid)
            if local is not None and local.assigned_agent == msg.sender_id:
                local.status = TaskStatus.IN_PROGRESS
                local.lease_expires_at = msg.timestamp + self.lease_s

        elif t is MessageType.TASK_RELEASE:
            tid = p.get("task_id")
            local = self.board.get(tid)
            if local is not None and local.assigned_agent == msg.sender_id:
                local.release(belief.now)
                self.bids.pop(tid, None)
                self.bid_opened_at.pop(tid, None)
                changed = True

        elif t is MessageType.TASK_COMPLETE:
            tid = p.get("task_id")
            local = self.board.get(tid)
            if local is not None and local.status is not TaskStatus.COMPLETE:
                local.complete()
                changed = True

        return changed

    # --- 8.5 conflict resolution ---

    def _resolve_conflict(self, incoming: MissionTask, sender_id, belief):
        """Two claims on one task at the same version. Decide deterministically."""
        local = self.board.get(incoming.task_id)
        if local is None:
            self.board.add(incoming)
            return True

        # rule 1: newer version wins
        if incoming.version != local.version:
            winner_task = incoming if incoming.version > local.version else local
            rule = "version"
        else:
            # rule 2: lower winning bid
            lb, ib = local.winning_bid, incoming.winning_bid
            if lb is not None and ib is not None and lb != ib:
                winner_task = local if lb < ib else incoming
                rule = "lower_bid"
            else:
                # rule 3: lower vehicle ID
                la = local.assigned_agent or "~"
                ia = incoming.assigned_agent or "~"
                winner_task = local if la <= ia else incoming
                rule = "lower_agent_id"

        loser_agent = (incoming.assigned_agent
                       if winner_task is local else local.assigned_agent)

        self.conflicts.append(ConflictRecord(
            at_time_s=belief.now, task_id=incoming.task_id,
            incumbent=local.assigned_agent, challenger=incoming.assigned_agent,
            winner=winner_task.assigned_agent, rule=rule,
            detail=f"v{local.version} vs v{incoming.version}"))

        changed = False
        if winner_task is incoming:
            self.board.tasks[incoming.task_id] = incoming
            changed = True

        # rule 4: if *we* lost, give it up
        if loser_agent == self.vehicle_id:
            self._log(f"t={belief.now:.0f} released {incoming.task_id} "
                      f"after conflict ({rule})")
            self._send(MessageType.TASK_RELEASE,
                       {"task_id": incoming.task_id, "reason": f"conflict:{rule}"},
                       belief)
            changed = True
        return changed

    # --- outbound: one protocol step ---

    def tick(self, belief):
        """Run one round of the protocol. Returns True if anything changed."""
        now = belief.now
        changed = False

        # 8.4 - reclaim tasks whose holder went silent
        for t in self.board.expire_leases(now):
            if t.assigned_agent == self.vehicle_id:
                continue                        # our own lease: renewed below
            self._log(f"t={now:.0f} {t.task_id} lease expired "
                      f"(held by {t.assigned_agent})")
            t.release(now)
            self.bids.pop(t.task_id, None)
            self.bid_opened_at.pop(t.task_id, None)
            self._announce([t], belief)
            changed = True

        # renew our own leases by reporting progress (step 6)
        for t in self.my_tasks(now):
            t.renew(now, self.lease_s)
            self._send(MessageType.TASK_ACCEPT,
                       {"task_id": t.task_id, "progress": "working",
                        "version": t.version}, belief)

        if not self.has_capacity(now):
            return changed

        open_tasks = self.board.open_tasks(now, self.capabilities)
        if not open_tasks:
            return changed

        # step 1 - announce anything open we haven't announced recently
        fresh = [t for t in open_tasks
                 if now - self.announced.get(t.task_id, -1e9) > self.bid_window_s]
        if fresh:
            self._announce(fresh, belief)
            for t in fresh:
                self.announced[t.task_id] = now
            changed = True

        # step 2/3 - bid on everything open (our own bid counts too)
        for t in open_tasks:
            mine = self.bids.get(t.task_id, {}).get(self.vehicle_id)
            if mine is None or mine.task_version != t.version:
                bid = compute_bid(t, belief, self.weights, self.capabilities, now)
                self.bids.setdefault(t.task_id, {})[self.vehicle_id] = bid
                self.bid_opened_at.setdefault(t.task_id, now)
                self._send(MessageType.TASK_BID, bid.to_payload(), belief)
                changed = True

        # step 4 - claim the best task we are currently winning
        claimed = self._claim_best(open_tasks, belief)
        return changed or claimed

    def _announce(self, tasks, belief):
        self._send(MessageType.TASK_ANNOUNCEMENT,
                   {"tasks": [t.to_payload() for t in tasks]}, belief)

    def _claim_best(self, open_tasks, belief):
        """Claim the highest-priority open task whose bidding we are winning."""
        now = belief.now
        for t in open_tasks:                    # already priority-ordered
            heard = self.bids.get(t.task_id, {})
            mine = heard.get(self.vehicle_id)
            if mine is None or not mine.eligible:
                continue

            # wait for the bidding window so rivals' bids can arrive, unless we
            # are the only drone that could possibly take it
            window_open = (now - self.bid_opened_at.get(t.task_id, now)
                           < self.bid_window_s)
            known_peers = len(belief.team.teammates)
            if window_open and known_peers and len(heard) <= known_peers:
                continue

            winner = best_bid(list(heard.values()))
            if winner is None or winner.vehicle_id != self.vehicle_id:
                continue

            t.claim(self.vehicle_id, mine.value, now, self.lease_s,
                    seen_version=self.seen_version.get(t.task_id, 0))
            self._note_version(t)
            self._log(f"t={now:.0f} claimed {t.task_id} with bid {mine.value:.3f}")
            self._send(MessageType.TASK_AWARD,
                       {"task": t.to_payload(), "bid": mine.value}, belief)
            return True
        return False

    # --- completion ---

    def complete_task(self, task_id, belief):
        t = self.board.get(task_id)
        if t is None:
            return
        t.complete()
        self._log(f"t={belief.now:.0f} completed {task_id}")
        self._send(MessageType.TASK_COMPLETE,
                   {"task_id": task_id, "task": t.to_payload()}, belief)

    def release_task(self, task_id, belief, reason="released"):
        t = self.board.get(task_id)
        if t is None:
            return
        t.release(belief.now)
        self._log(f"t={belief.now:.0f} released {task_id} ({reason})")
        self._send(MessageType.TASK_RELEASE,
                   {"task_id": task_id, "reason": reason}, belief)
