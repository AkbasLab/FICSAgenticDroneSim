"""The model's closed tool set: the fifteen tools Plan.docx 12.2 names, no more.
The model selects one by name; it never writes Python, never emits an AirSim
call, and never authors a protocol message - every message a tool sends is
built by CODE from the agent's own board and belief.

Two properties make fifteen tools safe rather than a larger attack surface:

* CODE OFFERS THE MENU. `offered_tools()` decides, from belief alone, which tools
  are legal RIGHT NOW and which values each parameter may take (a task_id must be
  one the board actually shows in a suitable state; recipients must be known
  teammates). A tool whose preconditions don't hold is simply not on the menu, so
  most tools are unavailable most of the time - by design.
* A HARD CAP ENDS ANY LOOP. Every non-terminal tool costs one of MAX_MODEL_ACTIONS,
  and once they are spent only the terminal tools remain, so a model cannot
  claim/release/announce its way into an infinite loop. (return_home, start_search
  and report_target never cost an action: they make progress or end the mission.)

Dormant tools are real, not decorative: report_target is only offered while a
sensed target is still unreported, which the deterministic loop normally prevents
(a sensed target is reported immediately - a fact, not a judgment). It exists,
validates and executes; a normal mission just rarely reaches it.
"""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from ..coordination.roles import Role
from .objectives import Objective

MAX_MODEL_ACTIONS = 8

FLIGHT, COORDINATION, QUERY = "flight", "coordination", "query"
ROLES = tuple(r.value for r in (Role.SCOUT, Role.RELAY, Role.RESERVE))

# Parameter names a tool may take beyond the always-required reason_code.
PARAM_X, PARAM_Y = "x", "y"


@dataclass(frozen=True)
class Tool:
    name: str
    category: str
    objective: Objective
    params: Tuple[str, ...]      # beyond reason_code
    meaning: str
    free: bool = False           # costs no model action (makes progress or ends the mission)


TOOLS: Tuple[Tool, ...] = (
    Tool("accept_task", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "take over a task a teammate released to you"),
    Tool("decline_task", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "turn down a task released to you (it stays open for others, and you won't auto-claim it)"),
    Tool("compute_task_cost", QUERY, Objective.TOOL_ACTION, ("task_id",),
         "ask the code for your deterministic cost of a task (lower is better); the answer appears next turn"),
    Tool("announce_task", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "tell the team a task you hold is up for bids"),
    Tool("send_bid", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "bid on a task a teammate announced (the code computes the bid - you never choose a number)"),
    Tool("claim_task", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "take an unheld task for yourself"),
    Tool("release_task", COORDINATION, Objective.TOOL_ACTION, ("task_id",),
         "give up a task you hold (it goes to the best bidder, if there is one)"),
    Tool("change_role", COORDINATION, Objective.TOOL_ACTION, ("new_role",),
         "change your role: scout (searches), relay (holds station) or reserve (spare)"),
    Tool("request_help", COORDINATION, Objective.TOOL_ACTION, ("recipients",),
         "ask teammates for help (informational; never an order). Name the teammates in this tool's own \"recipients\" parameter and leave outgoing_messages empty - the tool itself sends the request"),
    Tool("report_target", FLIGHT, Objective.REPORT, ("target_id",),
         "report a target you sensed to the team", free=True),
    Tool("start_search", FLIGHT, Objective.SEARCH_SECTOR, (),
         "begin sweeping the sector you hold", free=True),
    Tool("go_to_waypoint", FLIGHT, Objective.GO_TO_WAYPOINT, (PARAM_X, PARAM_Y),
         "fly to world position (x, y) in meters at your current altitude, e.g. to look somewhere new"),
    Tool("act_as_relay", COORDINATION, Objective.TOOL_ACTION, (),
         "become a relay: hold station and keep reporting in (does not route traffic for others)"),
    Tool("return_home", FLIGHT, Objective.RETURN_HOME, (),
         "stop and fly home to land", free=True),
    Tool("hold", FLIGHT, Objective.LISTEN, (),
         "stay here a few more seconds in case a teammate is about to report"),
)

BY_NAME: Dict[str, Tool] = {t.name: t for t in TOOLS}
assert len(TOOLS) == 15 and len(BY_NAME) == 15

# parameter name -> allowed values (a tuple), or None for a free number
Choices = Mapping[str, Optional[Tuple]]
Offered = Dict[str, Dict[str, Optional[Tuple]]]


def _uniq(values) -> Tuple:
    """Order-preserving de-duplication: a parameter's valid values are a SET, and a duplicate in belief
    must never turn into a repeated value in the menu (it once inflated a prompt 3x in a test)."""
    return tuple(dict.fromkeys(values))


def offered_tools(belief, *, listen_cap: int, max_actions: int = MAX_MODEL_ACTIONS,
                  waypoints_enabled: bool = True) -> Offered:
    """Which tools are legal right now, and what each parameter may be. Pure function of belief."""
    s, comm = belief.self_state, belief.communication
    actions_left = s.model_actions < max_actions
    rounds_left = belief.listen_rounds < listen_cap
    teammates = _uniq(belief.team.teammates)
    view = belief.team.task_view
    declined = set(comm.declined_tasks)
    scout = s.role == Role.SCOUT.value

    live = _uniq(t for t, _, st, _ in view if st != "complete")
    mine = _uniq(t for t, _, st, _ in view if st == "mine")
    unheld = _uniq(t for t, _, st, _ in view if st == "unheld" and t not in declined)

    offered: Offered = {"return_home": {}}
    if belief.search_queue:
        offered["start_search"] = {}
    sensed = _uniq(sid for sid, sg in belief.mission.targets_known.items()
                   if sg.source == "sensor" and not sg.confirmed)
    if sensed:
        offered["report_target"] = {"target_id": sensed}

    if actions_left:
        if rounds_left:
            offered["hold"] = {}
            if teammates:
                offered["act_as_relay"] = {}
            if waypoints_enabled:
                offered["go_to_waypoint"] = {PARAM_X: None, PARAM_Y: None}
        if teammates:
            offered["request_help"] = {"recipients": teammates}
        roles = tuple(r for r in ROLES if r != s.role)
        if roles:
            offered["change_role"] = {"new_role": roles}
        if live:
            offered["compute_task_cost"] = {"task_id": live}
        if mine:
            offered["release_task"] = {"task_id": mine}
            if teammates:
                offered["announce_task"] = {"task_id": mine}
        biddable = _uniq(t for t, _, _ in comm.announced_tasks
                         if t in live and t not in mine and t not in comm.bids_sent)
        if scout and biddable:
            offered["send_bid"] = {"task_id": biddable}
        if scout and unheld:
            offered["claim_task"] = {"task_id": unheld}
        offers = _uniq(t for t, _, _ in comm.offers_to_me if t in unheld)
        if offers:
            offered["decline_task"] = {"task_id": offers}
            if scout:
                offered["accept_task"] = {"task_id": offers}
    return offered
