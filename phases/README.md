# Phase Record

The study runs in 21 phases across 7 stages. This directory is the **evidence
trail**: one folder per phase, holding what that phase produced, what it
measured, and what demonstrates its exit criterion was met.

The plan itself lives in [`../docs/RESEARCH_PLAN.md`](../docs/RESEARCH_PLAN.md);
the detailed objectives live in the vault notes `AUV-01` … `AUV-23`. This
directory is neither — it records **what actually happened**, which is the part
that decays fastest if it is not written down at the time.

---

## Rules

1. **A phase is done when its exit criterion is demonstrably met** — not when
   its sub-items are ticked. Exit criteria are tests, not intentions.
2. **Evidence goes in the phase folder**, not in a chat log or someone's head.
   A transcript, a results table, a log file, a screenshot — something a reader
   who was not there can check.
3. **Completed phases are tagged**: `phase-NN-complete`, alongside any version
   tag that phase produced.
4. **Nothing is revised after the fact.** If a phase's conclusion turns out to
   be wrong, add a dated note saying so rather than editing the record.
5. **Failed and abandoned attempts stay.** Phase 18 explicitly forbids
   discarding unsuccessful runs; the same discipline applies here.

Start a new phase by copying [`_template/`](_template/).

**How many runs have been flown, and which of them count:**
[`RUN_LEDGER.md`](RUN_LEDGER.md). Kept separately because most of the runs on
disk are not study data, for reasons that are easy to forget.

---

## Status

