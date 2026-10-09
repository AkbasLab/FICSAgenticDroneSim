# Run Ledger

Every recorded run in this repo, what it was worth, and why. Update this file in the same commit as the data it describes. A session that is not valid study data says why. Nothing is deleted; a superseded session keeps its verdict. When a count changes, change it here, not in prose elsewhere.

Started 2026-10-08. Sessions before this date are listed from what is on disk under `runs/`; **verdicts marked (proposed) were written by Claude from the folder names, dates and summaries, and Arshad has not confirmed them.**

## 1. What counts as a valid run

A run is valid study data only if all of these hold. Fill in the "Check" column honestly; "unknown" is an allowed answer.

| Condition | Why it is here |
|---|---|
| Model is pinned: `model_card.is_pinned` true, exact digest recorded, temperature 0, seed recorded | Plan.docx 12.7: no silent model changes |
| Prompt and schema version frozen for the series, and named in the session | Prompts changed during the Oct 7 development runs, so those are development data |
| Every prompt and structured output saved | Plan.docx 12.7 and 18.4 |
| Flown live (or marked mock-only) | A mock result is not a live result |
| Ground reference verified: `ground_z` recorded after the drone has settled, and landing confirmed on the ground | SC found `ground_z` read while a drone was still falling made every altitude wrong by ~17-29 m |
| Collisions polled during flight, not read once after landing | SC found the landing contact overwrites earlier collisions. This repo does not poll collisions at all yet (see section 5) |
| Seed and scenario recorded | Needed to replay the run |

## 2. Run inventory

Sessions on disk under `runs/` as of 2026-10-08. Model for all of them: `llama3.1:8b` (digest `46e0c10c039e`), temperature 0, seed 17, local Ollama on this laptop.

| Session | Date | What it was | Live or mock | Verdict |
|---|---|---|---|---|
| `llm_llama31_8b_prompt_v0` | 2026-10-07 08:04 | First 4-drone LLM-policy mission, original prompt | unknown, confirm | development, prompt later changed (proposed) |
| `llm_llama31_8b_no_block_feedback` | 2026-10-07 08:06 | Ablation: guardian reasons NOT fed back to the model | unknown, confirm | development ablation, not final (proposed) |
| `llm_llama31_8b_block_feedback` | 2026-10-07 08:23 | Ablation: guardian reasons fed back on retry | unknown, confirm | development ablation, not final (proposed) |
| `probe_llama31_8b` | 2026-10-07 10:22 | 100-situation waypoint probe (old flat schema, my own generator) | n/a (no simulator) | diagnostic; numbers 17% / 33% / 98% / 100% are from the OLD schema and must be re-run (proposed) |
| `llm_llama31_8b_schema_v2` | 2026-10-07 12:50 | First mission under the Phase 12.3 schema | unknown, confirm | development (proposed) |
| `llm_llama31_8b_15tools` | 2026-10-07 13:37 | Full 15-tool set, first mission | unknown, confirm | development; first-attempt `request_help` field omissions seen (proposed) |
| `llm_llama31_8b_15tools_v2` | 2026-10-07 13:42 | Full 15-tool set, second mission: 0% fallback over 10 decisions, 5 corrected, 1 guardian block (`separation`) | unknown, confirm | best candidate for a "frozen" series, but not yet declared one (proposed) |

**Valid study data so far: none.** No session has had a frozen prompt/schema declared, and the ground-reference and collision checks in section 1 have not been run. This is expected for development data, and it is the honest starting count.

## 3. Runs that are not in `runs/` but exist in the history

These are recorded in `CURRENT_CONTEXT.md` and `PHASE_1-10_BUILD_PLAN.md` but have no folder here. List them so the count is not lost.

