"""The contract-net protocol, run independently on every drone - no
auctioneer anywhere. Each agent: bids on every open task, waits for others'
bids, locally decides who it thinks won each task using the exact same
deterministic rule everyone else applies, claims whatever it believes it
won, then absorbs a short settle window so a genuinely conflicting claim
from elsewhere still gets resolved by TaskBoard's Lamport-clock rule.
"""

import time
from typing import Optional

from .bidding import DEFAULT_WEIGHTS, BidWeights, compute_bid
from .message_bus import AgentLink
from .protocols import MessageType
from .tasks import TaskBoard
from ..core.scenario import Scenario

DEFAULT_BID_WINDOW_S = 2.0
# Exceeds the longest skill this build has actually measured live (~218s, Phase 5's full
# single-sector mission) - FICS's own doc flags a too-short lease as a real bug: a busy drone's
# lease expiring mid-sector lets a teammate steal work it is actively doing. Not exercised by
# runtime reclaim logic this phase (that's Phase 9's job) - kept generous as the field it sets.
DEFAULT_LEASE_S = 300.0


class TaskAllocator:
    def __init__(self, link: AgentLink, scenario: Scenario, drone_name: str,
                 weights: BidWeights = DEFAULT_WEIGHTS, bid_window_s: float = DEFAULT_BID_WINDOW_S,
                 lease_s: float = DEFAULT_LEASE_S):
        self.link = link
        self.scenario = scenario
        self.drone_name = drone_name
        self.weights = weights
        self.bid_window_s = bid_window_s
        self.lease_s = lease_s
        self.board = TaskBoard(scenario)

    def _drain_inbox(self):
        for msg in self.link.receive_available():
            if msg.type == MessageType.TASK_BID:
                self.board.apply_bid(msg.payload["task_id"], msg.sender, msg.payload["bid"])
            elif msg.type == MessageType.TASK_CLAIM:
                self.board.apply_claim(msg.payload["task_id"], msg.sender, msg.payload["bid"],
                                        msg.payload["version"])

    def _wait_and_drain(self, duration_s: float):
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._drain_inbox()
            time.sleep(0.1)
        self._drain_inbox()

    def allocate(self, world_position, battery_frac: float) -> Optional[str]:
        """Returns the sector_id this agent ends up responsible for, once its
        local board converges - or None if it won nothing."""
        own_bids = {}
        for task_id, task in self.board.tasks.items():
            sector = self.scenario.sector(task.sector_id)
            bid = compute_bid(world_position, battery_frac, workload=0, sector=sector, weights=self.weights)
            own_bids[task_id] = bid
            self.link.send(MessageType.TASK_BID, {"task_id": task_id, "bid": bid})

        self._wait_and_drain(self.bid_window_s)  # let everyone's bids actually arrive

        # One-to-one global assignment over the full bid matrix, not a per-task local
        # winner - see TaskBoard.greedy_global_assignment for why: picking winners one
        # task at a time let a single drone win more than one task while another won
        # none. Every agent runs this same deterministic procedure on the same
        # broadcast bid data, so independent runs converge without a coordinator.
        assignment = self.board.greedy_global_assignment(self.drone_name, own_bids)
        for task_id, bidder in assignment.items():
            if bidder == self.drone_name:
                bid = own_bids[task_id]
                version = self.board.next_version(task_id)
                self.board.apply_claim(task_id, self.drone_name, bid, version)
                self.link.send(MessageType.TASK_CLAIM, {"task_id": task_id, "bid": bid, "version": version})

        self._wait_and_drain(self.bid_window_s / 2)  # settle: absorb any conflicting claim

        for task_id, task in self.board.tasks.items():
            if task.assignee == self.drone_name:
                return task.sector_id
        return None
