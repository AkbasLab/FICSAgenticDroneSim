# Testing and verification (Phase 16, AUV-15)

How the project's behaviour is held by tests, mapped to AUV-15's list. Every test named here is checked to
exist by `tests/test_traceability.py`, so this map cannot silently go stale. Everything in sections 16.1, 16.2
and 16.4 runs **without a simulator**: on the mock (`simulator/mock_adapter.py`) and the shared simulated clock.

Run it all:

```
python -m unittest discover -s tests -p "test_*.py"          # about 13 minutes on the laptop; no simulator
```

## 16.1 Unit tests

| Item | Tests |
|---|---|
| Task-cost calculation | `tests/test_bids.py::BidTests::test_every_term_kept_and_the_sum_its_value` · `tests/test_bids.py::LanesTests::test_a_bid_costs_the_lanes_the_rule_policy_flies` · `tests/test_bids.py::BidTests::test_the_battery_is_costed_with_the_way_home` |
| Tie breaking | `tests/test_bids.py::RankTests::test_lowest_wins_and_the_vehicle_id_breaks_ties` · `tests/test_contract_net.py::ConflictRuleTests::test_equal_bids_go_to_the_lower_agent_id` · `tests/test_message_bus.py::DeliveryTests::test_ties_at_one_instant_are_read_by_sender_then_sequence` |
| Task-lease expiration | `tests/test_contract_net.py::DeliberatingTests::test_a_lease_runs_from_the_claim_and_reports_a_period_on` · `tests/test_contract_net.py::DeliberatingTests::test_progress_renews_every_lease` · `tests/test_team_policy.py::HundredMetreRadioTests::test_far_holders_lose_their_leases_and_sectors_are_searched_twice` |
| Message serialization | `tests/test_messages.py::EnvelopeTests::test_read_back_the_same_and_its_size` · `tests/test_messages.py::MalformedTests::test_the_envelope` · `tests/test_messages.py::MalformedTests::test_the_payload` |
| Message expiration | `tests/test_messages.py::EnvelopeTests::test_expiry_at_exactly_its_end` · `tests/test_lifetimes.py::InstantTests::test_at_the_instant_its_lifetime_ends_a_message_is_expired` · `tests/test_message_bus.py::DeliveryTests::test_nothing_after_it_expires` |
| Packet-loss sampling | `tests/test_network.py::ModelTests::test_a_draw_is_the_messages_own` · `tests/test_network.py::ModelTests::test_no_loss_loses_nothing` · `tests/test_network.py::BusTests::test_a_lost_message_is_recorded_and_never_arrives` |
| Latency scheduling | `tests/test_network.py::ModelTests::test_latency_is_the_mean_without_jitter_and_never_below_the_floor` · `tests/test_network.py::BusTests::test_latency_holds_a_message_until_it_arrives` · `tests/test_network.py::BusTests::test_bandwidth_delays_what_queues_behind` |
| Role transitions | `tests/test_roles.py::ChooseTests::test_the_three_roles` · `tests/test_roles.py::ChooseTests::test_free_with_a_teammate_unreachable_makes_a_relay` · `tests/test_recovery_policy.py::StopTests::test_role_changes_are_announced` |
| Belief-state aging | `tests/test_belief_state.py::StaleInformationTests::test_confidence_falls_to_zero_at_expiry_and_stays_there` · `tests/test_belief_state.py::StaleInformationTests::test_age_counts_from_when_it_was_true_not_when_it_arrived` · `tests/test_knowledge.py::PairLogTests::test_a_teammate_heard_and_then_expired` |
| Geofence checks | `tests/test_guardian.py::GeometryTests::test_the_geofence_is_the_operating_box_and_its_margin` · `tests/test_guardian.py::ModifyTests::test_just_outside_the_fence_is_moved_onto_it` · `tests/test_guardian.py::RejectTests::test_far_outside_the_fence` |
| Battery checks | `tests/test_bids.py::BidTests::test_not_eligible_on_battery` · `tests/test_rule_policy.py::LowBatteryAndDeadlineTests::test_not_enough_battery_to_start` · `tests/test_guardian.py::FallbackTableTests::test_short_of_battery_it_goes_home_round_the_zone_or_lands_there` |
| Invalid LLM output handling | `tests/test_llm_policy.py::FlightTests::test_garbage_is_corrected_once_then_the_rule_decides` · `tests/test_llm_policy.py::FlightTests::test_no_reply_is_a_fallback_recorded_as_such` · `tests/test_proposal.py::InvalidTests::test_values_the_skill_itself_refuses` |

## 16.2 Integration tests on the mock

One named test per scenario, each one flight (`tests/test_integration_mock.py`, about 17 s together):

