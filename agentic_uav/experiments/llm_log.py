"""Every prompt, every model output, every fallback (Phase 12.7).

Phase 6 logs what the agent believed. Phase 11 logs what the guardian stopped.
This logs what the *model* was asked and what it said — which is the only way a
run involving an LLM can be audited after the fact, and the only way a reviewer
can check that a reported behaviour came from the model rather than from the
fallback policy quietly doing the work.

The headline numbers this produces:

  * **fallback rate** — how often the deterministic policy had to take over.
    A high rate means the reported "LLM agent" results are substantially the
    rule agent's results wearing a costume, and any comparison between them is
    measuring nothing.
  * **correction rate** — how often one structured retry rescued a bad output.
  * **mean latency** — the cost of putting a model in a control loop, which is
    the practical objection to this whole approach and deserves a number.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class LLMTurn:
    """One decision cycle: what was asked, what came back, what was done."""
    step: int
    time_s: float
    vehicle_id: str
    system_prompt: str
    user_prompt: str
    raw_response: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    tool: Optional[str] = None
    reason_code: Optional[str] = None
    confidence: Optional[float] = None
    assessment: Optional[Dict[str, str]] = None

    attempts: int = 1
    corrected: bool = False
    rejection_reason: Optional[str] = None
    rejection_detail: Optional[str] = None

    used_fallback: bool = False
    fallback_cause: Optional[str] = None
    fallback_objective: Optional[str] = None

    latency_s: float = 0.0
    outcome: str = ""            # what actually happened as a result

    def as_dict(self):
        return asdict(self)

    def summary_line(self):
        if self.used_fallback:
            return (f"  [step {self.step} t={self.time_s:.1f}s] {self.vehicle_id} "
                    f"FALLBACK ({self.fallback_cause}) -> "
                    f"{self.fallback_objective or '?'}")
        mark = "corrected " if self.corrected else ""
        conf = f" conf={self.confidence:.2f}" if self.confidence is not None else ""
        reason = f" [{self.reason_code}]" if self.reason_code else ""
        return (f"  [step {self.step} t={self.time_s:.1f}s] {self.vehicle_id} "
                f"{mark}{self.tool}{reason}{conf} ({self.latency_s:.2f}s)")


class LLMDecisionLog:
    """The per-agent record. One of these per drone — never shared."""

    def __init__(self, vehicle_id, model_card=None):
        self.vehicle_id = vehicle_id
        self.model_card = model_card
        self.turns: List[LLMTurn] = []

    # --- recording ---

    def record(self, turn: LLMTurn):
        self.turns.append(turn)
        return turn

    # --- reading ---

    def fallbacks(self):
        return [t for t in self.turns if t.used_fallback]

    def corrections(self):
        return [t for t in self.turns if t.corrected]

    def tools_used(self):
        counts = {}
        for t in self.turns:
            if t.tool and not t.used_fallback:
                counts[t.tool] = counts.get(t.tool, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def reason_codes(self):
        counts = {}
        for t in self.turns:
            if t.reason_code:
                counts[t.reason_code] = counts.get(t.reason_code, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def rejection_reasons(self):
        counts = {}
        for t in self.turns:
            if t.rejection_reason:
                counts[t.rejection_reason] = counts.get(t.rejection_reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def stats(self):
        n = len(self.turns)
        if not n:
            return {"turns": 0, "fallback_rate": 0.0, "correction_rate": 0.0,
                    "mean_latency_s": 0.0, "mean_confidence": None}
        fb = len(self.fallbacks())
        corr = len(self.corrections())
        confs = [t.confidence for t in self.turns if t.confidence is not None]
        return {
            "turns": n,
            "model_decisions": n - fb,
            "fallbacks": fb,
            "fallback_rate": round(fb / n, 4),
            "corrections": corr,
            "correction_rate": round(corr / n, 4),
            "mean_latency_s": round(sum(t.latency_s for t in self.turns) / n, 3),
            "max_latency_s": round(max(t.latency_s for t in self.turns), 3),
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
            "tools_used": self.tools_used(),
            "reason_codes": self.reason_codes(),
            "rejections": self.rejection_reasons(),
        }

    # --- output ---

    def format_summary(self):
        s = self.stats()
        if not s["turns"]:
            return f"  {self.vehicle_id}: no LLM decisions"
        lines = [
            f"  {self.vehicle_id}",
            f"    decisions        : {s['turns']} "
            f"({s['model_decisions']} by the model, {s['fallbacks']} fallback)",
            f"    fallback rate    : {s['fallback_rate'] * 100:.0f}%",
            f"    corrections      : {s['corrections']} "
            f"({s['correction_rate'] * 100:.0f}%)",
            f"    latency          : mean {s['mean_latency_s']:.2f}s, "
            f"max {s['max_latency_s']:.2f}s",
        ]
        if s["mean_confidence"] is not None:
            lines.append(f"    mean confidence  : {s['mean_confidence']:.2f}")
        if s["tools_used"]:
            lines.append("    tools used       : " + ", ".join(
                f"{k}x{v}" for k, v in s["tools_used"].items()))
        if s["reason_codes"]:
            lines.append("    reason codes     : " + ", ".join(
                f"{k}x{v}" for k, v in s["reason_codes"].items()))
        if s["rejections"]:
            lines.append("    rejected output  : " + ", ".join(
                f"{k}x{v}" for k, v in s["rejections"].items()))
        return "\n".join(lines)

    def format_text(self, limit=20):
        rows = [t.summary_line() for t in self.turns[:limit]]
        if len(self.turns) > limit:
            rows.append(f"  ... {len(self.turns) - limit} more")
        return "\n".join(rows) if rows else "  (no decisions)"

    def save(self, path, include_prompts=True):
        """Write the full transcript to JSON (12.7: save all prompts and outputs).

        `include_prompts=False` exists for the case where only the decisions are
        wanted; the default is to save everything, because a prompt you did not
        keep is an experiment you cannot rerun.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = {
            "vehicle_id": self.vehicle_id,
            "model": self.model_card.as_dict() if self.model_card else None,
            "stats": self.stats(),
            "turns": [],
        }
        for t in self.turns:
            row = t.as_dict()
            if not include_prompts:
                row.pop("system_prompt", None)
                row.pop("user_prompt", None)
            payload["turns"].append(row)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=str)
        return path


def combined_stats(logs):
    """Team-level numbers across several per-agent logs."""
    turns = sum(len(l.turns) for l in logs)
    if not turns:
        return {"turns": 0, "fallback_rate": 0.0}
    fb = sum(len(l.fallbacks()) for l in logs)
    corr = sum(len(l.corrections()) for l in logs)
    lat = [t.latency_s for l in logs for t in l.turns]
    tools = {}
    for l in logs:
        for k, v in l.tools_used().items():
            tools[k] = tools.get(k, 0) + v
    return {
        "agents": len(logs),
        "turns": turns,
        "fallbacks": fb,
        "fallback_rate": round(fb / turns, 4),
        "corrections": corr,
        "correction_rate": round(corr / turns, 4),
        "mean_latency_s": round(sum(lat) / len(lat), 3) if lat else 0.0,
        "tools_used": dict(sorted(tools.items(), key=lambda kv: -kv[1])),
    }
