# Phase 8 exit criterion — evidence, 2026-11-04

> Four drones receive **one team mission**, divide the sectors **without a central assignment**, complete
> the work, and resolve simultaneous claims deterministically.

**Met on the mock.** 20 of 20 seeds passed all seven checks, each seed flown deliberating and contested and each way twice (80 flights): the four drones, told only the team mission, divided the four sectors by their own bids and claims, searched each exactly once, settled every simultaneous claim by AUV-08's rules the same way in every book, and flew identically when flown again. 4410 decisions known exactly. Generated from `../results/allocation-exit-20261104-085636-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_relay_001.toml`: the canonical mission, four drones on pads 4 m apart, four sectors |
| Agents | Phase 5's rule policy flying, Phase 8's team policy dividing: each told the team mission and no task |
| Network | every message delivered (range unlimited); read at the next tick |
| Manifest | `configs/allocation/default.toml`, fixed before any run: w_d 1, w_b 1, w_l 1, w_c 0, w_r 1; bid window 1 s; progress every 2 s; lease 10 s |
| Each seed flown | **deliberating** (the bid window) and **contested** (no window: every drone claims at once), each twice |
| Seeds | 1–20, Phase 4's |
| Code | commit `60496ea` + the step-5 files (dirty: True); `agentic_uav` digest `f85f583549e02b62` |
| Wall time | 198.72 s |

## The seven checks

