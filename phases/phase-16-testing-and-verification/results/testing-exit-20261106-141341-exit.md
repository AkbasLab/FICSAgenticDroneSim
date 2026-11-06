# Testing exit — AUV-15

Run 2026-11-06T13:42:14, `scripts/testing_exit.py`, 1887 s wall.

| Part | Result |
|---|---|
| planted | yes |
| history | yes |
| traceable | yes |
| scenarios | yes |
| deterministic | yes |
| regression | yes |

**Planted:** 37 of 37 defects discovered without the simulator (100.0 %; bar 90%).
**History:** coordination and communication defects 28 found without the simulator, 1 live (96.6 %); every code defect 55 / 5 (91.7 %).
**Regression:** 5 of 5 live checks passed.

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

**Exit criterion: MET**
