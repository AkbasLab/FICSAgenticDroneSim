# Phase 12 exit criterion — evidence, 2026-11-05

> Each drone uses a **distinct persistent agent context** to make mission-level decisions during flight, while every action still passes through structured validation and runtime assurance.

**Met on the mock.** 5 of 5 seeds passed all four checks on both flights -- the canonical four with the pinned model deciding, the guardian and the keep-out on, with no stop and with Drone1 stopped at 60 s -- and the model was frozen across the run. Generated from `../results/llm-exit-20261105-150453-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Model | `llama3.3:70b`, digest `a6eb4748fd2990ad2952b2335a95a7f952d1a06119a0aa6a2df6cd052a93a3fa` (`configs\llm\default.toml`) |
| Options | {'temperature': 0, 'seed': 0, 'num_ctx': 8192, 'num_predict': 400}; timeout 60.0 s; one correction (12.6); calls one at a time |
| Server | Ollama 0.40.6 on Vega gpu02 (one H100), via the tunnel http://127.0.0.1:11435 |
| Team | the canonical four; Phase 9's recovery policy as each drone's protocol and procedure; the model deciding every other decision through the tools |
| Guardian and keep-out | Phase 11's limits; keep-out {'half_width_m': 5.0, 'after_s': 10.0, 'min_altitude_m': 3.0} |
| Seeds | [1, 2, 3, 4, 5], each with no stop and with Drone1 stopped at 60 s; each flight then flown again offline from its recorded replies |
| Code | commit `e06c21d` (dirty: True); `agentic_uav` digest `6f8f69c16b51c0c7` |
| Wall time | 2291.9 s |

## The checks

| Check | What it requires |
|---|---|
| distinct_contexts | every context a drone's model was given names that drone; of a teammate it holds only what that teammate said; its memory is its own last decisions |
| llm_decides | every drone still flying made mission-level decisions with its model; every fallback says why |
| guarded | nothing reached the executor unreviewed; every skill started is one an approved decision started |
| replays_exactly | flown again from its recorded replies, with no model, the flight is the same: every delivery, record, decision and trajectory knot |
| model frozen (the run) | the server held the pinned digest before the first flight and after the last |

Each is shown able to fail in `tests/test_llm_exit.py`, on a real flight's record altered to break it.

## Every seed

| Seed | distinct_contexts | llm_decides | guarded | replays_exactly |
|---|---|---|---|---|
| 1 | yes | yes | yes | yes |
| 2 | yes | yes | yes | yes |
| 3 | yes | yes | yes | yes |
| 4 | yes | yes | yes | yes |
| 5 | yes | yes | yes | yes |

Model frozen: **yes**.

## The decisions

| | |
|---|---|
| Model decisions | **690**: 689 at once, 1 after the one correction, 0 fell back |
| Procedural decisions (the rule policy's, by design) | 650 |
| Agreed with the rule policy | 659 of 690 |
| Tools chosen | continue_task 618, start_search 44, hold 22, claim_task 5, accept_task 1 |
| Model latency per call | p50 3.24 s, p95 3.55 s, max 4.03 s (691 calls) |

Where it chose otherwise than the rule policy (stage, the rule's tool → the model's):

| Stage | Rule | Model | Times |
|---|---|---|---|
| waiting | hold | hold | 22 |
| waiting | hold | claim_task | 5 |
| waiting | hold | continue_task | 3 |
| waiting | start_search | accept_task | 1 |

## Findings, by flight

| Seed, flight | Met | Ended s | Model decisions (agreed) | Fallbacks | Corrected | Guardian interventions |
|---|---|---|---|---|---|---|
| 1, no stop | yes | 199.1 | 69 (66) | 0 | 0 | none |
| 1, Drone1 stopped | yes | 309.1 | 70 (66) | 0 | 0 | none |
| 2, no stop | yes | 199.1 | 69 (66) | 0 | 0 | none |
| 2, Drone1 stopped | yes | 309.1 | 70 (67) | 0 | 0 | none |
| 3, no stop | yes | 199.1 | 69 (66) | 0 | 0 | none |
| 3, Drone1 stopped | yes | 309.1 | 71 (68) | 0 | 0 | none |
| 4, no stop | yes | 193.0 | 67 (64) | 0 | 0 | none |
| 4, Drone1 stopped | yes | 309.1 | 69 (66) | 0 | 0 | none |
| 5, no stop | yes | 193.0 | 68 (65) | 0 | 0 | none |
| 5, Drone1 stopped | yes | 308.0 | 68 (65) | 0 | 1 | none |

## Verdict

**Exit criterion: MET** on the mock -- 5 of 5 seeds, 10 flights, the model frozen. Not flown live, by the user's decision: on a real clock the model's latency matters, and decisions are not yet stamped with when their information was read -- AUV-12F's experiment.
