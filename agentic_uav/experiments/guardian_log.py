"""The guardian's own log, kept separate from the decision log (Phase 11.4).

Why separate: if guardian interventions were mixed into the agent's decision
log, a mission that succeeded would look the same whether the agent was reliable
or whether the guardian quietly corrected it forty times. Those are completely
different claims, and only one of them is a result worth publishing.

So this log answers one question: **how much of the outcome was the agent, and
how much was the guardian?** For every evaluation it records the proposed
action, which named checks failed and why, what was substituted, and what
happened to the mission as a result.

`intervention_rate` is the headline number. An agent that needs the guardian on
one command in three is not a reliable agent, however well its missions score.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GuardianRecord:
    step: int
    time_s: float
    vehicle_id: str
    outcome: str

    # 11.4 required fields
    proposed_action: str                     # what the agent asked for
    proposed_detail: Dict[str, Any] = field(default_factory=dict)
    rejection_reason: str = ""               # why, if it was not approved
    substituted_action: Optional[str] = None  # the modification or fallback
    fallback: Optional[str] = None
    mission_effect: str = ""                 # what it cost the mission

    failed_checks: List[str] = field(default_factory=list)
    all_checks: List[str] = field(default_factory=list)
    flight_phase: str = ""
    battery_frac: float = 0.0

    def to_dict(self):
        return asdict(self)


class GuardianLog:
    def __init__(self, vehicle_id=""):
        self.vehicle_id = vehicle_id
        self.records: List[GuardianRecord] = []
        self.step = 0

    # --- recording ---

    def record(self, decision, belief) -> GuardianRecord:
        from ..agents.safety_guardian import GuardianOutcome

        self.step += 1
        proposed = decision.proposed
        rec = GuardianRecord(
            step=self.step,
            time_s=round(belief.now, 2),
            vehicle_id=belief.vehicle_id,
            outcome=decision.outcome.value,
            proposed_action=_name(proposed),
            proposed_detail=_detail(proposed),
            rejection_reason=("" if decision.outcome is GuardianOutcome.APPROVE
                              else decision.reason),
            substituted_action=(None if decision.outcome is GuardianOutcome.APPROVE
                                else _name(decision.command)),
            fallback=decision.fallback.value if decision.fallback else None,
            failed_checks=[f"{c.name}: {c.detail}" for c in decision.checks
                           if not c.passed],
            all_checks=[c.name for c in decision.checks],
            battery_frac=round(belief.battery_frac, 3),
        )
        self.records.append(rec)
        return rec

    def note_effect(self, record, effect: str):
        """Attach the mission consequence once the substituted action has run."""
        if record is not None:
            record.mission_effect = effect

    def set_phase(self, record, phase):
        if record is not None:
            record.flight_phase = getattr(phase, "value", str(phase))

    # --- analysis: the point of keeping this separate ---

    def stats(self):
        n = len(self.records)
        if n == 0:
            return {"evaluated": 0, "approved": 0, "interventions": 0,
                    "intervention_rate": 0.0, "by_outcome": {},
                    "by_failed_check": {}, "by_fallback": {}}

        by_outcome, by_check, by_fallback = {}, {}, {}
        for r in self.records:
            by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
            if r.fallback:
                by_fallback[r.fallback] = by_fallback.get(r.fallback, 0) + 1
            for c in r.failed_checks:
                name = c.split(":")[0]
                by_check[name] = by_check.get(name, 0) + 1

        approved = by_outcome.get("approve", 0)
        return {
            "evaluated": n,
            "approved": approved,
            "interventions": n - approved,
            "intervention_rate": round((n - approved) / n, 4),
            "by_outcome": by_outcome,
            "by_failed_check": by_check,
            "by_fallback": by_fallback,
        }

    def interventions(self):
        return [r for r in self.records if r.outcome != "approve"]

    # --- output ---

    def to_json(self, path=None, indent=2):
        text = json.dumps([r.to_dict() for r in self.records],
                          indent=indent, default=str)
        if path:
            with open(path, "w") as f:
                f.write(text)
        return text

    def format_text(self, only_interventions=True, limit=40):
        rows = self.interventions() if only_interventions else self.records
        if not rows:
            return "  (no guardian interventions - every command was approved)"
        lines = []
        for r in rows[:limit]:
            lines.append(
                f"  [step {r.step} t={r.time_s:.1f}s] {r.vehicle_id} "
                f"{r.outcome.upper()}")
            lines.append(f"      proposed : {r.proposed_action} {r.proposed_detail}")
            for c in r.failed_checks:
                lines.append(f"      FAILED   : {c}")
            if r.substituted_action:
                extra = f" (fallback: {r.fallback})" if r.fallback else ""
                lines.append(f"      executed : {r.substituted_action}{extra}")
            if r.mission_effect:
                lines.append(f"      effect   : {r.mission_effect}")
            lines.append("")
        if len(rows) > limit:
            lines.append(f"  ... {len(rows) - limit} more")
        return "\n".join(lines)

    def format_summary(self):
        s = self.stats()
        if s["evaluated"] == 0:
            return "  guardian evaluated nothing"
        lines = [
            f"  commands evaluated : {s['evaluated']}",
            f"  approved unchanged : {s['approved']}",
            f"  interventions      : {s['interventions']} "
            f"({s['intervention_rate']:.0%} of commands)",
        ]
        if s["by_outcome"]:
            lines.append("  by outcome:")
            for k, v in sorted(s["by_outcome"].items()):
                lines.append(f"      {k:<28} {v}")
        if s["by_failed_check"]:
            lines.append("  checks that failed:")
            for k, v in sorted(s["by_failed_check"].items(),
                               key=lambda kv: -kv[1]):
                lines.append(f"      {k:<28} {v}")
        if s["by_fallback"]:
            lines.append("  fallbacks used:")
            for k, v in sorted(s["by_fallback"].items()):
                lines.append(f"      {k:<28} {v}")
        return "\n".join(lines)


def merge(logs):
    """Combine several agents' guardian logs for a team-level view."""
    out = GuardianLog("team")
    for lg in logs:
        out.records.extend(lg.records)
    out.step = len(out.records)
    return out


def _name(command):
    if command is None:
        return "none"
    st = getattr(command, "skill_type", None)
    return getattr(st, "value", type(command).__name__)


def _detail(command):
    if command is None:
        return {}
    out = {}
    for attr in ("speed_mps", "timeout_s", "target_altitude", "duration_s"):
        v = getattr(command, attr, None)
        if v is not None:
            out[attr] = round(v, 2) if isinstance(v, float) else v
    for attr in ("waypoint", "point", "position", "home"):
        p = getattr(command, attr, None)
        if p is not None:
            out[attr] = [round(p.x, 1), round(p.y, 1), round(p.z, 1)]
            break
    return out
