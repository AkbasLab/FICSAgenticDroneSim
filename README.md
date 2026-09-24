# Adi-MLOps — Decentralized Agentic UAV Coordination

Research repository for a study on whether decentralized teams of persistent UAV
agents hold up better than centralized ones when the radio link degrades and
drones drop out.

> A decentralized team of persistent UAV agents that uses local belief states,
> structured peer communication, dynamic task allocation and bounded replanning
> can maintain greater **mission continuity** under communication degradation
> and agent loss than centralized planning or independent non-coordinating
> agents.

The claim is deliberately modest. It is about **resilience, not speed** — under
nominal communication a centralized controller is expected to win, and the plan
says so in writing before any result is inspected.

**Platform:** CarlaAir v0.1.7 — CARLA 0.9.16 and AirSim 1.8.1 in one Unreal
Engine 4.26 process, on Windows 11.

---

## Start here

| I want to… | Go to |
|---|---|
| Install the whole stack from scratch | [`docs/SETUP.md`](docs/SETUP.md) |
| Fly something, or look up a command | [`docs/CONTROLS.md`](docs/CONTROLS.md) |
| Understand what is being studied and why | [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) |
| Reproduce the frozen baseline measurements | [`docs/BASELINE_MISSIONS.md`](docs/BASELINE_MISSIONS.md) |
| Know exactly what machine produced them | [`docs/BASELINE_ENVIRONMENT.md`](docs/BASELINE_ENVIRONMENT.md) |

First flight, assuming the stack is installed:

```powershell
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
.\CarlaAir.ps1 Town10HD --no-traffic --quality Low
```

```powershell
conda activate carlaAir
python baseline\llama_airsim_agent.py
```

Type an instruction in plain English — `fly forward for 5 seconds then return
home and land`. The model plans it, the plan is validated, the drones fly it.

---

## Where the project is

**Phase 1 — freezing and documenting the baseline.** Phase tracking lives in the
vault note `AUV-22 — Phase Objectives Checklist`; each phase has a detail note
`AUV-01` … `AUV-23`.

| Stage | Phases | State |
|---|---|---|
| 0 · Foundations | 0–1 | Phase 0 complete; Phase 1 in progress |
| 1 · Platform | 2–4 | Not started |
| 2 · One agent | 5–6 | Not started |
| 3 · The team | 7–9 | Not started |
| 4 · Adversity | 10–11 | Not started |
| 5 · Intelligence | 12 | Not started |
| 6 · Apparatus | 13–16 | Not started |
| 7 · Science | 17–20 | Not started |

The ordering is load-bearing. Deterministic decentralized coordination (arm C)
is built and measured **before** any language model touches coordination (arm
D) — otherwise there is no way to separate "decentralisation helped" from "the
LLM helped", and the study has no contribution.

---

## The baseline this replaces

Tag `v0.1-open-loop-baseline` marks the system the project sets out to improve
on. In it:

- each drone receives a **separate** natural-language instruction;
- the model generates a **complete action list before takeoff**;
- plans are **validated** before any vehicle arms;
- drones execute **concurrently**, one thread each;
- **no replanning happens after launch.**

That last property is the one everything from Phase 5 onward exists to remove.
The baseline stays runnable because every later architecture is measured against
it, on the same ten missions.

Two properties of the current agent are worth stating plainly: **it is blind** —
no camera image or drone state ever reaches the model — and **it never
replans**. Both are design properties of the baseline, not defects.

---

## The four architectures being compared

They share one mission, the same vehicle skills, scenario manager, network model
and safety guardian. They differ in exactly one dimension — how coordination
decisions get made.

| Arm | Coordination | Isolates |
|---|---|---|
| **A** Centralized | One controller assigns all tasks | Nominal-efficiency baseline |
| **B** Independent | No negotiation between drones | Whether communication is worth anything |
| **C** Deterministic decentralized | Contract-net protocol, **no LLM** | Whether decentralisation is worth anything |
| **D** Agentic decentralized | Same protocol **plus** LLM policy | Whether the LLM is worth anything |

---

## Layout

```
docs/       RESEARCH_PLAN · SETUP · CONTROLS · BASELINE_ENVIRONMENT · BASELINE_MISSIONS
baseline/   the frozen open-loop agents, plus PROVENANCE.md
tools/      apply_logging.py — adds JSONL planning logs to the baseline agent
patches/    baseline.patch — the delta against the upstream tag
runs/       run output; the directory is tracked, its contents are not
```

The module tree the project refactors into during Phase 2 — `agentic_uav/` with
`core`, `simulator`, `control`, `agents`, `coordination`, `planners`,
`experiments` — is specified in `AUV-03 — Repository Architecture`. Its shape
encodes the experimental design: policies, planners and simulators are all
interchangeable, which is what makes selecting an architecture a configuration
change rather than four separate codebases.

---

## Provenance and licensing

The code in `baseline/` is **not original to this repository**. It comes from
`niranjanpillai2009-altr/AirSimRepo` at commit `e2b297d`, which declares **no
licence** — meaning all rights reserved by default.
[`baseline/PROVENANCE.md`](baseline/PROVENANCE.md) records the origin of every
file and the three changes applied on top of the upstream tag.

A licence grant or written permission is needed before this repository is
published. See `AUV-21 — Ethics, Licensing and Publication Compliance`.
