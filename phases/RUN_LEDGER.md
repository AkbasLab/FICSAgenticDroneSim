# Run Ledger

Every recorded run in this repo, what it was worth, and why. Update this file in the same commit as the data it describes. A session that is not valid study data says why. Nothing is deleted; a superseded session keeps its verdict. When a count changes, change it here, not in prose elsewhere.

Started 2026-10-08. Sessions before this date are listed from what is on disk under `runs/`; **verdicts marked (proposed) were written by Claude from the folder names, dates and summaries, and the operator has not confirmed them.**

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

Fill in exact dates and folders when the operator confirms them.

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

### Landing investigation, night of 2026-10-08 (run unattended overnight)

| Check | Result | Verdict |
|---|---|---|
| The operator's second full solo mission (`run_persistent_agent.py --airsim --sector A`) | landing step 64.0 s (154.2 to 218.2), final height -11.8 m again, same as the first | reproduced **by the operator**, deterministic on that side |
| The operator's `trace_landing.py --out-and-back 40` and `--hover-s 150`, then `--hover-s 60` | both read -11 to -12 (only the summary was relayed; the trace rows were not pasted). He also reports the drone starts on beach sand and ends at the same spot, and that after a bad landing a manual take-off is very slow, "as if from underground" | reported, not independently verified. Consistent with the drone actually ending ~12 m below the surface |
| Claude, fresh sim, `trace_landing.py --stop-above 0.3` (no `landAsync`, no disarm) | settles at 0.01-0.07 m, no sinking | clean |
| Claude, fresh sim, plain `trace_landing.py` | `land()` 7.0 s, ends 0.00 m, est_z = true_z throughout | clean |
| Claude, `--hover-s 60` | 6.1 s, ends 0.00 m | clean |
| Claude, 24 CPU cores saturated, `--hover-s 10`, fresh sim | 6.2 s, ends -0.01 m | clean: CPU load is not the trigger |
| Claude, full solo mission, fresh sim, default cruise height | different failure: the first lane overshoots to (41.2, 20.0, 8.7) and the drone collides with `SM_Awning41`; return_home and the 30 s legs time out; landing on the awning took 64 s. Landing there also read high, not -11.8 | **separate finding**: obstacles at the east edge of Sector A in Town10HD. Reproduced twice here; the operator's missions did not hit it (his lane ended at (40.0, 20.1)) |
| Claude, same mission at `--cruise-height 12` | lane clears the awning, then another 30 s timeout near (39.8, 29.2); return_home timed out at (3.3, 2.2); landing was clean (8.8 s, final height -0.0) | more obstacles at x ~ 40; altitude alone does not fix the scenario geometry |

**Correction to the earlier "not reproduced" note above:** the -11.8 m / 64 s landing *was* reproduced by the operator (twice in missions, and in trace variants). What Claude could not do is reproduce it on this machine in six landings across four fresh-sim setups. Whatever triggers it is something about the operator's own sessions that the fresh-sim runs did not recreate. Ruled out: CPU load, hovering time, the `landAsync`/disarm stage in isolation (clean here), horizontal drift.

**What was done about it:** `AirSimVehicleAdapter.land()` now checks its own final height and raises if the drone ends more than 1.5 m from the ground reference (`LAND_END_TOLERANCE_M`), so the skill returns FAILED with the height in the error instead of reporting a quiet success. This makes the anomaly impossible to miss; it does not explain it. Landing-based safety numbers still must not be cited.

| `runs/probe_llama31_8b_dynamic_zones_shown`, same 100 situations/seed/model/scenario as `probe_llama31_8b_dynamic_zones`, but `--show-zones` (prompt lists the zones active at decision time, current position). 0 fallbacks | none 19% legal (blind-dynamic 16%, static 17%); context 93% (92%, 98%); repair 100% flown legal at mean 4.8 m (5.1, 5.0); feedback retry legal 11% (8%), same point again 54% (65%). First-proposal failures: separation 73 (83), restricted_zones **25 (17)** | diagnostic. Telling the model about zones did not reduce zone violations (rose 17 to 25); separation violations fell 83 to 73. Single seed and one 8B model, so the changes are within what noise could plausibly produce; no mechanism tested. Not a frozen series |

