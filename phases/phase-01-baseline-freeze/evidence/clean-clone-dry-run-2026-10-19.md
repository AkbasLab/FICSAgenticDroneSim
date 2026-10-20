# Clean-clone dry run — 2026-10-19

The exit criterion says a new student can clone the repository, follow the
documentation, and reproduce the baseline flights without help. This is the
"at minimum" version of that test: a fresh clone, read and followed using
nothing outside it, by the original author's assistant rather than a second
person. **It cannot meet the criterion on its own** — it can only find what a
student would trip on before one is asked to try.

| | |
|---|---|
| Clone | `git clone` of the local `SC` at `f35ded6` into `D:\Research\CleanCloneDryRun-20261019` |
| Python | existing `carlaAir` env (not rebuilt — see finding 5) |
| Model | `llama3.3:70b` on Vega `gpu01`, Ollama 0.40.6, via the existing tunnel on 11435 |
| Simulator | CarlaAir v0.1.7, `.\CarlaAir.ps1 Town10HD` (launcher defaults: Epic, 1920×1080, 30 vehicles, 50 walkers requested / 49 spawned), roster of one in `settings.json` |

---

## Result

**Planning: reproduced exactly.** `run_missions.py --plan-only` from the clone,
protocol defaults, 30 runs: 27/27 scored correct, M08 unscoreable and
consistent. Against the citable `v6-polled` block, **all 42 drone-plans match
byte for byte** — same `plan_steps` and same `raw_output` — on every mission.

**Tests and audit: pass from the clone.** 98 tests OK; `audit_repo.py` clean.

**Flight: M01–M09 reproduce to the centimetre on the same server instance. M10
does not reliably land, and leftover drones contaminate later runs.** See
"Flight half" below — 97 runs flown from the clone across five blocks.

**But a student following the docs would not have got this far.** Every step
that worked did so because of knowledge that lives outside the documentation.

---

## Findings

Ordered by how early a student meets them.

### Blocking

1. **The repository a student clones is behind.** `SC` is 9 commits ahead of
   `fics/SC`. Everything on 2026-10-19 — the `num_ctx` protocol, polled
   landings, `v6-polled` itself — is local only. A clone from GitHub gets none
   of it.

2. **No document explains how to reach the study's model.** `SETUP.md` §7
   describes a local Ollama 0.34 with `llama3.2:3b` on the CPU. The protocol in
   `configs/missions/baseline_v1.toml` is `llama3.3:70b` on an H100. Vega, the
   GPU job, the SSH tunnel and `--ollama-host` appear only in code comments and
   in the runner's error message. Following the docs literally:

   ```
   REFUSING TO RUN
   no model endpoint at http://127.0.0.1:11434
   ```

   The Vega manual (`vega-carlaair-manual.tex`) exists, but outside the
   repository.

3. **`BASELINE_MISSIONS.md` names the wrong model and the wrong results.** Its
   Protocol says `llama3.2:3b` primary, and its Results section reports Block A
   (3B, execution invalid). `v6-polled` is not mentioned. A student would
   reproduce, and compare against, the superseded block.

### Will cause wrong or silently different results

4. **`SETUP.md` line 69 contains a literal tab.** `C:\path\to\...` became
   `C:\path<TAB>o\...` — a `\t` escape was interpreted somewhere. Copied as
   shown, `setx` stores a broken path.

5. **`environment.yml` installs a different CARLA wheel from the one
   documented.** It pins `carla==0.9.16` from PyPI. That wheel exists for
   cp310/win_amd64 (5,035,050 bytes), contradicting the `requirements.txt`
   comment that it is not published, and its SHA-256 is `5e7d46f1…865ca6`
   against the shipped wheel's `f255c0fa…727fc33`. `conda env create`
   succeeds, so a student gets a different binary with no warning. Either pin
   the shipped wheel or record that the PyPI one is what the study uses —
   whichever is actually installed in `carlaAir` today.

6. **The simulator launch command differs from the protocol.** `README.md` and
   `SETUP.md` §8 launch `--no-traffic --quality Low`; the measured conditions
   are Town10HD, Epic, traffic on. The ledger notes the GPU load is in the
   protocol deliberately.

### Stale, would confuse

