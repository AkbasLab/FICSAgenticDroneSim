# Phase 18 — exit-criterion evidence (2026-11-10)

> **Exit criterion (AUV-22):** every final cell has sufficient valid replications, and exclusions rest on
> predeclared technical criteria rather than unfavourable outcomes.

## 1. Predeclared, and only technical

`docs/EXCLUSIONS.md` version 1 was committed as `1f296e7` and pushed to `fics/SC` with `50f445d` and `95b71bd`
**before any held-out run of D**; A, B, C's runs of record were flown at `95b71bd` itself. Its five criteria (X1 crashed,
X2 no answer, X3 off the GPU, X4 not the frozen code, X5 not the pinned model) read only manifests, records and server
logs — never an outcome. Version 2 (2026-11-10) adds how an investigated request mismatch is recorded; no criterion
changed. Both versions are frozen (`configs/frozen.toml` v3–v6).

## 2. Sufficient valid replications

`scripts/factorial_exit.py` on the 960 runs of record (`results/factorial-exit-20261110-104348.md`):

| Check | Result |
|---|---|
| design — every run a cell of the design, a held-out test seed, flown once | pass |
| frozen code — the tree is its frozen version; every run at the package digest of `95b71bd` | pass |
| exclusions X1–X5 | **0 runs excluded** |
| paired completeness — 20 seeds with a valid A, B, C and D run, per cell | **12 of 12 cells, 20 each** |
| common random numbers — same files, roster, targets, planned faults; every message's fate the seeded draw | pass |
| decisions saved (18.4) — every D decision with its input, replies, validation, action, fallback; every guardian log | pass |
| variability — each D batch | 99 %, 98 %, 99 % (none under 95 %) |
| requests accounted — records against the server logs | pass (pair's interruption declared and verified) |

## 3. The one interruption, accounted for

Pair's batch was stopped at 68 of 80 by a misplaced Ctrl+C (2026-11-09 14:39) and resumed (job 78961). Its first
server log holds the requests of the runs that were cut off and flown again: **240 requests and 3 failed (HTTP 500 at
14:48:45, when job 78901 ended)**, all after its last complete run or overlapping only the cut-off runs. Declared in
`results/phase18-d-pair-20261109-123907/interruptions.json` and verified, not trusted: every request outside all
complete runs (236) and every failed one inside the declared interval; 2,734 in the records + 240 = 2,974 in the logs
exactly. The resumed job's 442 requests match its records exactly. No run excluded, none changed.

## Verdict

**Met, 2026-11-10.**