| What | Date | Outcome | Verdict |
|---|---|---|---|
| Phase 3 live skills flight, 4 drones | 2026-09-2x | 16/16 skill calls succeeded | capability demonstration, not scored |
| Phase 4 canonical mission, 4 drones, live | 2026-10-01 | all 4 flew, found both targets, stayed separated, landed | capability demonstration |
| Phase 5 solo agent, live | 2026-09/10 | works; unexplained position artifact noted | open, see section 5 |
| 4-drone concurrent live run (Phase 8 era) | 2026-10-02 | hung over an hour; infinite loop in `search_policy.py` fixed; solo flight OK afterwards, 4-drone concurrent still does not find targets | diagnostic, cause of the remaining gap unresolved |

Fill in exact dates and folders when Arshad confirms them.

### 2026-10-08 live checks (output pasted in chat, no `runs/` folder yet)

| Check | Result | Verdict |
|---|---|---|
| `scripts/check_ground_ref.py`, drone at rest after sim load | first raw z 29.245, settled z 29.245, waited 1.00 s | ground reference correct at rest; guard changed nothing |
| `run_persistent_agent.py --airsim --sector A`, solo | T1 found, returned home within ~0.3 m, landed. BUT: final position read z = -11.8 m, landing step took ~64 s and 21% battery, one `skill_failed` at step 3 | anomaly, **not reproduced** by the trace below; cause unknown. Drone was on the ground visually |
| `scripts/trace_landing.py`, 0.5 s samples through landing + 10 s after disarm | `land()` took 7.1 s; est_z and true_z agree throughout and end at -0.01; no drift after disarm. Collision flag true at t=0 and at touchdown (`SM_seaM`), false otherwise; est_z rose ~1.3 m in the first second of the descent before falling | clean landing. Matches SC's note about a wrong-way vertical excursion |

| `runs/probe_llama31_8b_schema_v2`, 100 seeded situations (seed 17), llama3.1:8b digest 46e0c10c039e, temp 0, CPU, ~1 h, current 12.3 schema + 15-tool set | none 17% legal; context 98%; repair 15% raw, 100% flown legal, 85% needed repair at mean 5.0 m; guardian-reason feedback: 83 illegal first proposals, legal on retry only 8%, same point again 61%; fallback 0% everywhere; mean confidence 0.8 for legal AND illegal | diagnostic series under the new schema. Replaces the old-schema numbers for citation. Not yet "valid study data" (no frozen-series declaration) |

