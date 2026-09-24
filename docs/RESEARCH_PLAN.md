# Research Plan — Decentralized Agentic UAV Coordination

**Status:** Phase 0 deliverable · **Version** 1.0 · **Date** 2026-09-18
**Platform:** CarlaAir v0.1.7 (CARLA 0.9.16 + AirSim 1.8.1), Unreal Engine 4.26
**Vault reference:** `AUV-01 — The Research Contribution`

This document is written *before* any code changes. Its purpose is to stop the
project becoming a collection of unrelated features. Nothing here may be
revised after results are inspected; revisions before the main experiment runs
must be dated and recorded in the change log at the end.

---

## 1. Central research claim

> A decentralized team of persistent UAV agents that uses **local belief
> states**, **structured peer communication**, **dynamic task allocation** and
> **bounded replanning** can maintain greater **mission continuity** under
> communication degradation and agent loss than centralized planning or
> independent non-coordinating agents.

**The claim is deliberately modest.** It does not assert that the agentic
approach is always better. Under nominal communication a centralized controller
is expected to be faster and more efficient — that is H1, and we expect it to
hold. The claimed advantage is **resilience**, not performance.

A plan that predicted victory on every axis would be a worse plan, because it
would be unfalsifiable in practice: any result could be explained away.

---

## 2. Research questions

### Primary — the study must answer these

| | |
|---|---|
| **RQ1** | How do centralized, independent, deterministic decentralized and agentic decentralized UAV teams differ in mission performance under **nominal** communication? |
| **RQ2** | How do those architectures **degrade** as message latency, packet loss and network partitioning increase? |
| **RQ3** | Does dynamic task reassignment and role adaptation improve **mission continuity** after communication loss or drone failure? |

### Secondary — attempt only once the platform is stable

| | |
|---|---|
| **RQ4** | When does LLM reasoning improve decisions beyond a deterministic task-allocation protocol? |
| **RQ5** | How often must deterministic safety or fallback logic override the LLM, and what performance cost results? |

RQ5 is retained deliberately. Most work in this area omits the question of how
often the language model has to be overruled, and at what cost. Reporting it is
part of the contribution.

---

## 3. Hypotheses

Recorded **before** the final experiments run. They are permitted to be wrong;
that is the point of writing them down first.

| | Hypothesis | Primary metric |
|---|---|---|
| **H1** | Centralized control will have **lower completion time** under nominal communication. | Mission completion time |
| **H2** | Decentralized coordination will retain a **greater percentage of nominal performance** as communications degrade. | Continuity retention |
| **H3** | Dynamic task leases and reassignment will reduce **orphaned tasks** and **recovery time** after drone loss. | Recovery time |
| **H4** | *(revised — see §3.1)* Agentic reasoning will retain more mission score than deterministic decentralized coordination **when the mission changes mid-flight**, and this advantage will be larger than under a static mission. | Continuity retention under perturbation |
| **H5** | Runtime assurance will reduce safety violations but may **increase mission duration** or cause more conservative behaviour. | Safety counts; completion time |

### 3.1 H4 — the gap and its resolution

**The problem.** H4 as originally stated — *"agentic reasoning will help most in
ambiguous or changing missions"* — had **no experiment attached to it**. The
study runs one fixed, unambiguous mission (distributed search-and-relay), and
the Phase 18 factorial contains no ambiguity or mission-change factor. As
written, H4 could not be tested, confirmed or refuted by any run in the design.

**The resolution adopted here: add a narrow mission-perturbation factor.**

At the mission midpoint, inject exactly one perturbation event, drawn
deterministically from the run seed:

| Perturbation | Effect |
|---|---|
| `sector_added` | A new search sector is added to the mission |
| `zone_restricted` | A restricted zone appears over an already-assigned sector |
| `priority_raised` | One sector's priority is raised above the others |

**Scope of the addition, kept deliberately small.** This is a targeted
sub-experiment, not an expansion of the main factorial:

- Architectures **C and D only** — the comparison H4 is actually about
- Communication conditions **Nominal and Moderately degraded only**
- Perturbation **off / on**
- 20 seeds, common across cells

That is 2 × 2 × 2 × 20 = **160 runs**, roughly 40 hours at 900 s per run,
additive to the main factorial rather than multiplying it.

**H4 becomes falsifiable as:** the difference in continuity retention between
arm D and arm C is *greater* under perturbation than without it. If the
difference is equal or smaller, H4 is refuted — which is a publishable result.

> **If this addition is not made, H4 must be dropped from the paper.** An
> untestable hypothesis in a results section is worse than an absent one.

---

## 4. Experimental factors

### 4.1 Architecture — the primary factor

All four arms share the same mission, vehicle skills, scenario manager, network
model and safety guardian. They differ in **exactly one dimension**: how
coordination decisions are made.

| Arm | Name | Coordination | Isolates |
|---|---|---|---|
| **A** | Centralized fleet controller | One controller assigns all tasks from delivered state | Nominal-efficiency baseline |
| **B** | Independent agents | No negotiation between drones | Whether communication is worth anything |
| **C** | Deterministic decentralized | Contract-net protocol, **no LLM** | Whether decentralisation is worth anything |
| **D** | Agentic decentralized | Same protocol **plus** LLM policy | Whether the LLM is worth anything |

