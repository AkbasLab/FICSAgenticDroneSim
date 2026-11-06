# Phase 13 exit criterion — evidence, 2026-11-06

> The architecture can be **selected through configuration** rather than maintaining four unrelated programs.

**Met on the mock.** 20 of 20 seeds passed all five checks. Generated from `../results/architecture-exit-20261106-102808-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `search_relay_001`, the canonical four |
| Configurations | 13, from `configs/architectures/`, each through `fly_architecture` |
| Flights | each seed: every configuration with no stop and with Drone1 stopped at 60 s (E with no stop); models by the echo; seeds 1–5 also D replayed from Phase 12's 70B, and every flight flown twice |
| Manifests | allocation `configs\allocation\default.toml`, recovery `configs\recovery\default.toml`, guardian `configs\guardian\default.toml`, keep_out `configs\keepout\default.toml`, phase12_record `phases\phase-12-llm-agent-policy\results\llm-exit-20261105-150453-exit.jsonl` |
| Seeds | 1–20 |
| Code | commit `f98fe25` (dirty: False); `agentic_uav` digest `10a9751f04c7a1eb` |
| Wall time | 313.8 s, seeds side by side (`--jobs 10`) |

## The configurations

| Name | Team | Decider | Switched off / on |
|---|---|---|---|
| A | central | rules | -- |
| B | independent | rules | -- |
| C | decentralized | rules | -- |
| C-link-inputs | decentralized | rules | link_inputs on |
| C-no-guardian | decentralized | rules | guardian off |
| D | decentralized | llm | -- |
| D-fallback | decentralized | llm-fallback | -- |
| D-no-guardian | decentralized | llm | guardian off |
| D-no-leases | decentralized | llm | leases off |
| D-no-memory | decentralized | llm | memory off |
| D-no-roles | decentralized | llm | roles off |
| D-perfect-comms | decentralized | llm | perfect_comms on |
| E | scripted | rules | -- |

## The checks, each seed

| Seed | by_configuration | arms_as_claimed | ablations_off | limits_kept | deterministic |
|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes |
| 2 | yes | yes | yes | yes | yes |
| 3 | yes | yes | yes | yes | yes |
| 4 | yes | yes | yes | yes | yes |
| 5 | yes | yes | yes | yes | yes |
| 6 | yes | yes | yes | yes | yes |
| 7 | yes | yes | yes | yes | yes |
| 8 | yes | yes | yes | yes | yes |
| 9 | yes | yes | yes | yes | yes |
| 10 | yes | yes | yes | yes | yes |
| 11 | yes | yes | yes | yes | yes |
| 12 | yes | yes | yes | yes | yes |
| 13 | yes | yes | yes | yes | yes |
| 14 | yes | yes | yes | yes | yes |
| 15 | yes | yes | yes | yes | yes |
| 16 | yes | yes | yes | yes | yes |
| 17 | yes | yes | yes | yes | yes |
| 18 | yes | yes | yes | yes | yes |
| 19 | yes | yes | yes | yes | yes |
| 20 | yes | yes | yes | yes | yes |

Problems recorded: 0.

| Check | What it requires |
|---|---|
| by_configuration | every flight is the configuration it was asked for, flown by the one entry point, on the same scenario, manifests, limits and keep-out |
| arms_as_claimed | C with no stop is Phase 9's flight; D by the echo and D-fallback are C's; D replayed is Phase 12's flight and decisions (seeds 1–5); B starts from C's first division and sends no task message; A flies only tasks the base awarded, and its drones send no task message but completions; E meets the mission |
| ablations_off | no leases: no lease runs out; no roles: no role change; no memory: the model never told its past; no guardian: none; link inputs: estimates kept, C's flight |
| limits_kept | every flight with agents, as flown: band, fence, zones, separation, speed, landings |
| deterministic | seeds 1–5: each configuration flown twice, the same flight |

Each check is shown able to fail in `tests/test_architecture_exit.py`, on a real seed's flights with one swapped or relabelled.

## Each configuration over the seeds (findings, not experiments)

| Configuration / flight | Met | Completion s (min, median, max) |
|---|---|---|
| A / Drone1 stopped | 20/20 | [308.2, 308.2, 308.2] |
| A / no stop | 20/20 | [192.1, 192.1, 192.1] |
| B / Drone1 stopped | 0/20 | None |
| B / no stop | 20/20 | [188.0, 188.0, 188.0] |
| C / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C / no stop | 20/20 | [194.1, 194.1, 194.1] |
| C-link-inputs / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C-link-inputs / no stop | 20/20 | [194.1, 194.1, 194.1] |
| C-no-guardian / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| C-no-guardian / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D (70B) / Drone1 stopped | 5/5 | [308.0, 309.1, 309.1] |
| D (70B) / no stop | 5/5 | [193.0, 199.1, 199.1] |
| D / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-fallback / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-fallback / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-guardian / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-no-guardian / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-leases / Drone1 stopped | 0/20 | None |
| D-no-leases / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-memory / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-no-memory / no stop | 20/20 | [194.1, 194.1, 194.1] |
| D-no-roles / Drone1 stopped | 20/20 | [307.1, 307.1, 307.1] |
| D-no-roles / no stop | 20/20 | [188.0, 188.0, 188.0] |
| D-perfect-comms / Drone1 stopped | 20/20 | [309.1, 309.1, 309.1] |
| D-perfect-comms / no stop | 20/20 | [194.1, 194.1, 194.1] |
| E / no stop | 20/20 | [192.1, 192.1, 192.1] |
