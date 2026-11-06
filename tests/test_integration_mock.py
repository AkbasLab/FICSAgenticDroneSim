#!/usr/bin/env python3
"""AUV-15's seven integration scenarios (16.2), each one mock flight, each named as the plan names it.

    python -m unittest discover -s tests -p test_integration_mock.py

WHY THESE EXIST
---------------
AUV-15, 16.2: "two agents allocate two tasks; four agents allocate four
tasks; one agent disappears and its task is reassigned; a partition divides
the team; delayed claims create a conflict and are resolved; the relay agent
fails and another agent assumes the role; malformed LLM output triggers
fallback." The vault note adds: "This list *is* the research contribution,
tested." Each behaviour is also held by its phase's exit (8, 9, 10, 12); here
each is one named test on one flight, with no simulator, in seconds, so 16.2
can be read straight off the suite and a regression in any of them fails a
test with the scenario's own name.
"""

import dataclasses
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentic_uav.core.messages import MessageType  # noqa: E402
from agentic_uav.experiments.allocation import contested, fly_team_on_mock, load_allocation  # noqa: E402
from agentic_uav.experiments.architecture import fly_architecture, load_architecture  # noqa: E402
from agentic_uav.experiments.conditions import load_network  # noqa: E402
from agentic_uav.experiments.guardian_exit import load_guardian  # noqa: E402
from agentic_uav.experiments.recovery import fly_recovery_on_mock, load_recovery  # noqa: E402
from agentic_uav.experiments.scenarios import load_scenario  # noqa: E402
from agentic_uav.coordination.keepout import KeepOutConfig  # noqa: E402

ALLOC, HEALTH = load_allocation(), load_recovery()
PAIR, FOUR = load_scenario("search_pair_001"), load_scenario("search_relay_001")


def seeded(scenario, seed=1):
    return dataclasses.replace(scenario, random_seed=seed)


def sectors(scenario):
    return {f"search {s.id}" for s in scenario.sectors}


def searched_by(run):
    return {t: d for d, ts in run.searched.items() for t in ts}


