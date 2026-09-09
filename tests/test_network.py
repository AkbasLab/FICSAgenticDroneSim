"""Phase 10 tests: the degraded-communications model, verified statistically.

A network model you haven't measured is just an assumption. These run thousands
of messages through it and check the empirical behaviour matches what was
configured — because every later result about "performance under 30% loss" is
only worth anything if the link really dropped about 30%.

The last group is the exit criterion: replay one mission under all four
conditions with reproducible delivery.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.comms_estimator import CommsEstimator
from agentic_uav.coordination import comms_conditions as cc
from agentic_uav.coordination.message_bus import MessageBus
from agentic_uav.coordination.network_model import (
    InterferenceZone, NetworkModel, NetworkProfile, Partition)
from agentic_uav.coordination.protocols import AgentMessage, MessageType
from agentic_uav.coordination.tasks import TaskStatus
from agentic_uav.core.models import Position3D
from agentic_uav.experiments.team_runner import build_allocating_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")

N = 4000          # sample size for the statistical checks


def _msg(sender="Drone1", mtype=MessageType.HEARTBEAT, now=0.0, seq=1):
    return AgentMessage(message_type=mtype, sender_id=sender,
                        recipient_ids=["Drone2"], timestamp=now,
                        sequence_number=seq, payload={"x": 1})


def _sample(profile, n=N, seed=1, position_of=None, now=0.0):
    net = NetworkModel(profile, seed=seed, position_of=position_of)
    delivered, delays = 0, []
    for i in range(n):
        v = net.evaluate(_msg(now=now, seq=i + 1), "Drone1", "Drone2", now)
        if v.delivered:
            delivered += 1
            delays.append(v.delay_s)
    return net, delivered / n, delays


# --- 10.6 empirical loss ---

def test_zero_loss_profile_drops_nothing():
    _net, rate, _d = _sample(NetworkProfile(name="perfect"))
    assert rate == 1.0


def test_empirical_loss_matches_configured_10_percent():
    _net, rate, _d = _sample(NetworkProfile(packet_loss_probability=0.10))
    assert 0.085 <= (1 - rate) <= 0.115, f"observed loss {1 - rate:.3f}"


def test_empirical_loss_matches_configured_30_percent():
    _net, rate, _d = _sample(NetworkProfile(packet_loss_probability=0.30))
    assert 0.28 <= (1 - rate) <= 0.32, f"observed loss {1 - rate:.3f}"


def test_loss_scales_monotonically():
    rates = []
    for p in (0.0, 0.1, 0.3, 0.6):
        _n, rate, _d = _sample(NetworkProfile(packet_loss_probability=p), n=2000)
        rates.append(rate)
    assert rates == sorted(rates, reverse=True), rates


# --- 10.6 empirical latency ---

def test_empirical_latency_matches_the_distribution():
    profile = NetworkProfile(latency_ms_mean=150.0, latency_ms_jitter=50.0)
    _net, _rate, delays = _sample(profile)
    mean_ms = sum(delays) / len(delays) * 1000.0
    var = sum((d * 1000.0 - mean_ms) ** 2 for d in delays) / len(delays)
    std_ms = var ** 0.5
    assert 145 <= mean_ms <= 155, f"mean {mean_ms:.1f}ms"
    assert 45 <= std_ms <= 55, f"std {std_ms:.1f}ms"


def test_latency_is_never_negative():
    """A big jitter on a small mean would give negative draws if unclamped."""
    profile = NetworkProfile(latency_ms_mean=20.0, latency_ms_jitter=200.0)
    _net, _rate, delays = _sample(profile, n=2000)
    assert all(d >= 0.0 for d in delays)


def test_zero_jitter_gives_constant_latency():
    profile = NetworkProfile(latency_ms_mean=100.0, latency_ms_jitter=0.0)
    _net, _rate, delays = _sample(profile, n=200)
    assert all(abs(d - 0.1) < 1e-9 for d in delays)


# --- 10.6 partitions block only intended links ---

def test_partition_blocks_only_across_the_split():
    profile = NetworkProfile(partitions=[Partition(
        group_a=["Drone1", "Drone2"], group_b=["Drone3", "Drone4"],
        start_s=10.0, end_s=100.0)])
    net = NetworkModel(profile, seed=1)

    # across the split, during the window: blocked
    assert not net.evaluate(_msg(), "Drone1", "Drone3", 50.0).delivered
    assert not net.evaluate(_msg(), "Drone4", "Drone2", 50.0).delivered
    # within a group, during the window: fine
    assert net.evaluate(_msg(), "Drone1", "Drone2", 50.0).delivered
    assert net.evaluate(_msg(), "Drone3", "Drone4", 50.0).delivered
    # outside the window: fine
    assert net.evaluate(_msg(), "Drone1", "Drone3", 5.0).delivered
    assert net.evaluate(_msg(), "Drone1", "Drone3", 150.0).delivered


def test_partition_cuts_the_far_group_off_from_base():
    profile = NetworkProfile(partitions=[Partition(
        group_a=["Drone1"], group_b=["Drone2"], start_s=0.0, end_s=100.0,
        base_side="a")])
    net = NetworkModel(profile, seed=1)
    assert net.base_reachable_for("Drone1", 50.0)
    assert not net.base_reachable_for("Drone2", 50.0)
    assert net.base_reachable_for("Drone2", 150.0)     # window over


# --- 10.6 expired messages are never delivered ---

def test_expired_message_is_not_delivered():
    bus = MessageBus(network=NetworkModel(
        NetworkProfile(latency_ms_mean=5000.0), seed=1))
    a, b = bus.register("Drone1"), bus.register("Drone2")
    a.send(MessageType.HEARTBEAT, {"x": 1}, now=0.0, ttl_s=1.0)
    assert b.receive_available(now=60.0) == []
    entry = bus.log.entries[0]
    assert entry.dropped and entry.drop_reason == "expired_before_delivery"


def test_message_ttl_varies_by_type():
    """10.4: a heartbeat should die young; a target report should not."""
    assert cc.ttl_for(MessageType.HEARTBEAT) < cc.ttl_for(MessageType.TARGET_FOUND)
    assert cc.ttl_for(MessageType.MISSION_UPDATE) == float("inf")
    assert cc.ttl_for(MessageType.TASK_AWARD) >= 120.0


def test_link_send_uses_the_per_type_ttl_by_default():
    bus = MessageBus()
    a = bus.register("Drone1")
    bus.register("Drone2")
    hb = a.send(MessageType.HEARTBEAT, {}, now=0.0)
    tf = a.send(MessageType.TARGET_FOUND, {}, now=0.0)
    assert tf.time_to_live_s > hb.time_to_live_s


# --- 10.3 seeded reproducibility ---

def test_same_seed_gives_identical_network_behaviour():
    p = NetworkProfile(packet_loss_probability=0.3, latency_ms_mean=100.0,
                       latency_ms_jitter=40.0)
    # two models built from scratch with the same seed must agree on every
    # decision AND every latency draw
    n1, n2 = NetworkModel(p, seed=7), NetworkModel(p, seed=7)
    s1 = [(n1.evaluate(_msg(seq=i), "A", "B", 0.0).delivered,
           round(n1.evaluate(_msg(seq=i), "A", "B", 0.0).delay_s, 9))
          for i in range(250)]
    s2 = [(n2.evaluate(_msg(seq=i), "A", "B", 0.0).delivered,
           round(n2.evaluate(_msg(seq=i), "A", "B", 0.0).delay_s, 9))
          for i in range(250)]
    assert s1 == s2


def test_different_seeds_give_different_behaviour():
    """Sanity: if seeds didn't matter, the reproducibility test would be vacuous."""
    p = NetworkProfile(packet_loss_probability=0.3)
    n1, n2 = NetworkModel(p, seed=1), NetworkModel(p, seed=2)
    s1 = [n1.evaluate(_msg(seq=i), "A", "B", 0.0).delivered for i in range(300)]
    s2 = [n2.evaluate(_msg(seq=i), "A", "B", 0.0).delivered for i in range(300)]
    assert s1 != s2


