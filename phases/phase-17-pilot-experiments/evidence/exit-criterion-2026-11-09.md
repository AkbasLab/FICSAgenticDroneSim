# Phase 17 — exit-criterion evidence (2026-11-09)

> **Exit criterion (AUV-16):** the team can explain why each final communication level is meaningful, and the
> runner produces complete, interpretable logs.

## 1. Why each final communication level is meaningful

The rule was written and committed **before** any level was measured: `docs/CONDITIONS.md`, version 1 (`aeec7c6`,
2026-11-06). A level is meaningful for a team size when it is not trivially easy, not trivially hard,
distinguishable between architectures, and communication is still useful (delivery ≥ 50 %). The sweep — A, B and C,
2 and 4 drones, every level, no failure and Drone1 stopped, development seeds 1–20, 840 runs on the mock at
`e44eaaf` — and the verdict are `results/calibration-20261106-193951.json` / `.md`, appended to `docs/CONDITIONS.md`
dated, the rule unchanged.

| Team | Level | Not easy | Not hard | Distinguishable | Delivery | Meaningful |
|---|---|---|---|---|---|---|
| 2 | moderate | yes | yes | yes | 67.5 % | **yes** |
| 2 | severe | yes | yes | yes | 49.5 % | **no** |
| 4 | moderate | yes | yes | yes | 75.2 % | **yes** |
| 4 | partitioned | yes | yes | yes | 70.3 % | **yes** |
| 4 | severe | yes | yes | yes | 56.9 % | **yes** |

**The explanation, per level.** Each chosen level separates the architectures when a drone is lost — the independent
agents (B) lose the mission in every seed while the central controller (A) and the decentralized team (C) recover
it, at a time cost that grows with degradation (4 drones, Drone1 stopped, median: A 308 s nominal → 428 s severe;
C 309 s → 494 s) — and still delivers most messages (57–75 %). 2-drone `severe` delivers 49.5 %: under the line by
half a point; the rule stands. `nominal` is kept as the reference P3 is measured against. Phase 18's communication
factor: 2 drones `nominal`, `moderate`; 4 drones `nominal`, `moderate`, `partitioned`, `severe`.

The levels themselves are frozen (`configs/network/*.toml` in `configs/frozen.toml`).

## 2. The runner's logs are complete

| Batch | Runs | Every run complete | Commit | Notes |
|---|---|---|---|---|
| `phase17-pilot-20261106-201311` (Vega gpu02) | 80 (C 40, D 40) | 80 of 80: manifest, events, report, records, trajectories | `cfb4d0e`, clean | 2,809 D decisions, 2,860 requests; variability 100 of 100 agreed |
| `phase17-pilot-d2-20261107-195223` (Vega gpu01) | 40 (D) | 40 of 40, gzip-checked after the copy | `4de38b1`, clean | 2,789 decisions; **2,821 requests in the records = 2,821 `POST /api/chat` in `serve-d2.log.gz`, all HTTP 200**, the server on CUDA (H100) throughout |

Each run's manifest names the commit, the package digest, the model's digest (`a6eb4748fd29…`), its options and
every file read with its digest. Failures are kept as completed runs (0035's 24,999 events among them). Metrics
(`metrics.jsonl`, `metrics.md`) and timelines (`timeline.html`, `timelines.html`) are computed from the run
directories alone, on the laptop. C's 40 Vega runs are byte-identical to the same runs flown on the laptop.

## 3. The logs are interpretable — they found what the aggregates hid

Read run by run (AUV-16 17.2), the timelines found three defects, each then traced in the decision records and the
guardian's log, fixed with tests that fail on the old code, and every run of record reproduced:

| Defect | Where it showed | Fix |
|---|---|---|
| D's `start_search` searched from where the drone was, across a silent teammate's keep-out; the guardian refused; a refusal sends a drone home | 7 of 10 two-drone D runs with Drone1 stopped (first batch) | `4de38b1`: in by the rule team's own way |
| A drone put on "stand by" then sent home: its landing's success took it back to "wait for a task" — a loop to the deadline | run 0027 (first batch) | `4de38b1`: going home is not waiting |
| A teammate silent over its own pad kept a keep-out over its neighbour's home: no route home, 150 refusals | run 0035 (re-fly), the rule team's own code | `45c03d7`: over its own pad, only the pad's column |

The first two left D's mission score at 3 of 10 against C's 10 of 10 — visible in the aggregate, but only the
timeline said why. The third left one run of forty; its cause sits in code C flies too.

## Not yet

The variability check on the re-fly batch (2026-11-08: gpu01's scratch hung and Ollama fell back to the CPU; to run
on Vega). The phase closes when it has.
