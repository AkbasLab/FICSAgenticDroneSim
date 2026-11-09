# Exclusions and replications — Phase 18, version 1

**Pre-registered 2026-11-09 (Phase 18, AUV-16 18.4's exit), before any held-out seed was flown.**

AUV-22, Phase 18's exit: "every final cell has sufficient valid replications, and exclusions rest on **predeclared
technical criteria** rather than unfavourable outcomes." This file declares, before a single held-out run exists,
which runs may be set aside, how a set-aside run is replaced, and when a cell is complete. Nothing here looks at a
mission's outcome. `scripts/factorial_exit.py` applies it exactly; it is frozen with the code (`configs/frozen.toml`).

## The design it applies to

Architectures A, B, C, D × {2 drones: `nominal`, `moderate`; 4 drones: `nominal`, `moderate`, `partitioned`,
`severe`} (the levels `docs/CONDITIONS.md` chose) × {`none`, `drone1-at-60s`}: **48 cells**. Each cell flies the
**20 test seeds** of `configs/seeds/heldout.toml`, in order. A, B and C fly on the mock; D on the mock against the
pinned `llama3.3:70b` (`configs/llm/default.toml`) served by Ollama on a Vega GPU node, one request at a time.

## A run is excluded only for one of these technical reasons

| | Reason | How it is seen |
|---|---|---|
| **X1** | **The run crashed** | its manifest says `crashed` (with the error and traceback), or it has no manifest after its batch ended |
| **X2** | **The model did not answer** — a timeout or the server gone, not an answer that could not be used | any decision of the run recorded as a `fallback` whose problem begins `no reply:` |
| **X3** | **The model ran off the GPU** | the batch job's Ollama log has no `inference compute … library=CUDA` line, or has `library=cpu` |
| **X4** | **Not the frozen code** | the manifest says `dirty: true`, or its package digest differs from the frozen code's |
| **X5** | **Not the pinned model** | the manifest's model digest or options differ from `configs/llm/default.toml` |

**Never a reason:** the mission not met; a long or censored completion time; a collision, a separation violation,
a guardian intervention or refusal; an answer from the model that could not be used and fell back to the rule (that
is D's own behaviour: it counts); any metric's value; anything seen in a timeline.

An excluded run is **kept on disk and reported** with its reason; it is only left out of the cell's analysis.

## Replacement — keeping the comparison paired

The architectures are compared seed by seed (common random numbers, AUV-16 18.1). So when a run is excluded, **its
seed is set aside in that cell for every architecture**, and the cell's **next unused reserve seed**, in the order
of `configs/seeds/heldout.toml`, is flown by all four architectures in that cell. A reserve run excluded in turn is
replaced the same way, by the next reserve.

## Sufficient replications

A cell is **complete** with **20 valid paired seeds**: 20 seeds each with a valid run of A, B, C and D. If the ten
reserves are used up before that, the cell is reported with the valid paired seeds it has, **flagged**, and never
filled from outside the held-out list.

## Checks that are reported, not exclusions

* **Model variability** for each D batch (`scripts/model_variability.py`, 100 recorded decisions asked again):
  the agreement is reported. Below 95 %, Phase 18's record flags it for Phase 19; no run is excluded for it.
* **Requests accounted for:** each D batch's requests in its records against the `POST /api/chat` lines in its
  server logs. A mismatch is investigated and reported.

## Procedure that keeps X2 and X3 rare (not a criterion)

Before each D batch or resumption: find idle GPUs (`ssh gpuNN nvidia-smi`); read Ollama's libraries once from scratch
so its GPU discovery finishes; start the server; check its `inference compute` line says CUDA; and send **one
warm-up request** with the pinned model and context, so the model is on the GPU before the batch's first decision.
(Phase 17's first pilot, run 0022: the first decision timed out at 60 s while the model was still loading — a cold
start; found while writing this file.)

## Versions

| Version | Date | What |
|---|---|---|
| 1 | 2026-11-09 | The criteria, the replacement rule and the completeness rule, before any held-out run (Phase 18) |
