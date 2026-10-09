"""Logged separately from the mission, per FICS's own design - mixing audit
records into the mission trace would make both harder to read. The headline
number is intervention_rate: the fraction of proposed commands the guardian
did not pass through unchanged. On a healthy, already-correct policy (the
only kind this repo's SearchAgentPolicy has ever been) that should sit at
~0; a rising rate on a future LLM policy is a direct measurement of how
often that policy proposes something unflyable.
"""

from dataclasses import dataclass
from typing import List, Optional

from ..agents.safety_guardian import Command, GuardianEvaluation, GuardianOutcome


@dataclass
class GuardianLogEntry:
    step: int
    command_kind: str
    target: Optional[tuple]
    outcome: str
    reason: Optional[str]
    failed_checks: List[str]
    fallback: Optional[str]
    move_m: Optional[float] = None  # steer-out distance (EXIT_ZONE only)


class GuardianLog:
    def __init__(self):
        self.entries: List[GuardianLogEntry] = []

    def record(self, step: int, command: Command, evaluation: GuardianEvaluation):
        self.entries.append(GuardianLogEntry(
            step=step, command_kind=command.kind, target=command.target,
            outcome=evaluation.outcome.value, reason=evaluation.reason,
            failed_checks=list(evaluation.failed_checks),
            fallback=evaluation.fallback.value if evaluation.fallback else None,
            move_m=getattr(evaluation, "move_m", None)))

    @property
    def intervention_rate(self) -> float:
        if not self.entries:
            return 0.0
        interventions = sum(1 for e in self.entries if e.outcome != GuardianOutcome.APPROVE.value)
        return interventions / len(self.entries)

    def by_outcome(self) -> dict:
        counts = {}
        for e in self.entries:
            counts[e.outcome] = counts.get(e.outcome, 0) + 1
        return counts

    def failed_check_counts(self) -> dict:
        counts = {}
        for e in self.entries:
            for name in e.failed_checks:
                counts[name] = counts.get(name, 0) + 1
        return counts

    def format_summary(self) -> str:
        total = len(self.entries)
        approved_unchanged = sum(1 for e in self.entries if e.outcome == GuardianOutcome.APPROVE.value)
        interventions = total - approved_unchanged
        rate_pct = (interventions / total * 100.0) if total else 0.0
        lines = [
            f"commands evaluated : {total}",
            f"approved unchanged : {approved_unchanged}",
            f"interventions      : {interventions} ({rate_pct:.0f}% of commands)",
            "by outcome:  " + " * ".join(f"{k} {v}" for k, v in self.by_outcome().items()),
        ]
        checks = self.failed_check_counts()
        if checks:
            lines.append("checks that failed:  " + " * ".join(f"{k} {v}" for k, v in checks.items()))
        return "\n".join(lines)
