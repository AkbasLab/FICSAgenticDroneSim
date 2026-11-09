# Follow-up to main_v1: DV2, the agentic agent with task-phase tools

**Status:** built and tested with scripted models; not yet run with llama.
**Disclosure:** this was designed *after* the main_v1 results were seen. It is a
separately labelled follow-up. main_v1, including D's 33% success, stays in the
paper as measured.

## Why

main_v1's agentic agent D chose `start_search` in 98.5% of 8,237 decisions and
re-flew finished sectors until its battery reserve sent it home
(`RESULTS_main_v1.md`). Its tool set had no way to say "this task is done"
except `report_target`, the tool for a detected target. Nothing stopped a
second `start_search` on a searched sector either. The scripted control used
`report_target` by convention, so the development check could not expose this.

## What DV2 changes (and nothing else)

| | D (main_v1) | DV2 |
|---|---|---|
| tools | 15 | the same 15 + `report_task_complete` |
| `start_search` on a searched sector | accepted, re-flies it | rejected as `wrong_phase`; one correction naming `report_task_complete`; then the deterministic fallback |
| bidding / searching while a finished task is unreported | accepted | rejected as `wrong_phase` the same way |
| `report_task_complete` before the sweep | n/a | rejected as `wrong_phase` ("fly the sweep first") |
| context line after a sweep | "sweep complete, completion not yet reported" | "sweep complete - next step is report_task_complete; searching it again finds nothing new" |
| coordination streak limit | only when holding no task | also while holding one |

Same model (llama3.1:8b, temperature 0), same prompts otherwise, same
allocation rules, guardian, network profiles, scenario family and exclusions.
Every `wrong_phase` rejection and every fallback is logged, so the analysis
separates completions **the model chose** from those **the fallback made**
(`analyse_factorial.py` reports both).

**Lifecycle fix (all architectures).** A drone holding a task with no new event
used to leave its loop in the air (main_v1's two 4.7 s D runs). It now
re-decides, and after 30 rounds with no progress it gives the task up (its
lease lapses, a teammate can take it) and goes home. On 36 development runs of
A, B and C this branch was never entered, so their behaviour is unchanged.

## Evidence so far (scripted models, development seeds)

| model | D | DV2 |
|---|---|---|
| **repeater** (always `start_search`, main_v1's failure) 2 drones | coverage 0.5, ~740 s | coverage 1.0, 195 s, landed |
| repeater, 4 drones | coverage 1.0, ~753 s | coverage 1.0, 113 s, landed |
| **bidder** (always `send_bid`) 2 drones | coverage 0, drones left airborne | coverage 1.0, landed |
| **scripted control** | = C | = C, completion via `report_task_complete` |

The repeater result is the important one: DV2 completes the mission *even if
the model never learns to report*, because the phase check plus fallback
catches it. So a DV2 success has to be read together with how often the model
chose the right phase itself. That is why `completions_by_model` and
`wrong_phase_fallbacks` are reported next to success.

Tests: `tests/test_dv2.py` (33 checks). Four new injected defects
(`phase_check_off`, `completion_tool_not_offered`, `airborne_exit`,
`seeds_reused_across_designs`) are all caught.

## Running it

```powershell
conda activate carlaAir
cd C:\Users\Owner\Documents\FICSAgenticDroneSim-main
$env:AGENTIC_UAV_NUM_GPU = "all"
python scripts/freeze.py                      # must say "unchanged"

# 1. development check with the real model (16 runs, ~1 h)
python scripts/run_factorial.py configs/experiments/factorial_dv2_dev.yaml
python scripts/analyse_factorial.py results/dv2_dev
#    look at: completions_by_model > 0, and success on most runs

# 2. the held-out follow-up (1,280 runs; A/B/C take minutes, DV2 most of a day)
python scripts/run_factorial.py configs/experiments/factorial_main_v2.yaml
python scripts/analyse_factorial.py results/main_v2
```

- `main_v2` uses held-out seeds 21–40. main_v1 used 1–20. The runner refuses
  a design whose seeds overlap a sealed design (`test_seal.json` for main_v1,
  `test_seal_main_v2.json` for this one).
- A, B and C are re-run on the new seeds so every comparison stays paired.
- Do not change prompts or rules after step 2 starts; the seal enforces it.
- If step 1 shows llama never chooses `report_task_complete`, report that as
  the result. Do not tune the prompt on held-out seeds.

## How to report both

1. **main_v1** as the pre-registered result: D 33%, with the transcript diagnosis.
2. **main_v2** as a disclosed follow-up on fresh seeds: "after main_v1 exposed a
   tool-set gap, we added an explicit completion tool and phase validation and
   re-evaluated on unused held-out seeds."
3. For DV2, always give the model-chosen vs fallback split. If most completions
   come from the fallback, the honest claim is that guardrails rescue a weak
   planner, not that the planner plans well.

## Where could the agentic architecture be better?

**In main_v1, nowhere.** The task is fully specified: four sectors, known
geometry, clear rules. C's rules are close to optimal by construction, so the
best an LLM can do is match them, slower. Network condition barely moved D,
which also shows the bottleneck was the agent, not communication.

**DV2 can at best approach C here.** Its purpose is to remove an artefact of
the tool design, so the comparison is about the architecture rather than a
missing tool. It should not be expected to beat C on this mission.

**Where an LLM agent could plausibly add value** are situations the rules
were not written for. Each would be a new, predeclared scenario family:

- **Operator intent in natural language mid-mission** ("prioritise the
  north-east, a hiker was last seen there"). Rules need someone to translate
  it first; an LLM agent can re-prioritise from the text.
- **Unanticipated events or new task types** (a sector reported flooded, or
  an "inspect this structure" request). The deterministic policy has no branch
  for them.
- **Free-text or ambiguous teammate reports** ("possible target, low
  confidence, near the treeline"). Rules need a fixed message schema.
- **Trade-offs without a written rule** (low battery vs. one unsearched
  sector vs. a likely target).
- **Hybrid: rules by default, LLM on exceptions.** Probably the strongest
  claim available: the guardian and deterministic policy handle routine
  steps, and the model is called only when something falls outside them.
  DV2's fallback already works this way in one direction.

Any of these needs its own development work and held-out seeds, and its
metrics fixed in advance, so it does not become a scenario tuned until D wins.