| Scenario | Test |
|---|---|
| Two agents allocate two tasks | `tests/test_integration_mock.py::IntegrationScenarios::test_1_two_agents_allocate_two_tasks` |
| Four agents allocate four tasks | `tests/test_integration_mock.py::IntegrationScenarios::test_2_four_agents_allocate_four_tasks` |
| One agent disappears and its task is reassigned | `tests/test_integration_mock.py::IntegrationScenarios::test_3_one_agent_disappears_and_its_task_is_reassigned` |
| A partition divides the team | `tests/test_integration_mock.py::IntegrationScenarios::test_4_a_partition_divides_the_team` |
| Delayed claims create a conflict and are resolved | `tests/test_integration_mock.py::IntegrationScenarios::test_5_delayed_claims_create_a_conflict_and_are_resolved` |
| The relay agent fails and another assumes the role | `tests/test_integration_mock.py::IntegrationScenarios::test_6_the_relay_agent_fails_and_another_agent_assumes_the_role` |
| Malformed LLM output triggers fallback | `tests/test_integration_mock.py::IntegrationScenarios::test_7_malformed_llm_output_triggers_fallback` |

Each behaviour is also held, over 20 seeds, by its phase's exit: Phases 8 (allocation, conflicts), 9 (stops,
roles), 10 (partitions), 12 (the model's fallback).

## 16.3 AirSim regression tests

Five live checks, kept deliberately small, in `scripts/airsim_regression.py`; each is a flight in CarlaAir
against its mock twin, flown by a person (the simulator needs a display):

| Check | What passes |
|---|---|
| `single-waypoint` — single-drone waypoint mission | in Phase 5's live mission the drone takes off, flies its task, lands at its pad, no failure |
| `pair-apart` — two-drone non-conflicting mission | in Phase 8's live pair the two divide the sectors as the mock twin does, both land, no collision |
| `four-search` — four-drone search mission | Phase 3's four drones fly their skills live, each skill succeeds as on the mock |
| `reassign` — task reassignment during flight | in Phase 9's live pair one drone is stopped; the other takes its task in flight (the reassignment) |
| `return-home` — return-home fallback | Phase 5's live mission with a fault injected once: the drone recovers or returns home and lands |

`python scripts/airsim_regression.py --dry-run` runs every check's mock twin without a simulator.

## 16.4 Determinism

`tests/test_determinism.py`: with the same architecture, model output and seed, the run's directory repeats —
the report and trajectories byte for byte, the events and records in everything but a model call's latency, which
is timed on the wall clock (the run's own time, as its manifest's are; on a loaded Linux machine a replay's 0.000 s
became 0.001 s) — and so, checked one by one, do network events, target placement, injected faults and the
deterministic policies' decisions; a different seed changes them.

| What repeats | Test |
|---|---|
| The whole run directory | `tests/test_determinism.py::DeterminismTests::test_every_run_directory_repeats_byte_for_byte` · `tests/test_determinism.py::DeterminismTests::test_only_the_wall_clock_is_set_aside` |
| Network events | `tests/test_determinism.py::DeterminismTests::test_network_events_repeat` |
| Target placement | `tests/test_determinism.py::DeterminismTests::test_target_placement_repeats` |
| Injected faults | `tests/test_determinism.py::DeterminismTests::test_injected_faults_repeat` |
| Deterministic policies | `tests/test_determinism.py::DeterminismTests::test_deterministic_policies_repeat_exactly` |
| The same model output | `tests/test_determinism.py::DeterminismTests::test_the_same_model_output_repeats_exactly` |

### A live model's residual variability — to be measured, not assumed

Temperature 0 and a fixed seed reduce a served model's variance; they do not remove it (batching, kernels,
server versions). It is recorded **separately**, by this protocol, with the first live-model batch (Phase 17):

1. Take the first 100 decisions a live batch records (their requests are in each run's records).
2. Ask the same server, with the same pinned model and options, each request again, one at a time.
3. Report the fraction whose reply parses to the same tool and parameters (**agreement**), and the replies that
   differ, as they are.
4. Record it beside the batch, with the server version and the model's digest. Agreement below 100 % is a
   finding about the model, not a defect to hide; the experiment's replays stay exact either way.

## 16.5 Continuous integration

`.github/workflows/tests.yml` runs every test above on each pull request and each push to `SC`, on Windows with
Python 3.10, from `requirements-ci.txt` (what the simulator-free tests need, and nothing else): numpy, and the
`airsim` package with what it imports — used for its types, never a simulator — but not the OpenCV it lists and
never imports. Windows, because the recorded goldens pin the runner's console output as Windows prints it, and
goldens are never re-recorded; Python 3.10, because AirSim's `tornado` 4.5.3 runs on nothing newer than 3.11. Tried
first on Linux (WSL Ubuntu, Python 3.10): the suite passes there but for those Windows path strings. Tests that need
CarlaAir, Vega or a model server skip themselves when it is absent; the live regression set is run by hand.
