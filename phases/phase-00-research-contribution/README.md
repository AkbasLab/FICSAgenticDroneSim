# Phase 0 — Define the exact research contribution

**Stage:** 0 · Foundations · **Vault note:** `AUV-01 — The Research Contribution`
**Started:** 2026-09-18 · **Completed:** deliverable done, exit criterion untested

> Decide what is being claimed, and write it down *before* touching the code —
> so the project cannot quietly become a collection of unrelated features.

---

## Objectives

- [x] **0.1** Define the central research claim
- [x] **0.2** Define the research questions — RQ1–RQ3 primary, RQ4–RQ5 secondary
- [x] **0.3** State the hypotheses H1–H5, written before the experiments run
- [x] **0.4** Set scope boundaries — no RL, no fine-tuning, no counter-UAS, no 20/100 drones
- [x] 📄 Create [`docs/RESEARCH_PLAN.md`](../../docs/RESEARCH_PLAN.md)

## Exit criterion

> Every team member can explain, in one minute, the difference between several
> drones executing static instructions, several independent agents, a
> centralized fleet controller, and a decentralized agent team.

**Met:** not yet — this is a spoken test with the team, and nobody has run it.

Those four are exactly the four experimental arms, which is why the plan uses
them as the gate: if the distinction cannot be stated crisply, everything
downstream drifts. Reference answers are in `RESEARCH_PLAN.md` §7.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Research plan | [`docs/RESEARCH_PLAN.md`](../../docs/RESEARCH_PLAN.md) | v1.0, 2026-09-18 |

## Record

### 2026-09-18 — plan written, H4 found untestable and repaired

H4 as originally stated — *"agentic reasoning will help most in ambiguous or
changing missions"* — had **no experiment attached to it**. The study runs one
fixed, unambiguous mission, and the Phase 18 factorial contained no ambiguity or
mission-change factor, so H4 could not have been confirmed or refuted by any run
in the design.

Resolved by adding a narrow mission-perturbation factor: one perturbation event
at the mission midpoint, drawn deterministically from the run seed
(`sector_added`, `zone_restricted`, `priority_raised`), applied to **arms C and
D only**, under **nominal and moderately degraded** communication only. That is
2 × 2 × 2 × 20 = 160 runs, additive to the main factorial rather than
multiplying it.

H4 is now falsifiable: the C-to-D gap in continuity retention must be *larger*
under perturbation than without it. If it is equal or smaller, H4 is refuted —
which is itself publishable.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-09-18 | The claim is about **resilience, not performance** | A plan predicting victory on every axis is unfalsifiable in practice — any result could be explained away. H1 concedes centralized control will be faster under nominal comms |
| 2026-09-18 | Keep RQ5 — how often the LLM must be overruled, and what it costs | Most work in this area omits it; reporting it is part of the contribution |
| 2026-09-18 | Factorial runs against the **mock adapter**, AirSim reserved for demonstration | 4 GB VRAM and 15.7 GB RAM. Stated openly as a methodological choice, not discovered later as a limitation |
| 2026-09-18 | Add the perturbation factor rather than drop H4 | An untestable hypothesis in a results section is worse than an absent one |

## Open questions

- The exit criterion needs a team present. Until it is run, Phase 0 is not
  formally closed even though its deliverable is complete.
- Phase 9's "controlled emergence" is defined by five design assertions with
  **no metric**. If the paper leads on that phrase, a measurement is needed —
  see `AUV-19 — Remarks and Risk Register`.
