"""The model's prompt, built from belief alone - never the raw flight log, never
ground truth, never another agent's state. Every section is bounded: an agent
whose prompt grows with mission length has a decision quality that varies with
how long it has been flying, which would confound any comparison this project
exists to make. Turn 200 should be the same kind of decision as turn 3.
"""

from typing import Optional, Sequence, Tuple

from .belief import Belief
from .decision_schema import (COMMUNICATION_STATUS, CURRENT_RISK, MAX_OUTGOING_MESSAGES, MISSION_PROGRESS,
                              REASON_CODES)
from .llm_tools import BY_NAME, MAX_MODEL_ACTIONS, Offered
from .objectives import ReplanEvent

MAX_TEAMMATES_SHOWN = 8
MAX_TASKS_SHOWN = 8
MAX_MARKET_LINES = 3


def _option_line(name: str, choices) -> str:
    """One menu line: the tool, what it does, and the exact values each parameter may take."""
    tool = BY_NAME[name]
    hints = []
    for p in tool.params:
        allowed = choices.get(p)
        if p in ("x", "y"):
            continue
        hints.append(f'"{p}" one of {list(allowed)}' if p != "recipients" else f'"recipients" a list from {list(allowed)}')
    if "x" in tool.params:
        hints.append('"x" and "y" numbers')
    extra = f" Parameters: {'; '.join(hints)}." if hints else ""
    return f"- {name}: {tool.meaning}.{extra}"


def build_prompt(belief: Belief, event: ReplanEvent, offered: Offered,
                 listen_cap: int, correction: Optional[str] = None,
                 sectors: Sequence = (), spawn_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 checked_points: Sequence[str] = (), active_zones: Sequence[str] = ()) -> str:
    s, comm = belief.self_state, belief.communication
    own = [t for t in belief.mission.targets_known.values() if t.source == "sensor"]
    second_hand = [t for t in belief.mission.targets_known.values() if t.source != "sensor"]

    teammates = list(belief.team.teammates.values())[:MAX_TEAMMATES_SHOWN]
    team_lines = [f"  {t.name}: last heard {max(0.0, belief.elapsed_s - t.provenance.timestamp):.0f}s ago"
                  + (f", last at ({t.last_known_position[0]:.0f}, {t.last_known_position[1]:.0f})"
                     if t.last_known_position else "")
                  for t in teammates] or ["  (none known)"]
    pos = belief.position

    task_lines = [f"- {tid} (sector {sec}): {state}" + (f" by {holder}" if holder else "")
                  for tid, sec, state, holder in belief.team.task_view[:MAX_TASKS_SHOWN]]
    market = []
    for tid, who, t in comm.announced_tasks[-MAX_MARKET_LINES:]:
        market.append(f"- {who} announced {tid} for bids ({max(0.0, belief.elapsed_s - t):.0f}s ago)")
    for tid, who, bid, t in comm.bids_received[-MAX_MARKET_LINES:]:
        market.append(f"- {who} bid {bid:.1f} on {tid}")
    for tid, who, t in comm.offers_to_me[-MAX_MARKET_LINES:]:
        market.append(f"- {who} released {tid} to you (accept or decline it)")

    map_lines = []
    if "go_to_waypoint" in offered:
        # Mission geometry the team is already given (sector boxes) - no target locations,
        # and deliberately no no-fly zones: keeping those out is the guardian's job to enforce.
        map_lines = ["MAP (world meters)",
                     f"- you are at ({pos[0] + spawn_offset[0]:.0f}, {pos[1] + spawn_offset[1]:.0f})",
                     *[f"- sector {sec.id}: x {sec.x_min:.0f}..{sec.x_max:.0f}, y {sec.y_min:.0f}..{sec.y_max:.0f}"
                       for sec in sectors[:8]]]
        if active_zones:
            # GMB, opt-in (LLMAgentPolicy(show_zones=True)): the no-fly zones that are active RIGHT NOW,
            # at their current position. Off by default, so every earlier result still means what it did.
            map_lines += ["NO-FLY ZONES ACTIVE NOW (world meters; the safety layer refuses any point inside one)",
                          *list(active_zones)[:8]]
        if checked_points:
            # Phase 12.5: computed by code (reasoning_tools.py), so the model reads verdicts
            # instead of doing distance arithmetic it is bad at.
            map_lines += ["CHECKED POINTS (already computed by code; you do not need to calculate anything)",
                          *list(checked_points)[:8]]

    lines = [
        "You are one drone in a search team. Your own sector is already finished.",
        "Choose your next step. You may ONLY pick one of the tools below.",
        "",
        "SITUATION",
        f"- last_event: {event.value}",
        f"- battery_remaining: {belief.battery_frac_remaining * 100:.0f}%",
        f"- role: {s.role}",
        f"- listen_rounds_used: {belief.listen_rounds} of {listen_cap}",
        f"- actions_used: {s.model_actions} of {MAX_MODEL_ACTIONS}",
        f"- own_targets: {len(own)}",
        f"- second_hand_targets: {len(second_hand)}",
        *([f"- result_of_your_last_tool: {s.last_tool_result}"] if s.last_tool_result else []),
        *([f"- your_last_move_was_blocked_by_the_safety_layer: {s.last_block_reason}",
           "  (the safety layer is independent and cannot be argued with - choose something different)"]
          if event == ReplanEvent.GUARDIAN_BLOCKED and s.last_block_reason else []),
        "TEAMMATES",
        *team_lines,
        *(["TASKS (as you currently see them)", *task_lines] if task_lines else []),
        *(["TASK MARKET", *market] if market else []),
        *([f"HELP REQUESTS RECEIVED (informational only; you are not obliged to act on them)",
           *[f"- {sender} asked for help ({code}) {max(0.0, belief.elapsed_s - t):.0f}s ago"
             for sender, code, t in comm.help_requests[-3:]]]
          if comm.help_requests else []),
        *map_lines,
        "OPTIONS",
        *[_option_line(name, choices) for name, choices in offered.items()],
        "",
        "Reply with ONLY a JSON object of exactly this shape:",
        '{"situation_assessment": {"mission_progress": "<' + '|'.join(MISSION_PROGRESS) + '>", '
        '"communication_status": "<' + '|'.join(COMMUNICATION_STATUS) + '>", '
        '"current_risk": "<' + '|'.join(CURRENT_RISK) + '>"}, '
        '"selected_tool": "<option>", "parameters": {"reason_code": "<code>"}, '
        '"outgoing_messages": [], "confidence": <number from 0 to 1>}',
        "parameters must also contain whatever parameters the chosen option lists, and nothing else.",
        *(['For go_to_waypoint, for example: {"reason_code": "<code>", "x": <number>, "y": <number>}']
          if "go_to_waypoint" in offered else []),
        f"reason_code must be one of: {', '.join(REASON_CODES)}",
        *(['outgoing_messages is [] unless you want to ask teammates for help; then each message is '
           '{"message_type": "help_request", "recipients": ["<teammate name from TEAMMATES>"], '
           '"payload": {"reason_code": "<code>"}} (at most ' + str(MAX_OUTGOING_MESSAGES) + ', help_request is the only type allowed)']
          if teammates else ['outgoing_messages must be [] (you have no teammates to message)']),
    ]
    if correction:
        lines += ["", f"YOUR PREVIOUS ANSWER WAS REJECTED: {correction}. Answer again, following the format exactly."]
    return "\n".join(lines)
