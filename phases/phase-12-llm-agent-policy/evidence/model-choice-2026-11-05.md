# Phase 12 model choice — evidence, 2026-11-05

The same recorded decisions, put to each candidate model, one at a time, on one H100 (Vega gpu02, Ollama 0.40.6), with the manifest's options. Generated from `../results/llm-bench-*`; nothing transcribed.

## bench1 -- the first menu

`llm-bench-20261105-125057-bench1.jsonl`: 200 decisions sampled evenly from `llm-bench-requests-20261105-104205.jsonl`.

| Model | Digest | Valid at once | Usable after one correction | Fallback | Agreed with the rule | p50 s | p95 s | Actions chosen |
|---|---|---|---|---|---|---|---|---|
| llama3.3:70b | `a6eb4748fd29` | 193/200 | 200/200 | 0/200 | 87/200 | 3.441 | 3.671 | continue_task 73, decline_task 4, go_to_waypoint 1, hold 3, start_search 119 |
| llama3.1:8b | `46e0c10c039e` | 193/200 | 200/200 | 0/200 | 165/200 | 0.597 | 0.702 | continue_task 187, release_task 13 |
| llama3.2:3b | `a80c4f17acd5` | 196/200 | 196/200 | 4/200 | 0/200 | 0.356 | 0.377 | accept_task 189, hold 4, start_search 3 |

## bench2 -- the menu corrected

`llm-bench-20261105-131132-bench2.jsonl`: 200 decisions sampled evenly from `llm-bench-requests-20261105-131044.jsonl`.

| Model | Digest | Valid at once | Usable after one correction | Fallback | Agreed with the rule | p50 s | p95 s | Actions chosen |
|---|---|---|---|---|---|---|---|---|
| llama3.3:70b | `a6eb4748fd29` | 196/200 | 200/200 | 0/200 | 192/200 | 3.225 | 3.607 | continue_task 178, decline_task 4, hold 4, start_search 14 |
| llama3.1:8b | `46e0c10c039e` | 196/200 | 200/200 | 0/200 | 90/200 | 0.528 | 0.646 | continue_task 98, go_to_waypoint 14, release_task 88 |
| llama3.2:3b | `a80c4f17acd5` | 194/200 | 194/200 | 6/200 | 8/200 | 0.353 | 0.38 | accept_task 6, decline_task 5, go_to_waypoint 25, hold 55, release_task 95, start_search 8 |

## What bench1 showed

The first menu offered `start_search` and `accept_task` even while the drone was already doing that, and did not say what was flying. Read as "keep searching", the 70B chose `start_search` 105 times of 200 while already searching, the 3B `accept_task` 175 times -- each, executed, would have restarted the search from its first lane; the 8B chose `continue_task` on arriving at its sector, with nothing flying. The menu was corrected (what is flying is said; no restart, no idle offered) and the decisions re-collected; bench1 is kept as found: how the actions are offered steers what models choose.

## The choice

**llama3.3:70b**, the user's choice, on bench2's evidence: every reply usable, 192 of 200 the rule's own choice and the rest reasonable, at 3.2 s a decision. The 8B, six times faster, gave its task back in 88 of 200 decisions -- under Phase 11's finding that a give-back costs the rule team about 100 s, ruinous. The 3B failed six times outright. Pinned by its digest in `configs/llm/default.toml`.

The quality-against-latency trade this measures is its own research part: vault note AUV-12F.