| Check | What it requires |
|---|---|
| met | both flights complete the mission (AUV-05's criteria), every drone ending its part itself |
| no central assignment | every drone told the team mission and nothing more; every claim resting on its own bid and the bids it had heard (deliberating: every drone's); the task flown the last one claimed |
| one holder each | every sector searched, each by exactly one drone; every book agreeing at the end |
| conflicts resolved by the rules | contested: at least one simultaneous claim, each settled for the lowest bid (the lower id on a tie), every book logging the same corrections, every loser releasing; deliberating: none |
| leases renewed | no lease run out in any book; every holder reporting from claim to completion with no gap over a progress period and a tick |
| deterministic | each way flown twice: the same books, the same division, the same decisions |
| known exactly | Phase 6's knowledge log passes every decision |

Each is shown able to fail in `tests/test_allocation_exit.py`, on a real seed's flights altered to break it.

## Every seed

| Seed | met | no_central_assignment | one_holder_each | conflicts_resolved | leases_renewed | deterministic | known_exactly | Division | Conflict (contested) | Completion s |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 2 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 3 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 4 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 5 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 6 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 7 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 8 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 9 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 10 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 11 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 12 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 13 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 14 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 15 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 16 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 17 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 18 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 19 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |
| 20 | yes | yes | yes | yes | yes | yes | yes | Drone1→S3, Drone2→S4, Drone3→S1, Drone4→S2 | S2: 4 at 0 s, Drone4 kept | 188.0 / 188.0 |

The division is the same on every seed: the targets move with the seed, the bids do not -- a drone bids on where the sectors are and where it stands, not on what it might find. Phase 4's scripted controller, with the hand assignment Drone *i* to S*i*, takes 192.1 s -- beside it, not a pass condition.

## Seed 17 in detail

### The bids at the start

What each drone bid from its pad (seconds until it would finish the task), recomputed with `coordination/bids.py` and checked against the bids each claim in the record says it heard:

| Drone | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| Drone1 | 114.3 | 108.8 | 130.3 | 127.6 |
| Drone2 | 113.9 | 108.4 | 129.8 | 127.2 |
| Drone3 | 113.6 | 108.1 | 129.5 | 126.9 |
| Drone4 | 113.5 | 108.0 | 129.4 | 126.8 |

Every one of the 16 bids the claims recorded hearing matches. Drone4, nearest the sectors by a few metres, bids lowest on every task; the reading of the table -- each task to the best bidder not yet given one -- gives Drone4 S2, Drone3 S1, Drone2 S4, Drone1 S3.

### Deliberating: every bid heard, then the claims

| Drone | Claimed | At s | Its bid | Bids it had heard |
|---|---|---|---|---|
| Drone1 | search S3 | 1 | 130.3 | Drone1 130.3, Drone2 129.8, Drone3 129.5, Drone4 129.4 |
| Drone2 | search S4 | 1 | 127.2 | Drone1 127.6, Drone2 127.2, Drone3 126.9, Drone4 126.8 |
| Drone3 | search S1 | 1 | 113.6 | Drone1 114.3, Drone2 113.9, Drone3 113.6, Drone4 113.5 |
| Drone4 | search S2 | 1 | 108.0 | Drone1 108.8, Drone2 108.4, Drone3 108.1, Drone4 108.0 |

Messages of the deliberating flight, by type (each sent once, to the three others): heartbeat 698, status_update 365, task_accept 12, task_award 4, task_bid 16, task_complete 4.

### Contested: everyone claims at once

At 0 s, with no bid heard yet, **4 drones claimed search S2**, each on its own bid:

| Drone | Its claim |
|---|---|
| Drone1 | 108.834 |
| Drone2 | 108.406 |
| Drone3 | 108.108 |
| Drone4 | 107.975 |

The lowest is Drone4's. What every book logged when the claims had been heard:

| Book | Kept | Its claim lost | Rule | At s |
|---|---|---|---|---|
| Drone1 | Drone4 | Drone1 | lowest valid bid | 0.5 |
| Drone1 | Drone4 | Drone2 | lowest valid bid | 0.5 |
| Drone1 | Drone4 | Drone3 | lowest valid bid | 0.5 |
| Drone2 | Drone4 | Drone1 | lowest valid bid | 0.5 |
| Drone2 | Drone4 | Drone2 | lowest valid bid | 0.5 |
| Drone2 | Drone4 | Drone3 | lowest valid bid | 0.5 |
| Drone3 | Drone4 | Drone1 | lowest valid bid | 0.5 |
| Drone3 | Drone4 | Drone2 | lowest valid bid | 0.5 |
| Drone3 | Drone4 | Drone3 | lowest valid bid | 0.5 |
| Drone4 | Drone4 | Drone1 | lowest valid bid | 0.5 |
| Drone4 | Drone4 | Drone2 | lowest valid bid | 0.5 |
| Drone4 | Drone4 | Drone3 | lowest valid bid | 0.5 |

The losers released: Drone1 at 0.5 s, Drone2 at 0.5 s, Drone3 at 0.5 s. Then each claimed again:

| Drone | Claims, in order |
|---|---|
| Drone1 | search S2 at 0 s (108.8), then search S3 at 0.5 s (130.3) |
| Drone2 | search S2 at 0 s (108.4), then search S4 at 0.5 s (127.2) |
| Drone3 | search S2 at 0 s (108.1), then search S1 at 0.5 s (113.6) |
| Drone4 | search S2 at 0 s (108.0) |

The same division as deliberating, every book telling the same story.

### Leases

Each holder's lease as a teammate's book saw it: renewed by every progress report heard, from the claim to the completion (the times are when the book took them in, a tick after sending):

| Flight | Holder | Task | Book | Renewals | Widest gap s | Lease ran out |
|---|---|---|---|---|---|---|
| deliberating | Drone1 | search S3 | Drone2's | 70 | 2.0 | no |
| deliberating | Drone2 | search S4 | Drone1's | 69 | 2.0 | no |
| deliberating | Drone3 | search S1 | Drone1's | 63 | 2.0 | no |
| deliberating | Drone4 | search S2 | Drone1's | 60 | 2.0 | no |
| contested | Drone1 | search S3 | Drone2's | 70 | 2.0 | no |
| contested | Drone2 | search S4 | Drone1's | 69 | 2.0 | no |
| contested | Drone3 | search S1 | Drone1's | 63 | 2.0 | no |
| contested | Drone4 | search S2 | Drone1's | 61 | 2.0 | no |


## Beside the exit: the canonical 100 m radio

One flight of the scenario's own seed on its own 100 m radio -- a finding, not part of the exit (decided 2026-11-04). Met: True. **8 searches of 4 sectors, 20 lease expiries.** Who searched what: Drone1 S4, S2; Drone2 S1, S3; Drone3 S4, S1; Drone4 S2, S4.

A drone searching a far sector is out of every teammate's reach for most of its search: its progress reports go unheard, its lease runs out while it is still working, and a teammate that has finished claims the "returned" task and searches it again. The first expiries:

| Book | At s | Task | Why |
|---|---|---|---|
| Drone1 | 51 | search S2 | Drone4's lease ran out at 51.000 |
| Drone1 | 142.7 | search S4 | Drone3's lease ran out at 142.700 |
| Drone1 | 160.2 | search S1 | Drone2's lease ran out at 160.200 |
| Drone1 | 169.7 | search S3 | Drone4's lease ran out at 169.600 |
| Drone1 | 267.4 | search S2 | Drone3's lease ran out at 267.300 |
| Drone1 | 271.9 | search S3 | Drone2's lease ran out at 271.800 |

Leases are the mechanism Phase 9 recovers a lost drone with; under a partition they cannot tell a lost drone from an unheard one. That is Phase 10's subject.

**Exit criterion: MET** on the mock.
