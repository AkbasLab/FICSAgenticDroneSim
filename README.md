# Runtime assurance for LLM-driven UAV teams

A multi-drone simulation in CarlaAir (CARLA and AirSim in one Unreal process) where each drone is a persistent
agent that decides for itself, coordinates over a degradable message bus, and is held inside a deterministic
safety envelope. A language model can sit in each agent's decision slot, but it is held to the same rules as
any other policy: it proposes, an independent runtime guardian disposes.

The current research question, for the ACM TRUST submission *From AI Guardrails to Dynamic Operational
Boundary Assurance* (EIGTrust track): **when the operational boundaries themselves change during a mission,
how often must the guardian override the policy, and at what cost?** This repository holds the guardian, the
agent architecture around it, and the experiments measuring it. It is the GMB (geographical and mechanical
boundaries) line of work in the FICS Lab's
[FICSAgenticDroneSim](https://github.com/AkbasLab/FICSAgenticDroneSim) project and was written independently
of that repository's `main` branch. Licensing follows the lab repository (MIT, see `LICENSE` on its `GMB`
branch).

## Contribution so far

1. **A deterministic runtime guardian** (`fics_drone/agents/safety_guardian.py`). Ten checks (altitude, geofence,
   restricted zones, waypoint validity, speed, timeout, battery reserve, separation, landing site, conflicting
   commands) sit between any policy and the vehicle. Soft violations are narrowed into the envelope, hard ones
   are refused, and a policy that keeps proposing unsafe commands is escalated to a sticky return-home-and-land.
   Same command and same belief always give the same verdict, and every refusal names its check.
2. **Dynamic boundaries.** No-fly zones can switch on, switch off and drift during a mission. The guardian
   reads mission time. If a zone appears over an aircraft it steers the aircraft out and the policy re-plans;
   an optional per-tick monitor stops a flight leg the moment the aircraft is inside a newly active zone.
3. **An LLM in the policy slot without giving up safety.** Each agent can use a local model over a menu of
   15 tools, built each turn by code (a tool appears only if its preconditions hold), with a structured decision
   schema, one correction attempt, a deterministic fallback, and a hard action cap so a model cannot loop.
   The model card (pinned model, digest, temperature, seed) and every prompt and raw output are saved.
4. **Measurement.** A scorer, a guardian log (interventions by check, steer-out distance), a waypoint probe that
   asks a model for 100 seeded situations and judges each answer with the guardian's own checks, and a run
   ledger recording which runs are valid data and why the others are not.

## Results so far

Everything here is from a mock vehicle or a local 8B model. **Nothing yet comes from a live flight with a
dynamic zone**, and the only language-model evidence near a dynamic zone is the waypoint probe below (single
waypoints, not whole missions). Treat these as pilot numbers.

*Dynamic zones, deterministic policy, kinematic mock, four agents* (`runs/dynamic_zone_mock_pilot_v3`):

| Condition | Guardian interventions | Time inside an active zone | Steer-out distance |
|---|---|---|---|
| static zone only | 0 of 82 commands | 0 s | 0 m |
| zone appears mid-mission | 1 of 83 | about 3 s | 8.6 m |
| zone drifts across a sector, guardian acts at command boundaries | 3 of 83 | about 3.6 s | 4.0 m |
| same, with the per-tick monitor | 7 of 91 | about 2.5 s | 19.6 m |

All drones ended home and out of every zone in all runs. The guardian reacts about 3 s after a zone appears,
because it normally acts when a command is proposed. The per-tick monitor shortens that on flight legs
(about 30%) at roughly twice the interventions and five times the steer-out distance, and it does nothing when
the drone is in a non-flight step. The mock is deterministic, so repeats are identical: the effective sample
is one run per condition.

*A model proposing waypoints, static zones, llama3.1:8b, 100 seeded situations* (`runs/probe_llama31_8b_schema_v2`):
the model alone proposes a legal waypoint 17% of the time (every failure is a separation violation); with
pre-computed facts about candidate points 98%; with its answer snapped to the nearest legal point 100% at a mean
move of 5 m. Telling the model the guardian's reason and asking again fixes only 8% of illegal proposals, and
61% of the time it proposes the same point again. Its self-reported confidence is the same (0.8) for legal and
illegal proposals, so it carries no signal.

*The same probe with two dynamic zones* (one over Sector A active from 10 s, one over Sector D from 60 s;
same situations, same model and seed; `runs/probe_llama31_8b_dynamic_zones`, compared with
`scripts/analyze_dynamic_probe.py`). The model is never told about zones, so the question is what the guardian
has to catch:

| | static zones | dynamic zones, model not told | dynamic zones, model told |
|---|---|---|---|
| model alone, legal | 17% | 16% | 19% |
| with pre-computed facts, legal | 98% | 92% | 93% |
| snapped to nearest legal point, legal | 100% | 100% | 100% |
| needed repair / mean repair move | 85% / 5.0 m | 86% / 5.1 m | 84% / 4.8 m |
| first proposals that violate a zone | n/a | 17 | 25 |
| first proposals that violate separation | 83 | 83 | 73 |
| retry after the guardian's reason is legal | 8% | 8% | 11% |

The zones changed little because the model's dominant error is already flying to a teammate's position
(83 separation violations either way); only one proposal became newly illegal. The one clear effect is on the
pre-computed-facts condition (98% to 92%): in 5 of the 8 illegal cases the model chose the centre of a sector
that now lies inside an active zone. Why it did so despite the facts in its prompt was not investigated. In this
scenario 23 of the 100 situations start with the drone already inside an active zone (zones were placed over
sectors where situations are sampled, so that share is by construction); the guardian's steer-out would move
those drones a mean of 6.3 m (max 9.5 m). Timeouts and fallbacks: none.

