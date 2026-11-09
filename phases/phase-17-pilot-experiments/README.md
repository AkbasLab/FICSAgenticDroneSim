# Phase 17 — Pilot experiments

**Stage:** 7 · Science · **Vault note:** `AUV-16 — Pilots, Experiment and Analysis`
**Started:** 2026-11-06 · **Completed:** — (the D re-fly's variability check is still to run on Vega)

> Pilots debug the methodology; they are not results. Phase 17 pre-registered how a communication level is judged,
> swept the levels on the mock and chose them by that rule, flew C and D on the live 70B on Vega, and read every
> run's timeline. The timelines found three defects that no aggregate showed — two in D's tools and its going home,
> one in the rule team's own keep-out, which C flies too. Each was fixed with tests that fail on the old code, every
> run of record reproduced, D re-flown, and then everything that decides a flight and its scoring was frozen and
> Phase 18's held-out seeds were drawn from the freeze.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **17.1** A small matrix — C and D, 2 and 4 drones, nominal and each size's calibrated degraded level, no failure and Drone1 stopped, development seeds 1–5 (`configs/experiments/phase17_pilot.toml`, 80 runs on Vega; D re-flown, `phase17_pilot_d2.toml`, 40 runs)
- [x] **17.2** Inspect individual timelines — `scripts/timeline.py`: each drone's task, role, skills, outages, model decisions and guardian, the team's messages, partitions, reallocations and progress; all 120 live runs drawn and read
- [x] **17.3** Calibrate communication conditions — the rule pre-registered (`docs/CONDITIONS.md`, `aeec7c6`) before an 840-run sweep; levels chosen by it
- [x] **17.4** Freeze the final configurations — `configs/frozen.toml` (138 files, version 1; the held-out seeds as version 2), checked by the suite and CI; **held-out seeds** drawn from the freeze (`configs/seeds/heldout.toml`)
- [ ] ✅ **Exit:** the team can explain why each final communication level is meaningful, and the runner produces complete, interpretable logs — *met on the evidence below; closed once the D re-fly's variability check has run*

## Exit criterion

> The team can explain why each final communication level is meaningful, and the runner produces complete,
> interpretable logs.

**Why each level is meaningful:** `docs/CONDITIONS.md`, applied exactly as pre-registered — every chosen level
separates the architectures when a drone is lost and still delivers most messages (57–75 %); 2-drone `severe` is out
because it delivers 49.5 %, under the rule's 50 % line. **Complete, interpretable logs:** all 120 live-model runs
complete with every file, every model request in the records found in the server's log, and the timelines found
three defects the aggregates hid. · **Evidence:** [`evidence/exit-criterion-2026-11-09.md`](evidence/exit-criterion-2026-11-09.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The calibration rule, pre-registered | `docs/CONDITIONS.md` | **Done**; version 1, unchanged |
| The calibration sweep and its verdict | `scripts/calibrate_conditions.py`, `agentic_uav/experiments/calibration.py`, `results/calibration-20261106-193951.*` | **Done**; 840 runs |
| Run timelines | `scripts/timeline.py`, `agentic_uav/experiments/timeline.py`; `timeline.html` per run, `timelines.html` per batch | **Done** |
| The pilot on Vega | `configs/experiments/phase17_pilot.toml`, `results/phase17-pilot-20261106-201311/`, `docs/VEGA-BATCH.md` | **Done**; 80 runs |
| Model variability | `scripts/model_variability.py`; `model-variability-*.md` in each batch | First batch **100/100**; D re-fly **to run** |
| The three defects' fixes and tests | `agentic_uav/agents/llm_tools.py`, `agents/team_policy.py`, `coordination/keepout.py`; `tests/test_pilot_defects.py`, `tests/test_keepout.py` | **Done** |
| D re-flown | `configs/experiments/phase17_pilot_d2.toml`, `results/phase17-pilot-d2-20261107-195223/` | **Done**; 40 runs |
| The freeze | `configs/frozen.toml`, `agentic_uav/experiments/freeze.py`, `scripts/freeze.py`, `tests/test_freeze.py` | **Done**; version 2 |
| Held-out seeds | `configs/seeds/heldout.toml`, `agentic_uav/experiments/heldout.py`, `scripts/draw_heldout_seeds.py`, `tests/test_heldout.py` | **Done**; 20 + 10 reserves |

## Plan

Approved 2026-11-06 ("Approve, build it all"), shown in full first: the calibration rule pre-registered, then its
code and the timelines, the sweep, the pilot batch on Vega (the user running every Vega step), the timelines read,
the freeze and the held-out seeds, and the close — pushing and tagging without asking again. After the first pilot
the user chose **"Fix and re-fly D"**; after the re-fly, for the third defect, **"Fix, no re-fly"**.

## Record

### 2026-11-06 — the rule first, then the sweep

`docs/CONDITIONS.md` fixed how a level is judged — not trivially easy, not trivially hard, distinguishable, and
communication still useful (delivery ≥ 50 %) — and was committed (`aeec7c6`) before the sweep ran. The sweep: A, B
and C, 2 and 4 drones, every level, both failure conditions, development seeds 1–20, 840 runs on the mock. Chosen
for the pilots: **2 drones `moderate`, 4 drones `severe`**; for Phase 18: 2 drones `nominal`, `moderate`; 4 drones
`nominal`, `moderate`, `partitioned`, `severe`. The separation came from B; whether C and D separate was the pilots'
question.

### 2026-11-06/07 — the pilot on Vega

80 runs (C and D, the matrix above) on gpu02 (PBS job 77898), the batch running on the GPU node beside Ollama
0.40.6 and the pinned `llama3.3:70b` (`a6eb4748fd29`), one request at a time, at commit `cfb4d0e`. Code reached Vega
as a `git bundle`; results came back by `scp`; an email from the login node said when the batch ended. The
variability check asked 100 recorded decisions again: **100 agreed**. C's 40 runs are byte-identical to the same runs
on the laptop (Python 3.11 on Vega, 3.10 here). D: 2,809 decisions, median latency 6.95 s (p95 7.51 s).

### 2026-11-07 — the timelines: two defects in D

C completed 10 of 10 two-drone runs with Drone1 stopped; **D completed 3 of 10** (first written as 4 of 10, a
miscount, corrected 2026-11-08 from the batch's metrics). All seven failures were the same: the survivor held
Drone1's sector and the model chose `start_search`, which searched **from where the drone was** — across the
keep-out round Drone1's last position; the guardian refused it, rightly, and a refusal sends a drone home. The rule
team never does this: it searches from where it is only when the way to its first lane is clear. And in one of the
seven (0027), after the model put the drone on "stand by" and then sent it home, the landing's success took it back
to "wait for a task" — a hold on the ground, a failed landing retried, to the deadline. Fixed (`4de38b1`):
`start_search` goes in by the rule team's own way; going home is not waiting. Tests re-fly 0029 with the 70B's own
recorded answers.

### 2026-11-07/08 — D re-flown, and a third defect, in the rule team

40 D runs on gpu01 (job 78240; gpu02 was busy), at `4de38b1`: **39 met**; the two-drone Drone1-stopped cells
**10 of 10 at 283.8 s** (C 283.7 s). Every request in the records (2,821) is in the server's log, all answered, all
on the GPU. One run failed, 0035 (4 drones, severe, no failure): Drone3 went silent while descending onto its pad at
(8, 0) and never spoke again; the keep-out round its last position covered **Drone4's home at (12, 0)**, 4 m away;
from 351 s Drone4 had no route home, its straight way and every landing elsewhere refused — 150 refusals, to 2,991 s.
Every decision in it was the rule team's own: **C flies the same going home**; it did not meet this timing in these
seeds. Fixed (`45c03d7`): a teammate over its own pad keeps only its pad's column (1 m either side). A replay of 0035
with the model's own answers fails exactly as live on the old code (150 refusals from 351 s) and lands Drone4 on the
new; replaying all 40 D runs, the fix changes only 0035's outcome. Not re-flown, by the user's choice: the replay is
the evidence, and D flies live again in Phase 18 on the frozen code.

On 2026-11-08 the variability check for the re-fly could not run: gpu01's connection to scratch hung, Ollama's GPU
discovery timed out and it fell back to the CPU (`serve-d2-variability.log.gz`, kept); the 40 runs were copied home
first. To run on Vega.

### Reproductions after each fix

After each of the three fixes: the suite (1,391 → 1,393 → 1,401 tests, all passing); Phase 13's exit identical; Phase
14's batch reports, records and trajectories identical to its run of record; the pilot's 40 C runs identical to
Vega's, byte for byte; the 40 D runs flown by the echo identical to before; the calibration identical but for stamps
and code digests. No run of record took a changed path.

### 2026-11-08/09 — the freeze and the held-out seeds

`configs/frozen.toml` version 1 (`62702e8`): every file that decides how the drones fly, how the model is asked and
how a run is scored — `agentic_uav/`, `configs/` but not `configs/experiments/`, `docs/METRICS.md`,
`docs/CONDITIONS.md` — 138 files with their SHA-256. `tests/test_freeze.py` fails the suite, and CI, on any change; the
one way through is a new version with a date and a note (`python scripts/freeze.py --note "..."`). Shown on the real
tree: one comment line in `configs/network/severe.toml` fails the suite.

The held-out seeds were then **derived from freeze version 1** — its SHA-256 seeding a hash counter into
1000..999999, development seeds passed over — so nobody chose them, and recorded as freeze version 2: test seeds
343699, 280070, 458535, 821103, 442986, 605891, 312883, 674924, 657750, 8139, 388194, 545599, 634176, 679573, 747877,
640554, 43505, 541297, 720295, 825940; reserves (in order, for runs excluded by a technical criterion declared
before Phase 18) 392707, 777569, 573239, 32319, 411779, 187409, 527499, 131349, 413823, 559298.

## What the pilots say (methodology, not conclusions)

| Cell (5 seeds each) | C | D, first | D, re-flown |
|---|---|---|---|
| 2 drones, nominal or moderate, no failure | 10/10 | 10/10 | 10/10 |
| 2 drones, nominal or moderate, Drone1 stopped | 10/10, 283.7 s | **3/10** | 10/10, 283.8 s |
| 4 drones, nominal | 10/10 | 10/10 | 10/10 |
| 4 drones, severe, no failure | 5/5 | 5/5 | 4/5 (0035, fixed since) |
| 4 drones, severe, Drone1 stopped | 5/5 | 5/5 | 5/5 |

On the fixed code C and D do not separate on outcomes at five seeds; D asks the model 28–174 times a run. The mock
pauses its clock during a model call, so these completion times leave out the model's ~7 s a decision — the
question AUV-12F keeps apart (model size against decision latency and runtime assurance).

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-06 | **The calibration rule pre-registered before the sweep** | Levels chosen by a rule fixed before any number, not by looking |
| 2026-11-06 | **2 drones `moderate`, 4 drones `severe`**, by the rule; 2-drone `severe` out at 49.5 % delivery | The rule stands, by half a point |
| 2026-11-06 | **The batch runs on the GPU node itself**, one request at a time | No tunnel; an answer depends only on its prompt |
| 2026-11-07 | **"Fix and re-fly D"** (the user) | The two defects were D's own; the pilot exists to find them before the freeze |
| 2026-11-08 | **"Fix, no re-fly"** (the user) for the pad keep-out | The model's own answers replayed show it; D flies live in Phase 18 on the frozen code |
| 2026-11-08 | **A silent teammate over its own pad keeps its pad's column, not the full square** | The pads are 4 m apart to be used together; elsewhere the full square stands |
| 2026-11-08 | **Freeze the whole package and configs**, not a hand-picked list | Every change to what flies or scores is visible and dated |
| 2026-11-09 | **Held-out seeds derived from the freeze** | Verifiable by anyone, chosen by no one |

## Open questions

1. **The D re-fly's variability** — to run on Vega (`model_variability.py` on `phase17-pilot-d2-20261107-195223`).
2. **What each Phase 13 ablation is worth** with the live model and degraded links was not part of the pilots; it
   goes to Phase 18's design, within its compute budget.
3. **Seven severe-link D runs leave their record part-way when replayed** on the mock, on the old code and the new
   alike; outcomes unchanged. Worth understanding before Phase 18 relies on replay.
4. **Latency** — AUV-12F: a real-clock run is needed to measure what the 70B's decision time costs a flight.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