**The ordering C before D is load-bearing.** Arm C must be built and measured
before any language model touches coordination. Without that, there is no way
to separate "decentralisation helped" from "the LLM helped", and the study has
no contribution.

### 4.2 Communication condition

Levels of an independent variable — **not** claims about any real radio system.
Exact values calibrated by the Phase 17 pilots.

| Condition | Profile |
|---|---|
| **Nominal** | Low latency, no intentional packet loss, no partition |
| **Moderately degraded** | Moderate latency and jitter, ~10% independent packet loss |
| **Severely degraded** | High latency, ~30% packet loss, limited message rate |
| **Partitioned** | Two groups cannot communicate for an interval; base may be unreachable from one group |

### 4.3 Agent loss

Present / absent, injected at a seed-determined time.

### 4.4 Mission perturbation

Off / on, per §3.1. Applied only to the C–D sub-experiment.

### 4.5 Seeding

For a given seed: the same messages are lost, the same latency samples drawn,
the same targets placed, the same failure at the same simulation time.

**Seeds are common across architectures.** Comparisons are paired. Without
this, architecture differences drown in scenario variance.

---

## 5. Metrics

Defined here, implemented and tested in Phase 14–15. **No metric may be
invented after inspecting results.**

| # | Metric | Definition |
|---|---|---|
| **1** | **Mission completion** | `w1·Coverage + w2·TargetDetection + w3·SafeReturn`, with components also reported separately |
| **2** | **Completion time** | `t_complete − t_start`. Failed missions record **timeout**, never a fast completion |
| **3** | **Continuity retention** | `MissionScore(degraded) / MissionScore(nominal)` — the ratio the central claim rests on, and the metric for H2 |
| **4** | **Recovery time** | `t(replacement task accepted) − t(failure or partition)` |
| **5** | **Safety** | Collisions; separation violations; restricted-zone entries; emergency fallbacks; unsafe proposals; guardian interventions |
| **6** | **Communication overhead** | Messages; bytes; **messages per completed task**; duplicates; expired messages |

Metric 3 is the one that must be got right. It measures **capability retained**,
not raw performance — an architecture can be slower in absolute terms and still
win on this.

---

## 6. Scope boundaries

### In scope

- Simulated target detection — **not** computer vision
- Deterministic low-level flight control
- Fixed or nearly fixed operating altitude
- One canonical mission: distributed search-and-relay
- Four drones

### Explicitly excluded

| Excluded | Why |
|---|---|
| Reinforcement learning | A project in its own right; would confound attribution |
| LLM fine-tuning | Same; also makes the model non-reproducible for reviewers |
| Adversarial counter-UAS behaviour | Separate threat model, separate study |
| 20 or 100 drones | Infeasible on available hardware; adds scale effects that mask coordination effects |
| Swarming formations, target recognition, cyberattacks, human factors | Each is a study on its own. Combining them makes results harder to attribute, not richer |

**Discipline here is what makes the study finishable.** Every exclusion above
was considered and rejected on the grounds that it would make the results less
interpretable.

### Platform constraints that shape the design

Recorded because they are real and they bound what can be run:

- **4 GB VRAM.** The simulator uses 2.6–3.2 GB. Language models run on CPU
  (`num_gpu: 0`) and compete for system RAM, not video memory.
- **15.7 GB system RAM.** A 3B model fits alongside the simulator; an 8B model
  requires closing other applications; a 12B model does not fit at all.
- Consequently the factorial runs against the **mock adapter**, with AirSim
  reserved for demonstration and regression runs. This is a deliberate
  methodological choice, stated openly, not a limitation discovered later.

---

## 7. Exit criterion for Phase 0

> Every team member can explain, **in one minute**, the difference between:
> 1. several drones executing static instructions;
> 2. several independent agents;
> 3. a centralized fleet controller;
> 4. a decentralized agent team.

Those four are precisely the four experimental arms. If the distinction cannot
be stated crisply, the rest of the plan will drift.

**Reference answers:**

1. **Static instructions** — each drone runs a fixed, pre-computed sequence.
   No decisions after takeoff. Nothing observes, nothing adapts. *(This is what
   the current baseline does.)*
2. **Independent agents** — each drone observes, decides and replans on its own,
   continuously. But they do not talk to each other, so two may search the same
   sector while a third is missed. *(Arm B.)*
3. **Centralized controller** — one process holds the whole picture and assigns
   every task. Efficient when it can see and reach everyone; degrades sharply
   when it cannot. *(Arm A.)*
4. **Decentralized agent team** — each drone decides locally, but they negotiate
   through a message protocol: bidding for tasks, holding leases, detecting peer
   failure and reassigning. No single point of failure. *(Arms C and D.)*

---

## 8. Change log

| Date | Change |
|---|---|
| 2026-09-18 | v1.0 — initial document. H4 revised per §3.1 and mission-perturbation factor added to make it testable. |

---

*Phase 0 deliverable. Next: Phase 1 — freeze and document the baseline
(`AUV-02 — Baseline Freeze`).*