def test_reset_restores_the_same_sequence():
    p = NetworkProfile(packet_loss_probability=0.3)
    net = NetworkModel(p, seed=5)
    first = [net.evaluate(_msg(seq=i), "A", "B", 0.0).delivered for i in range(200)]
    net.reset()
    again = [net.evaluate(_msg(seq=i), "A", "B", 0.0).delivered for i in range(200)]
    assert first == again


# --- other mechanisms ---

def test_range_blocks_distant_pairs():
    positions = {"Drone1": Position3D(0, 0, -8), "Drone2": Position3D(500, 0, -8)}
    net = NetworkModel(NetworkProfile(communication_range_m=100.0), seed=1,
                       position_of=positions.get)
    assert not net.evaluate(_msg(), "Drone1", "Drone2", 0.0).delivered
    positions["Drone2"] = Position3D(50, 0, -8)
    assert net.evaluate(_msg(), "Drone1", "Drone2", 0.0).delivered


def test_rate_limit_caps_messages_per_second():
    net = NetworkModel(NetworkProfile(message_rate_limit=5.0), seed=1)
    ok = sum(1 for i in range(20)
             if net.evaluate(_msg(seq=i), "Drone1", "Drone2", 0.0).delivered)
    assert ok == 5, ok
    # a second later the window has moved on
    assert net.evaluate(_msg(), "Drone1", "Drone2", 1.5).delivered


