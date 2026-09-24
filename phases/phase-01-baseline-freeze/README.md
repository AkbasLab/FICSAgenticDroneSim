# Phase 1 — Freeze and document the baseline

**Stage:** 0 · Foundations · **Vault note:** `AUV-02 — Baseline Freeze`
**Started:** 2026-09-18 · **Completed:** —

> Preserve an open-loop system as an experimental constant. You cannot show you
> improved something you did not first pin down.

---

## Objectives

- [ ] **1.1** Tag the baseline release — `v0.1-open-loop-baseline`
- [x] **1.2** Record the exact environment — OS, Python, simulator, models, packages, settings, startup procedure
- [x] 📄 `requirements.txt`, `environment.yml`, [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md)
- [ ] **1.0** Write the open-loop agent — *added 2026-09-24, see the record below*
- [ ] **1.3** Run the ten-mission baseline set and record the results
- [ ] ✅ **Exit criterion** — see below

## Exit criterion

> A new student can clone the repository, follow the documentation, and
> reproduce the baseline flights **without help from the original developer.**

**Met:** no. Untested — and it cannot be self-certified. It needs either a real
second person, or at minimum a clean-clone dry run performed using nothing
outside the clone.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Open-loop agent | `baseline/open_loop_agent.py` | **Not written yet** |
| Baseline tag | `v0.1-open-loop-baseline` | Pending — tagged once the agent runs the mission set |
| Environment record | [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md) | v1.0, §9 rewritten 2026-09-24 |
| Mission set | [`docs/BASELINE_MISSIONS.md`](../../docs/BASELINE_MISSIONS.md) | Defined; **results empty** |
| Package manifests | `requirements.txt`, `environment.yml` | Done |
| Run data | [`results/`](results/) | Empty |

## Record

### 2026-09-18 — environment and mission set documented

Environment captured by reading the machine rather than transcribing
documentation: hardware, OS, Python 3.10.21, CarlaAir v0.1.7 with archive
SHA-256, AirSim settings and hash, 43 pinned packages, Ollama models with
manifest and weight digests.

Ten missions defined (M01–M10) spanning simple movement, multi-step movement,
return-and-land, repetition, altitude change, ambiguous wording, and two- and
four-drone simultaneous flight. Protocol: three runs per mission,
`llama3.2:3b` primary at `temperature 0`, Town10HD, no traffic.

### 2026-09-24 — baseline frozen into its own repository

The tag existed in an external repository but **did not match the documented
baseline**. Three changes lived only as uncommitted working-tree edits: the
OneDrive Documents-path fix, the frozen Ollama options, and the multi-drone
spawn spacing. The frozen options *are* the measurement protocol, so the
documented system and the tagged system were not the same thing.

Resolved by creating this repository and tagging the baseline here.

### 2026-09-24 — decision reversed: write our own agent

The external code carried **no licence**, so default copyright applied: no right
to redistribute, no right to create derivative works. Vendoring it made Phase 20
— which publishes a public artifact — dependent on a licence grant that had not
been sought and might never be given.

**The project chose to reimplement rather than ask.** All external code was
purged from this repository's history, not merely deleted going forward, so no
commit contains it. The tag `v0.1-open-loop-baseline` was dropped with it: after
the purge it named a commit containing no baseline at all, which would have been
a lie in the record. It returns when there is a baseline to name.

This adds implementation work (objective 1.0) before 1.3 can run. It buys an
artifact that is wholly ours to licence, and it removes a publication blocker
that would otherwise have surfaced at the worst possible moment.

Carried across as specification, not code: the eight-action vocabulary, the
open-loop property, the JSON-schema finding, and the NED and known-folder
behaviours — facts and APIs rather than anyone's expression of them. Prior
published benchmark figures stay in `BASELINE_MISSIONS.md` as attributed
citations.

Removed with it: `tools/apply_logging.py`, which existed only to patch logging
into someone else's script. The new agent logs natively, so measurement is not
an opt-in step that can be forgotten.

### Pending — 1.0 then 1.3

Write the agent, then 24 scored runs plus M09/M10. Restore `settings.json` after
the multi-drone missions, or the single-drone missions become invalid.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-09-24 | New repository rather than building on the external clone | It is another author's repo with a published tag; a personal repo avoids rewriting anything of theirs |
| 2026-09-24 | **Reimplement the baseline; use no external agent code** | No licence means no right to redistribute or derive. Phase 20 publishes an artifact |
| 2026-09-24 | Purge history rather than delete going forward | History is published too; a deletion commit leaves the code retrievable |
| 2026-09-24 | Drop the tag until the agent exists | A tag named `open-loop-baseline` on a commit with no baseline is a false record |
| 2026-09-24 | Logging is built into the agent, not patched in | A measurement step that can be skipped will be skipped, and the fields cannot be reconstructed afterwards |
| 2026-09-24 | Commit email is the GitHub noreply address | Account blocks pushes exposing a private email; noreply keeps it private and still attributes |
| 2026-09-24 | Repository kept **private** for now | Publication is a Phase 20 decision, taken deliberately rather than by default |

## Open questions

- **Absolute paths in the docs.** `SETUP.md` and `CONTROLS.md` quote this
  machine's paths (`D:\Research\...`, `D:\AllSetups\...`). A student on another
  machine meets them immediately, and the exit criterion is explicitly about
  someone else. Decide whether they become placeholders before the exit test.
- **Which licence** this repository carries, now that it is free to choose one.
  Settled in `AUV-21` before Phase 20.
