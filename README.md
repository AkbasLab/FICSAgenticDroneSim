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

## Branch policy — `SC`

This work is maintained on the **`SC`** branch of
`AkbasLab/FICSAgenticDroneSim`. **SC stands for Swarm Coordination**, and the
branch is a single-author line dedicated to building that capability
**from scratch**, phase by phase.

> [!] **`main` is not merged into `SC`, now or in future.**

That is deliberate, not an oversight:

* The baseline here is an **independent clean-room reimplementation**. No code
  from any other author's repository is used, which is recorded in
  [`phases/phase-01-baseline-freeze/`](phases/phase-01-baseline-freeze/) along
  with the licensing reasoning behind it.
* The value of this branch is that every defect, measurement and reversal is
  attributable to work done here. Merging a parallel codebase in would destroy
  that, and the phase record would stop meaning anything.
* Histories are genuinely unrelated — there is no common ancestor with `main`,
  so a merge is not a tidy-up, it is a fusion of two separate projects.

So, concretely, on this branch:

```
never:   git merge fics/main
never:   git rebase fics/main
never:   git pull            (bare, with main tracked)
use:     git pull fics SC
```

There is no branch protection enforcing this — it requires `admin` on the
repository, which this author does not hold. It therefore rests on discipline,
which is why it is written down here rather than left to memory.

Work from `main` that turns out to be worth having is **reimplemented** here and
credited in the phase record, not merged.

---

## Start here

| I want to… | Go to |
|---|---|
| Install the whole stack from scratch | [`docs/SETUP.md`](docs/SETUP.md) |
| Fly something, or look up a command | [`docs/CONTROLS.md`](docs/CONTROLS.md) |
| Write my own agent against the simulator | [`docs/carlaair/00-architecture.md`](docs/carlaair/00-architecture.md) |
| Look up any simulator control, feature or API | [`docs/carlaair/`](docs/carlaair/) — the reference set |
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
python baseline\open_loop_agent.py
```

Type an instruction in plain English — `fly forward for 5 seconds then return
home and land`. The model plans it, the plan is validated, the drones fly it.

---

## Where the project is

**Phase 1 — freezing and documenting the baseline.**

Each phase keeps its own record in [`phases/`](phases/): objectives, the exit
criterion and whether it is actually met, deliverables, decisions taken, and the
evidence. Start at [`phases/README.md`](phases/README.md) for the status of all
21 phases. Objectives are mirrored from the vault note `AUV-22 — Phase
Objectives Checklist`; each phase also has a detail note `AUV-01` … `AUV-23`.

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

The baseline is the open-loop system the project sets out to improve on, written
from scratch here as `baseline/open_loop_agent.py`. In it:

- each drone receives a **separate** natural-language instruction;
- the model generates a **complete action list before takeoff**;
- plans are **validated** before any vehicle arms;
- drones execute **concurrently**, one thread each;
- **no replanning happens after launch.**

That last property is the one everything from Phase 5 onward exists to remove.
The baseline stays runnable because every later architecture is measured against
it, on the same ten missions. It is tagged `v0.1-open-loop-baseline` once it
runs the mission set.

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
docs/       RESEARCH_PLAN · SETUP · CONTROLS · BASELINE_* · carlaair/ reference set
configs/    missions/ — the mission set as data, edit here to add or change one
baseline/   the open-loop agent — original to this project, and frozen
scripts/    experiment entry points: run_missions.py
tools/      development tooling: audit_repo.py, the doc generators
tests/      unit tests for the pure logic — no simulator, no model
phases/     one folder per phase: objectives, exit criterion, evidence, decisions
runs/       raw run output; the directory is tracked, its contents are not
```

**`scripts/` versus `tools/`**: scripts run experiments and produce evidence;
tools maintain the repository and never appear in a result. The split follows
the module tree in `AUV-03`, which Phase 2 builds out.

**Two output locations, deliberately.** `runs/agent-log.jsonl` is the raw,
git-ignored log of *every* planning call ever made on this machine, whatever
invoked it. `phases/phase-NN-*/results/` holds curated, tracked evidence for a
specific scored series. Neither replaces the other: the first is a black box
recorder, the second is the experimental record.

```powershell
python -m unittest discover tests     # 30 tests, no simulator needed
python tools\audit_repo.py            # run before every commit
```

`docs/` says what the project intends; `phases/` records what it actually did,
including the attempts that failed. Measurements land in
`phases/phase-NN-*/results/`, exit-criterion proof in `evidence/`, and each
completed phase is tagged `phase-NN-complete`.

The module tree the project refactors into during Phase 2 — `agentic_uav/` with
`core`, `simulator`, `control`, `agents`, `coordination`, `planners`,
`experiments` — is specified in `AUV-03 — Repository Architecture`. Its shape
encodes the experimental design: policies, planners and simulators are all
interchangeable, which is what makes selecting an architecture a configuration
change rather than four separate codebases.

---

## Status, provenance and licensing

> **This project is under active development and carries no licence yet.**
> Nothing here is a finished result. The baseline has not flown the mission set,
> no measurements have been recorded, and interfaces will change without notice
> until Phase 2 settles the module structure.
>
> **No licence is granted.** Absent one, default copyright applies: this is
> readable by those given access, not reusable. A licence is chosen deliberately
> in `AUV-21 — Ethics, Licensing and Publication Compliance`, before Phase 20
> publishes anything. Until then the repository stays private and unlicensed —
> by decision, not by oversight.

**All code here is original to this project.** No third-party agent code is
vendored, imported or required at runtime. The only dependencies are the
published libraries in `requirements.txt` — `airsim`, `carla`, `ollama` and the
usual scientific stack.

An earlier prototype of the open-loop agent existed in an external repository
that declares no licence, which under default copyright grants no right to
redistribute or to build derivative works. Rather than seek a grant, the
baseline was reimplemented from scratch and the external code was removed from
this repository's history. The reasoning is recorded in
[`docs/BASELINE_ENVIRONMENT.md`](docs/BASELINE_ENVIRONMENT.md) §9, and the
choice in [`phases/phase-01-baseline-freeze/`](phases/phase-01-baseline-freeze/).

That leaves the repository free to carry whatever licence the project chooses
when the time comes — which is the point of removing the dependency, and why
the choice can wait rather than being forced by someone else's terms.
