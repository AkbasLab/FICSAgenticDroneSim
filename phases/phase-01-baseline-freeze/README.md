# Phase 1 — Freeze and document the baseline

**Stage:** 0 · Foundations · **Vault note:** `AUV-02 — Baseline Freeze`
**Started:** 2026-09-18 · **Completed:** —

> Preserve the current open-loop system as an experimental constant. You cannot
> show you improved something you did not first pin down.

---

## Objectives

- [x] **1.1** Tag the baseline release — `v0.1-open-loop-baseline`
- [x] **1.2** Record the exact environment — OS, Python, simulator, models, packages, settings, startup procedure
- [x] 📄 `requirements.txt`, `environment.yml`, [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md)
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
| Baseline tag | `v0.1-open-loop-baseline` → `63eb663` | Done |
| Environment record | [`docs/BASELINE_ENVIRONMENT.md`](../../docs/BASELINE_ENVIRONMENT.md) | v1.0 |
| Mission set | [`docs/BASELINE_MISSIONS.md`](../../docs/BASELINE_MISSIONS.md) | Defined; **results empty** |
| Package manifests | `requirements.txt`, `environment.yml` | Done |
| Logging tool | [`tools/apply_logging.py`](../../tools/apply_logging.py) | Done |
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

The tag existed upstream but **did not match the documented baseline**. Three
changes lived only as uncommitted working-tree edits: the OneDrive
Documents-path fix, the frozen Ollama options, and the multi-drone spawn
spacing. The frozen options *are* the measurement protocol, so the documented
system and the tagged system were not the same thing.

Resolved by creating this repository, copying the baseline code with those
changes included, and tagging it here. Provenance recorded in
[`baseline/PROVENANCE.md`](../../baseline/PROVENANCE.md).

Also found and fixed: `apply_logging.py` had hardcoded absolute paths into one
machine's folders, which would have failed the exit criterion on its own. It now
resolves paths relative to the repository and verifies its own preconditions.

### Pending — 1.3

24 scored runs plus M09/M10. Requires the logging patch applied first, or
planning latency and raw model output cannot be recovered afterwards. Restore
`settings.json` after the multi-drone missions, or the single-drone missions
become invalid.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-09-24 | New repository rather than building on the upstream clone | Upstream is another author's repo with a published tag; a personal repo avoids rewriting anything of theirs |
| 2026-09-24 | Baseline code **copied**, upstream prose **referenced** | Keeps authorship unambiguous — see `PROVENANCE.md` |
| 2026-09-24 | Commit email is the GitHub noreply address | Account blocks pushes exposing a private email; noreply keeps it private and still attributes |
| 2026-09-24 | Repository kept **private** | `baseline/` is third-party code with no declared licence. Private is storage; public would be redistribution |

## Open questions

- **Licensing.** The upstream repository declares no licence, so its code is
  all-rights-reserved by default. Phase 20 publishes the artifact publicly — a
  licence grant or written permission is needed before then. See
  `AUV-21 — Ethics, Licensing and Publication Compliance`.
- **Absolute paths in the docs.** `SETUP.md` and `CONTROLS.md` quote this
  machine's paths (`D:\Research\...`, `D:\AllSetups\...`). A student on another
  machine meets them immediately. Decide whether they become placeholders
  before the exit test is run.
