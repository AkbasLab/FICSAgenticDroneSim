"""Phase 7 tests: the message protocol under perfect communication.

The containment tests matter most. A message bus that agents can reach around is
worse than no bus at all, because the resulting coordination results would look
good for the wrong reason. These check behaviourally that an agent cannot read
another agent's mail, cannot see messages still in flight, and cannot learn about
a teammate except by having a message delivered to it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination.message_bus import AgentLink, MessageBus
from agentic_uav.coordination.protocols import AgentMessage, MessageType
from agentic_uav.experiments.team_runner import build_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

SCENARIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "configs", "missions", "search_relay_001.yaml")


def _team(latency_s=0.0, loss_rate=0.0, rng=None):
    scenario = load_scenario(SCENARIO)
    return build_team(scenario, lambda vid: MockVehicleAdapter(0.0),
                      latency_s=latency_s, loss_rate=loss_rate, rng=rng)


# --- 7.1 / 7.2 envelope ---

def test_envelope_has_required_fields():
    m = AgentMessage(message_type=MessageType.HEARTBEAT, sender_id="Drone1",
                     recipient_ids=["Drone2"], mission_id="m1", timestamp=5.0,
                     sequence_number=3, time_to_live_s=30.0,
                     payload={"status": "ok"}, confidence=0.9)
    for f in ["message_id", "message_type", "sender_id", "recipient_ids",
              "mission_id", "timestamp", "sequence_number", "time_to_live_s",
              "payload", "confidence"]:
        assert hasattr(m, f), f
    assert m.message_id                      # auto-assigned
    assert m.expires_at == 35.0
    assert not m.expired(34.0) and m.expired(35.0)
    assert m.size_bytes() > 0


def test_all_thirteen_message_types_exist():
    expected = {"HEARTBEAT", "STATUS_UPDATE", "TASK_ANNOUNCEMENT", "TASK_BID",
                "TASK_AWARD", "TASK_ACCEPT", "TASK_RELEASE", "TASK_COMPLETE",
                "INTENT_UPDATE", "TARGET_FOUND", "HELP_REQUEST", "ROLE_CHANGE",
                "MISSION_UPDATE"}
    assert expected <= set(MessageType.__members__)


def test_addressing_rules():
    m = AgentMessage(MessageType.HEARTBEAT, sender_id="Drone1",
                     recipient_ids=["Drone2"])
    assert m.addressed_to("Drone2")
    assert not m.addressed_to("Drone3")
    assert not m.addressed_to("Drone1")      # never delivered back to sender
    b = AgentMessage(MessageType.HEARTBEAT, sender_id="Drone1")   # broadcast
    assert b.addressed_to("Drone2") and b.addressed_to("Drone3")
    assert not b.addressed_to("Drone1")


# --- 7.3 no hidden global communication ---

def test_link_exposes_only_send_and_receive():
    bus = MessageBus()
    link = bus.register("Drone1")
    public = [a for a in dir(link) if not a.startswith("_")]
    assert sorted(public) == ["receive_available", "send"], public


def test_agent_cannot_read_another_agents_mail():
    bus = MessageBus()
    a = bus.register("Drone1")
    b = bus.register("Drone2")
    c = bus.register("Drone3")
    a.send(MessageType.STATUS_UPDATE, {"secret": 1}, recipients=["Drone2"], now=0.0)
    assert len(b.receive_available(now=0.0)) == 1
    assert c.receive_available(now=0.0) == []    # not addressed to Drone3


def test_agent_cannot_see_messages_still_in_flight():
    bus = MessageBus(latency_s=10.0)
    a = bus.register("Drone1")
    b = bus.register("Drone2")
    a.send(MessageType.HEARTBEAT, {"status": "ok"}, now=0.0)
    assert b.receive_available(now=5.0) == []    # still in flight
    assert bus.in_flight_count() == 1            # visible to the sim, not the agent
    assert len(b.receive_available(now=10.0)) == 1


def test_expired_message_is_never_delivered():
    bus = MessageBus(latency_s=5.0)
    a = bus.register("Drone1")
    b = bus.register("Drone2")
    a.send(MessageType.HEARTBEAT, {"status": "ok"}, now=0.0, ttl_s=2.0)
    assert b.receive_available(now=20.0) == []
    entry = bus.log.entries[0]
    assert entry.dropped and entry.drop_reason == "expired_before_delivery"


def test_agent_holds_no_reference_to_the_bus_internals():
    agents, _tasks, _bus, _truth = _team()
    agent = agents[0]
    assert isinstance(agent.link, AgentLink)
    assert not hasattr(agent, "bus")
    # the link's own attributes are private and slot-limited
    assert AgentLink.__slots__ == ("_bus", "_vehicle_id", "_seq")


# --- 7.4 logging ---

def test_message_log_records_every_required_field():
    bus = MessageBus()
    a = bus.register("Drone1")
    bus.register("Drone2")
    a.send(MessageType.STATUS_UPDATE, {"x": 1}, now=3.0)
    e = bus.log.entries[0]
    for f in ["message_id", "message_type", "sender_id", "recipient_id",
              "created_at", "scheduled_delivery_at", "actual_delivery_at",
              "delivered", "dropped", "size_bytes", "expires_at",
              "influenced_decision"]:
        assert hasattr(e, f), f
    assert e.created_at == 3.0
    assert e.scheduled_delivery_at == 3.0        # perfect comms: no latency


def test_log_marks_messages_that_influenced_a_decision():
    agents, tasks, bus, _t = _team()
    run_team(agents, tasks, bus)
    influential = [e for e in bus.log.entries if e.influenced_decision]
    assert influential, "no message was ever credited to a decision"
    assert bus.stats()["influential"] == len(influential)


# --- exit criterion ---

def test_four_agents_exchange_heartbeats_and_status_while_flying():
    agents, tasks, bus, _t = _team()
    report = run_team(agents, tasks, bus)
    assert len(agents) == 4
    assert report.all_completed, {v: r.completed for v, r in report.agents.items()}

    by_type = bus.log.by_type()
    assert by_type["heartbeat"]["delivered"] > 0
    assert by_type["status_update"]["delivered"] > 0

    # every agent both sent and received
    for a in agents:
        sent = [e for e in bus.log.entries if e.sender_id == a.vehicle_id]
        got = [e for e in bus.log.entries
               if e.recipient_id == a.vehicle_id and e.delivered]
        assert sent, f"{a.vehicle_id} sent nothing"
        assert got, f"{a.vehicle_id} received nothing"


def test_team_belief_updates_only_when_messages_are_delivered():
    """The exit criterion's second half - and the strongest containment check.

    With the bus dropping everything, no agent may learn about any teammate,
    even though all four are flying the same mission at the same time.
    """
    # perfect comms: agents learn about each other
    agents, tasks, bus, _t = _team()
    run_team(agents, tasks, bus)
    for a in agents:
        assert a.belief.team.teammates, f"{a.vehicle_id} learned nothing"

    # total blackout: identical run, but nothing is delivered
    class Blackhole(MessageBus):
        def _drop(self):
            return True

    scenario = load_scenario(SCENARIO)
    agents2, tasks2, bus2, _t2 = build_team(
        scenario, lambda vid: MockVehicleAdapter(0.0))
    dead = Blackhole()
    for a in agents2:                       # swap in a bus that delivers nothing
        a.link = dead.register(a.vehicle_id)
        a._message_log = dead.log
    run_team(agents2, tasks2, dead)

    for a in agents2:
        assert not a.belief.team.teammates, (
            f"{a.vehicle_id} learned about teammates with no delivered messages: "
            f"{list(a.belief.team.teammates)}")
    assert dead.stats()["delivered"] == 0


def test_target_knowledge_spreads_only_by_message():
    """Drone2 searches S2, which has no target - it can only know about T1/T2
    because a teammate's TARGET_FOUND message reached it."""
    agents, tasks, bus, _t = _team()
    run_team(agents, tasks, bus)
    d2 = next(a for a in agents if a.vehicle_id == "Drone2")
    assert d2.belief.detections, "Drone2 learned no targets"
    # and it recorded that this was second-hand, not its own observation
    assert d2.belief.assumptions, "second-hand target not recorded as an assumption"
    assert any("reported by" in a.evidence for a in d2.belief.assumptions)


