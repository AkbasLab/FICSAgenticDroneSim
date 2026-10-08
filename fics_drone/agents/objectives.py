"""What the agent can decide to do next, and what makes it decide again.
Kept separate from the loop itself (persistent_agent.py) so the vocabulary
of "things that can happen" is visible in one place."""

from enum import Enum


class Objective(str, Enum):
    TAKE_OFF = "take_off"
    GO_TO_SECTOR = "go_to_sector"
    SEARCH_SECTOR = "search_sector"
    REPORT = "report"
    LISTEN = "listen"  # Phase 7: sector fully swept, nothing of its own left to do - lingers
    # briefly to catch a late-arriving TARGET_FOUND from a teammate before heading home, instead
    # of heading home the instant its own work ends and missing a report that was en route
    CHECK_FOR_ORPHANS = "check_for_orphans"  # Phase 9: after listening, before heading home -
    # is there a teammate's task that's unheld (lease lapsed, or its holder is believed failed)?
    # Picking this up instead of going home is the actual "team changes shape" behavior.
    GO_TO_WAYPOINT = "go_to_waypoint"  # Phase 12: the ONE objective that carries model-supplied
    # coordinates (world x, y only - altitude stays code-owned). Offered only at the model's single
    # decision point, consumes one of the code-capped listen rounds, and is guardian-checked like
    # every other flight command.
    TOOL_ACTION = "tool_action"  # Phase 12 (15-tool set): a model-chosen coordination/information tool
    # (claim, release, announce, bid, accept, decline, cost, role, relay, help). No motion except
    # act_as_relay's hold; the agent dispatches on the tool name the policy handed over.
    RETURN_HOME = "return_home"
    LAND = "land"
    DONE = "done"


class ReplanEvent(str, Enum):
    """What the agent re-decides in response to - never a bare timer tick."""
    TASK_ASSIGNED = "task_assigned"
    SKILL_SUCCEEDED = "skill_succeeded"
    SKILL_FAILED = "skill_failed"
    TARGET_DETECTED = "target_detected"
    REPORT_SENT = "report_sent"
    BATTERY_LOW = "battery_low"
    BATTERY_CRITICAL = "battery_critical"
    GUARDIAN_BLOCKED = "guardian_blocked"
    NEW_TASK_ASSIGNED = "new_task_assigned"  # Phase 9: picked up an orphaned teammate's task
    GUARDIAN_ESCALATED = "guardian_escalated"  # Phase 11: the guardian stopped asking and flew/
    # landed the aircraft itself after repeated unsafe proposals - mission ends here, terminally
