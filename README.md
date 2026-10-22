# Decentralized Agentic UAV Coordination

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
| Serve the study's model from a GPU cluster | [`docs/vega/`](docs/vega/) — the Vega HPC manual |
| Reproduce the frozen baseline measurements | [`docs/SETUP.md`](docs/SETUP.md) §9, then [`docs/BASELINE_MISSIONS.md`](docs/BASELINE_MISSIONS.md) |
| Know which runs are valid data, and why | [`phases/RUN_LEDGER.md`](phases/RUN_LEDGER.md) |
| Know exactly what machine produced them | [`docs/BASELINE_ENVIRONMENT.md`](docs/BASELINE_ENVIRONMENT.md) |

First flight, assuming the stack is installed and the model endpoint from
[`docs/SETUP.md`](docs/SETUP.md) §7 is answering on 11435:

```powershell
cd $env:CARLAAIR_ROOT        # set once in docs/SETUP.md
.\CarlaAir.ps1 Town10HD
```

```powershell
conda activate carlaAir
python baseline\open_loop_agent.py --model llama3.3:70b --ollama-host http://127.0.0.1:11435
```

Type an instruction in plain English — `fly forward for 5 seconds then return
home and land`. The model plans it, the plan is validated, the drones fly it.
Without a GPU server, SETUP §7c has a laptop-only smoke test with a small
model.

---

## Where the project is

**Phases 1 to 5 are complete** (2026-10-20 to 2026-10-21), each tagged
`phase-NN-complete`. **Phase 6, the belief state, is next.**

| Phase | Done | What it left |
|---|---|---|
| 1 · Baseline freeze | 2026-10-20 | The open-loop baseline, frozen as `v0.1-open-loop-baseline`: 30 runs on `llama3.3:70b`, reproduced from a clean clone |
| 2 · Repository architecture | 2026-10-20 | The baseline moved into `agentic_uav/` without changing what it does: goldens unedited, a 30-run re-flight identical |
| 3 · Flight-skill layer | 2026-10-21 | Eleven skills with contracts and structured results, a mock simulator held to the same contract; four drones flown live |
| 4 · Search-and-relay mission | 2026-10-21 | The canonical mission as data, a judge of AUV-05's six criteria, and a scripted controller that meets it on 20 of 20 seeds |
| 5 · Persistent single agent | 2026-10-21 | One rule-based agent, told only its task, choosing each next skill on events: 20 of 20 seeds and 5 of 5 troubles on the mock, four live flights |

Each phase keeps its own record in [`phases/`](phases/): objectives, the exit
criterion and whether it is actually met, deliverables, decisions taken, and the
evidence. Start at [`phases/README.md`](phases/README.md) for the status of all
21 phases. Objectives are mirrored from the vault note `AUV-22 — Phase
Objectives Checklist`; each phase also has a detail note `AUV-01` … `AUV-23`.

| Stage | Phases | State |
|---|---|---|
| 0 · Foundations | 0–1 | Phase 0 deliverable done, its exit (the one-minute explanation) untested; **Phase 1 complete** |
| 1 · Platform | 2–4 | **Complete**: Phases 2, 3 and 4 |
| 2 · One agent | 5–6 | **Phase 5 complete**; Phase 6 next |
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

That last property is the one everything from Phase 5 onward exists to remove;
Phase 5 removed it for one drone.
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
docs/         RESEARCH_PLAN · SETUP · CONTROLS · BASELINE_* · carlaair/ reference set · vega/
configs/      missions/ — the baseline's mission set as data; scenarios/ — the
              search-and-relay mission and its variants (TOML), from Phase 4
agentic_uav/  the research modules, built from Phase 2 on (see below)
baseline/     open_loop_agent.py — the baseline's command line, now a thin entry
              point over agentic_uav/; the original single file is the tag
              v0.1-open-loop-baseline
scripts/      experiment entry points: run_missions.py, the command line of
              agentic_uav/experiments/runner.py; the exit scripts of Phases 3-5,
              four_drone_skills.py, search_relay_exit.py and single_agent_exit.py
              (each --sim mock or airsim)
tools/        development tooling: audit_repo.py, fly_chat.py, record_golden.py,
              the doc generators
tests/        unit tests, and the golden tests that pin the baseline's behaviour
              (tests/golden/) — no simulator, no model