| Phase | Name | Exit criterion | State |
|---|---|---|---|
| **0** | [Research contribution](phase-00-research-contribution/) | Team can explain the four architectures in one minute | Deliverable done · exit untested |
| **1** | [Baseline freeze](phase-01-baseline-freeze/) | A new student clones, follows the docs, reproduces the baseline unaided | **Complete** 2026-10-20, at the minimum standard (clean-clone test); `v0.1-open-loop-baseline` |
| **2** | [Repository architecture](phase-02-repository-architecture/) | Baseline examples run through the modular structure unchanged | **Complete** 2026-10-20 — goldens unedited after every step; a 30-run re-flight matches `v6-polled` |
| **3** | [Flight-skill layer](phase-03-flight-skill-layer/) | Four drones take off, navigate, hold, return, land — each skill returning a structured result | **Complete** 2026-10-21 — eleven skills, a mock, one contract; the four-drone script met live in CarlaAir and on the mock |
| **4** | [Search-and-relay mission](phase-04-search-relay-mission/) | A scripted, non-agentic controller completes the canonical mission | **Complete** 2026-10-21 — the scripted controller meets all 20 exit seeds on the mock; a small variant met 20 of 20 in each of three CarlaAir flights |
| **5** | [Persistent single agent](phase-05-persistent-agent/) | One agent completes a search task with no preflight action list | **Complete** 2026-10-21 — one agent told only "search S3" meets 20/20 seeds and 5/5 troubles on the mock; in CarlaAir, three nominal flights of a small variant (20/20 seeds each) and one with an injected fault, 4 of 4 met |
| **6** | [Belief state](phase-06-belief-state/) | The logger can show exactly what an agent knew and did not know | **Complete** 2026-11-02 — 1340 of 1340 decisions logged complete, correct and without a leak on the mock (a single agent and an independent pair, 20 seeds each); 10 of 10 in a CarlaAir flight |
| **7** | [Inter-agent messaging](phase-07-inter-agent-messaging/) | Four agents exchange heartbeats; team beliefs update only on delivery | **Complete** 2026-11-04 — on the mock, 20 of 20 seeds: 5,820 teammate records each traced to a delivered message, blocked flights believing nothing, talking steering nothing; live, two drones talking in CarlaAir, MET, every decision the mock twin's |
| **8** | [Decentralized task allocation](phase-08-decentralized-task-allocation/) | Four drones divide sectors with no central assignment | **Complete** 2026-11-04 — on the mock, 20 of 20 seeds, deliberating and contested, each twice: one team mission, every sector held once, simultaneous claims settled by the rules, identical when flown again; the optional live flight, flown later, MET |
| **9** | [Roles and failure recovery](phase-09-roles-and-failure-recovery/) | One agent is stopped; the rest reassign its task with no human command | **Complete** 2026-11-04 — on the mock, 20 of 20 seeds, each drone stopped in turn and each stopped flight twice: every survivor detected the stop from silence, a reserve took its task, the mission met with no new command; reprioritization and 9.4 beside it; the optional live flight, flown later, NOT MET -- the survivor collided with the stopped drone; with the keep-out fix (2026-11-05) flown again, NOT MET on coverage but no collision |
| **10** | [Degraded communications](phase-10-degraded-communications/) | The same mission replays under four conditions with reproducible delivery | **Complete** 2026-11-04 — on the mock, 20 of 20 seeds, each condition with and without a drone stopped, every flight twice: every message's fate reproduced, every network as configured, nominal exactly Phase 9; the model verified statistically; the team's costs under each recorded as findings |
| **11** | [Runtime safety guardian](phase-11-runtime-safety-guardian/) | Injected unsafe commands are prevented from executing | **Complete** 2026-11-04 — on the mock, 20 of 20 seeds: 33 unsafe or invalid commands injected through the rule-policy and LLM channels, every one caught as expected and none started; no guarded flight broke a limit; clean flights unchanged, no intervention; each refusal's cost to the mission recorded as a finding |
| **12** | [LLM as agent policy](phase-12-llm-agent-policy/) | Each drone decides from a distinct persistent context, still validated | **Complete** 2026-11-05 (as a capability) — on the mock, the pinned llama3.3:70b chosen on a benchmark, 5 of 5 seeds, stop and no stop: distinct contexts, the model deciding (690 decisions, 0 fallbacks), every action guarded (0 interventions), every flight replayed exactly; no live flight, by the user's decision |
| **13** | [Comparison architectures](phase-13-comparison-architectures/) | Architecture is selected by configuration, not four codebases | **Complete** 2026-11-06 — on the mock, 13 configurations (A, B, C, D, E and eight ablations) through one entry point and one harness, 20 of 20 seeds: each arm what it claims, each ablation's mechanism off, every limit kept, deterministic; every earlier run of record reproduced; no live flight, by the plan |
| **14** | [Experiment runner](phase-14-experiment-runner/) | A batch command runs a config list unattended, one result directory per run | **Complete** 2026-11-06 — on the mock, `scripts/run_batch.py`: a 43-run batch with no prompts, one complete directory per run (manifest, report, 19-type event log, records), all nine checks; failed and crashed runs kept; byte-identical when flown again; resumable |
| **15** | [Evaluation metrics](phase-15-evaluation-metrics/) | Every primary metric has a written definition and tested implementation | **Complete** 2026-11-06 — `docs/METRICS.md` committed before any code; P1–P6, coordination efficiency and 15 diagnostics implemented exactly as defined, absent with a reason rather than 0, stamped with the definitions' digest; all eight checks on a 43-run batch |
| **16** | [Testing and verification](phase-16-testing-and-verification/) | Most coordination defects are findable without launching the simulator | **Complete** 2026-11-06 — 37 of 37 planted coordination and communication defects found without the simulator (36 of 37 on the first run); 28 of 29 of the project's own; AUV-15's tests mapped and checked, seven scenarios, determinism; CI on Windows; the five AirSim regression checks flown live, all passed |
| **17** | [Pilot experiments](phase-17-pilot-experiments/) | Each communication level is defensibly meaningful; logs interpretable | **In progress** — levels chosen by a pre-registered rule (2 drones `moderate`, 4 drones `severe`); 120 live-model runs on Vega, every timeline read: three defects found and fixed, D re-flown (two-drone Drone1-stopped 3/10 → 10/10, as C); everything that flies or scores frozen; held-out seeds drawn from the freeze. The re-fly's variability check remains |
| 18 | Main factorial | Every cell has enough valid replications; exclusions predeclared | Not started |
| 19 | Analysis | Each conclusion rests on both statistics and inspected decision traces | Not started |
| 20 | Paper and artifact | Published repository and paper | Not started |

### Stages

| Stage | Phases | Theme |
|---|:--:|---|
| 0 · Foundations | 0–1 | Decide what is being claimed; freeze what exists |
| 1 · Platform | 2–4 | Make the simulator scriptable and the mission canonical |
| 2 · One agent | 5–6 | Replace preflight plans with a persistent loop and a belief state |
| 3 · The team | 7–9 | Messaging, task allocation, roles — **all without an LLM** |
| 4 · Adversity | 10–11 | Degrade the network; guard the aircraft |
| 5 · Intelligence | 12 | Only now does the language model touch coordination |
| 6 · Apparatus | 13–16 | Four architectures, a runner, metrics, tests |
| 7 · Science | 17–20 | Pilots, the factorial, analysis, publication |

---

## Two orderings that are load-bearing

**Phase 8 before Phase 12.** Deterministic decentralized coordination must be
built and measured before any language model touches task allocation.
Otherwise there is no way to separate "decentralisation helped" from "the LLM
helped", and the study has no contribution to report.

**Phase 12 after the apparatus is stable.** The plan is explicit that the LLM
is to be evaluated as an agentic decision component, not used to paper over an
unfinished simulator.

If schedule pressure ever makes one of these look negotiable, it is not.
