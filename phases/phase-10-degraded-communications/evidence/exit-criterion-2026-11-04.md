# Phase 10 exit criterion — evidence, 2026-11-04

> The same mission can be replayed under nominal, degraded, severe and partitioned conditions with
> **reproducible message delivery**.

**Met on the mock.** 20 of 20 seeds passed all four checks: the canonical mission flown under each condition with no stop and with Drone1 stopped at 60 s, every flight twice, and on Phase 9's own network once (360 flights). Every message met the same fate at the same time when flown again; every network did, message by message, what its condition says; nominal was Phase 9; 28,921 decisions known exactly. Generated from `../results/network-exit-20261104-174326-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_relay_001.toml`: the canonical mission, four drones, four sectors |
| Agents | Phase 9's recovery policy, each told only the team mission; on a Phase 10 network each also estimates its links over 10 s -- shown, not acted on |
| Conditions | `configs/network/nominal.toml`; `configs/network/moderate.toml`; `configs/network/severe.toml`; `configs/network/partitioned.toml` |
| Lifetimes | heartbeat 3 s, status_update 10 s; the task and role messages 10 s |
| Seeds | 1–20: each places the targets and seeds every message's fate |
| Code | commit `e0efe8b` + the step-5 files (dirty: True); `agentic_uav` digest `ed301de89476f791` |
| Wall time | 1453.02 s |

## The four checks

| Check | What it requires |
|---|---|
| reproducible | every message's fate and time -- sent, scheduled, delivered, or why not -- identical between the two flights (in a canonical order: the bus records in the order threads sent), and every record and decision |
| as configured | the network did what its condition says, message by message: each loss and latency the model's own draw for that message, after its sender's queue; each refusal where the bucket says; each cut where the partition says; nothing out of range; nothing delivered past its lifetime |
| nominal is Phase 9 | nominal's flights, both ways, are Phase 9's -- every delivery, every record, every decision |
| known exactly | Phase 6's knowledge log passes every decision, under every condition |

Each is shown able to fail in `tests/test_network_exit.py`, on a real seed's flights altered to break it.

## Every seed

| Seed | reproducible | as_configured | nominal_is_phase_9 | known_exactly | Decisions known exactly |
|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | 1332 / 1332 |
| 2 | yes | yes | yes | yes | 1446 / 1446 |
| 3 | yes | yes | yes | yes | 1329 / 1329 |
| 4 | yes | yes | yes | yes | 1359 / 1359 |
| 5 | yes | yes | yes | yes | 1555 / 1555 |
| 6 | yes | yes | yes | yes | 1455 / 1455 |
| 7 | yes | yes | yes | yes | 1451 / 1451 |
| 8 | yes | yes | yes | yes | 1437 / 1437 |
| 9 | yes | yes | yes | yes | 1454 / 1454 |
| 10 | yes | yes | yes | yes | 1493 / 1493 |
| 11 | yes | yes | yes | yes | 1520 / 1520 |
| 12 | yes | yes | yes | yes | 1457 / 1457 |
| 13 | yes | yes | yes | yes | 1422 / 1422 |
| 14 | yes | yes | yes | yes | 1489 / 1489 |
| 15 | yes | yes | yes | yes | 1477 / 1477 |
| 16 | yes | yes | yes | yes | 1525 / 1525 |
| 17 | yes | yes | yes | yes | 1452 / 1452 |
| 18 | yes | yes | yes | yes | 1323 / 1323 |
| 19 | yes | yes | yes | yes | 1526 / 1526 |
| 20 | yes | yes | yes | yes | 1419 / 1419 |

## Beside the exit: how the team fared under each condition

Findings, not pass conditions -- the network is the independent variable, and this is the first look at what it does to Phase 9's team. Over the 20 seeds:

