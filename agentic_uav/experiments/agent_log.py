"""The agent log: every planning call and every flight, appended to one JSONL.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 5. The file
is still `runs/agent-log.jsonl` at the repository root: the raw record of every
planning call ever made, whatever made it -- the runner, the interactive
agent, the sandbox. The runner's own JSONL is the scored series; neither
replaces the other.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..planners.base_planner import PlanRecord
from .provenance import REPO_ROOT, provenance

LOG_PATH = os.path.join(REPO_ROOT, "runs", "agent-log.jsonl")


def log_execution(outcomes: list[dict[str, Any]], separation: dict[str, Any] | None = None) -> None:
    """Append one execution record for a flown mission.

    Written to the same JSONL as the planning records, tagged `"kind":
    "execution"`, so a reader can reconstruct a whole mission from one file:
    what was asked, what was planned, and what the aircraft actually did.

    These two are deliberately separate records rather than one. A plan is
    produced even when nothing flies (`--plan-only`), and a plan can be correct
    while the flight fails -- which is precisely the distinction 1.3 has to
    report.
    """
    record = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "execution",
        # Which agent flew this. Cheap to record, impossible to reconstruct.
        "code": provenance(),
        "drones": len(outcomes),
        "completed": all(o["completed"] for o in outcomes),
        "any_collision": any(
            o.get("collision", {}).get("has_collided") for o in outcomes
        ),
        "separation": separation,
        "outcomes": outcomes,
    }
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"  [log write failed: {exc}]")


def log_record(record: PlanRecord) -> None:
    """Append one planning call to the JSONL log.

    A failure to log is reported but never stops a flight; a failure to log
    silently would be worse, because the run would look measured when it is not.
    """
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_json()) + "\n")
    except OSError as exc:
        print(f"  [log write failed: {exc}]")
