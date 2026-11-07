# Communication conditions — the calibration rule, version 1

**Pre-registered 2026-11-06 (Phase 17, AUV-16 17.3), before the calibration sweep was run.**

AUV-16: "Choose degradation levels that produce **distinguishable but not trivial** outcomes. Avoid conditions
where every architecture succeeds almost perfectly; every architecture always fails; latency is so high no
communication is useful; or packet loss is too low to affect coordination." This file fixes, before any number is
seen, how a level is judged; the sweep's results and the levels chosen are added below it, dated, afterwards.

## The sweep

On the mock, laptop only, `scripts/calibrate_conditions.py`:

| | |
|---|---|
| Architectures | A (central), B (independent), C (decentralized rules). D is not swept: by the echo it flies C's flight exactly (Phase 13), and its live model is the pilots' |
| Teams | 2 drones (`search_pair_001`), 4 drones (`search_relay_001`) |
| Levels | `nominal` (the reference), `moderate`, `severe`, and `partitioned` (4 drones only: its groups name four) |
| Failures | `none`, `drone1-at-60s` |
| Seeds | **development seeds 1–20** — never the held-out seeds |

Each run is scored with docs/METRICS.md (version 1).

## The rule

For a team size and a degraded level, a **cell** is one failure condition; in each cell, for each architecture:
the success rate (`P1.success`), the median completion time (`P2.completion_s`, censored at the deadline), its
interquartile range, and the mean continuity retention (`P3.continuity_retention`). The level's own **delivery
rate** is the fraction of deliveries received (`MESSAGE_RECEIVED` ÷ (`MESSAGE_RECEIVED` + `MESSAGE_DROPPED`)),
over all its runs.

A level is **meaningful** for a team size when all four hold:

1. **Not trivially easy.** In at least one cell, at least one architecture either succeeds in fewer than 95 % of
   seeds, or has a median completion at least 10 % longer than its own at `nominal` in the same failure condition.
2. **Not trivially hard.** Not every architecture succeeds in 5 % of seeds or fewer, in both cells.
3. **Distinguishable.** In at least one cell, two architectures differ by at least 20 percentage points in success
   rate; or by at least 10 % in median completion (of the faster) with interquartile ranges that do not overlap;
   or by at least 0.05 in mean continuity retention.
4. **Communication still useful.** The delivery rate is at least 50 %.

`nominal` is always kept: it is the reference P3 is measured against.

**The pilots' degraded level** is, for each team size, the most degraded meaningful level among `severe`, then
`moderate` — in that order of preference. If neither is meaningful for a team size, no level is chosen for it by
this version; a sweep over loss rates would be a version 2 of this file, dated, with its reason.

**Phase 18's communication factor** takes every level found meaningful here, plus `nominal`.

## Results — 2026-11-06 (the rule above, version 1, unchanged)

The sweep: 840 runs (`configs/experiments/phase17_calibration.toml`), at commit `e44eaaf`; the rule's file sha256 `363c0cbffd3a3dac`; the record `phases/phase-17-pilot-experiments/results/calibration-20261106-193951.json`.

| Team | Level | Not easy | Not hard | Distinguishable | Useful (delivery) | Meaningful |
|---|---|---|---|---|---|---|
| 2 | moderate | yes | yes | yes | yes (67.5 %) | yes |
| 2 | severe | yes | yes | yes | **no** (49.5 %) | **no** |
| 4 | moderate | yes | yes | yes | yes (75.2 %) | yes |
| 4 | partitioned | yes | yes | yes | yes (70.3 %) | yes |
| 4 | severe | yes | yes | yes | yes (56.9 %) | yes |

**Chosen.**
* The pilots' degraded level: **2 drones `moderate`**, **4 drones `severe`**.
* Phase 18's communication levels: 2 drones `nominal`, `moderate`; 4 drones `nominal`, `moderate`, `partitioned`, `severe`.

**Why each is meaningful.** Every chosen level separates the architectures when a drone is lost: independent
agents (B) lose the mission in every seed while the central controller (A) and the decentralized team (C) recover
it, at a cost in time that grows with the degradation (4 drones, Drone1 stopped, median: A 308 s nominal, 428 s
severe; C 309 s, 494 s); and
each still delivers most messages (57–75 %). **Why 2-drone `severe` is not:** it delivers 49.5 % of messages,
under the rule's 50 % line for communication still being useful — by half a point, and the rule, fixed before the
sweep, stands. The separation so far comes from B; whether C and D separate is the pilots' question.

## Versions

| Version | Date | What |
|---|---|---|
| 1 | 2026-11-06 | The rule, before the sweep (Phase 17) |