phases/       one folder per phase: objectives, exit criterion, evidence, decisions
runs/         raw run output; the directory is tracked, its contents are not
```

**`scripts/` versus `tools/`**: scripts run experiments and produce evidence;
tools maintain or explore the repository and **never appear in a result**.

`fly_chat.py` sits on that boundary and is worth explaining: it drives the
simulator and the model like a script, but records nothing, so it cannot
contribute to a result. It exists for the question a fixed mission set cannot
answer -- *what does this model do if I phrase it like THIS* -- and it plans
through the same planner and flies through `fly_plans`, the same path the
runner uses, so what it shows you transfers. Its two deliberate departures from
the study (a prompt addendum, and leaving a drone hovering when its plan never
lands) are passed in as arguments; it changes nothing in the study's code.

**Two output locations, deliberately.** `runs/agent-log.jsonl` is the raw,
git-ignored log of *every* planning call ever made on this machine, whatever
invoked it. `phases/phase-NN-*/results/` holds curated, tracked evidence for a
specific scored series. Neither replaces the other: the first is a black box
recorder, the second is the experimental record.

```powershell
python -m unittest discover tests     # no simulator or model needed
python tools\record_golden.py --check # the goldens alone, with a per-case report
python tools\audit_repo.py            # run before every commit
python tools\fly_chat.py              # interactive: ask a model, fly the answer
```

`docs/` says what the project intends; `phases/` records what it actually did,
including the attempts that failed. Measurements land in
`phases/phase-NN-*/results/`, exit-criterion proof in `evidence/`, and each
completed phase is tagged `phase-NN-complete`.

The module tree is specified in `AUV-03 — Repository Architecture`. Its shape
encodes the experimental design: policies, planners and simulators are all
interchangeable, which is what makes selecting an architecture a configuration
change rather than four separate codebases. Phase 2 built these parts of it,
by moving the baseline without changing what it does; Phase 3 added the
flight-skill layer and the mock simulator, Phase 4 the mission and its judge,
and Phase 5 the agent:

```
agentic_uav/
  core/         plain data shared by everything: positions, vehicle state,
                primitive commands and results, protocol constants, errors;
                the real and simulated clocks; geometry and the scenario;
                what an agent can sense, and the events it replans on
  simulator/    the only code that talks to a simulator: the VehicleAdapter and
                SceneAdapter protocols, the AirSim adapter, the mock adapter
                (simulated time, contacts, injectable faults), the scenario
                manager, AirSim's settings.json; the mission world (ground
                truth solved exactly from trajectories), coverage, the poller;
                an agent's sensors; faults injected in front of an adapter
  control/      the open-loop executor, the ground reference, contact
                classification, the separation monitor; navigation (the one
                place altitude becomes NED) and the eleven mission-level skills,
                each with a contract and a four-state SkillResult; routing and
                the scripted controller; the action executor (a skill on its
                own thread, watched and abortable)
  planners/     the MissionPlanner protocol: the plan schema and validation, the
                prompt, the Ollama planner and a replay planner
  agents/       the persistent agent: belief, decisions, validation, the
                event-driven loop and the rule-based policy. It reaches no
                ground truth, and a test enforces that
  experiments/  the mission runner, the agent log, provenance; team flight;
                scenarios, the evaluator (AUV-05's six criteria), and the exit
                runs of Phases 4 and 5
```

`coordination/` arrives with the team phases, from Phase 7; it is not
created empty. `tests/golden/` holds what the baseline did before any of
it moved — every AirSim call, every model request, every runner and sandbox
output — and the tests check the moved code against it.
`tests/test_adapter_contract.py` holds every adapter to the same promises:
the AirSim adapter, the mock, and, with `AUV_LIVE_AIRSIM=1`, a running
CarlaAir.

---

## Status, provenance and licensing

> **This project is under active development.** Phases 1-5 are complete and
> tagged; the module structure settled in Phase 2 and has only grown since,
> but interfaces may still change as later phases need. The Phase 1 baseline is
> frozen at `v0.1-open-loop-baseline`: flown in full on `llama3.3:70b` (block
> `v6-polled`, 30 runs) and reproduced from a clean clone. See
> [`docs/BASELINE_MISSIONS.md`](docs/BASELINE_MISSIONS.md) for the results and
> [`phases/RUN_LEDGER.md`](phases/RUN_LEDGER.md) for which blocks are valid.
>
> **Licence: MIT**, held by the Flexible & Intelligent Complex Systems (FICS)
> Research Group — see [`LICENSE`](LICENSE). This matches the licence on the
> parent repository, so the work is usable and redistributable on the same terms
> as the rest of the lab's output.

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

That is what makes the MIT licence above possible. Had the external code
remained, this repository could not have been licensed at all — the choice would
have been someone else's to make. Reimplementing from scratch is what turned
licensing from a blocker into a decision.
