# Phase 16 exit criterion — evidence, 2026-11-06

> Most coordination and communication defects can be discovered without launching CARLA-Air.

**Met.** Generated from `../results/testing-exit-20261106-141341-exit.jsonl`; nothing is transcribed.

| | |
|---|---|
| Code | commit `f144d24` (dirty: False); `agentic_uav` digest `15fdc1e18b8ed308` |
| Wall time | 1887.1 s (the defects planted in 4 throwaway copies at once) |

## The parts

| Part | Result |
|---|---|
| planted | yes |
| history | yes |
| traceable | yes |
| scenarios | yes |
| deterministic | yes |
| regression | yes |

## 1 · Planted defects

**37 of 37 discovered** by the simulator-free tests named in `tests/planted_defects.py`, against a bar of 90% fixed before the first run. Their first run (2026-11-06, the same 37, the same tests) discovered **36 of 37 (97.3 %)**: the one missed — a drone re-announcing its *own* task when its own lease lapsed — had no test, because a live holder renews its lease long before it could lapse. A test was added (`test_contract_net.py::DeliberatingTests::test_a_holder_never_gives_its_own_task_away_by_its_own_lease`) and this run, of record, discovers all 37.

| # | Defect | File | Discovered by |
|---|---|---|---|
| 1 | range ignored | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 2 | no delay | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 3 | no rate limit | `agentic_uav/simulator/message_bus.py` | test_network.py |
| 4 | network range ignored | `agentic_uav/simulator/message_bus.py` | test_network.py |
| 5 | partitions ignored | `agentic_uav/simulator/message_bus.py` | test_network.py |
| 6 | losses ignored | `agentic_uav/simulator/message_bus.py` | test_network.py |
| 7 | no latency | `agentic_uav/simulator/message_bus.py` | test_lifetimes.py |
| 8 | read early | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 9 | stale news read | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 10 | order not total | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 11 | shared, not a copy | `agentic_uav/simulator/message_bus.py` | test_message_bus.py |
| 12 | half the losses | `agentic_uav/simulator/network.py` | test_belief_state.py |
| 13 | no floor | `agentic_uav/simulator/network.py` | test_network.py |
| 14 | never heals | `agentic_uav/simulator/network.py` | test_network.py |
| 15 | no bandwidth | `agentic_uav/simulator/network.py` | test_network.py |
| 16 | bucket never empties | `agentic_uav/simulator/network.py` | test_network.py |
| 17 | expiry boundary | `agentic_uav/core/messages.py` | test_messages.py |
| 18 | malformed payloads accepted | `agentic_uav/core/messages.py` | test_messages.py |
| 19 | late lease | `agentic_uav/coordination/tasks.py` | test_tasks.py |
| 20 | long first lease | `agentic_uav/coordination/tasks.py` | test_tasks.py |
| 21 | progress never renews | `agentic_uav/coordination/contract_net.py` | test_contract_net.py |
| 22 | re-announces its own task | `agentic_uav/coordination/contract_net.py` | test_contract_net.py |
| 23 | no bid window | `agentic_uav/coordination/contract_net.py` | test_contract_net.py |
| 24 | ties unbroken | `agentic_uav/coordination/contract_net.py` | test_network.py |
| 25 | worst claim wins | `agentic_uav/coordination/contract_net.py` | test_contract_net.py |
| 26 | distance to the task ignored | `agentic_uav/coordination/bids.py` | test_bids.py |
| 27 | battery not costed | `agentic_uav/coordination/bids.py` | test_bids.py |
| 28 | never failed | `agentic_uav/coordination/health.py` | test_health.py |
| 29 | late unreachable | `agentic_uav/coordination/health.py` | test_health.py |
| 30 | never heard again | `agentic_uav/coordination/health.py` | test_health.py |
| 31 | ladder steps down | `agentic_uav/coordination/health.py` | test_belief_state.py |
| 32 | drops its task to relay | `agentic_uav/coordination/roles.py` | test_roles.py |
| 33 | relays toward the dead | `agentic_uav/agents/recovery_policy.py` | test_belief_state.py |
| 34 | keeps out of the living | `agentic_uav/coordination/keepout.py` | test_belief_state.py |
| 35 | a cross, not a square | `agentic_uav/coordination/keepout.py` | test_belief_state.py |
| 36 | confidence never falls | `agentic_uav/agents/belief_state.py` | test_belief_state.py |
| 37 | records live twice as long | `agentic_uav/agents/belief_state.py` | test_belief_state.py |

## 2 · The project's own defects

From `defect-history-2026-11-06.md`, every code defect in the phase reports, Phases 3–15, by what found it:

| | Without the simulator | Live CarlaAir | Share without |
|---|---|---|---|
| Coordination and communication | 28 | 1 | **96.6 %** |
| Every code defect | 55 | 5 | 91.7 % |

## 3 · The five AirSim regression checks, flown live

| Check | Passed | Why | Record |
|---|---|---|---|
| single-waypoint | yes | the script's own checks: exit code 0 | `phases/phase-16-testing-and-verification/results/single-waypoint/single-agent-live-20261106-130936-regression.jsonl` |
| pair-apart | yes | the script's own checks: exit code 0 | `phases/phase-16-testing-and-verification/results/pair-apart/allocation-live-20261106-131436-regression.jsonl` |
| four-search | yes | the script's own checks: exit code 0 | `phases/phase-16-testing-and-verification/results/four-search/four-drone-skills-airsim-20261106-131844-regression.jsonl` |
| reassign | yes | held: detected, reassigned, kept_out | `phases/phase-16-testing-and-verification/results/reassign/recovery-live-20261106-131653-regression.jsonl` |
| return-home | yes | the script's own checks: exit code 0 | `phases/phase-16-testing-and-verification/results/return-home/single-agent-live-20261106-131254-regression.jsonl` |
