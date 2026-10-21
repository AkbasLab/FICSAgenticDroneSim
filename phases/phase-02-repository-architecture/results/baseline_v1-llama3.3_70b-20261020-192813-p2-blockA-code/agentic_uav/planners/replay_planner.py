"""Recorded model replies, replayed through the same validation as a live model.

No model, no network, no GPU. Give it the replies a model actually produced --
from a results file or by hand -- and it returns the PlanRecords a live planner
would have returned for them. Two uses:

* tests, which can exercise planning without Ollama;
* re-flying EXACT recorded plans. The M10 investigation of 2026-10-06 flew
  hand-built plans to remove the model as a variable; replaying the recorded
  replies does the same without retyping a plan.

It is a deterministic `MissionPlanner`, which is also the shape AUV-03 asks the
deterministic policies of later phases to take.

Parsing and validation are the Ollama planner's own (`json.loads`, then
`validate`), so a reply produces the same plan, notes and error text whichever
planner handled it. `tests/test_planners.py` checks that against every reply in
the planning goldens.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from ..core.errors import PlanError
from .base_planner import PlanRecord
from .plan_schema import validate

REPLAY_ENDPOINT = "replay"   # recorded as the endpoint, so a replayed row says so


class ReplayPlanner:
    """Answers each (drone, instruction) with a reply recorded earlier.

    `replies` maps `(drone, instruction)` to the raw text the model returned.
    A request with no recorded reply is a configuration error and raises
    KeyError: inventing a plan would be a silent change of experiment.
    """

    def __init__(self, replies: dict[tuple[str, str], str], model: str = "replay") -> None:
        self.replies = dict(replies)
        self.model = model

    @classmethod
    def from_rows(cls, rows: Iterable[dict[str, Any]]) -> "ReplayPlanner":
        """Build from result rows (the runner's JSONL): every drone of every row.

        If one (drone, instruction) was answered differently across rows, the
        replies disagree and there is no single thing to replay, so it raises.
        """
        replies: dict[tuple[str, str], str] = {}
        model = None
        for row in rows:
            model = model or row.get("model")
            for drone in row.get("per_drone", []):
                key = (drone["drone"], drone["instruction"])
                raw = drone.get("raw_output", "")
                if key in replies and replies[key] != raw:
                    raise ValueError(f"{key} has more than one recorded reply; "
                                     f"replay a single block, not a mixture")
                replies[key] = raw
        return cls(replies, model=model or "replay")

    @classmethod
    def from_jsonl(cls, path: str) -> "ReplayPlanner":
        with open(path, encoding="utf-8") as handle:
            return cls.from_rows(json.loads(line) for line in handle if line.strip())

    def plan(self, instruction: str, drone: str) -> PlanRecord:
        raw = self.replies[(drone, instruction)]
        try:
            steps, notes = validate(json.loads(raw))
            return PlanRecord(drone, instruction, raw, steps, 0.0, True, None,
                              notes, self.model, REPLAY_ENDPOINT)
        except (PlanError, json.JSONDecodeError) as exc:
            return PlanRecord(drone, instruction, raw, None, 0.0, False, str(exc),
                              [], self.model, REPLAY_ENDPOINT)