### Root cause of the -11.8 m landing, 2026-10-09 (found live with the operator watching)

**Noclip.** Pressing P in the CarlaAir window toggles noclip: nothing collides, including the ground. Evidence: (1) a hover-60 trace on a fresh sim sank at a constant **0.20 m/s with `hit=False` throughout, from 5.6 s to -11.79 m at 64 s** (that is `landAsync`'s descent rate times its 60 s timeout, 0.2 x 60 = 12 m); (2) the operator had pressed P in that session, and said so ("i think it happens when i press P ... i'm not sure u did that when u ran tests"); (3) Claude never pressed P, and all of Claude's earlier landings were clean; (4) with noclip on, a *disarmed* drone free-falls (-1 m at 4.6 s to -47 m at 10 s, speed 8.6 m/s); (5) the operator's missions skip the `SM_Awning41` collision that stopped Claude's, because noclip lets him fly through it. This corrects the earlier "cause unknown" entries above: the anomaly was caused by the noclip toggle, not by flight time, CPU load or horizontal drift.

**Fix:** `AirSimVehicleAdapter.land()` no longer relies on contact to stop it. After the slow approach, if the drone is within 1.0 m of the ground reference it probes at most 0.5 m below it at 0.5 m/s looking for a new collision timestamp; contact means disarm, no contact means noclip, so it returns to the reference, holds and stays armed (`adapter.landing_note` says so). If the drone is clearly above the reference (holding on an awning) it still uses `landAsync`. Verified live in both modes: **normal** 4.9 s, contact with `SM_seaM`, rests at -0.01 m; **noclip** (P pressed) trace 12.1 s, ends -0.03 m and holds armed with the landing note; **full solo mission under noclip**: T1 found, home at (-0.2, 0.1), landing 12.0 s (153.2 to 165.2 s), final height -0.0 m, versus 64 s and -11.8 m before the fix. Known limit: under noclip the armed hold lasts only while a script keeps commanding the drone; after the script exits the sim lets it fall out of the world (measured 194 m below the map at 8 m/s). It does not change a run's result. **Record the noclip state of every live run**: a run with P on and a run with P off are different experimental conditions (collisions on versus off). 330 tests pass.

**Do we still need noclip? (2026-10-09, tested)** Fresh sim, noclip OFF, full solo mission on a temporary scenario with Sector A pulled in to x 20..36, y 20..36 (file not kept). The awning at x ~ 41 is out of the route and the first two lanes completed, but the drone then stopped at (35.8, 29.1) for a 30 s timeout (solid object near x 36-40, y 29-30), returned home, never found T1 (`target_found: None`); the first search leg also hit a 30 s timeout at step 3, as in noclip runs. The new landing worked with noclip off (4.7 s, final height -0.0 m). Verdict: noclip is no longer needed for the landing, but Sector A as laid out cannot be completed with collisions on; fixing that needs either a clear area of the map (a survey of obstacles, a team decision) or a statement in the paper that collisions were not modelled. Open question for Taner/Akbas.

Open: the -11.8 m / 64 s landing from the full mission. Next step is to repeat the full mission a few times and log `land()` duration and the post-landing position each time, to see whether it recurs.

### 2026-10-28 live check of the migrated failure-recovery script (no runs/ folder)

- Ran `scripts/run_failure_recovery.py --airsim` against CarlaAir v0.1.7 (four drones, one slot, per-user ports). The `--airsim` path is not routed through the experiment runner, so it wrote no run folder.
- Result class matched the pre-migration script: 2 of 4 sectors searched in both. The mock run of the same scenario covers 4 of 4, so the live sim is slower and drains batteries faster.
- Noclip state for this run was not recorded, so it cannot be compared with the noclip runs above.
- Runs made before the clock fix (the 5 s and 8 s Ollama runs) were scored on the telemetry clock, which starts about 3 s before the agents mission clock, and keep their old numbers.
- The Ollama tag llama3.1:latest floats; the model used had digest 46e0c10c039e. Report the digest, not the tag.

### 2026-11-02 live runs of the zone monitor and sighting confirmation (no runs/ folder)

Not study data: single runs, a moved target and a zone that appears when the drone nears it. They show whether the pieces work under real physics, nothing more.

- **Set-up.** CarlaAir v0.1.7, Town10HD, one slot. A solo Drone1 agent with the deterministic policy (no model), flown by `~/live_zone_smoke.py` through `AirSimVehicleAdapter` pointed at the sim's only vehicle, `SimpleFlight`. The script and the results (`~/live_smoke_cal.json`, `_z2.json`, `_z3.json`) sit on the Heidi machine, outside git; the Heidi proof-of-concept expires 2026-11-30.
- **cal: no dynamic zone, T1 at (30, 30).** Found T1 in 166 s with 55% battery used. First slow near T1 at about 121 s (the mock gets there in about 5 s). The hover jitters 1-2 m and the speed never settles below about 0.5 m/s. Noclip state was not recorded; the drone flew through x 36-40, y 29-30, which the 2026-10-09 test found solid, so noclip was probably on.
- **Noclip on, after cal.** The drone fell through the ground once it had landed and was disarmed. The next takeoff failed at the ground-settle check, and a sim reset put it straight back into the fall. After noclip was turned off (P) the drone rests at ground level (z about 29.24 in the sim's frame) and takeoff works. This matches the 2026-10-09 root cause.
- **z1: noclip off, T1 at (30, 30).** Pinned at (41.4, 20.0) from about 54 s to the end (203 s), against the awning near x 41 on Sector A's first lane. Never got near T1; every later skill failed. Same blocker as 2026-10-09: Sector A cannot be completed with collisions on.
- **z2: noclip off, target moved to (28, 20).** That spot is on a lane the drone had just flown freely. A 16 m zone box around it switched on when the drone first came within 4.5 m, for 12 s. It arrived mid-leg, before the target was sensed (an agent only senses after a leg ends). Trace: `zone_interrupt`, `exit_zone` steer-out to (17.0, 20.3), waited, resumed after the zone expired at 52 s, found T1 (closest 0.17 m). About 2.0 s inside the zone. The confirm flow did not run.
- **z3: as z2, but the zone switched on 0.15 s after detection, so it lands inside the 2 s report hold.** Trace: `target_detected`, `sighting_blocked(T1, clears=46.8s)`, `confirm_target`, `exit_zone` steer-out, `sighting_confirmed(T1)`, `return_home`, `land`. About 2.5 s inside the zone, 80 s run, 74% battery left, closest 0.1 m, then 7 s within 3.1 m of the target. The zone was triggered by the drone's own detection, so say so wherever this is cited.
- **Still untested live:** a drifting zone, a zone that never expires, two or more drones (the confirmer choice), and a model in the policy slot.

### 2026-11-02 model probe of confirm_target (prompt level, no sim, no `runs/` folder)

Not a mission run: the real prompt, menu and parser were fed to the real model for a drone that has finished its own sector while a blocked sighting waits, and the answer was parsed. Scripts `~/model_confirm_probe.py`, `~/model_confirm_probe2.py`, `~/model_probe_where.py` and results `~/model_confirm_probe*.json` sit on the Heidi machine, outside git.

- **Model.** `llama3.1:latest` through Ollama on the Heidi machine (8B, digest 46e0c10c039e), temperature 0.5, seeds 1-8. Prompt as built by `context_builder.py`.
- **Scenarios.** A: the code would send this drone, zone clears in 4 s. B: the code would send Drone1 (next to the target), 4 s. C: Drone1, 40 s. D: nothing waiting, so `confirm_target` is not on the menu.
- **As built (probe 1, 25 answers).** `confirm_target` was never chosen. `go_to_waypoint` every time, including D. Every answer parsed. In A, 2 of 3 re-sampled answers flew to the sighting's coordinates (28, 20); in B 1 of 3; the rest copied Drone1's position (30, 25), as did all of D.
- **Clearer wording (probe 2, 48 answers, wording tuned after probe 1).** V1 put `confirm_target` first in the options and added "to confirm one of these, choose confirm_target; flying there with go_to_waypoint does not confirm it". V2 added a hint on when to take it. `confirm_target` was still never chosen. `go_to_waypoint` to the sighting's coordinates rose to 5-6 of 8 (V1) and 7-8 of 8 (V2).
- **Reading.** The model understands there is something to go and do at the sighting, and keeps using `go_to_waypoint` for it. That flight has no wait for the zone, no dwell and no TARGET_FOUND, so the sighting would stay unconfirmed. This is one 8B model; the 70B has not been tried. Nothing in the repo was changed for the wording.

### 2026-11-02 model probe of confirm_target with Mistral Small 24B (prompt level, sim running, no `runs/` folder)

Same probe as the Llama 8B one above, same prompts and scenarios A-C, run with `mistral-small:24b` through Ollama on the Heidi machine (ID 8039dd90c113), temperature 0.5, seeds 1-8, while CarlaAir was running. Script `~/model_confirm_probe3.py`, results `~/model_confirm_probe_mistral-small_24b.json`, outside git. Chosen over larger or other models because it is not a Chinese-developed model (a project preference) and fits next to the sim.

- **Chose `confirm_target`:** as built (V0) 23 of 24 (A 8, B 7, C 8); with the clearer wording V1 19 of 24 (A 7, B 6, C 6); with V1 plus the hint V2 22 of 24 (A 8, B 7, C 7). 64 of 72 overall. Every other answer was `go_to_waypoint`, and none of those flew to the sighting. All 72 answers parsed.
- **It does not weigh who should go.** B (a teammate is right next to the target) and C (the zone takes 40 s to clear) got `confirm_target` almost as often as A (the code would send this drone): 20 of 24 and 21 of 24 against 23 of 24. Whether taking it every time is good is not measured here; a second drone going there is blocked by the guardian's separation rule, and a 40 s wait is allowed up to 45 s.
- **Wording.** The as-built wording worked, so nothing in the repo was changed for it. V1, the one I tuned after the Llama result, was slightly worse than the original.
- **GPU.** Peak 20650 MiB of 23034 MiB with the sim (about 3.5 GB) and Mistral loaded together, so they fit with about 2.4 GB spare.
- **Limits.** One model, one temperature, 8 seeds a scenario, a single hand-built situation. It says a 24B model uses the tool where an 8B one never did; it does not say the model decides well. Not comparable with the SC branch's 70B. Vega's 70B is still untried.

### 2026-11-02 live run of the real scenario at a cruise height chosen from the map (no `runs/` folder)

Not study data: one run, a zone set off by the drone's own detection, no model. It shows the real scenario can now be flown with collisions on, and that the confirm flow works there.

- **Route check before flying.** CARLA ray casts (exact geometry) along Sector A's diagonal transit, its four lanes (each extended 2 m, because the real drone overshoots a waypoint) and the way home, at cruise heights from 6 to 16 m. Frame, measured by placing the drone at five known points: CARLA x, y = drone-local x, y + (-172.2, 183.86), no rotation; CARLA z = 27.45 minus the sim's z; ground at CARLA z -1.8. Results: at 7 to 9 m a row of awnings at x 41.4 to 42 blocks the east end of every lane, and the first hit on lane y=20 is at (41.5, 20.0), where the pinned run above stopped. A lamp pole at (29.6, 30.4), 0.4 m from T1, blocks the way home from 8.5 to 10 m. 11 m and above is clear. 6 m is clear on paper only: the awnings start 7.0 m above ground and the drone floats 0.5 to 1.9 m above its command (it reached 13.9 m at a command of 12). An earlier check against object bounding boxes was useless (aggregate foliage actors flagged every height) and was replaced by the ray casts.
- **Set-up.** Fresh sim, collisions on (noclip off, inferred from the drone resting on the ground before and after; the sim cannot report it). Solo Drone1, deterministic policy, vehicle `SimpleFlight`, cruise height 12 m, T1 at its real position (30, 30). The lab's appear box (24-40 by 24-40) switched on 0.15 s after the agent sensed the target, for 12 s, so it lands inside the report hold.
- **Result (z4).** `target_detected`, `sighting_blocked(T1, clears=148.6s)`, `confirm_target`, `exit_zone` steer-out south to (33.4, 21.0), `sighting_confirmed(T1)`, `return_home`, `land`. About 2.25 s inside the zone (9 samples), 187 s in all with 38% battery left, closest approach 1.4 m, then about 10 s within 2.5 to 3.9 m of T1 for the confirming dwell. The drone passed the awning row without touching it.
- **Limits.** One run. The zone was triggered by the drone's detection, not scheduled. Only the appear shape was flown; a drifting zone, a zone that never leaves, two or more drones and a model in the policy slot are still untested live.

### 2026-11-02 live repeats of the real scenario, and the drifting zone that exposed two live-only problems (no `runs/` folder)

Not study data: single solo drone, deterministic policy, no model, zone switched on by the drone's own detection (`--trigger-on detect`, 12 s window, cruise height 12 m, collisions on). Result files are `live_smoke_<tag>.json` on Heidi, copied to the laptop backup. Each tag was one flight.

| Runs | Zone | Adapter / exit rule | Target confirmed | Time inside zone | Wall time | Battery left |
|---|---|---|---|---|---|---|
| r1-r3 | none (control) | old / old | 3 of 3 found | 0 | 113-117 s | 61-62% |
| z4-z7 | appears at the target (lab box) | old / old | 4 of 4 | 2.25 s each | 140-187 s | 38-53% |
| d1-d5 | drifts west over the target (lab drift box) | old / old | 2 of 5 (d1, d5) | 3.0-4.0 s | 177-243 s | 19-41% |
| d6-d8 | same drift | 2 m/s short moves / exit across the drift | 2 of 3 | 1.0-1.5 s | 87-96 s | 68-71% |
| d9-d11 | same drift | 1 m/s short moves / exit across the drift | 3 of 3 | 1.0 s each | 102-109 s | 64-66% |

- **What the first drifting runs showed (d2-d4).** The steer-out was a 3 m move west, the way the zone was heading. The live drone does not start a position move of 2 to 3 m at all (probe from a hover: 1 m is inside the 1 m tolerance, 2 m and 3 m sat still for 20 s, 5 m and 8 m arrived in about 7 s). So it sat while the zone passed over it, the 30 s timeout fired, the confirm retried twice more (30 s each) and gave up. Event log of d5 (timeouts and positions) is what pinned this down; d4's guardian log showed every later command approved, so the failure was in flight, not the guardian.
- **Two changes (commits `8427ab5`, `ba6ebe9`).** Moves under 4.5 m go out as a velocity command; the guardian's exit point must stay outside every zone until the drone has arrived plus 2 s (new test, suite 385 passed).
- **d6 failed for a third reason.** At 2 m/s the drone coasted 1.0 to 1.3 m after a short hop, so the 3 s report hold failed ("drifted more than 1.0 m"). Coast measured at 2, 1.5 and 1 m/s: 1.0-1.3, 0.75-1.0 and 0.5-0.6 m. 1 m/s was chosen and d9-d11 followed.
- **Condition change to remember.** Short search hops (3.3 m) used to stall, so runs before `8427ab5` took about twice as long (T1 reached near 120 s vs 50-73 s). Do not compare wall time or battery across that line. No control without a zone was flown with the new adapter.
- **Confirming distance.** With the zone present the drone confirms from where it first saw the target, 3.2 to 3.5 m from T1 (closest approach), not from on top of it.
- **Limits.** One drone, one scenario, one seed of the zone trigger; the zone is set off by the drone's own detection; d1-d5 are the old behaviour and are kept because they are the evidence for the two fixes. A zone that never leaves, two or more drones, and a model in the policy slot are still untested live. `live_zone_smoke.py` is kept outside the repo (`--drift`, event log) and is backed up with the results.

### 2026-11-02 first two-drone live flights: one live drone, one simulated teammate (no `runs/` folder)

Not study data, and **mixed fidelity**: Drone1 is the live CarlaAir vehicle, Drone2 is the repo's kinematic mock (15 m/s, no physics, no ground), both on one shared message bus, as `run_team_threaded` does. Same drifting zone, same trigger (the zone switches on when Drone1 itself senses T1, 12 s window) and same code as the solo d9-d11 runs. Script `live_team_smoke.py` is kept outside the repo and backed up with the results (`live_team_<tag>.json` on Heidi).

| Runs | Teammate's sector | Cruise height | Result |
|---|---|---|---|
| t1 | B (no target there) | 8 m (by mistake) | T1 confirmed, 1.0 s inside the zone |
| t2 | A (same sector as Drone1) | 8 m (by mistake) | Drone2 found and confirmed T1 first; Drone1 never saw the zone (0 s) but still swept all of sector A, took 199 s, 34% battery left, and stalled on the way home (below) |
| t5-t7 | B | 12 m | T1 confirmed 3 of 3, 1.0 / 1.0 / 2.25 s inside the zone (t5 pulled away slower), 102-107 s, battery 64-66%, Drone1 landed within 0.5 m of home each time |

- **The mistake in t1-t2.** The team script did not set the 12 m cruise height the solo runs use, so Drone1 flew at 8 m. In t2 the return leg passed near (30, 31), where the Sector A awnings and pole are: the drone crawled for about 35 s, then landed there, and had to be flown home by hand before the next flight. The obstacle as the cause is a guess, not checked. t1 and t2 are kept only as the record of that mistake; do not compare them with the solo runs. t5-t7 are the valid ones. A chain run now stops itself if Drone1 does not land within 4 m of home.
- **What the teammate changed in t5-t7: nothing visible.** Drone2 (sector B) stayed at least 15 m away, heard Drone1's `target_sighted` (zone-blocked sighting) and `target_found` messages on the bus, finished its own sector, listened, and went home. Drone1 behaved as in the solo runs (same exit point (34.2, 25.0), same blocked-then-confirm sequence, 1.0 s inside the zone in two of three).
- **t2 is the one that shows the team doing something.** The simulated teammate reached T1 about 7 s in, long before the live drone, and confirmed it; Drone1 got the `target_found` message but kept searching its whole sector, so a teammate's confirmation did not stop its search (the code was not read for why). This was seen once at 8 m cruise height, so repeat it at 12 m before citing it.
- **Limits.** One live drone beside a mock: the mock has no physics, the two drones were never closer than 13.9 m, and the live-to-mock separation check was therefore never tested. Two live vehicles, a teammate near the target, and a teammate that is the better-placed confirmer are untested live. The zone is still set off by the drone's own detection.

### 2026-11-02 first fully live two-drone flights, and a near collision (no `runs/` folder)

Not study data: both drones are real sim vehicles (Drone1 = `SimpleFlight`, Drone2 = `Drone2`, placed 20 m east by `~/Documents/AirSim/settings.json`; the launcher rebuilds `~/.carlaair/airsim-settings.json` from that file on every start, so edit the source file, backup `settings.json.bak-2026-11-02`). Same code, 12 m cruise height, drifting zone switched on by Drone1's own detection (12 s window), deterministic policy, no model, one shared message bus. Script `live_two_smoke.py` (outside the repo, backed up with the results as `live_two_<tag>.json`).

| Runs | Drone2's sector | Target confirmed | Drone1 time in zone | Closest the drones got | Both landed near home |
|---|---|---|---|---|---|
| l1a, l1b, l1c | B | 3 of 3 (Drone2 got the `target_found` message each time) | 2.25 / 2.5 / 1.0 s | 17.1-18.5 m | yes, within 0.5 m |
| l2a | A (same as Drone1) | yes, but by **Drone2**; Drone1 never met the zone (0 s) and swept its whole sector (39% battery left) | 0.0 s | **0.52 m** | yes |
| l2b | A | yes, by Drone1 (1.0 s in the zone) | 1.0 s | **0.09 m** | **no: Drone2 stuck in the air near (30, 21.6)** |

- **Route check for Sector B** (CARLA ray casts, lighter than the Sector A check: one lateral line and two heights per segment) found 10, 12 and 14 m clear for both possible ground levels. The Sector A check at Drone1's ground level does not cover Drone2's lane height, which sits about 1.4 m lower on this map; that was not rechecked.
- **Near collision in both L2 flights.** Both drones fly the diagonal to the Sector A entrance (20, 20) at the same time and met there about 16 to 21 s in, 0.5 m apart (l2a) and 0.09 m apart (l2b). The guardian's separation rule did fire, but only on a later waypoint (23.3, 20.0) within 5 m of the teammate's last reported position; it does not look at the path between waypoints, so the crossing was not stopped. Whether the two bodies touched was not read (collision flags were not logged during the flights). Two drones headed for the same entrance is a real hazard, not a rounding error.
- **l1a: both drones had one failed search leg** (`skill_failed->search_sector`) a little after takeoff, and the zone switched on 15 to 19 s later in l1a than in l1b and l1c. The cause was not logged (no event log in this script).
- **l2b ending.** Drone2 was blocked twice by separation near the target, the guardian ended its mission (`escalated after repeated unsafe proposals (separation)`), and the fallback return flew it to about 21 m and left it hovering at (30.2, 21.6). Commands to fly home then barely moved it and its reported position jumped around; the collision record named `InstancedFoliageActor` (a tree) at about (30.0, 22.1, height 21 m). The sim has to be restarted to clear it; flying it home by hand did not work (it climbed but would not move sideways).
- **Limits.** Five flights, one drone pair, deterministic policy; the zone is triggered by the drone's own detection; wall times are not comparable with the solo runs (Drone2's long search sets the run length, and some legs failed). The rule that stops a drone whose teammate already confirmed the target was not studied.

### 2026-11-03 same-sector flights after the separation fix (no `runs/` folder)

Not study data: the same fully live two-drone setup as the entry above (both drones real, 12 m, drifting zone switched on by Drone1's detection, deterministic policy), both drones sent to Sector A, which is the case that nearly collided.

- **What changed in the code** (commit 526cd51). A drone now announces where it is heading in the heartbeat it sends as it sets off. The guardian's separation check compares the target and the straight path to it with every point a teammate holds (its last reported position, and its announced destination while that is under 30 s old), not only the target against the last position. A drone blocked only by separation holds still in 2 s steps for up to 25 s and asks again; those waits do not count toward the guardian's repeated-rejection escalation (that escalation is what ended Drone2's mission in l2b). Going home is exempt, as before. Nine new tests; the full suite passes (394).
- **Result.**

| Runs | Closest the drones got | Samples under 5 m | Target confirmed | Landed near home |
|---|---|---|---|---|
| l2a, l2b (before the fix) | 0.52 m, 0.09 m | 40, 41 | yes, yes | yes, no (Drone2 stuck) |
| l3a, l3b (after) | 7.44 m, 6.05 m | 0, 0 | yes (by Drone2 in l3a, by Drone1 in l3b) | yes, yes (within 0.5 m) |

- **What it costs.** The second drone into a shared sector waits at the entrance until the first has moved on and then follows it along the same lanes. In l3a Drone1 waited 26 s and then 16 s and finished with 26% battery after 223 s; in l3b Drone2 waited about 36 s at the entrance before entering and finished with 33% battery after 201 s. Two drones sharing one sector is a deliberate worst case; the cost for sectors that do not overlap was not measured.
- **Limits.** Two flights. The check is a distance rule on straight paths and on the last announced points, not a prediction in time, so it can block a crossing that would have been safe, and a teammate's last reported position counts however old it is. The cause of the l2b hang in the tree was not studied and the fallback return that led there was not changed. Wall times and battery are not comparable with the solo runs.

## 4. Conditions of the data

Recorded because a run's conditions are part of the result.

- Model: `llama3.1:8b`, pinned, temperature 0, seed 17
- Host: a laptop, one local Ollama process serving all four agents
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
