"""Phase 17: a live model's residual variability, measured by docs/TESTING.md's protocol (AUV-15 16.4).

    sample = recorded_decisions("runs/experiments/<batch>", n=100)     # the first n model decisions, in run order
    result = ask_again(sample, ask)                                     # each asked again; agreement and differences

Temperature 0 and a fixed seed reduce a served model's variance; they do not remove it. The protocol: take the
first 100 decisions a live batch recorded, ask the same server, same pinned model and options, each request again
-- rebuilt exactly from its recorded context, its digest checked against the one recorded -- one at a time, and
report the fraction whose reply names the same tool with the same parameters, and the replies that differ, as
they are. Only decisions the model made in one answer ("llm") are taken: a corrected decision's later request
holds the model's own earlier answer, which the protocol does not re-ask.
"""

from __future__ import annotations

import gzip
import json
import os
from typing import Any

from ..agents.llm_context import render
from ..agents.llm_policy import _same, digest
from ..agents.llm_tools import parse_reply


def recorded_decisions(batch_dir: str, n: int = 100) -> list[dict[str, Any]]:
    out = []
    for rid in sorted(os.listdir(batch_dir)):
        path = os.path.join(batch_dir, rid, "records.json.gz")
        if not os.path.isfile(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as h:
            llm = (json.load(h).get("llm") or {})
        entries = sorted(((e["at"], d, e) for d, g in llm.items() for e in g["log"] if e["kind"] == "llm"),
                         key=lambda x: (x[0], x[1]))
        for at, drone, e in entries:
            tool, params, _ = parse_reply(e["replies"][0])
            out.append({"run_id": rid, "drone": drone, "at": at, "context": e["context"],
                        "prompt_digest": e["prompt_digest"], "tool": tool, "parameters": params,
                        "reply": e["replies"][0]})
            if len(out) >= n:
                return out
    return out


def ask_again(sample: list[dict[str, Any]], ask: Any) -> dict[str, Any]:
    rows, problems = [], []
    for s in sample:
        messages = render(s["context"])
        if digest(messages) != s["prompt_digest"]:
            problems.append(f"{s['run_id']} {s['drone']} at {s['at']}: the rebuilt request is not the one recorded")
            continue
        try:
            raw = ask({"messages": messages, "meta": {}})
        except Exception as exc:                # recorded, never hidden
            rows.append({**_key(s), "agreed": False, "error": repr(exc)})
            continue
        tool, params, _ = parse_reply(raw)
        same = tool == s["tool"] and _same(params or {}, s["parameters"] or {})
        rows.append({**_key(s), "agreed": same, "first": {"tool": s["tool"], "parameters": s["parameters"]},
                     "again": {"tool": tool, "parameters": params}, "reply_again": None if same else raw})
    asked = [r for r in rows if "error" not in r]
    return {"asked": len(rows), "errors": len(rows) - len(asked), "agreed": sum(r["agreed"] for r in asked),
            "agreement": (sum(r["agreed"] for r in asked) / len(asked)) if asked else None,
            "problems": problems, "rows": rows}


def _key(s: dict[str, Any]) -> dict[str, Any]:
    return {"run_id": s["run_id"], "drone": s["drone"], "at": s["at"], "prompt_digest": s["prompt_digest"]}