7. `run_missions.py --help` says multi-drone missions rewrite `settings.json`
   and need a restart. Since 2026-10-06 extra drones spawn at runtime and the
   roster stays at one.
8. `SETUP.md` §5 says `requirements.txt` pins carla by local file URL; it no
   longer lists carla at all.
9. `README.md` says 90 tests (there are 98) and that Block A "is being
   re-flown".
10. `SETUP.md` §8 runs `.\env_setup\TestEnv.ps1` without saying it is relative
    to `%CARLAAIR_ROOT%`.
11. `RUN_LEDGER.md` header says "Updated 2026-10-06"; §5 Conditions still lists
    `num_ctx 4096` and the October 6 flight times.
12. `baseline/open_loop_agent.py` defaults to `MODEL = "llama3.2:3b"` and
    `num_ctx = 4096`. The runner overrides both from the config, so results are
    unaffected, but `python baseline\open_loop_agent.py` — the command the
    README gives — plans with the 3B model.

---

## Flight half — 2026-10-19 22:56 to 2026-10-20 00:12

Every run flown from the clone with `run_missions.py --ollama-host
http://127.0.0.1:11435`, and compared run-by-run against `v6-polled` on plan
(raw model output), completion, landing, `ground_z`, flight time, final
position, per-step AGL, obstacle contacts and drone contacts.

| Block | Missions | Runs | Result |
|---|---|---|---|
| `dryrun-flight` | M01–M08, M09, M10 | 30 | M01–M09: 27/27 identical to v6. M10: 2/3 landed |
| `dryrun-M10-rate` | M10 ×10 | 10 | 8/10 landed |
| `dryrun-block2` | M01–M09 | 27 | **contaminated** — flown after M10 without a restart; see finding 14 |
| `clean2` (after restart) | M01–M08 | 24 | 22/22 flown identical to v6; M08 runs 2–3 unflown, Vega dropped |
| `clean2` + `clean2-M08` (new Vega job, 2026-10-20 ~00:45) | M08 ×2, M09, M10 | 8 | M08 identical; M09 3/3 landed but **plan changed** (finding 18); M10 3/3 landed |
| `newjob-plan` | all, `--plan-only` | 30 | 9 of 10 missions byte-identical to v6; M09 differs, consistently |

The clean block is complete: 30 runs in v6's order on a freshly started
simulator, **30/30 completed and landed**.

### M01–M09: reproduced

