"""Phase 13's exit: every architecture, selected by configuration, through one harness (AUV-13).

    flights = seed_flights(scenario, seed, ctx, twice=seed <= 5)
    checks = exit_checks(flights, scenario, ctx)

AUV-13's exit criterion: "The architecture can be selected through
configuration rather than maintaining four unrelated programs."

THE FLIGHTS, each seed: every configuration in `configs/architectures/` --
A, B, C, D, E and the ablations -- through `fly_architecture`, with no stop and
with Drone1 stopped at 60 s (E, which has no agents, with no stop only); every
model decision by the ECHO (the rule's own choice), except "D (70B)", which on
seeds 1–5 is D REPLAYED from Phase 12's recorded llama3.3:70b replies. On the
first five seeds every flight is flown twice.
Every flight on a perfect network: how the arms fare
on degraded links is Phase 17's experiment, and that `perfect_comms` really
ignores a degraded network is held by `test_architecture`.

THE CHECKS, each on every seed:

    by_configuration  every flight is the configuration it was asked for, flown by the one
                      entry point; every configuration shares the scenario, the protocol and
                      recovery manifests, the guardian's limits and the keep-out
    arms_as_claimed   C with no stop is Phase 9's flight; D by the echo is C; D's model
                      replaced by its fallback is C; D replayed is Phase 12's flight (seeds
                      1-5); B starts from C's own first division and sends no task message;
                      A's every flown task was awarded by the base; E is Phase 4's plan
    ablations_off     no leases: no task comes back from a silent drone; no roles: no role
                      change sent; no memory: the model is never told its past; no guardian:
                      none; link inputs: estimates kept, the flight C's
    limits_kept       every flight, as flown: band, fence, zones, separation, speed, landings
    deterministic     flown twice, the same flight (seeds 1-5)

FINDINGS, not experiments (Phase 17's): each arm's missions met and times,
with and without the stop.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from ..agents.independent_policy import initial_division
from ..control.scripted import ALTITUDE_STEP_M, BASE_ALTITUDE_M
from ..core.messages import MessageType
from ..planners.llm_ask import EchoAsk, ReplayAsk
from .architecture import all_architectures, fly_architecture, load_architecture
from .guardian_exit import limits_kept, same_flight

CHECKS = ("by_configuration", "arms_as_claimed", "ablations_off", "limits_kept", "deterministic")
STOPS = ((None, "no stop"), ({"Drone1": 60.0}, "Drone1 stopped"))
TASK_TYPES = {MessageType.TASK_ANNOUNCEMENT, MessageType.TASK_BID, MessageType.TASK_AWARD, MessageType.TASK_ACCEPT,
              MessageType.TASK_RELEASE, MessageType.TASK_COMPLETE}
D70 = "D (70B)"


def _sent(run: Any) -> list[Any]:
    seen, out = set(), []
    for d in run.team.deliveries:
        if d.message.message_id not in seen:
            seen.add(d.message.message_id)
            out.append(d.message)
    return out


def seed_flights(scenario: Any, seed: int, ctx: dict[str, Any], twice: bool,
                 phase12: dict[tuple[int, str], dict[str, Any]] | None = None) -> dict[tuple[str, str], Any]:
    """{(configuration, flight label): [flight, flight again?]}."""
    out: dict[tuple[str, str], Any] = {}
    for name in all_architectures():
        arch = load_architecture(name)
        for stop, label in STOPS:
            if arch.team == "scripted" and stop:
                continue
            runs = [fly_architecture(arch, scenario, seed, ctx["alloc"], ctx["health"], ctx["limits"],
                                     ctx["keep_out"], stop, ask=EchoAsk()) for _ in range(2 if twice else 1)]
            out[(name, label)] = runs
    if phase12:
        for stop, label in STOPS:
            rec = phase12.get((seed, label))
            if rec is not None:
                f = fly_architecture(load_architecture("D"), scenario, seed, ctx["alloc"], ctx["health"],
                                     ctx["limits"], ctx["keep_out"], stop, ask=ReplayAsk(rec["records"]))
                out[(D70, label)] = [f, rec]
    return out


def exit_checks(flights: dict[tuple[str, str], Any], scenario: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    p: dict[str, list[str]] = {k: [] for k in CHECKS}
    # --- by configuration
    for (name, label), fs in flights.items():
        if name == D70:
            continue
        for f in fs:
            if f.architecture != load_architecture(name):
                p["by_configuration"].append(f"{name}, {label}: flew {f.architecture.name}")
    # --- the arms
    c = {lab: flights[("C", lab)][0].run for _, lab in STOPS}
    for name in ("D", "D-fallback"):
        for _, lab in STOPS:
            p["arms_as_claimed"] += [f"{name}, {lab}: {x}" for x in same_flight(flights[(name, lab)][0].run, c[lab])]
    if ctx.get("phase9") is not None:
        p["arms_as_claimed"] += [f"C, no stop, against Phase 9: {x}" for x in same_flight(c["no stop"], ctx["phase9"])]
    for _, lab in STOPS:
        if (D70, lab) in flights:
            f, rec = flights[(D70, lab)]
            if json.loads(json.dumps(f.run.executed, default=str)) != rec["executed"]:
                p["arms_as_claimed"].append(f"D replayed, {lab}: not Phase 12's flight")
            if [[e.get("prompt_digest") for e in g["log"]] for g in f.llm.values()] != \
                    [[e.get("prompt_digest") for e in g["log"]] for g in rec["llm"].values()]:
                p["arms_as_claimed"].append(f"D replayed, {lab}: not Phase 12's decisions")
    heights = {v.id: BASE_ALTITUDE_M + i * ALTITUDE_STEP_M for i, v in enumerate(scenario.vehicles)}
    division = initial_division(scenario.brief(), ctx["alloc"], heights)
    if {d: ts[0] for d, ts in c["no stop"].searched.items() if ts} != division:
        p["arms_as_claimed"].append(f"B's division {division} is not C's first")
    for _, lab in STOPS:
        b = flights[("B", lab)][0].run
        if any(m.message_type in TASK_TYPES for m in _sent(b)):
            p["arms_as_claimed"].append(f"B, {lab}: a task message was sent")
        a = flights[("A", lab)][0].run
        awards = {(m.recipient_ids[0], m.payload["task_id"]) for m in _sent(a)
                  if m.message_type is MessageType.TASK_AWARD and m.sender_id == "base"}
        flown = {(d, t) for d, ts in a.searched.items() for t in ts}
        if not flown <= awards:
            p["arms_as_claimed"].append(f"A, {lab}: flew tasks the base never awarded: {sorted(flown - awards)}")
        if any(m.message_type in TASK_TYPES - {MessageType.TASK_COMPLETE} and m.sender_id != "base" for m in _sent(a)):
            p["arms_as_claimed"].append(f"A, {lab}: a drone sent a task message other than a completion")
    if not flights[("E", "no stop")][0].run.report.success:
        p["arms_as_claimed"].append("E: Phase 4's plan did not meet the mission")
    # --- the ablations
    for _, lab in STOPS:
        nl = flights[("D-no-leases", lab)][0].run
        if "lease ran out" in json.dumps(nl.policies):
            p["ablations_off"].append(f"D-no-leases, {lab}: a lease ran out")
        nr = flights[("D-no-roles", lab)][0].run
        if any(m.message_type is MessageType.ROLE_CHANGE for m in _sent(nr)):
            p["ablations_off"].append(f"D-no-roles, {lab}: a role change was sent")
        nm = flights[("D-no-memory", lab)][0]
        if any(e["context"]["memory"] for g in nm.llm.values() for e in g["log"] if e["kind"] != "procedural"):
            p["ablations_off"].append(f"D-no-memory, {lab}: the model was told its past")
        for name in ("C-no-guardian", "D-no-guardian"):
            if flights[(name, lab)][0].run.guardians:
                p["ablations_off"].append(f"{name}, {lab}: a guardian flew")
        li = flights[("C-link-inputs", lab)][0].run
        if not any(e.belief["communication"].get("links") for t in li.team.traces.values() for e in t):
            p["ablations_off"].append(f"C-link-inputs, {lab}: no link estimates kept")
        p["ablations_off"] += [f"C-link-inputs, {lab}: {x}" for x in same_flight(li, c[lab])]
    # --- limits, determinism
    for (name, label), fs in flights.items():
        run = fs[0].run
        if name == "E" or not hasattr(run, "team"):
            continue
        p["limits_kept"] += [f"{name}, {label}: {x}" for x in limits_kept(run, ctx["limits"], scenario)]
        if len(fs) == 2 and name != D70:
            p["deterministic"] += [f"{name}, {label}: {x}" for x in same_flight(fs[0].run, fs[1].run)]
    checks = {k: {"ok": not v, "problems": v[:20]} for k, v in p.items()}
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


def findings(flights: dict[tuple[str, str], Any]) -> dict[str, Any]:
    out = {}
    for (name, label), fs in flights.items():
        run = fs[0].run
        report = run.report if not hasattr(run, "team") else run.team.report
        entry = {"met": run.met, "completion_s": None if report.completion_s is None else round(report.completion_s, 1)}
        if hasattr(run, "searched"):
            entry["searched"] = run.searched
        out[f"{name} / {label}"] = entry
    return out


def by_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Each configuration and flight over the seeds: met, and completion min / median / max."""
    keys = sorted({k for r in rows for k in r["findings"]})
    out = {}
    for k in keys:
        fs = [r["findings"][k] for r in rows if k in r["findings"]]
        done = [f["completion_s"] for f in fs if f["completion_s"] is not None]
        out[k] = {"met": sum(f["met"] for f in fs), "of": len(fs),
                  "completion_s": [min(done), round(statistics.median(done), 1), max(done)] if done else None}
    return out