def test_bandwidth_cap_blocks_oversized_traffic():
    net = NetworkModel(NetworkProfile(bandwidth_bytes_per_second=200.0), seed=1)
    delivered = sum(1 for i in range(20)
                    if net.evaluate(_msg(seq=i), "Drone1", "Drone2", 0.0).delivered)
    assert 0 < delivered < 20, delivered
    assert net.dropped_by_reason.get("bandwidth", 0) > 0


def test_asymmetric_link_degrades_one_direction_only():
    p = NetworkProfile(asymmetric_links={"Drone1->Drone2": 1.0})
    net = NetworkModel(p, seed=1)
    forward = sum(1 for i in range(200)
                  if net.evaluate(_msg(seq=i), "Drone1", "Drone2", 0.0).delivered)
    backward = sum(1 for i in range(200)
                   if net.evaluate(_msg(seq=i), "Drone2", "Drone1", 0.0).delivered)
    assert forward == 0, forward
    assert backward == 200, backward


def test_interference_zone_degrades_links_inside_it():
    positions = {"Drone1": Position3D(0, 0, -8), "Drone2": Position3D(200, 0, -8)}
    p = NetworkProfile(interference_zones=[InterferenceZone(
        zone_id="Z1", centre=(0.0, 0.0), radius_m=30.0, extra_loss=0.5)])
    net = NetworkModel(p, seed=3, position_of=positions.get)
    inside = sum(1 for i in range(1000)
                 if net.evaluate(_msg(seq=i), "Drone1", "Drone2", 0.0).delivered)
    # Drone1 sits in the zone, so ~50% should be lost
    assert 0.40 <= inside / 1000 <= 0.60, inside / 1000


def test_burst_loss_drops_a_run_of_messages():
    p = NetworkProfile(burst_loss_probability=1.0, burst_length_s=5.0)
    net = NetworkModel(p, seed=1)
    assert not net.evaluate(_msg(), "A", "B", 0.0).delivered      # starts a burst
    assert not net.evaluate(_msg(), "A", "B", 1.0).delivered      # still in it
    assert net.dropped_by_reason.get("burst_loss", 0) >= 2


# --- 10.5 agents estimate, never read, the configuration ---

def test_estimator_approximates_the_real_loss_rate():
    """The agent sees only sequence numbers and arrival times."""
    est = CommsEstimator("Drone1", heartbeat_interval_s=10.0)
    # sender emitted 100 messages; 30 never arrived
    arrived = [i for i in range(1, 101) if i % 10 >= 3]
    for seq in arrived:
        est.observe(_msg(sender="Drone2", seq=seq, now=0.0), now=1.0)
    observed = est.estimated_loss_rate()
    assert 0.25 <= observed <= 0.35, observed


def test_estimator_measures_information_age():
    """Age on arrival, not wire latency - see comms_estimator's docstring."""
    est = CommsEstimator("Drone1")
    for seq in range(1, 51):
        est.observe(_msg(sender="Drone2", seq=seq, now=10.0), now=10.25)
    assert abs(est.estimated_message_age_s() - 0.25) < 0.01


def test_estimator_never_touches_the_network_config():
    """Structural: an agent's estimator holds no reference to the model."""
    agents, tasks, bus, _t = build_allocating_team(
        load_scenario(SCENARIO), lambda vid: MockVehicleAdapter(0.0),
        network=cc.condition("severe"), seed=3)
    run_team(agents, tasks, bus)
    for a in agents:
        assert a.comms is not None
        reachable = vars(a.comms).values()
        assert not any(isinstance(v, (NetworkModel, NetworkProfile))
                       for v in reachable)
        # and the belief holds an estimate, not the configured 30%
        assert isinstance(a.belief.communication.recent_loss_rate, float)


def test_agents_notice_degradation_without_being_told():
    nominal = _estimated_loss("nominal")
    severe = _estimated_loss("severe")
    assert severe > nominal, (nominal, severe)