Across the 54 clean single- and two-drone runs: same plans byte for byte
(except M09 on the second Vega job, finding 18), every
drone landed, `ground_z` 29.25 (M09's Drone2 29.28) on every run, zero obstacle
contacts, M09 separation 4.02–4.03 m as in v6. Worst differences from v6:
**flight time 0.10 s, final x/y 0.03 m, step altitude 0.03 m.**

### M10: the land failure reproduces, and v6's 3/3 was favourable

19 M10 runs now exist (3 in v6, 16 here). **All 19** have the Drone1–Drone3
contact at t ≈ 17 s, following Drone3's jump from 18 m to ~33 m AGL during
`fly_backward` — the open defect in `RUN_LEDGER.md`. **3 of the 16 clone runs
ended with Drone3 unable to descend** (`land did not descend: 33.8–36.3 m above
ground`), teardown landing also failing, control then released in the air.

The failures separate cleanly from the successes:

| | contact duration | max penetration | Drone1 final x |
|---|---|---|---|
| 16 runs that landed (incl. v6) | 0.10–0.66 s | 0.04–0.33 m | 15.6–18.9 m |
| 3 runs that failed | 2.31–3.73 s | 0.39–0.45 m | 3.1–9.6 m |

A long contact both shoves Drone1 back and leaves Drone3 unable to move
vertically. At the observed 13/16 (81%) a three-run block lands cleanly about
54% of the time, so v6's "42/42 drone-landings" is a true record of those three runs
but **not** a property of M10. The landing safeguard did its job: every failure
was detected, raised and recorded rather than reported as a landing.

### Findings from the flight half

13. **M10 lands about 81% of the time (13/16 from the clone).** Not a clone or environment
    problem — it is the Drone3 altitude jump, upstream of `land`. Any Phase 1
    claim about M10 landing needs this rate, not v6's 3/3.

14. **Runtime-spawned drones outlive their mission, and wreck later ones.**
    After M10, Drone2–4 stay in the world; `reset_world` parks them back at
    their spawn poses, which lie on the single-drone flight paths. Block 2,
    flown after M10 without a restart: **17 of 27 runs hit them** — every run
    of M01 and M03, and runs of M04, M05, M07 and M09 — with flights stretched
    to 61–201 s and drones left pinned or hanging up to 11 m above ground.
    Only M02, M06 and M08, which do not fly far enough forward, were clean.
    Nothing warned: the runner checks the declared roster, not vehicles left
    over in the scene, and records the contacts as `obstacle`.
    `BASELINE_MISSIONS.md` says to restart *between multi-drone missions* but
    not before single-drone missions that follow one, and
    `open_loop_agent.py` (`ensure_vehicles` docstring) claims a fleet "flies
    one-, two- and four-drone missions without a restart" — contradicted
    here. v6 avoided it only because it flew M10 last.

    **Fixed 2026-10-20 in `626e0f2`.** `ensure_vehicles` raises
    `ForeignVehicleError` when the scene holds a drone the flight does not
    use, which also covers `fly_chat`. `run_missions.py` checks the whole
    series against the scene before the first takeoff (`series_conflicts`) and
    refuses a bad order; a mid-series hit stops cleanly and keeps the runs
    already written. Restart rule corrected in `BASELINE_MISSIONS.md`, the
    `ensure_vehicles` and `write_settings` docstrings, the runner's module
    docstring, and `docs/carlaair/00-architecture.md`. 12 new tests in
    `tests/test_vehicles.py`; 110 pass. Verified live: with M10's drones in
    the scene, the runner and the agent both refuse M01 with every drone still
    on the ground; after a restart, M01 → M09 → M10 passes the check and flies
    3/3 complete.

15. **`settings.json` hash does not match the record.** The live file
    (unchanged since 2026-09-28, so the one v6 used) hashes `ea20fe8b…`, not
    the `59e6d9b7…` in `BASELINE_ENVIRONMENT.md` §5. Content matches the table
    there; likely whitespace or line endings, but a student checking the hash
    will see a mismatch.

16. **A dropped Vega endpoint is handled correctly.** When the remote side
    closed at ~00:10, the runner refused the affected runs, excluded them from
    every figure and printed a warning. Worth keeping exactly as is.

17. **The `manifest.json` endpoint field is wrong for v6.** It records
    `ollama_endpoint: http://127.0.0.1:11434` while the runs went to 11435 —
    it captures the default, not the `--ollama-host` actually used. The
    per-drone `endpoint` field is right.

18. **Temperature 0 is deterministic per server instance, not across them.**
    On a second Vega job (70763, `gpu01`, same Ollama 0.40.6, same weights,
    same options), M09's Drone1 answered
    `{"action": "fly_to", "x": 0, "y": 0, "z": 0}` where v6 and the first job
    gave `{"action": "fly_to", "x": 0, "y": 0}`. The new instance repeats its
    answer exactly (3/3 flown, 3/3 plan-only), and the other 9 missions stay
    byte-identical. It still scores correct, since scoring compares action
    sequences. Likely cause: a different card or a fresh load changing
    floating-point reduction order; not verified. Implication: "same raw
    output" is not a reproducibility criterion across jobs, and which card
    served a block should be recorded alongside the Ollama version.

19. **That `z: 0` flew Drone1 home at ground level.** `fly_to` z is relative
    to `ground_z`, so `z: 0` is 0 m AGL: the return leg ran at **0.01 m**
    instead of ~8 m, flight 3.3 s shorter. Nothing was in the way on M09's
    path, so it landed, but this is the unbounded `fly_to` z (decided in
    `fba0c98`) appearing in a real model output for the first time. A
    different mission, or the same one in traffic, would put the aircraft
    into whatever is at ground level.

---

## What this does and does not show

It shows the planning half is reproducible to the byte from the repository's
code and config, given the model endpoint. It shows the documentation is not
yet sufficient for someone to find that endpoint, choose the right model, or
compare against the right results. Findings 1–3 alone would stop a student.

The exit criterion stays **not met**.
