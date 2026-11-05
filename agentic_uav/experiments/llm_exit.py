"""Phase 12's exit: each drone decides with its own LLM context, every action still guarded (AUV-12).

    flights = llm_flights(scenario, seed, alloc, health, ask, fly)    # flown with the model, then replayed offline
    checks = exit_checks(flights)

AUV-12's exit criterion: "Each drone uses a distinct persistent agent context
to make mission-level decisions during flight, while every action still passes
through structured validation and runtime assurance."

THE FLIGHTS, each seed: the canonical four with Phase 9's team as protocol and
procedure and the pinned model deciding (`LLMPolicy`), the guardian and the
keep-out on, with no stop and with Drone1 stopped at 60 s. Every reply is
recorded; then each flight is flown AGAIN offline from its record
(`ReplayAsk`), no model.

THE CHECKS, each on every flight:

    distinct_contexts  every context a drone's model was given names that drone, and
                       holds of a teammate only what that teammate said; its memory is
                       its own decisions only
    llm_decides        every drone still flying made mission-level decisions with its
                       model; every fallback says why
    guarded            nothing reached the executor unreviewed (no direct entry in any
                       guardian log), and every skill started is one an approved decision
                       started
    replays_exactly    the flight flown again from its record is the same flight: every
                       delivery, record, decision and trajectory knot

And over the run: `model_frozen` -- the server held the pinned digest before the
first flight and after the last.

FINDINGS, not pass conditions: whether the mission was met and when; the
decisions by kind; agreement with the rule policy; the guardian's
interventions (H5); invalid replies and fallbacks; the model's latency.
"""

from __future__ import annotations

import dataclasses
import statistics
from typing import Any

from ..planners.llm_ask import Recorder, ReplayAsk
from .guardian_exit import interventions, same_flight
from .llm import fly_llm_on_mock

CHECKS = ("distinct_contexts", "llm_decides", "guarded", "replays_exactly")
STOPS = ((None, "no stop"), ({"Drone1": 60.0}, "Drone1 stopped"))
TEAMMATE_KEYS = {"id", "health", "role", "heard_s_ago", "last_position_m", "task"}


def llm_flights(scenario: Any, seed: int, config: Any, health: Any, ask: Any, fly: dict[str, Any]) -> dict[str, Any]:
    sc = dataclasses.replace(scenario, random_seed=seed)
    out = {}
    for stop, label in STOPS:
        rec = Recorder(ask)
        run, logs = fly_llm_on_mock(sc, config, health, rec, label, stop, **fly)
        again, again_logs = fly_llm_on_mock(sc, config, health, ReplayAsk(rec.records), label, stop, **fly)
        out[label] = {"run": run, "logs": logs, "replay": again, "replay_logs": again_logs, "records": rec.records}
    return out


def distinct(logs: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    for drone, log in logs.items():
        own = [e for e in log["log"] if e["kind"] != "procedural"]
        for i, e in enumerate(own):
            ctx = e["context"]
            if ctx["you"]["id"] != drone:
                problems.append(f"{drone} was given {ctx['you']['id']}'s context at {e['at']}")
            for m in ctx["teammates"]:
                if m["id"] == drone or not set(m) <= TEAMMATE_KEYS:
                    problems.append(f"{drone} at {e['at']}: a teammate entry holds more than was said: {sorted(m)}")
            mine = [(x["tool"], x["parameters"]) for x in own[:i] if x["kind"] in ("llm", "corrected")][-5:]
            told = [(m["tool"], m["parameters"]) for m in ctx["memory"]]
            if told != mine:
                problems.append(f"{drone} at {e['at']}: its memory is not its own last decisions")
    return problems


def decides(run: Any, logs: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    for drone in run.survivors:
        log = logs[drone]
        if log["decisions"].get("llm", 0) + log["decisions"].get("corrected", 0) == 0:
            problems.append(f"{drone} made no decision with its model")
        problems += [f"{drone} fell back at {e['at']} with no reason" for e in log["log"]
                     if e["kind"] == "fallback" and not e["problems"]]
    return problems


def guarded(run: Any) -> list[str]:
    problems = [f"{e['drone']} at {e['at']}: a command reached the handle unreviewed" for e in interventions(run)
                if e["source"] == "direct"]
    for drone, trace in run.team.traces.items():
        started = sum("started " in e.action for e in trace)
        ran = len(run.executed.get(drone, []))
        if started != ran:
            problems.append(f"{drone}: {ran} skills started, {started} by approved decisions")
    return problems


def exit_checks(flights: dict[str, Any]) -> dict[str, Any]:
    checks = {k: {"ok": True, "problems": []} for k in CHECKS}
    for label, f in flights.items():
        for k, problems in (("distinct_contexts", distinct(f["logs"])), ("llm_decides", decides(f["run"], f["logs"])),
                            ("guarded", guarded(f["run"])), ("replays_exactly", same_flight(f["replay"], f["run"]))):
            checks[k]["problems"] += [f"{label}: {p}" for p in problems]
    for k in CHECKS:
        checks[k]["ok"] = not checks[k]["problems"]
        checks[k]["problems"] = checks[k]["problems"][:20]
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


def findings(flights: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for label, f in flights.items():
        run, logs = f["run"], f["logs"]
        model = [e for log in logs.values() for e in log["log"] if e["kind"] != "procedural"]
        calls = [s for e in model for s in e["latency_s"]]
        kinds: dict[str, int] = {}
        for log in logs.values():
            for k, v in log["decisions"].items():
                kinds[k] = kinds.get(k, 0) + v
        tools: dict[str, int] = {}
        for e in model:
            if e["tool"]:
                tools[e["tool"]] = tools.get(e["tool"], 0) + 1
        inter = interventions(run)
        out[label] = {
            "met": run.met, "completion_s": None if run.team.report.completion_s is None
            else round(run.team.report.completion_s, 1), "searched": run.searched,
            "decisions": kinds, "agreed": sum(1 for e in model if e.get("agreed")), "model_decisions": len(model),
            "tools": dict(sorted(tools.items())),
            "fallback_why": sorted({e["problems"][0][:80] for e in model if e["kind"] == "fallback"}),
            "interventions": {o: sum(e["outcome"] == o for e in inter) for o in sorted({e["outcome"] for e in inter})},
            "intervention_checks": sorted({c for e in inter for c in e["checks"]}),
            "calls": len(calls), "latency_p50_s": round(statistics.median(calls), 3) if calls else None,
            "latency_max_s": max(calls) if calls else None,
        }
    return out