| `runs/dynamic_zone_mock_pilot`, `scripts/run_dynamic_zone_study.py`, 4 conditions x 3 repeats, 4 agents, deterministic policy, kinematic mock (no simulator, no LLM) | static: 0 interventions of 82 commands. appear / appear_expire: 1 intervention of 83 (one steer-out, Drone1), ~15 telemetry samples (~3 s at 5 Hz) inside the active zone before the guardian caught it. drift: 3 interventions of 83, 1 steer-out, ~17-18 samples (~3.5 s) inside. Targets 2/2 and every drone home in all 12 runs; coverage 91% static vs 90% dynamic (both under the scenario's 95% requirement, so no run passes overall) | pilot, MOCK ONLY. The mock is deterministic: all 3 repeats per condition are identical (mission 25.2 s in every run), so the repeats add no information. appear and appear_expire are identical because the policy never waits for a zone to expire. Steer-out distance and mission-time cost were NOT recorded |

| `runs/dynamic_zone_mock_pilot_v2` (first both-modes series, monitor off/on) | 2 of 9 monitor-on runs and 0 of 12 monitor-off scored `home=False` | **superseded by v3**. Cause was a scorer artifact: the recorder's last sample could be 0.2 s stale (~3 m at 15 m/s) and read an already-landed drone as not home. Kept per the no-deletion rule; do not cite |
| `runs/dynamic_zone_mock_pilot_v3` (same, after one extra recorder sample before stop) | 21 of 21 runs home. static: 0 of 82 interventions. appear (cmd and tick) / appear_expire: 1 of 83, steer-out 8.6 m, 3.0 s exposure, identical in both modes. drift cmd: 3 of 83, 4.0 m, 3.6 s exposure, 25.2 s. drift tick: 7 of 91, 19.6 m, 2.4-2.6 s exposure, 26.2 s, 4 interrupts | valid MOCK pilot, deterministic policy. Repeats are identical so effective n=1 per cell. The per-tick monitor covers flight legs only (no change in `appear`, where the drone was in a non-flight step) |
| `runs/dynamic_zone_llm_llama31_8b_appear` (LLM arm, llama3.1:8b digest 46e0c10c039e, monitor on, zone at 60 s) | 6 model decisions, **5 timeouts (83% fallback)**; 83 guardian commands, 0 interventions, 0 s exposure; mission 124 s | **INVALID for any LLM claim**. Four agents share one Ollama process at ~11 s/call, so they exceed the 30 s budget and fall back to the deterministic policy; two drones made no model decisions. The zone appeared after the work was done. Kept as a record of why the LLM arm needs a different design (see GMB_DYNAMIC_BOUNDARIES.md) |

| `runs/probe_llama31_8b_dynamic_zones`, 100 seeded situations (seed 17, same as `probe_llama31_8b_schema_v2`), llama3.1:8b digest 46e0c10c039e, temp 0, CPU, scenario `search_relay_dynamic_001` (zones DZ_A from 10 s, DZ_D from 60 s). Laptop slept during the run; 0 fallbacks/timeouts | none 16% legal (static 17%); context 92% (98%); repair 14% raw, 100% flown legal, 86% needed repair at mean 5.1 m (85%, 5.0); feedback retry legal 8% (8%), same point again 65% (61%). On the model's own first proposal: separation 83 (same as static) plus restricted_zones 17. Replay: 23 of 100 situations start inside an active zone, mean steer-out 6.3 m, max 9.5 m | diagnostic series under dynamic zones. Compared like-for-like with the static series (the `none` and `feedback`-first answers are identical inputs; `context`/`repair` prompts change with the zones). The 98%->92% drop in `context` is 5 zone cases (model chose a sector centre inside an active zone) + 3 separation cases; the prompt text was not inspected. Zone placement makes the 23% inside-zone share by construction. Not yet declared a frozen series |

Open: the -11.8 m / 64 s landing from the full mission. Next step is to repeat the full mission a few times and log `land()` duration and the post-landing position each time, to see whether it recurs.

## 4. Conditions of the data

Recorded because a run's conditions are part of the result.

- Model: `llama3.1:8b`, pinned, temperature 0, seed 17
- Host: Arshad's laptop, one local Ollama process serving all four agents
- Latency: about 11 s per model call; queueing on one process can exceed a 30 s budget
- Simulator: CarlaAir (confirm version and map before the first study run)
- For comparison: the SC branch runs `llama3.3:70b` on an H100 (ERAU Vega) at about 0.7-1.8 s per plan. Results from the 8B here should say so.

## 5. Open measurement questions

Each one blocks a claim until resolved. Taken from reading the SC run ledger on 2026-10-08 and auditing `fics_drone/simulator/airsim_adapter.py`.

1. **`ground_z` timing.** `connect_and_takeoff()` records `ground_z` from the drone's position at the moment it is called, with no check that the drone has finished settling. If it is called while the drone is still falling, every altitude after it is wrong. Possible link to the Phase 5 position artifact. Unverified.
2. **No collision polling.** Nothing in the repo reads collisions. Separation is computed from positions, which is fine for the guardian, but "collisions" (Plan.docx Phase 15, primary metric 5) cannot be reported yet. If added, poll during flight, because a single read after landing can only see the landing contact.
3. **Declared roster vs runtime spawn.** Live runs use drones declared in `settings.json`. SC found that declared drones can fall onto each other at start, and that drones added at runtime with `simAddVehicle` place cleanly. Untested here; possibly related to the 4-drone live gap.
4. **Model size.** All LLM numbers are from an 8B model. State this wherever they are cited.

## 6. Keeping this honest
- Update in the same commit as the data it describes.
- A session that is not valid study data says why.
- Nothing is deleted.
- Do not change a verdict in place; add a dated line under "Corrections".

### Corrections
(none yet)
