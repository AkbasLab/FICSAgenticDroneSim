"""One drone's side of the contract-net (AUV-08, 8.2, 8.4, 8.5): what it hears, what it says.

    net = ContractNet("Drone2", tasks_from_brief(brief), config)
    for message in delivered:  outs += net.receive(message, now)
    outs += net.tick(now, bid_fn, progress=0.4)          # bid_fn(task) -> Bid, from the drone's own belief
    net.holding, net.idle, net.news                       # what the agent acts on
    net.complete(now) / net.release(now, why)             # when its task is done, or given up

PURE LOGIC. It holds no clock, no bus and no other drone: messages come in,
messages to send go out (`Out`: a type and a payload; the agent puts them in
envelopes and broadcasts them). So the protocol is tested on scripted message
sequences, with no flight at all.

THE PROTOCOL, AS AUV-08 GIVES IT, and what carries each step:

    1 an unassigned task is announced     the brief announces the mission's tasks;
                                          TASK_ANNOUNCEMENT one that returns to the pool
    2 eligible drones compute a bid       `bids.bid_for`, from the drone's own belief
    3 bids are exchanged                  TASK_BID, with every term
    4 the best bidder claims the task     TASK_AWARD, the winner's claim, with its bid
    5 others acknowledge the claim        TASK_ACCEPT, naming the holder
    6 the winner reports progress         STATUS_UPDATE's task group, every progress period
    7 the lease expires if reports stop   each drone, from its own book
    8 an expired or released task is      TASK_ANNOUNCEMENT, one version on
      announced again

WHO CLAIMS WHAT. A drone holding nothing bids for every open task it has not
bid for, and starts its BID WINDOW. A bid counts only while its message is
current (`BID_TTL_S`, the bid's time to live): a teammate heard bidding that
has since become busy, unheard, or gone home stops counting, and a drone
still waiting bids again when its own bid lapses. When the window has passed, it reads the
bids it has heard -- its own and its teammates', for open tasks, from drones
that hold nothing -- lowest first (the vehicle id breaking ties), and gives
each task to the best bidder not yet given one. If that gives it a task, it
claims it. Every drone that heard the same bids gives the same answer, so
with a window long enough to hear them all there is nothing to resolve. With
a window of 0 (CONTESTED), every drone claims at once on its own bids alone,
and the conflicts are made to happen.

DUPLICATE CLAIMS (8.5), settled by each drone from the claims it hears --
all of a tick's claims together, at the start of its next tick, so claims made
at the same instant are weighed against each other at once, not one by one:

    1 compare task versions: a claim for an older version is refused
    2 the lowest valid bid wins
    3 equal bids: the lower agent id wins
    4 losers release (TASK_RELEASE), and bid again for what is left
    5 every correction is logged (`corrections`): in every drone's book,
      each claim that lost, to whom, by which rule -- the winner's own
      book included, so all of them tell the same story

LEASES (8.4). A claim starts its lease; each progress report renews it from
when it was sent. A drone that sees a teammate's lease run out reopens the
task one version on in its own book and announces it; the others take the
newer version. Its own lease a drone renews by reporting.

Every claim a drone makes is kept with the bids it had heard (`claims_made`),
so the record can trace each claim to what was behind it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from ..core.messages import DEFAULT_TTL_S, AgentMessage, MessageType
from .bids import AllocationConfig, Bid
from .tasks import MissionTask, TaskBook, TaskStatus

EPS = 1e-9
CLAIM_RANKING = 6               # decimal places a bid is compared to: no float noise decides a conflict
RULES = ("task version", "lowest valid bid", "lower agent id")
BID_TTL_S = DEFAULT_TTL_S[MessageType.TASK_BID]      # a bid counts for as long as its message is current


@dataclass(frozen=True)
class Out:
    """A message to send: its type and payload. The agent makes the envelope."""

    kind: MessageType
    payload: dict[str, Any]


@dataclass(frozen=True)
class Correction:
    """One conflict settled in one drone's book (8.5, rule 5)."""

    at: float
    task_id: str
    version: int
    kept: str
    displaced: str
    rule: str
    by: str

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "task_id": self.task_id, "version": self.version, "kept": self.kept,
                "displaced": self.displaced, "rule": self.rule, "by": self.by}


@dataclass(frozen=True)
class ClaimMade:
    """A claim this drone made, with the bids it had heard for that task when it did."""

    at: float
    task_id: str
    version: int
    value: float
    heard: dict[str, float] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"at": round(self.at, 3), "task_id": self.task_id, "version": self.version,
                "value": round(self.value, 3), "heard": {k: round(v, 3) for k, v in sorted(self.heard.items())}}


