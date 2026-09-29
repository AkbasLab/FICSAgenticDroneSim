# Results — Phase 1.3 baseline mission runs

Each **session** of flying produces three artifacts with a shared stem. One
session per file set, deliberately: sessions are kept separate rather than
merged into one long log, so each is short enough to read and can be cited on
its own.

## Naming convention

```
<set>-<model>-<stamp>[-<block>].jsonl        the runs, one JSON object per run
<set>-<model>-<stamp>[-<block>].md           the summary table
<set>-<model>-<stamp>[-<block>]-code/        the exact code that flew them
```

| Part | Meaning |
|---|---|
| `<set>` | mission set from `configs/missions/`, e.g. `baseline_v1` |
| `<model>` | the model, `:` replaced by `_` because Windows filenames forbid it |
| `<stamp>` | `YYYYMMDD-HHMMSS` when the session started — sorts chronologically |
| `<block>` | optional label passed with `--block`, e.g. `blockB-M09` |

Timestamps are never reused and files are never overwritten: **a re-run is a
new session, not a correction of an old one.**

## What the `-code/` folder holds

```
open_loop_agent.py     the exact agent that flew these runs
run_missions.py        the exact runner
<set>.toml             the exact mission set and protocol
manifest.json          commit, dirty-tree flag, file digests, Python version
```

**Why the code is copied rather than referenced by commit.** A git SHA
identifies a run's code only if the tree was clean when it flew. In practice
runs are flown from uncommitted work — most of this project's flights were, and
the manifest records `"dirty": true` when so. The copy is the only thing that
answers "which agent produced this number" with certainty.

Every row in the JSONL repeats the same manifest, so a single run can be traced
without opening the folder.

## What a row contains

| Field | |
|---|---|
| `mission`, `attempt`, `t` | which mission, which repeat, when |
| `per_drone[]` | instruction, raw model output, validated plan, correctness, latency |
| `all_valid`, `all_correct` | plan validity and exact-sequence match |
| `execution` | executed steps, completion, collisions, closest approach |
| `protocol` | map, quality, traffic, inference options in force |
| `protocol.code` | the manifest described above |

## Sessions so far

| Session | Missions | Runs | Result |
|---|---|---|---|
| `…-20260928-212436` | M01–M08 | 24 | 21/21 scored correct, 24/24 flown, 0 collisions |

**That first session predates the code snapshot**, so it has no `-code/`
folder. The agent has changed materially since — teardown landing, runtime
vehicle spawning, one connection per thread — so those runs cannot be
reproduced exactly from the current tree. Re-flying them is recorded as an open
item in [`../README.md`](../README.md).
