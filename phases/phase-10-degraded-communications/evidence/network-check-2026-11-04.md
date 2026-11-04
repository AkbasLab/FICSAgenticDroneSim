# Phase 10, 10.6 — the network model verified statistically, 2026-11-04

> Run thousands of mock messages and confirm: empirical loss rate approximates the configured rate; empirical
> latency approximates the specified distribution; partitions block only intended links; expired messages are
> not delivered; identical seeds produce identical network behaviour. (AUV-10, 10.6)

**Verified.** Every check held on every condition, seeds 1–20: the exact ones on every seed, the two statistical ones (tests at 1 %) rejecting on no more than 2 seeds of 20 -- 1 rejection(s) in all, of 160 tests. Generated from `../results/network-check-20261104-170034-check.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Messages | heartbeats through the real bus (`simulator/message_bus.py` with the model), no flight, from Drone1, Drone2, Drone3, Drone4: STEADY, every drone broadcasting every 1 s for 1000 s (12,000 deliveries a seed); BURST, every 0.25 s for 100 s |
| Conditions | `configs/network/nominal.toml`; `configs/network/moderate.toml`; `configs/network/severe.toml`; `configs/network/partitioned.toml` |
| Stress networks | slow: latency 3 ± 1 s, around a heartbeat's 3 s lifetime; narrow: 500 bytes a second, sent four a second -- built for the check, since the four conditions rarely reach these limits |
| Seeds | 1–20 |
| Code | commit `316f0ca` + the step-4 files (dirty: True); `agentic_uav` digest `9ad888c89d698d77` |
| Wall time | 152.76 s |

## How each is held

| Check | Held to |
|---|---|
| loss | among deliveries the network decided by chance (not rate-limited, partitioned, out of range), the share lost inside p ± 2.576 √(p(1−p)/n), a 99 % interval; with p = 0, none |
| latency | scheduled arrival less the moment it finished leaving its sender (recomputed from sizes and bandwidth), against a normal of the mean and jitter raised to the floor -- a point mass there -- by a one-sample KS test at 1 %, D below 1.628/√n, taken over distinct values |
| rate limit | every message's admission against a bucket of one second's worth, recomputed independently; refused to every recipient or none |
| partitions | every delivery's status against the partition's rule, pair by pair and instant by instant |
| expiry | nothing delivered at or past its lifetime's end; everything arriving past it, expired; nothing left pending |
| seeds | the same seed, the same record; the drones sending in reverse order, the same record; another seed, another record |

Each check is shown able to fail in `tests/test_network_check.py`, on a real stream altered to break it.

## By condition

| Condition | Loss configured | Loss measured (mean of seeds) | Loss rejections | Latency mean / sd measured | Latency rejections | Refused (burst) | Cut | Expired | Seeds | All |
|---|---|---|---|---|---|---|---|---|---|---|
| nominal | 0 | 0.0000 | 0 | 0.100 / 0.000 s (configured 0.1 ± 0) | 0 | 0 | 0 | 0 | yes | yes |
| moderate | 0.1 | 0.1011 | 0 | 0.300 / 0.099 s (configured 0.3 ± 0.1) | 1 | 0 | 0 | 0 | yes | yes |
| severe | 0.3 | 0.2991 | 0 | 1.006 / 0.488 s (configured 1 ± 0.5) | 0 | 15,920 | 0 | 474 | yes | yes |
| partitioned | 0 | 0.0000 | 0 | 0.100 / 0.000 s (configured 0.1 ± 0) | 0 | 0 | 9,600 | 0 | yes | yes |

**Rejections** (a true model is rejected one time in a hundred by chance):

* moderate, seed 6, latency: KS D 0.0158 above 0.0157 over 10767.

Severe's latencies at the floor: 0.0288 of them, the normal's mass below the floor being 0.0287 -- the point mass, measured.

## The stress networks

| Network | Delivered | Expired | Latency KS (failed seeds) | Delivered late |
|---|---|---|---|---|
| slow | 29,322 | 66,678 | 0 | 0 |
| narrow | 1,440 | 94,560 | 0 | 0 |

Narrow's latencies hold only if each drone's send queue is recomputed message by message from the sizes: they test the bandwidth model where it bites.

**10.6: VERIFIED.**