def _key(value: float, who: str) -> tuple[float, str]:
    return (round(value, CLAIM_RANKING), who)


class ContractNet:
    def __init__(self, owner: str, tasks: Iterable[MissionTask], config: AllocationConfig, leases: bool = True) -> None:
        self.owner = owner
        self.config = config
        self.leases = leases                # Phase 13's ablation: off, a silent holder's task never returns
        self.book = TaskBook(owner, tasks)
        self.bids: dict[tuple[str, int], dict[str, tuple[float, float]]] = {}   # bidder -> (value, sent), eligible
        self.my_bids: dict[tuple[str, int], Bid] = {}
        self._bid_at: dict[tuple[str, int], float] = {}
        self.claims: dict[tuple[str, int], dict[str, tuple[float, float]]] = {}   # claimant -> (bid, when)
        self._unsettled: set[tuple[str, int]] = set()
        self._logged: set[tuple[str, int, str]] = set()
        self.acks: dict[tuple[str, int], set[str]] = {}
        self.holding: str | None = None
        self.round_started_at: float | None = None
        self.last_progress_at: float | None = None
        self.done = False
        self.corrections: list[Correction] = []
        self.claims_made: list[ClaimMade] = []
        self.news: list[dict[str, Any]] = []                          # for the agent: what changed for it
        self.abandoned: list[dict[str, Any]] = []                     # Phase 9: tasks given up, and why

    # ------------------------------------------------------------ state

    @property
    def idle(self) -> bool:
        """Nothing for it: holding nothing, and no open task it could bid a value for."""
        if self.holding is not None:
            return False
        for t in self.book.open():
            bid = self.my_bids.get((t.task_id, t.version))
            if bid is None or bid.eligible:
                return False
        return True

    def take_news(self) -> list[dict[str, Any]]:
        news, self.news = self.news, []
        return news

    # ------------------------------------------------------- what it hears

    def receive(self, message: AgentMessage, now: float) -> list[Out]:
        kind, p, sender = message.message_type, message.payload, message.sender_id
        if kind is MessageType.STATUS_UPDATE:
            if "task_id" not in p:
                return []
            task_id, version = p["task_id"], p["task_version"]
        elif kind in (MessageType.TASK_ANNOUNCEMENT, MessageType.TASK_BID, MessageType.TASK_AWARD,
                      MessageType.TASK_ACCEPT, MessageType.TASK_RELEASE, MessageType.TASK_COMPLETE):
            task_id, version = p["task_id"], p["version"]
        else:
            return []
        if not self.book.knows(task_id):
            return []
        out: list[Out] = []
        self._catch_up(task_id, version, now, f"{message.message_id} speaks of version {version}")
        t = self.book.get(task_id)
        key = (task_id, version)
        if kind is MessageType.TASK_ANNOUNCEMENT:
            return out                                               # caught up above, if it was newer
        if version < t.version:
            if kind is MessageType.TASK_AWARD:
                self.corrections.append(Correction(now, task_id, version, f"version {t.version}", sender,
                                                   RULES[0], self.owner))
            return out
        if kind is MessageType.TASK_BID:
            self.bids.setdefault(key, {})[sender] = (p["value"], message.timestamp)
        elif kind is MessageType.TASK_AWARD:
            if t.status is not TaskStatus.COMPLETE:
                self.claims.setdefault(key, {})[sender] = (p["value"], message.timestamp)
                self._unsettled.add(key)
        elif kind is MessageType.TASK_ACCEPT:
            self.acks.setdefault(key, set()).add(sender)
        elif kind is MessageType.TASK_RELEASE:
            # A loser's release says only that it has let go: its claim lost already. A
            # holder's returns the task to the pool, one version on.
            if t.status is TaskStatus.CLAIMED and t.assigned_agent == sender:
                self.book.update(t.reopened(), now, f"{sender} released it: {p['why']}")
        elif kind is MessageType.TASK_COMPLETE:
            if t.status is not TaskStatus.COMPLETE:
                held = t if (t.status is TaskStatus.CLAIMED and t.assigned_agent == sender) \
                    else t.claimed(sender, message.timestamp, self.config.lease_s)
                self.book.update(held.completed(), now, f"{sender} completed it")
                if self.holding == task_id:
                    # Done by a teammate while this drone held it: there is nothing left to do here.
                    self.holding = None
                    self.last_progress_at = None
                    self.round_started_at = now
                    self.news.append({"what": "lost", "task": task_id, "why": f"{sender} completed it"})
        elif kind is MessageType.STATUS_UPDATE:
            if t.status is TaskStatus.CLAIMED and t.assigned_agent == sender:
                self.book.update(t.renewed(message.timestamp, self.config.lease_s), now,
                                 f"{sender} reported progress {p['task_progress']:.2f}")
            elif t.status is TaskStatus.OPEN and not self.claims.get(key):
                # Its claim never reached us; its progress did.
                self.claims.setdefault(key, {})[sender] = (math.inf, message.timestamp)
                self.book.update(t.claimed(sender, message.timestamp, self.config.lease_s), now,
                                 f"{sender} reported progress on it, its claim unheard")
        return out

    def _catch_up(self, task_id: str, version: int, now: float, why: str) -> None:
        """A message for a newer version than this drone knows: the task went back to the pool unheard."""
        t = self.book.get(task_id)
        if version > t.version and t.status is not TaskStatus.COMPLETE:
            self.book.update(replace(t, status=TaskStatus.OPEN, assigned_agent=None, lease_expires_at=None,
                                     version=version), now, why)
            if self.holding == task_id:
                self.holding = None
                self.round_started_at = now
                self.news.append({"what": "lost", "task": task_id, "why": why})

    def _settle_all(self, now: float) -> list[Out]:
        out: list[Out] = []
        for key in sorted(self._unsettled):
            out += self._settle(key, now)
        self._unsettled.clear()
        return out

    def _settle(self, key: tuple[str, int], now: float) -> list[Out]:
        """The best claim heard for this version holds the task (8.5, rules 2-5)."""
        task_id, version = key
        t = self.book.get(task_id)
        if t.version != version or t.status is TaskStatus.COMPLETE or not self.claims.get(key):
            return []
        claims = self.claims[key]
        best = min(claims, key=lambda who: _key(claims[who][0], who))

        def rule(who: str) -> str:
            return RULES[2] if _key(claims[who][0], "")[0] == _key(claims[best][0], "")[0] else RULES[1]

        for who in sorted(claims):
            if who != best and (task_id, version, who) not in self._logged:
                self._logged.add((task_id, version, who))
                self.corrections.append(Correction(now, task_id, version, best, who, rule(who), self.owner))
        current = t.assigned_agent if t.status is TaskStatus.CLAIMED else None
        if best == current:
            return []
        out: list[Out] = []
        self.book.update(t.claimed(best, claims[best][1], self.config.lease_s), now,
                         f"{best}'s claim ({claims[best][0]:.3f})" + (f" displaced {current}'s" if current else ""))
        if current == self.owner:
            self.holding = None
            self.round_started_at = now
            why = f"lost to {best}'s claim by the {rule(self.owner)}"
            out.append(Out(MessageType.TASK_RELEASE, {"task_id": task_id, "version": version, "why": why}))
            self.news.append({"what": "lost", "task": task_id, "why": why})
        if best != self.owner:
            out.append(Out(MessageType.TASK_ACCEPT, {"task_id": task_id, "version": version, "holder": best}))
        return out

    # ------------------------------------------------------- what it does

    def tick(self, now: float, bid_fn: Callable[[MissionTask], Bid], progress: float = 0.0) -> list[Out]:
        out = self._settle_all(now)
        if self.leases:
            out += self._leases(now)
        if self.holding is None and not self.done:
            out += self._bid(now, bid_fn)
            if self.round_started_at is not None and now >= self.round_started_at + self.config.bid_window_s - EPS:
                out += self._claim(now)
        if self.holding is not None and (self.last_progress_at is None
                                         or now - self.last_progress_at >= self.config.progress_period_s - EPS):
            out.append(self._progress(now, progress))
        return out

    def _leases(self, now: float) -> list[Out]:
        out = []
        for t in self.book.tasks():
            if t.lease_expired(now) and t.assigned_agent != self.owner:
                again = t.reopened()
                why = f"{t.assigned_agent}'s lease ran out at {t.lease_expires_at:.3f}"
                self.book.update(again, now, why)
                out.append(Out(MessageType.TASK_ANNOUNCEMENT, {"task_id": t.task_id, "version": again.version,
                                                               "why": why}))
        return out

    def _bid(self, now: float, bid_fn: Callable[[MissionTask], Bid]) -> list[Out]:
        out = []
        for t in self.book.open():
            key = (t.task_id, t.version)
            if key in self.my_bids and now - self._bid_at[key] < BID_TTL_S - EPS:
                continue
            bid = bid_fn(t)
            self.my_bids[key] = bid
            self._bid_at[key] = now
            self.round_started_at = now
            if bid.eligible:
                self.bids.setdefault(key, {})[self.owner] = (bid.value, now)
                tm = bid.terms
                out.append(Out(MessageType.TASK_BID, {"task_id": t.task_id, "version": t.version, "value": bid.value,
                                                      "d": tm["D"], "b": tm["B"], "l": tm["L"], "c": tm["C"],
                                                      "r": tm["R"]}))
        return out

    def _choice(self, now: float) -> str | None:
        """The task the current bids give this drone: each task to the best free bidder not yet given one."""
        entries = []
        for t in self.book.open():
            for who, (value, sent) in self.bids.get((t.task_id, t.version), {}).items():
                if now - sent >= BID_TTL_S - EPS:
                    continue                                          # lapsed: no longer counts
                if who == self.owner or not self.book.held_by(who):
                    entries.append((_key(value, who), t.task_id))
        given_tasks, given_drones = set(), set()
        for (value, who), task_id in sorted(entries):
            if task_id in given_tasks or who in given_drones:
                continue
            given_tasks.add(task_id)
            given_drones.add(who)
            if who == self.owner:
                return task_id
        return None

    def _claim(self, now: float) -> list[Out]:
        task_id = self._choice(now)
        if task_id is None:
            return []
        t = self.book.get(task_id)
        key = (task_id, t.version)
        value = self.bids[key][self.owner][0]
        self.claims.setdefault(key, {})[self.owner] = (value, now)
        heard = {who: v for who, (v, sent) in self.bids.get(key, {}).items() if now - sent < BID_TTL_S - EPS}
        self.claims_made.append(ClaimMade(now, task_id, t.version, value, heard))
        self.book.update(t.claimed(self.owner, now, self.config.lease_s), now, f"claimed it with {value:.3f}")
        self.holding = task_id
        self.round_started_at = None
        self.last_progress_at = now                                   # the claim starts the lease
        self.news.append({"what": "claimed", "task": task_id, "value": value})
        return [Out(MessageType.TASK_AWARD, {"task_id": task_id, "version": t.version, "value": value})]

    def _progress(self, now: float, progress: float) -> Out:
        t = self.book.get(self.holding)
        self.book.update(t.renewed(now, self.config.lease_s), now, f"reported progress {progress:.2f}")
        self.last_progress_at = now
        return Out(MessageType.STATUS_UPDATE, {"task_id": t.task_id, "task_version": t.version,
                                               "task_progress": max(0.0, min(1.0, progress))})

    def complete(self, now: float) -> list[Out]:
        """Its task is done."""
        if self.holding is None:
            return []
        t = self.book.get(self.holding)
        self.book.update(t.completed(), now, "completed it")
        self.holding = None
        self.last_progress_at = None
        return [Out(MessageType.TASK_COMPLETE, {"task_id": t.task_id, "version": t.version})]

    def release(self, now: float, why: str) -> list[Out]:
        """Give its task back to the pool (it cannot finish it), and bid for nothing more."""
        self.done = True
        if self.holding is None:
            return []
        t = self.book.get(self.holding)
        self.book.update(t.reopened(), now, f"released it: {why}")
        self.holding = None
        self.last_progress_at = None
        return [Out(MessageType.TASK_RELEASE, {"task_id": t.task_id, "version": t.version, "why": why})]

    def abandon(self, task_id: str, now: float, why: str) -> bool:
        """Give an open task up: no drone can still do it (Phase 9, 9.3). True if it was open."""
        t = self.book.get(task_id)
        if t.status is not TaskStatus.OPEN:
            return False
        self.book.update(t.abandoned(), now, f"abandoned: {why}")
        self.abandoned.append({"at": round(now, 3), "task_id": task_id, "version": t.version, "why": why})
        self.news.append({"what": "abandoned", "task": task_id, "why": why})
        return True

    def stop(self) -> None:
        """Bid for nothing more (it is going home)."""
        self.done = True

    def as_json(self) -> dict[str, Any]:
        row = {"owner": self.owner, "holding": self.holding, "book": self.book.as_json(),
               "corrections": [c.as_json() for c in self.corrections],
               "claims_made": [c.as_json() for c in self.claims_made],
               "book_log": [e.as_json() for e in self.book.log]}
        if self.abandoned:                       # only when it happened: every earlier record is as it was
            row["abandoned"] = list(self.abandoned)
        return row