*Telling the model about the zones* (third column; `--show-zones`, `runs/probe_llama31_8b_dynamic_zones_shown`):
the prompt lists the zones active at decision time at their current position. It did **not** help: the number
of first proposals inside a zone went **up** (17 to 25) while separation violations went down (83 to 73), and
the legal rate moved from 16% to 19%. Possibly the model anchors on the listed boxes (it is also shown the
sector boxes, which overlap the zones), but with one seed, 100 situations and one 8B model, differences of
this size are not reliable and no mechanism was tested. The defensible reading is that visibility did not make
the model avoid zones, so the guardian and repair layer still do the work.

## Limitations

- **Simulation only.** The live-flight evidence is for static scenarios (four drones flying a scored mission, a
  solo persistent agent). Four drones flying concurrently live do not find targets on the development laptop,
  concluded to be resource contention and not a logic fault; that conclusion is unverified.
- **Small models, slow hardware.** Model runs used an 8B model on a laptop CPU, about 11 s per call. Four agents
  sharing one model process exceed a 30 s decision budget, which is why a whole-mission LLM run against a dynamic
  zone was invalid (5 of 6 decisions timed out; the run is kept in the ledger and flagged). A larger model on
  GPU hardware will behave differently and numbers from one must not be quoted as the other.
- **The guardian checks a waypoint's endpoint, not the path**, and acts at command boundaries unless the
  per-tick monitor (flight legs, dynamic zones only) is on.
- **The scripted policy never waits for a zone to expire**: when a zone blocks its sector it gives up and returns
  home, so "zone appears" and "zone appears, then expires" give identical results.
- **Noclip changes what a live run means.** Pressing P in the CarlaAir window toggles noclip: nothing collides,
  the ground included. With it off, the drone can fly into street furniture (an awning at the east edge of
  Sector A stops the first lane); with it on it passes through everything. These are different experimental
  conditions and every live run must record which was used. An earlier live anomaly (final height -11.8 m, landing
  about 64 s) was this: with noclip on, `landAsync` descends 0.2 m/s with nothing to stop it. `land()` now probes
  for ground contact instead and, with none, holds at the ground reference and stays armed (the sim lets such a
  drone fall once the script exits, which does not affect a run's result). Fixed and verified in both modes; the
  full account is in `phases/RUN_LEDGER.md`.

## Reproducing it

Most things run with no simulator and no GPU:

```bash
python -m pytest -q                                   # ~12 min, 318+ tests; some use real timers
python scripts/run_dynamic_zone_study.py --repeats 3  # the dynamic-zone study above, mock
python scripts/run_guardian_demo.py                   # unsafe commands caught by the guardian
python scripts/run_canonical_mission.py               # the scored search-and-relay mission, mock
```

Model runs need [Ollama](https://ollama.com) and a pinned tag (`llama3.1:8b` for the recorded runs; a floating
tag is flagged as unpinned in the model card):

```bash
python scripts/probe_waypoints.py --backend ollama --n 100 --save runs/<name>      # ~1 h on CPU
python scripts/run_llm_agents.py --backend ollama --save runs/<name>               # four LLM agents, one Ollama
python scripts/analyze_dynamic_probe.py <static_run> <dynamic_run> \
    --scenario configs/missions/search_relay_dynamic_001.json
```

Live flight needs CarlaAir running (`CarlaAir.ps1 Town10HD`) and `--airsim` on the mission scripts.
`scripts/check_ground_ref.py` and `scripts/trace_landing.py` are live checks of the ground reference and the
landing, added after a ground-reference defect was found in a related project.

Every run is recorded in `phases/RUN_LEDGER.md` with a verdict. Nothing is deleted; a conclusion that turns out
wrong gets a dated correction. Seeds, scenario files (`configs/missions/`), saved prompts and raw model output
(`runs/`) are in the repository.

## Layout

```
fics_drone/
  core/          scenario (zones, sectors, drones), skill results, interfaces
  control/       flight constants and the skill layer (take off, go to, hold, return, land)
  simulator/     AirSim adapter (the only code that talks to AirSim) and mock adapters
  agents/        persistent agent, belief, rule and LLM policies, SafetyGuardian, reasoning tools
  coordination/  message bus, network model, bidding and allocation, task board, roles
  evaluation/    the scorer
  experiments/   team runner, guardian and LLM logs, waypoint probe
  telemetry/     position sampler used for scoring
configs/missions/   static and dynamic-zone scenario files
scripts/            one entry point per experiment
runs/               saved results and model output
phases/             run ledger and a template for phase records
tests/
```

## Design rules

- **Deterministic safety.** The guardian is plain code and never a second model, so it cannot inherit the
  failure modes it exists to contain.
- **The model owns judgment, code owns facts.** Take-off, landing, retries, low battery and "sector swept"
  are code. The model decides only where both options are safe and the choice cannot strand a drone.
- **Ground truth stays out of the agent.** An agent knows only what its own sensor model and received messages
  told it, and each belief records where a fact came from.
- **Failures are data.** Failed and invalid runs are kept and labelled, not discarded.

## Status of the team plan

Phases 1-12 of the team's phased plan are implemented here: natural-language planning, multi-drone control, the
skill layer, the scored search-and-relay mission, persistent agents with belief states, messaging, decentralized
allocation and role recovery, degraded communications, the runtime guardian, and the LLM policy. Phases 7-12
are verified in mock only; Phases 1-4 and a solo Phase 5 agent have flown live. The comparison architectures and
experiment runner (Phases 13-14) are in the lab repository's `main` branch and are not duplicated here.
