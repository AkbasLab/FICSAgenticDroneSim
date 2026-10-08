"""The audit trail for a model run: every prompt, every raw output, the model
card, and the numbers that say how much of the result is the model and how
much is the deterministic policy and the guardian. A reviewer re-running the
experiment needs exactly this - not a summary.
"""

import json
import os
from typing import Dict, Optional


def summarize(policies: Dict[str, object], agents: Dict[str, object]) -> dict:
    records = [r for p in policies.values() for r in p.records]
    rejections: Dict[str, int] = {}
    for r in records:
        if r.rejected_as:
            rejections[r.rejected_as] = rejections.get(r.rejected_as, 0) + 1
    chosen: Dict[str, int] = {}
    for r in records:
        if r.source == "model":
            key = r.tool or r.objective.value
            chosen[key] = chosen.get(key, 0) + 1
    guardian = [e for a in agents.values() for e in a.guardian_log.entries]
    blocked = [e for e in guardian if e.outcome == "reject_and_replan"]
    model = [r for r in records if r.source == "model" and r.assessment is not None]
    risk: Dict[str, int] = {}
    for r in model:
        risk[r.assessment["current_risk"]] = risk.get(r.assessment["current_risk"], 0) + 1
    return {
        "assessed_risk": risk,
        "mean_confidence": (sum(r.confidence for r in model) / len(model)) if model else None,
        "messages_sent": sum(len(r.messages) for r in model),
        "model_owned_decisions": len(records),
        "fallback": sum(1 for r in records if r.source == "fallback"),
        "fallback_rate": (sum(1 for r in records if r.source == "fallback") / len(records)) if records else 0.0,
        "corrected": sum(1 for r in records if r.corrected),
        "rejected_as": rejections,
        "model_chose": chosen,
        "waypoints_proposed": sum(1 for r in records if r.raw_waypoint is not None),
        "waypoints_repaired": sum(1 for r in records if r.repaired),
        "guardian_blocked": len(blocked),
        "guardian_blocked_checks": sorted({c for e in blocked for c in e.failed_checks}),
    }


def save_run(directory: str, policies: Dict[str, object], agents: Dict[str, object],
             card: Optional[dict]) -> None:
    os.makedirs(directory, exist_ok=True)
    for name, policy in policies.items():
        with open(os.path.join(directory, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({
                "drone": name, "model_card": card,
                "decisions": [{
                    "step": r.step, "source": r.source, "objective": r.objective.value, "tool": r.tool, "args": r.args,
                    "reason_code": r.reason_code, "waypoint": r.waypoint, "raw_waypoint": r.raw_waypoint,
                    "repaired": r.repaired, "repair_distance_m": r.repair_distance_m,
                    "assessment": r.assessment, "confidence": r.confidence, "messages": r.messages,
                    "rejected_as": r.rejected_as,
                    "corrected": r.corrected, "prompts": r.prompts, "raw_outputs": r.raw_outputs,
                } for r in policy.records],
            }, f, indent=2)
    with open(os.path.join(directory, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"model_card": card, "summary": summarize(policies, agents)}, f, indent=2)
