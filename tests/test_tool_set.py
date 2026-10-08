"""The fifteen-tool set (Plan.docx 12.2). What has to hold: the registry is exactly the plan's
fifteen; CODE decides which tools are on the menu (so most are unavailable most of the time);
every value a model supplies is checked against what was offered; every message a tool sends
is built by code, never authored by the model; and a hard cap means no model can loop.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fics_drone.agents import persistent_agent
from fics_drone.agents.belief import Belief
from fics_drone.agents.belief_schema import (MissionBelief, Provenance, SelfState, TargetSighting,
                                             TeammateRecord)
from fics_drone.agents.decision_schema import DecisionRejected, RejectionKind, decision_json, parse_decision
from fics_drone.agents.llm_backends import ScriptedBackend
from fics_drone.agents.llm_policy import LLMAgentPolicy, make_policy_factory
from fics_drone.agents.llm_tools import BY_NAME, MAX_MODEL_ACTIONS, ROLES, TOOLS, offered_tools
from fics_drone.agents.objectives import Objective, ReplanEvent
from fics_drone.agents.ollama_backend import DECISION_SCHEMA
from fics_drone.agents.persistent_agent import PersistentAgent
from fics_drone.coordination.bidding import compute_bid
from fics_drone.coordination.message_bus import AgentLink, MessageBus
from fics_drone.coordination.protocols import MessageType
from fics_drone.coordination.roles import HealthMonitor
from fics_drone.coordination.tasks import TaskBoard, TaskStatus
from fics_drone.core.scenario import load_scenario
from fics_drone.experiments.team_runner import run_team_with_faults
from fics_drone.simulator.kinematic_mock_adapter import KinematicMockVehicleAdapter

SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "missions", "search_relay_001.json")
PLAN_TOOLS = {"accept_task", "decline_task", "compute_task_cost", "announce_task", "send_bid", "claim_task",
              "release_task", "change_role", "request_help", "report_target", "start_search",
              "go_to_waypoint", "act_as_relay", "return_home", "hold"}
LISTEN_CAP = 3


def _belief(teammates=(), view=(), phase="listening", rounds=1, role="scout", actions=0, queue=0):
    b = Belief(self_state=SelfState(position=(0.0, 0.0, 8.0), elapsed_s=0.0, battery_s=300.0),
               mission=MissionBelief(sector_id="C", search_queue=[object()] * queue))
    b.phase, b.listen_rounds = phase, rounds
    b.self_state.role, b.self_state.model_actions = role, actions
    for name in teammates:
        b.team.teammates[name] = TeammateRecord(name, (10.0, 10.0, 8.0), Provenance(timestamp=0.0, source="heartbeat"))
    b.team.task_view = list(view)
    return b


def _offer(b, **kw):
    return offered_tools(b, listen_cap=LISTEN_CAP, **kw)


VIEW = [("search_A", "A", "complete", "Drone1"), ("search_B", "B", "unheld", None),
        ("search_C", "C", "mine", "Drone3"), ("search_D", "D", "held", "Drone4")]


class TestRegistry(unittest.TestCase):
    def test_it_is_exactly_the_plans_fifteen_tools(self):
        self.assertEqual(len(TOOLS), 15)
        self.assertEqual({t.name for t in TOOLS}, PLAN_TOOLS)
        self.assertEqual(set(BY_NAME), PLAN_TOOLS)

    def test_progress_tools_are_free_and_everything_else_costs_an_action(self):
        self.assertEqual({t.name for t in TOOLS if t.free}, {"report_target", "start_search", "return_home"})

    def test_every_coordination_tool_maps_to_the_single_tool_action_objective(self):
        for name in ("accept_task", "decline_task", "compute_task_cost", "announce_task", "send_bid", "claim_task",
                     "release_task", "change_role", "request_help", "act_as_relay"):
            self.assertEqual(BY_NAME[name].objective, Objective.TOOL_ACTION, name)
        self.assertEqual(BY_NAME["hold"].objective, Objective.LISTEN)
        self.assertEqual(BY_NAME["start_search"].objective, Objective.SEARCH_SECTOR)
        self.assertEqual(BY_NAME["report_target"].objective, Objective.REPORT)

    def test_the_decoder_schema_names_exactly_these_tools(self):
        self.assertEqual(set(DECISION_SCHEMA["properties"]["selected_tool"]["enum"]), PLAN_TOOLS)
        params = DECISION_SCHEMA["properties"]["parameters"]["properties"]
        self.assertEqual(set(params), {"reason_code", "x", "y", "task_id", "target_id", "new_role", "recipients"})
        self.assertEqual(set(params["new_role"]["enum"]), set(ROLES))


class TestTheMenuIsOwnedByCode(unittest.TestCase):
    def test_a_lone_drone_with_no_tasks_gets_only_the_basics(self):
        o = _offer(_belief())
        self.assertEqual(set(o), {"return_home", "hold", "go_to_waypoint", "change_role"})
        self.assertEqual(set(o["change_role"]["new_role"]), set(ROLES) - {"scout"})

    def test_teammates_unlock_relay_and_help(self):
        o = _offer(_belief(teammates=("Drone1", "Drone2")))
        self.assertIn("act_as_relay", o)
        self.assertEqual(o["request_help"]["recipients"], ("Drone1", "Drone2"))

    def test_task_tools_only_appear_when_a_task_is_in_a_suitable_state(self):
        o = _offer(_belief(teammates=("Drone1",), view=VIEW))
        self.assertEqual(o["claim_task"]["task_id"], ("search_B",))                 # only the unheld one
        self.assertEqual(set(o["compute_task_cost"]["task_id"]), {"search_B", "search_C", "search_D"})  # not complete
        self.assertEqual(o["release_task"]["task_id"], ("search_C",))               # only mine
        self.assertEqual(o["announce_task"]["task_id"], ("search_C",))
        for absent in ("send_bid", "accept_task", "decline_task", "report_target", "start_search"):
            self.assertNotIn(absent, o)

    def test_announce_needs_someone_to_announce_to(self):
        self.assertNotIn("announce_task", _offer(_belief(view=VIEW)))
        self.assertIn("release_task", _offer(_belief(view=VIEW)))

    def test_send_bid_needs_an_announced_task_that_is_not_mine_and_not_already_bid_on(self):
        b = _belief(teammates=("Drone4",), view=VIEW)
        b.communication.announced_tasks = [("search_D", "Drone4", 0.0)]
        self.assertEqual(_offer(b)["send_bid"]["task_id"], ("search_D",))
        b.communication.bids_sent = ["search_D"]
        self.assertNotIn("send_bid", _offer(b))
        b.communication.bids_sent = []
        b.communication.announced_tasks = [("search_C", "Drone1", 0.0)]    # one I hold myself
        self.assertNotIn("send_bid", _offer(b))

    def test_accept_and_decline_need_a_task_released_to_me_that_is_still_unheld(self):
        b = _belief(teammates=("Drone1",), view=VIEW)
        b.communication.offers_to_me = [("search_B", "Drone1", 0.0)]
        o = _offer(b)
        self.assertEqual((o["accept_task"]["task_id"], o["decline_task"]["task_id"]),
                         (("search_B",), ("search_B",)))
        b.team.task_view = [(t, s, "held" if t == "search_B" else st, "Drone2" if t == "search_B" else h)
                            for t, s, st, h in VIEW]     # someone else took it meanwhile
        o = _offer(b)
        self.assertNotIn("accept_task", o)
        self.assertNotIn("decline_task", o)

    def test_report_target_needs_a_sensed_target_not_yet_reported(self):
        b = _belief()
        b.mission.targets_known["T1"] = TargetSighting("T1", (1.0, 1.0, 8.0), 0.0, confirmed=False, source="sensor")
        self.assertEqual(_offer(b)["report_target"]["target_id"], ("T1",))
        b.mission.targets_known["T1"].confirmed = True
        self.assertNotIn("report_target", _offer(b))
        b.mission.targets_known["T2"] = TargetSighting("T2", (1.0, 1.0, 8.0), 0.0, confirmed=True, source="message")
        self.assertNotIn("report_target", _offer(b))       # second-hand: nothing of mine to report

    def test_start_search_needs_a_sector_to_search(self):
        self.assertNotIn("start_search", _offer(_belief()))
        self.assertIn("start_search", _offer(_belief(queue=5)))

    def test_only_a_scout_scouts(self):
        b = _belief(teammates=("Drone4",), view=VIEW, role="relay")
        b.communication.announced_tasks = [("search_D", "Drone4", 0.0)]
        b.communication.offers_to_me = [("search_B", "Drone1", 0.0)]
        o = _offer(b)
        for absent in ("claim_task", "send_bid", "accept_task"):
            self.assertNotIn(absent, o)
        self.assertIn("decline_task", o)                      # turning work down is always allowed
        self.assertEqual(set(o["change_role"]["new_role"]), {"scout", "reserve"})

    def test_a_declined_task_is_never_offered_for_claiming(self):
        b = _belief(view=VIEW)
        b.communication.declined_tasks = ["search_B"]
        self.assertNotIn("claim_task", _offer(b))

    def test_the_action_cap_leaves_only_the_progress_tools(self):
        b = _belief(teammates=("Drone1",), view=VIEW, queue=3, actions=MAX_MODEL_ACTIONS)
        b.mission.targets_known["T1"] = TargetSighting("T1", (1.0, 1.0, 8.0), 0.0, confirmed=False, source="sensor")
        self.assertEqual(set(_offer(b)), {"return_home", "start_search", "report_target"})

    def test_exhausted_listen_rounds_remove_only_the_waiting_tools(self):
        o = _offer(_belief(teammates=("Drone1",), view=VIEW, rounds=LISTEN_CAP))
        for gone in ("hold", "act_as_relay", "go_to_waypoint"):
            self.assertNotIn(gone, o)
        self.assertIn("claim_task", o)

    def test_waypoints_can_be_switched_off(self):
        self.assertNotIn("go_to_waypoint", _offer(_belief(), waypoints_enabled=False))


class TestParametersAreCheckedAgainstTheOffer(unittest.TestCase):
    OFFER = {"claim_task": {"task_id": ("search_B",)}, "request_help": {"recipients": ("Drone1", "Drone2")},
             "change_role": {"new_role": ("relay", "reserve")}, "report_target": {"target_id": ("T1",)},
             "return_home": {}}

    def _kind(self, raw):
        with self.assertRaises(DecisionRejected) as ctx:
            parse_decision(raw, self.OFFER, ["Drone1", "Drone2"])
        return ctx.exception.kind, ctx.exception.detail

    def test_valid_parameters_are_returned_as_validated_args(self):
        d = parse_decision(decision_json("claim_task", params={"task_id": "search_B"}), self.OFFER, [])
        self.assertEqual((d.tool, d.args, d.objective), ("claim_task", {"task_id": "search_B"}, Objective.TOOL_ACTION))
        d = parse_decision(decision_json("request_help", params={"recipients": ["Drone2"]}), self.OFFER, [])
        self.assertEqual(d.args, {"recipients": ("Drone2",)})

    def test_a_task_id_that_was_not_offered_is_rejected_and_the_valid_ones_are_named(self):
        kind, detail = self._kind(decision_json("claim_task", params={"task_id": "search_Z"}))
        self.assertEqual(kind, RejectionKind.BAD_FIELDS)
        self.assertIn("search_B", detail)

    def test_a_real_tool_that_is_not_on_the_menu_is_unknown(self):
        self.assertEqual(self._kind(decision_json("release_task", params={"task_id": "search_C"}))[0],
                         RejectionKind.UNKNOWN_OBJECTIVE)

    def test_bad_recipients_roles_and_targets_are_rejected(self):
        for raw in (decision_json("request_help", params={"recipients": ["Drone99"]}),
                    decision_json("request_help", params={"recipients": []}),
                    decision_json("request_help", params={"recipients": ["Drone1", "Drone1"]}),
                    decision_json("request_help", params={"recipients": "Drone1"}),
                    decision_json("change_role", params={"new_role": "scout"}),       # already one; not offered
                    decision_json("change_role", params={"new_role": "commander"}),
                    decision_json("report_target", params={"target_id": "T9"})):
            self.assertEqual(self._kind(raw)[0], RejectionKind.BAD_FIELDS, raw)

    def test_missing_or_extra_parameters_are_rejected(self):
        self.assertEqual(self._kind(decision_json("claim_task"))[0], RejectionKind.BAD_FIELDS)
        self.assertEqual(self._kind(decision_json("return_home", params={"task_id": "search_B"}))[0],
                         RejectionKind.BAD_FIELDS)
        self.assertEqual(self._kind(decision_json("claim_task", params={"task_id": "search_B", "bid": 0.1}))[0],
                         RejectionKind.BAD_FIELDS)    # a model can never name its own bid


class TestBoardRelease(unittest.TestCase):
    def _board(self):
        b = TaskBoard(load_scenario(SCENARIO_PATH))
        b.apply_claim("search_C", "Drone3", 5.0, 1)
        return b

    def test_the_holder_can_release_and_the_version_keeps_counting_up(self):
        b = self._board()
        v = b.release("search_C", "Drone3")
        self.assertEqual(v, 2)
        t = b.tasks["search_C"]
        self.assertEqual((t.status, t.assignee, t.winning_bid), (TaskStatus.OPEN, None, None))

    def test_only_the_holder_can_release_and_never_a_complete_task(self):
        b = self._board()
        self.assertIsNone(b.release("search_C", "Drone1"))
        self.assertEqual(b.tasks["search_C"].assignee, "Drone3")
        b.mark_complete("search_C", "Drone3")
        self.assertIsNone(b.release("search_C", "Drone3"))

    def test_a_forged_or_stale_release_cannot_free_someone_elses_work(self):
        b = self._board()
        self.assertFalse(b.apply_release("search_C", "Drone1", 5))     # sender is not the holder
        self.assertFalse(b.apply_release("search_C", "Drone3", 1))     # not newer than what we know
        self.assertFalse(b.apply_release("search_Z", "Drone3", 5))     # no such task
        self.assertEqual(b.tasks["search_C"].assignee, "Drone3")
        self.assertTrue(b.apply_release("search_C", "Drone3", 2))
        self.assertEqual(b.tasks["search_C"].status, TaskStatus.OPEN)

    def test_a_reclaim_after_a_release_beats_a_stale_claim_still_in_flight(self):
        b = self._board()
        b.release("search_C", "Drone3")
        self.assertTrue(b.apply_claim("search_C", "Drone1", 9.0, b.next_version("search_C")))
        self.assertFalse(b.apply_claim("search_C", "Drone3", 1.0, 1))   # the old claim, arriving late


def _agent(name="Drone3", offset=(20.0, 0.0, 0.0), sector="C", bus=None):
    scenario = load_scenario(SCENARIO_PATH)
    bus = bus or MessageBus()
    agent = PersistentAgent(KinematicMockVehicleAdapter(name), scenario, sector, offset, 300.0, drone_name=name,
                            link=AgentLink(bus, name), task_board=TaskBoard(scenario),
                            health_monitor=HealthMonitor(2.0))
    return agent


def _use(agent, tool, **args):
    agent._pending_action = (tool, {"reason_code": "search_elsewhere", **args})
    return agent._execute_tool()


def _inbox(agent):
    return agent.link.receive_available()


def _hold(agent, task_id="search_C", bid=5.0, version=1):
    """Give `agent` a claim on a task, as allocation would have."""
    agent.task_board.apply_claim(task_id, agent.drone_name, bid, version, now=0.0, lease_s=300.0)


class TestEachHandler(unittest.TestCase):
    def setUp(self):
        self.bus = MessageBus()
        self.me, self.peer = _agent("Drone3", bus=self.bus), _agent("Drone1", (0.0, 0.0, 0.0), "A", self.bus)

    def test_change_role_updates_the_role_and_the_heartbeat_reports_it(self):
        self.assertEqual(_use(self.me, "change_role", new_role="reserve"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(self.me.belief.self_state.role, "reserve")
        hb = [m for m in _inbox(self.peer) if m.type == MessageType.HEARTBEAT]
        self.assertEqual(hb[-1].payload["role"], "reserve")

    def test_act_as_relay_sets_the_role_holds_and_uses_a_round(self):
        with mock.patch.object(persistent_agent, "LISTEN_HOLD_S", 0.2):
            self.assertEqual(_use(self.me, "act_as_relay"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual((self.me.belief.self_state.role, self.me.belief.listen_rounds), ("relay", 1))

    def test_request_help_sends_one_code_built_message_to_the_named_teammates_only(self):
        self.assertEqual(_use(self.me, "request_help", recipients=("Drone1",), reason_code="teammate_may_need_help"),
                         ReplanEvent.SKILL_SUCCEEDED)
        got = [m for m in _inbox(self.peer) if m.type == MessageType.HELP_REQUEST]
        self.assertEqual([(m.sender, m.payload) for m in got], [("Drone3", {"reason_code": "teammate_may_need_help"})])

    def test_compute_task_cost_is_the_deterministic_bid_and_relays_cost_more(self):
        scenario = load_scenario(SCENARIO_PATH)
        _use(self.me, "compute_task_cost", task_id="search_B")
        expected = compute_bid((20.0, 0.0), 1.0, 0, scenario.sector("B"))
        self.assertIn(f"{expected:.1f}", self.me.belief.self_state.last_tool_result)
        scout_cost = self.me._own_bid("search_B")
        self.me.belief.self_state.role = "relay"
        self.assertGreater(self.me._own_bid("search_B"), scout_cost)
        self.assertEqual([m for m in _inbox(self.peer) if m.type != MessageType.HEARTBEAT], [])   # a query sends nothing

    def test_announce_needs_to_hold_the_task_and_sends_only_its_id(self):
        self.assertEqual(_use(self.me, "announce_task", task_id="search_C"), ReplanEvent.SKILL_FAILED)   # not held
        self.assertEqual(_inbox(self.peer), [])
        _hold(self.me)
        self.assertEqual(_use(self.me, "announce_task", task_id="search_C"), ReplanEvent.SKILL_SUCCEEDED)
        sent = [m for m in _inbox(self.peer) if m.type == MessageType.TASK_ANNOUNCE]
        self.assertEqual([m.payload for m in sent], [{"task_id": "search_C"}])

    def test_send_bid_is_computed_by_code_and_goes_only_to_the_announcer(self):
        self.peer.task_board.apply_claim("search_A", "Drone1", 3.0, 1, now=0.0, lease_s=300.0)
        self.me.task_board.apply_claim("search_A", "Drone1", 3.0, 1, now=0.0, lease_s=300.0)
        self.assertEqual(_use(self.me, "send_bid", task_id="search_A"), ReplanEvent.SKILL_FAILED)  # never announced
        self.me.belief.communication.announced_tasks = [("search_A", "Drone1", 0.0)]
        self.assertEqual(_use(self.me, "send_bid", task_id="search_A"), ReplanEvent.SKILL_SUCCEEDED)
        bids = [m for m in _inbox(self.peer) if m.type == MessageType.TASK_BID]
        self.assertEqual(len(bids), 1)
        self.assertEqual(set(bids[0].payload), {"task_id", "bid"})
        self.assertAlmostEqual(bids[0].payload["bid"], self.me._own_bid("search_A"))
        self.assertEqual(self.me.belief.communication.bids_sent, ["search_A"])

    def test_claim_task_takes_an_unheld_task_queues_its_sector_and_tells_the_team(self):
        self.assertEqual(_use(self.me, "claim_task", task_id="search_B"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(self.me.task_board.tasks["search_B"].assignee, "Drone3")
        self.assertEqual(self.me.belief.mission.sector_id, "B")
        self.assertGreater(len(self.me.belief.mission.search_queue), 0)
        claims = [m for m in _inbox(self.peer) if m.type == MessageType.TASK_CLAIM]
        self.assertEqual([m.payload["task_id"] for m in claims], ["search_B"])

    def test_claim_task_refuses_a_task_someone_else_genuinely_holds(self):
        self.me.task_board.apply_claim("search_B", "Drone2", 4.0, 1, now=0.0, lease_s=300.0)
        self.assertEqual(_use(self.me, "claim_task", task_id="search_B"), ReplanEvent.SKILL_FAILED)
        self.assertEqual(self.me.task_board.tasks["search_B"].assignee, "Drone2")

    def test_accept_requires_an_offer_and_decline_blocks_the_deterministic_auto_claim_too(self):
        self.assertEqual(_use(self.me, "accept_task", task_id="search_B"), ReplanEvent.SKILL_FAILED)
        self.me.belief.communication.offers_to_me = [("search_B", "Drone1", 0.0)]
        self.assertEqual(_use(self.me, "decline_task", task_id="search_B"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(self.me.belief.communication.offers_to_me, [])
        self.assertIn("search_B", self.me.belief.communication.declined_tasks)
        # the deterministic orphan check honours the decline: B stays unclaimed (it would take B first otherwise)
        self.me.belief.mission.sector_id = "A"
        self.me._check_for_orphans()
        self.assertNotEqual(self.me.task_board.tasks["search_B"].assignee, "Drone3")

    def test_release_awards_the_lowest_bidder_deterministically(self):
        _hold(self.me)
        self.me.task_board.apply_bid("search_C", "Drone1", 7.0)
        self.me.task_board.apply_bid("search_C", "Drone2", 3.0)
        self.assertEqual(_use(self.me, "release_task", task_id="search_C"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(self.me.task_board.tasks["search_C"].status, TaskStatus.OPEN)
        rel = [m for m in _inbox(self.peer) if m.type == MessageType.TASK_RELEASE]
        self.assertEqual((rel[0].payload["awarded_to"], rel[0].payload["version"]), ("Drone2", 2))

    def test_releasing_the_sector_i_was_about_to_sweep_clears_my_queue(self):
        self.assertEqual(_use(self.me, "claim_task", task_id="search_B"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertGreater(len(self.me.belief.mission.search_queue), 0)
        _use(self.me, "release_task", task_id="search_B")
        self.assertEqual(self.me.belief.mission.search_queue, [])

    def test_report_target_reports_only_the_named_target(self):
        for tid in ("T1", "T2"):
            self.me.belief.mission.targets_known[tid] = TargetSighting(tid, (5.0, 5.0, 8.0), 0.0, source="sensor")
        self.me._pending_action = ("report_target", {"target_id": "T2", "reason_code": "my_work_is_done"})
        self.me._execute(Objective.REPORT, [])
        found = [m.payload["target_id"] for m in _inbox(self.peer) if m.type == MessageType.TARGET_FOUND]
        self.assertEqual(found, ["T2"])
        self.assertTrue(self.me.belief.mission.targets_known["T2"].confirmed)
        self.assertFalse(self.me.belief.mission.targets_known["T1"].confirmed)

    def test_a_tool_with_no_pending_action_does_nothing(self):
        self.me._pending_action = None
        self.assertEqual(self.me._execute_tool(), ReplanEvent.SKILL_FAILED)


class TestTheTaskMarketEndToEnd(unittest.TestCase):
    """announce -> bid -> release (to the best bidder) -> accept: a real in-flight contract-net,
    every message built by code, three independent boards converging."""

    def test_the_whole_negotiation(self):
        bus = MessageBus()
        a, b, c = _agent("Drone3", bus=bus), _agent("Drone1", (0, 0, 0), "A", bus), _agent("Drone2", (0, 20, 0), "B", bus)
        for ag in (a, b, c):                        # everyone's board agrees A holds search_C, as after allocation
            ag.task_board.apply_claim("search_C", "Drone3", 5.0, 1, now=0.0, lease_s=300.0)

        _use(a, "announce_task", task_id="search_C")
        b._observe_messages()
        c._observe_messages()
        self.assertEqual([t for t, _, _ in b.belief.communication.announced_tasks], ["search_C"])

        self.assertEqual(_use(b, "send_bid", task_id="search_C"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(_use(c, "send_bid", task_id="search_C"), ReplanEvent.SKILL_SUCCEEDED)
        a._observe_messages()
        bidders = {who for _, who, _, _ in a.belief.communication.bids_received}
        self.assertEqual(bidders, {"Drone1", "Drone2"})

        lowest = min(a.task_board.bids_for("search_C").items(), key=lambda kv: (kv[1], kv[0]))[0]
        _use(a, "release_task", task_id="search_C")
        for ag in (b, c):
            ag._observe_messages()
        self.assertEqual(b.task_board.tasks["search_C"].status, TaskStatus.OPEN)
        winner, loser = (b, c) if lowest == "Drone1" else (c, b)
        self.assertEqual([t for t, _, _ in winner.belief.communication.offers_to_me], ["search_C"])
        self.assertEqual(loser.belief.communication.offers_to_me, [])

        self.assertEqual(_use(winner, "accept_task", task_id="search_C"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(winner.task_board.tasks["search_C"].assignee, winner.drone_name)
        for ag in (a, loser):
            ag._observe_messages()
        for ag in (a, loser):                       # all three boards now agree who holds it
            self.assertEqual(ag.task_board.tasks["search_C"].assignee, winner.drone_name)
        self.assertEqual(loser.belief.communication.offers_to_me, [])


class TestPromptShowsTheMarket(unittest.TestCase):
    def _prompt(self, b, offered=None):
        backend = ScriptedBackend([decision_json("return_home")], respond=None)
        LLMAgentPolicy(backend).decide(b, ReplanEvent.SKILL_SUCCEEDED)
        return backend.prompts[0]

    def test_only_offered_tools_appear_and_valid_ids_are_listed(self):
        p = self._prompt(_belief(teammates=("Drone1",), view=VIEW))
        self.assertIn("- claim_task:", p)
        self.assertIn("search_B", p)
        for absent in ("- send_bid:", "- accept_task:", "- start_search:", "- report_target:"):
            self.assertNotIn(absent, p)
        self.assertIn("TASKS (as you currently see them)", p)

    def test_market_state_role_and_last_tool_result_are_shown(self):
        b = _belief(teammates=("Drone4",), view=VIEW, role="relay")
        b.communication.announced_tasks = [("search_D", "Drone4", 0.0)]
        b.communication.bids_received = [("search_C", "Drone1", 4.5, 0.0)]
        b.communication.offers_to_me = [("search_B", "Drone1", 0.0)]
        b.self_state.last_tool_result = "your cost for search_B is 41.2 (lower is better)"
        b.self_state.model_actions = 2
        p = self._prompt(b)
        for needle in ("TASK MARKET", "Drone4 announced search_D", "Drone1 bid 4.5 on search_C",
                       "Drone1 released search_B to you", "role: relay", "actions_used: 2 of 8",
                       "result_of_your_last_tool: your cost for search_B is 41.2"):
            self.assertIn(needle, p)

    def test_the_prompt_stays_bounded_however_busy_the_market_gets(self):
        def with_entries(n):
            b = _belief(teammates=("Drone1",), view=VIEW)
            b.communication.announced_tasks = [("search_D", "Drone4", 0.0)] * n
            b.communication.bids_received = [("search_C", "Drone1", 4.5, 0.0)] * n
            return len(self._prompt(b))
        # only the latest few are shown, so 500 entries cost exactly what 3 do
        self.assertEqual(with_entries(500), with_entries(3))


class TestPolicyWiring(unittest.TestCase):
    def test_a_claim_becomes_a_tool_action_with_validated_args(self):
        b = _belief(teammates=("Drone1",), view=VIEW)
        policy = LLMAgentPolicy(ScriptedBackend([decision_json("claim_task", "teammate_may_need_help",
                                                               params={"task_id": "search_B"})], respond=None))
        self.assertEqual(policy.decide(b, ReplanEvent.SKILL_SUCCEEDED), (Objective.TOOL_ACTION, "coordinating"))
        self.assertEqual(policy.take_action(), ("claim_task", {"task_id": "search_B",
                                                              "reason_code": "teammate_may_need_help"}))
        self.assertIsNone(policy.take_action())          # once

    def test_a_fallback_decision_carries_no_action(self):
        policy = LLMAgentPolicy(ScriptedBackend(["junk", "junk"], respond=None))
        policy.decide(_belief(), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(policy.records[0].source, "fallback")
        self.assertIsNone(policy.take_action())

    def test_the_policy_asks_again_at_the_coordinating_phase(self):
        backend = ScriptedBackend([decision_json("return_home")], respond=None)
        LLMAgentPolicy(backend).decide(_belief(phase="coordinating"), ReplanEvent.SKILL_SUCCEEDED)
        self.assertEqual(backend.calls, 1)

    def test_a_failed_tool_is_a_fact_not_a_judgment(self):
        backend = ScriptedBackend(respond=None)
        LLMAgentPolicy(backend).decide(_belief(phase="coordinating"), ReplanEvent.SKILL_FAILED)
        self.assertEqual(backend.calls, 0)

    def test_holding_an_unsearched_sector_means_search_it_if_the_model_does_not(self):
        policy = LLMAgentPolicy(ScriptedBackend(["junk", "junk"], respond=None))
        self.assertEqual(policy.decide(_belief(phase="coordinating", queue=4), ReplanEvent.SKILL_SUCCEEDED),
                         (Objective.SEARCH_SECTOR, "searching"))


class TestNoModelCanLoop(unittest.TestCase):
    def test_a_model_that_never_stops_using_tools_is_cut_off_and_the_drone_lands(self):
        """The model keeps asking for a free information tool forever. After MAX_MODEL_ACTIONS the tool
        leaves the menu, its answers are rejected, the fallback takes over - and the mission ends."""
        scenario = load_scenario(SCENARIO_PATH)
        agent = _agent()
        asked = []

        def greedy(prompt):
            asked.append(prompt)
            return decision_json("compute_task_cost", params={"task_id": "search_B"})

        agent.policy = LLMAgentPolicy(ScriptedBackend(respond=greedy), sectors=scenario.sectors)
        with mock.patch.object(persistent_agent, "LISTEN_HOLD_S", 0.1):
            report = agent.run()
        self.assertEqual(agent.belief.self_state.model_actions, MAX_MODEL_ACTIONS)
        self.assertEqual(sum(1 for t in report.trace if t.endswith("->tool_action")), MAX_MODEL_ACTIONS)
        self.assertTrue(report.trace[-1].endswith("->done"))
        self.assertIn("land", " ".join(report.trace))

    def test_claim_then_release_forever_still_terminates(self):
        scenario = load_scenario(SCENARIO_PATH)
        agent = _agent()
        flip = {"n": 0}

        def churn(prompt):
            flip["n"] += 1
            if "- release_task:" in prompt:
                return decision_json("release_task", params={"task_id": "search_B"})
            return decision_json("claim_task", params={"task_id": "search_B"})

        agent.policy = LLMAgentPolicy(ScriptedBackend(respond=churn), sectors=scenario.sectors)
        with mock.patch.object(persistent_agent, "LISTEN_HOLD_S", 0.1):
            report = agent.run()
        self.assertLessEqual(agent.belief.self_state.model_actions, MAX_MODEL_ACTIONS)
        self.assertTrue(report.trace[-1].endswith("->done"))


class TestModelDrivenRecovery(unittest.TestCase):
    def test_survivors_finish_a_dead_drones_sector_using_the_models_own_claim_tool(self):
        """Phase 9's recovery, but the pickup is now a MODEL decision: claim_task when it is offered,
        wait otherwise. No deterministic orphan check is involved on the model path."""
        def respond(prompt):
            import re
            claim = re.search(r"- claim_task:.*?one of \['([^']+)'", prompt)
            if claim:
                return decision_json("claim_task", params={"task_id": claim.group(1)})
            if "- hold:" in prompt:
                return decision_json("hold", "waiting_for_report")
            return decision_json("return_home")

        scenario = load_scenario(SCENARIO_PATH)
        adapters = {d.name: KinematicMockVehicleAdapter(d.name, speed_mps=25.0) for d in scenario.drones}
        factory, policies = make_policy_factory(ScriptedBackend(respond=respond), scenario)
        reports, agents, _, _ = run_team_with_faults(
            scenario, adapters, bus=MessageBus(), kill_name="Drone2", kill_at_s=0.0, heartbeat_interval_s=2.0,
            policy_factory=factory)

        self.assertIn("killed", reports["Drone2"].trace[-1])
        completed = set()
        for n, a in agents.items():
            if n == "Drone2":
                continue
            completed |= {t.sector_id for t in a.task_board.tasks.values() if t.status == TaskStatus.COMPLETE}
        self.assertEqual(completed, {s.id for s in scenario.sectors})
        claims = [r for p in policies.values() for r in p.records if r.tool == "claim_task"]
        self.assertGreater(len(claims), 0, "the recovery must have come from the model's claim_task")
        for n, rep in reports.items():
            if n != "Drone2":
                self.assertTrue(rep.trace[-1].endswith("->done"), n)


if __name__ == "__main__":
    unittest.main()
