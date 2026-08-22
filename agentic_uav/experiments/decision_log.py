"""Per-decision belief logging (Phase 6 exit criterion).

For every decision an agent makes, record exactly what it knew and what it did
*not* know at that moment. Without this, a decentralized experiment can't be
audited: if an agent makes a good choice you can't tell whether it reasoned well
or quietly had information it shouldn't have had, and if it makes a bad choice
you can't tell whether the policy was wrong or the belief was simply stale.

Each entry captures the trigger events, the full belief snapshot, the explicit
knowledge gaps, and the resulting objective/skill - so a run can be replayed
decision by decision.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DecisionRecord:
    step: int
    time_s: float
    vehicle_id: str
    triggers: List[str] = field(default_factory=list)
    known: Dict[str, Any] = field(default_factory=dict)
    unknown: List[str] = field(default_factory=list)
    objective: str = ""
    skill: str = ""
    guardian_override: Optional[str] = None
    outcome: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class DecisionLog:
    def __init__(self, vehicle_id):
        self.vehicle_id = vehicle_id
        self.records: List[DecisionRecord] = []

    def start(self, step, time_s, triggers, belief, roster=None, sectors=None):
        rec = DecisionRecord(
            step=step, time_s=round(time_s, 2), vehicle_id=self.vehicle_id,
            triggers=list(triggers),
            known=belief.known(),
            unknown=belief.unknown(roster=roster, all_sectors=sectors))
        self.records.append(rec)
        return rec

    def finish(self, rec, objective=None, skill=None, override=None, outcome=None):
        if rec is None:
            return
        if objective is not None:
            rec.objective = objective
        if skill is not None:
            rec.skill = skill
        if override is not None:
            rec.guardian_override = override
        if outcome is not None:
            rec.outcome = outcome

    # --- output ---

    def to_json(self, path=None, indent=2):
        data = [r.to_dict() for r in self.records]
        text = json.dumps(data, indent=indent, default=str)
        if path:
            with open(path, "w") as f:
                f.write(text)
        return text

    def format_text(self, max_gaps=6):
        """Human-readable audit trail: what it knew / didn't know / did."""
        lines = []
        for r in self.records:
            s = r.known.get("self", {})
            lm = r.known.get("local_map", {})
            team = r.known.get("team", {})
            lines.append(
                f"[step {r.step} t={r.time_s:.1f}s] {r.vehicle_id} "
                f"triggers={','.join(r.triggers) or '-'}")
            lines.append(
                f"    KNEW    : pos={s.get('position')} "
                f"battery={s.get('battery_frac', 0):.0%} "
                f"searched={lm.get('searched_regions')} "
                f"targets={lm.get('observed_targets')}")
            if team:
                for vid, t in team.items():
                    lines.append(
                        f"              team[{vid}] pos={t.get('last_position')} "
                        f"age={t.get('age_s')}s conf={t.get('status_confidence')}"
                        f"{' STALE' if t.get('stale') else ''}")
            gaps = r.unknown[:max_gaps]
            more = len(r.unknown) - len(gaps)
            lines.append(f"    DID NOT KNOW: {'; '.join(gaps) if gaps else 'nothing'}"
                         + (f" (+{more} more)" if more > 0 else ""))
            act = f"    DECIDED : {r.objective}"
            if r.skill:
                act += f" via {r.skill}"
            if r.guardian_override:
                act += f"  [guardian: {r.guardian_override}]"
            if r.outcome:
                act += f" -> {r.outcome}"
            lines.append(act)
            lines.append("")
        return "\n".join(lines)
