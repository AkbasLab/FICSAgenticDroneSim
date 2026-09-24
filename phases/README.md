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

---

## Status

| Phase | Name | Exit criterion | State |
|---|---|---|---|
| **0** | [Research contribution](phase-00-research-contribution/) | Team can explain the four architectures in one minute | Deliverable done · exit untested |
| **1** | [Baseline freeze](phase-01-baseline-freeze/) | A new student clones, follows the docs, reproduces the baseline unaided | **In progress** |
| 2 | Repository architecture | Baseline examples run through the modular structure unchanged | Not started |
| 3 | Flight-skill layer | Four drones take off, navigate, hold, return, land — each skill returning a structured result | Not started |
| 4 | Search-and-relay mission | A scripted, non-agentic controller completes the canonical mission | Not started |
| 5 | Persistent single agent | One agent completes a search task with no preflight action list | Not started |
| 6 | Belief state | The logger can show exactly what an agent knew and did not know | Not started |
| 7 | Inter-agent messaging | Four agents exchange heartbeats; team beliefs update only on delivery | Not started |
| 8 | Decentralized task allocation | Four drones divide sectors with no central assignment | Not started |
| 9 | Roles and failure recovery | One agent is stopped; the rest reassign its task with no human command | Not started |
| 10 | Degraded communications | The same mission replays under four conditions with reproducible delivery | Not started |
| 11 | Runtime safety guardian | Injected unsafe commands are prevented from executing | Not started |
| 12 | LLM as agent policy | Each drone decides from a distinct persistent context, still validated | Not started |
| 13 | Comparison architectures | Architecture is selected by configuration, not four codebases | Not started |
| 14 | Experiment runner | A batch command runs a config list unattended, one result directory per run | Not started |
| 15 | Evaluation metrics | Every primary metric has a written definition and tested implementation | Not started |
| 16 | Testing and verification | Most coordination defects are findable without launching the simulator | Not started |
| 17 | Pilot experiments | Each communication level is defensibly meaningful; logs interpretable | Not started |
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