class IntegrationScenarios(unittest.TestCase):

    def test_1_two_agents_allocate_two_tasks(self):
        run = fly_recovery_on_mock(seeded(PAIR), ALLOC, HEALTH, "pair")
        self.assertTrue(run.met)
        who = searched_by(run)
        self.assertEqual(set(who), sectors(PAIR))                        # both tasks done
        self.assertEqual(len(set(who.values())), 2)                       # by two different drones
        self.assertEqual(sum(len(ts) for ts in run.searched.values()), 2)  # each once

    def test_2_four_agents_allocate_four_tasks(self):
        run = fly_recovery_on_mock(seeded(FOUR), ALLOC, HEALTH, "four")
        self.assertTrue(run.met)
        who = searched_by(run)
        self.assertEqual(set(who), sectors(FOUR))
        self.assertEqual(len(set(who.values())), 4)
        self.assertEqual(sum(len(ts) for ts in run.searched.values()), 4)

    def test_3_one_agent_disappears_and_its_task_is_reassigned(self):
        nominal = searched_by(fly_recovery_on_mock(seeded(FOUR), ALLOC, HEALTH, "no stop"))
        lost = next(t for t, d in nominal.items() if d == "Drone1")
        run = fly_recovery_on_mock(seeded(FOUR), ALLOC, HEALTH, "Drone1 stopped", {"Drone1": 60.0})
        self.assertTrue(run.met)
        self.assertIn("Drone1", run.stopped)
        self.assertNotIn(lost, run.searched.get("Drone1", []))
        self.assertIn(lost, {t for d, ts in run.searched.items() if d != "Drone1" for t in ts})   # someone else

    def test_4_a_partition_divides_the_team(self):
        net = load_network("partitioned")
        run = fly_recovery_on_mock(seeded(FOUR), ALLOC, HEALTH, "partitioned", network=net)
        part = net.partitions[0]
        groups = [set(g) for g in part.groups]
        cut = [d for d in run.team.deliveries if d.status == "partitioned"]
        self.assertTrue(cut)                                              # it divided them
        for d in cut:                                                     # only across, only while in force
            self.assertTrue(part.start_s <= d.sent_at <= part.end_s)
            self.assertFalse(any({d.message.sender_id, d.recipient} <= g for g in groups))
        across = [d for d in run.team.deliveries if d.status == "delivered" and part.start_s < d.sent_at < part.end_s
                  and not any({d.message.sender_id, d.recipient} <= g for g in groups)]
        self.assertEqual(across, [])
        self.assertTrue(run.met)                                          # and the team still met the mission

    def test_5_delayed_claims_create_a_conflict_and_are_resolved(self):
        # No bid window: every drone claims at once, before any bid can arrive. Unlimited radio, as in Phase 8,
        # so the conflict is the only thing that differs from the deliberating flight.
        run = fly_team_on_mock(seeded(FOUR), contested(ALLOC), "contested", range_m=None)
        corrections = [c for n in run.nets.values() for c in n["corrections"]]
        self.assertTrue(corrections)                                      # claims crossed: a conflict
        self.assertTrue(all(c["rule"] for c in corrections))              # settled by a rule
        calm = fly_team_on_mock(seeded(FOUR), ALLOC, "deliberating", range_m=None)
        self.assertEqual(run.searched, calm.searched)                     # to the same division
        self.assertTrue(run.met)

    def test_6_the_relay_agent_fails_and_another_agent_assumes_the_role(self):
        # Drone3 stops at 100 s; Drone4, free, bridges toward it (RELAY at 118.5 s) and is itself stopped at 119 s,
        # while relaying. Another drone must take the role.
        run = fly_recovery_on_mock(seeded(FOUR), ALLOC, HEALTH, "relay lost", {"Drone3": 100.0, "Drone4": 119.0})
        relay = lambda d: [c for c in run.policies[d]["roles"]["log"] if c["after"] == "relay"]  # noqa: E731
        self.assertTrue(relay("Drone4"))
        stop4 = run.stopped["Drone4"]
        role_at_stop = [c for c in run.policies["Drone4"]["roles"]["log"] if c["at"] <= stop4][-1]["after"]
        self.assertEqual(role_at_stop, "relay")                            # it failed as the relay
        after = [(d, c["at"]) for d in ("Drone1", "Drone2") for c in relay(d) if c["at"] > stop4]
        self.assertTrue(after, "no other drone took the relay role")
        announced = [m for m in {x.message.message_id: x.message for x in run.team.deliveries}.values()
                     if m.message_type is MessageType.ROLE_CHANGE and m.payload["role"] == "relay"
                     and m.sender_id in ("Drone1", "Drone2") and m.timestamp > stop4]
        self.assertTrue(announced)                                        # and said so
        self.assertTrue(run.met)

    def test_7_malformed_llm_output_triggers_fallback(self):
        def garbage(request):
            return '{"tool": "start_search", "parameters": '                  # cut off: not JSON
        ko = KeepOutConfig(5.0, 10.0, 3.0)
        f = fly_architecture(load_architecture("D"), PAIR, 1, ALLOC, HEALTH, load_guardian(), ko, ask=garbage)
        kinds = [e["kind"] for log in f.llm.values() for e in log["log"] if e["kind"] != "procedural"]
        self.assertTrue(kinds)
        self.assertEqual(set(kinds), {"fallback"})                        # every model decision fell back
        self.assertTrue(all(e["problems"] for log in f.llm.values() for e in log["log"] if e["kind"] == "fallback"))
        c = fly_architecture(load_architecture("C"), PAIR, 1, ALLOC, HEALTH, load_guardian(), ko)
        self.assertEqual(f.run.searched, c.run.searched)                  # the rule policy flew it
        self.assertTrue(f.run.met)


if __name__ == "__main__":
    unittest.main()