| Condition / flight | Met | Completion s (min, median, max) | Searched twice | Leases run out | Alarms about live drones (suspected, unreachable, failed) | Loss the drones estimated | Stale decisions | Stop detected at the thresholds; task taken by the rules |
|---|---|---|---|---|---|---|---|---|
| nominal / no stop | 20/20 | 194.1, 194.1, 194.1 | 0 | 0 | 0, 0, 0 | 0.0 | 0 | - |
| nominal / Drone1 stopped | 20/20 | 309.1, 309.1, 309.1 | 0 | 20 | 0, 0, 0 | 0.0 | 0 | 20/20; 20/20 |
| moderate / no stop | 20/20 | 194.1, 307.7, 439.7 | 20 | 18 | 30, 7, 4 | 0.0881 | 0 | - |
| moderate / Drone1 stopped | 20/20 | 308.7, 311.9, 596.3 | 22 | 41 | 12, 2, 0 | 0.0879 | 0 | 20/20; 8/20 |
| severe / no stop | 20/20 | 342.4, 510.9, 684.5 | 54 | 161 | 1129, 30, 22 | 0.2898 | 0 | - |
| severe / Drone1 stopped | 20/20 | 394.5, 494.4, 604.9 | 43 | 136 | 467, 12, 9 | 0.2902 | 0 | 1/20; 3/20 |
| partitioned / no stop | 20/20 | 313.3, 313.3, 313.3 | 20 | 80 | 160, 160, 160 | 0.0 | 0 | - |
| partitioned / Drone1 stopped | 20/20 | 432.4, 432.4, 432.4 | 20 | 80 | 80, 80, 80 | 0.0 | 0 | 20/20; 20/20 |

Every message's fate, over the 20 seeds (one flight of each pair):

| Condition / flight | delivered | lost | rate_limited | partitioned | expired | out_of_range | pending |
|---|---|---|---|---|---|---|---|
| nominal / no stop | 67,585 | 0 | 0 | 0 | 0 | 0 | 1,520 |
| nominal / Drone1 stopped | 65,923 | 0 | 0 | 0 | 0 | 0 | 21,428 |
| moderate / no stop | 68,401 | 8,765 | 0 | 0 | 0 | 0 | 8,085 |
| moderate / Drone1 stopped | 62,367 | 9,948 | 0 | 0 | 0 | 0 | 25,095 |
| severe / no stop | 99,073 | 46,730 | 8,028 | 0 | 110 | 0 | 9,400 |
| severe / Drone1 stopped | 56,980 | 36,354 | 6,918 | 0 | 64 | 0 | 27,697 |
| partitioned / no stop | 99,465 | 0 | 0 | 15,966 | 0 | 0 | 2,160 |
| partitioned / Drone1 stopped | 83,143 | 0 | 0 | 12,118 | 0 | 0 | 30,499 |

*Pending* is what was still waiting in an inbox when the flight ended: chiefly every message to the stopped drone, which never reads again, and to drones that had landed and ended their part. Not a loss: nobody was left to read it.

## Seed 17, partitioned: the partition taken for a failure

{Drone1, Drone2, base} cut from {Drone3, Drone4} from 60 to 120 s; no drone stopped. Every drone's ladder:

| Drone | About | Suspected | Unreachable | Failed | Recovered |
|---|---|---|---|---|---|
| Drone1 | Drone3 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone1 | Drone4 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone2 | Drone3 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone2 | Drone4 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone3 | Drone1 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone3 | Drone2 | 62.5 s | 69.5 s | 89.5 s | 120.5 s |
| Drone4 | Drone1 | 62.5 s | 69.5 s | 89.5 s | 120.7 s |
| Drone4 | Drone2 | 62.5 s | 69.5 s | 89.5 s | 120.7 s |

Each side climbed the other up the whole ladder -- suspected 2.5 s into the partition, unreachable at 9.5, **failed at 29.5** -- exactly as it climbs for a stopped drone, and took each back the moment the partition healed. From silence alone, a partition longer than the failure threshold *is* a failure to these agents. Their tasks came back through the leases, as Phase 9 intends for a failure: sectors searched twice, the team home later. Telling the two apart is the open question this phase was built to make testable.

## What the findings say

* **The mission was met under every condition, both ways, on every seed** -- Phase 9's recovery, built on every message being delivered, still holds the team together on a network that loses three messages in ten.
* **But it is paid for.** Under moderate loss, sectors searched twice and leases running out appear; under severe, the median flight with no stop takes 510.9 s against nominal's 194.1, with 54 repeated searches and 161 leases run out over the 20 seeds. Silence is read as absence: a holder's progress lost on the way lets its lease run out while it works.
* **The failure ladder raises false alarms.** 1,129 suspicions of live drones under severe with no stop, 22 of them carried all the way to failed; under the partition, 160 live drones called failed. Phase 9's detector reads silence alone, and every network condition makes silence.
* **A stop is no longer detected at Phase 9's thresholds under loss.** Its check holds the ladder to a tick of each threshold, measured from the stopped drone's last message heard; under loss and latency the last message heard is earlier, so the rungs come early, or the task is taken by a rule Phase 9's check did not foresee. The team still finished every time.
* **The drones' own estimates were close**: loss estimated 0.088 under moderate (0.10 configured) and 0.290 under severe (0.30 plus the rate limit's gaps), never told. **No stale-message decision** under any condition.

**Exit criterion: MET** on the mock.