def _estimated_loss(condition_name):
    agents, tasks, bus, _t = build_allocating_team(
        load_scenario(SCENARIO), lambda vid: MockVehicleAdapter(0.0),
        network=cc.condition(condition_name), seed=11)
    run_team(agents, tasks, bus)
    vals = [a.comms.estimated_loss_rate() for a in agents if a.comms]
    return sum(vals) / len(vals)


# --- exit criterion: reproducible replay under all four conditions ---

def _replay(condition_name, seed=17):
    agents, tasks, bus, _t = build_allocating_team(
        load_scenario(SCENARIO), lambda vid: MockVehicleAdapter(0.0),
        network=cc.condition(condition_name), seed=seed, lease_s=150.0,
        heartbeat_interval_s=15.0)
    run_team(agents, tasks, bus)
    completed = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                completed.setdefault(t.task_id, t.assigned_agent)
    s = bus.stats()
    return {"completed": completed, "sent": s["sent"],
            "delivered": s["delivered"], "drops": s["drop_reasons"]}


def test_all_four_conditions_run():
    for name in cc.ORDER:
        r = _replay(name)
        assert r["sent"] > 0, name


def test_each_condition_is_reproducible():
    """Same seed, same condition, byte-identical delivery outcome."""
    for name in cc.ORDER:
        a, b = _replay(name), _replay(name)
        assert a == b, f"{name} was not reproducible"


def test_conditions_differ_from_each_other():
    """If they all behaved the same, the study would prove nothing."""
    nominal = _replay("nominal")
    severe = _replay("severe")
    assert severe["delivered"] / severe["sent"] < \
        nominal["delivered"] / nominal["sent"]


def test_partition_shows_up_as_partition_drops():
    r = _replay("partitioned")
    assert r["drops"].get("partitioned", 0) > 0


def test_degradation_does_not_break_the_mission():
    """The architecture should still complete the work under every condition -
    that is the result the later comparison rests on."""
    for name in cc.ORDER:
        r = _replay(name)
        assert len(r["completed"]) == 4, (name, r["completed"])


if __name__ == "__main__":
    tests = [
        ("zero-loss profile drops nothing", test_zero_loss_profile_drops_nothing),
        ("empirical loss ≈ 10%", test_empirical_loss_matches_configured_10_percent),
        ("empirical loss ≈ 30%", test_empirical_loss_matches_configured_30_percent),
        ("loss scales monotonically", test_loss_scales_monotonically),
        ("empirical latency matches distribution",
         test_empirical_latency_matches_the_distribution),
        ("latency is never negative", test_latency_is_never_negative),
        ("zero jitter = constant latency", test_zero_jitter_gives_constant_latency),
        ("partition blocks only across the split",
         test_partition_blocks_only_across_the_split),
        ("partition cuts far group off from base",
         test_partition_cuts_the_far_group_off_from_base),
        ("expired message is not delivered", test_expired_message_is_not_delivered),
        ("TTL varies by message type", test_message_ttl_varies_by_type),
        ("send uses per-type TTL by default",
         test_link_send_uses_the_per_type_ttl_by_default),
        ("same seed = identical behaviour",
         test_same_seed_gives_identical_network_behaviour),
        ("different seeds differ", test_different_seeds_give_different_behaviour),
        ("reset restores the sequence", test_reset_restores_the_same_sequence),
        ("range blocks distant pairs", test_range_blocks_distant_pairs),
        ("rate limit caps messages/sec", test_rate_limit_caps_messages_per_second),
        ("bandwidth cap blocks traffic", test_bandwidth_cap_blocks_oversized_traffic),
        ("asymmetric link degrades one direction",
         test_asymmetric_link_degrades_one_direction_only),
        ("interference zone degrades links inside",
         test_interference_zone_degrades_links_inside_it),
        ("burst loss drops a run", test_burst_loss_drops_a_run_of_messages),
        ("estimator approximates real loss",
         test_estimator_approximates_the_real_loss_rate),
        ("estimator measures information age", test_estimator_measures_information_age),
        ("estimator never touches the config",
         test_estimator_never_touches_the_network_config),
        ("agents notice degradation unaided",
         test_agents_notice_degradation_without_being_told),
        ("all four conditions run", test_all_four_conditions_run),
        ("each condition is reproducible", test_each_condition_is_reproducible),
        ("conditions differ from each other", test_conditions_differ_from_each_other),
        ("partition shows up as partition drops",
         test_partition_shows_up_as_partition_drops),
        ("mission completes under every condition",
         test_degradation_does_not_break_the_mission),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
