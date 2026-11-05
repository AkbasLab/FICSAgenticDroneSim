"""Phase 12's model choice: the same recorded decisions put to each candidate model (plan, step 5).

    requests = collect(scenario, seeds, config, health, fly)       # from echo flights: no GPU
    rows = run(requests, ask, model)                              # one model, on a server
    summary = summarize(rows)

Every decision a model would have been asked in the echo flights -- the exact
messages, and the rule policy's own answer -- is recorded. Each candidate is
then asked the same messages, one at a time, and measured on:

    valid        the reply reads as a decision (`llm_tools.parse_reply`): no problems
    possible     the action it chose is one the context offered as possible now
    corrected    an unusable reply made usable by the one correction (12.6)
    agreed       it chose what the rule policy chose -- a sanity measure, not a score:
                 a model is not better for copying the rules
    latency      seconds per reply, p50 and p95

Offline, the guardian cannot be asked (it needs the flight's live state); every
action the context offers has already passed the tools' own checks. Which model
then flies the exit is the user's choice, from this.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
import time
from typing import Any

from ..agents.llm_tools import HOLD_MAX_S, parse_reply
from .llm import fly_llm_on_mock


class _Collect:
    """An echo that also keeps every request it is asked."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> str:
        self.requests.append({"messages": request["messages"], "rule_reply": request["meta"]["rule_reply"],
                              "drone": request["meta"]["drone"]})
        return request["meta"]["rule_reply"]


def collect(scenario: Any, seeds: tuple[int, ...], config: Any, health: Any, fly: dict[str, Any],
            stops: tuple[dict[str, float] | None, ...] = (None, {"Drone1": 60.0})) -> list[dict[str, Any]]:
    out = []
    for seed in seeds:
        sc = dataclasses.replace(scenario, random_seed=seed)
        for stop in stops:
            c = _Collect()
            fly_llm_on_mock(sc, config, health, c, "bench", stop, **fly)
            label = "no stop" if not stop else f"{next(iter(stop))} stopped"
            out += [dict(r, seed=seed, flight=label) for r in c.requests]
    return out


def sample(requests: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Evenly spaced, so every flight and stage is in it; all of them when `limit` is None."""
    if limit is None or limit >= len(requests):
        return list(requests)
    step = len(requests) / limit
    return [requests[int(i * step)] for i in range(limit)]


def _offered(messages: list[dict[str, str]]) -> list[tuple[str, str]]:
    actions = json.loads(messages[1]["content"])["actions"]
    return [(a["tool"], json.dumps(a["parameters"], sort_keys=True)) for a in actions]


def _key(tool: str | None, params: dict[str, Any]) -> tuple[str | None, str]:
    norm = {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in params.items()}
    return tool, json.dumps(norm, sort_keys=True)


def possible(tool: str | None, params: dict[str, Any], offered: set[tuple[str | None, str]]) -> bool:
    """Among the offered actions -- a hold of any duration the tools allow, if a hold is offered."""
    if tool == "hold" and any(t == "hold" for t, _ in offered):
        d = params.get("duration_s")
        return isinstance(d, (int, float)) and not isinstance(d, bool) and 1 <= d <= HOLD_MAX_S
    return _key(tool, params) in offered


def run(requests: list[dict[str, Any]], ask: Any, model: str) -> list[dict[str, Any]]:
    rows = []
    for r in requests:
        offered = {_key(t, json.loads(p)) for t, p in _offered(r["messages"])}
        rule_tool, rule_params, _ = parse_reply(r["rule_reply"])
        messages, replies, latencies, problems, tool, params = r["messages"], [], [], [], None, {}
        for attempt in range(2):
            started = time.perf_counter()
            try:
                raw = ask({"messages": messages, "meta": {"rule_reply": r["rule_reply"], "drone": r["drone"]}})
            except Exception as exc:
                latencies.append(round(time.perf_counter() - started, 3))
                problems = [f"no reply: {exc!r}"]
                break
            latencies.append(round(time.perf_counter() - started, 3))
            replies.append(raw)
            tool, params, problems = parse_reply(raw)
            if not problems and not possible(tool, params, offered):
                problems = [f"{tool} {params} is not among the actions offered"]
            if not problems:
                break
            messages = messages + [{"role": "assistant", "content": raw},
                                   {"role": "user", "content": "That answer cannot be used: " + "; ".join(problems)
                                    + ". Answer again with one JSON object, choosing from \"actions\"."}]
        first_ok = len(replies) >= 1 and not parse_reply(replies[0])[2] and \
            possible(*parse_reply(replies[0])[:2], offered)
        rows.append({"model": model, "seed": r["seed"], "flight": r["flight"], "drone": r["drone"],
                     "replies": replies, "latency_s": latencies, "problems": problems,
                     "valid_first": first_ok, "usable": not problems, "corrected": not first_ok and not problems,
                     "tool": tool, "parameters": params,
                     "agreed": not problems and _key(tool, params) == _key(rule_tool, rule_params)})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    first = [r["latency_s"][0] for r in rows if r["latency_s"]]
    tools: dict[str, int] = {}
    for r in rows:
        if r["usable"]:
            tools[r["tool"]] = tools.get(r["tool"], 0) + 1
    q = statistics.quantiles(first, n=20) if len(first) >= 2 else first
    return {"decisions": n, "valid_first": sum(r["valid_first"] for r in rows),
            "usable_after_one_correction": sum(r["usable"] for r in rows),
            "corrected": sum(r["corrected"] for r in rows), "fallback": sum(not r["usable"] for r in rows),
            "agreed": sum(r["agreed"] for r in rows),
            "latency_p50_s": round(statistics.median(first), 3) if first else None,
            "latency_p95_s": round(q[18], 3) if len(first) >= 2 else (first[0] if first else None),
            "tools": dict(sorted(tools.items()))}