def test_run_is_deterministic():
    a1, t1, b1, _ = _team()
    r1 = run_team(a1, t1, b1)
    a2, t2, b2, _ = _team()
    r2 = run_team(a2, t2, b2)
    assert r1.message_stats["sent"] == r2.message_stats["sent"]
    assert r1.message_stats["delivered"] == r2.message_stats["delivered"]
    assert r1.sectors_searched == r2.sectors_searched
    assert r1.targets_found == r2.targets_found


if __name__ == "__main__":
    tests = [
        ("envelope has all required fields", test_envelope_has_required_fields),
        ("all 13 message types exist", test_all_thirteen_message_types_exist),
        ("addressing + broadcast rules", test_addressing_rules),
        ("link exposes only send/receive_available",
         test_link_exposes_only_send_and_receive),
        ("agent cannot read another agent's mail",
         test_agent_cannot_read_another_agents_mail),
        ("agent cannot see messages in flight",
         test_agent_cannot_see_messages_still_in_flight),
        ("expired message is never delivered",
         test_expired_message_is_never_delivered),
        ("agent holds no bus internals",
         test_agent_holds_no_reference_to_the_bus_internals),
        ("message log records every required field",
         test_message_log_records_every_required_field),
        ("log marks messages that influenced a decision",
         test_log_marks_messages_that_influenced_a_decision),
        ("4 agents exchange heartbeats + status while flying",
         test_four_agents_exchange_heartbeats_and_status_while_flying),
        ("team belief updates ONLY on delivered messages",
         test_team_belief_updates_only_when_messages_are_delivered),
        ("target knowledge spreads only by message",
         test_target_knowledge_spreads_only_by_message),
        ("run is deterministic", test_run_is_deterministic),
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
