"""Phase 10's exit: the same mission replayed under four conditions, with reproducible message delivery.

    flights = network_flights(scenario, seed, config, health, models)    # every condition, both variants, twice
    exit_checks(flights, scenario)                                       # the four checks below

AUV-10's exit criterion: "The same mission can be replayed under nominal,
degraded, severe and partitioned conditions with reproducible message
delivery." How each part is shown, on the canonical four-drone mission with
Phase 9's agents, each seed flown under each condition with no stop and with
Drone1 stopped at 60 s (the same failure at the same time, 10.3), every
flight twice; and each seed flown on Phase 9's own network, no model, both
ways, once:

* REPRODUCIBLE: every message's fate and time -- sent, scheduled, delivered,
  or why not -- identical between the two flights, in a canonical order
  (the bus records in the order threads happened to send); and with it every
  drone's record and every decision.
* AS CONFIGURED: each flight's network did exactly what its condition says,
  message by message: each loss and each latency the model's own draw for
  that message, after the sender's queue; each refusal where the bucket
  says; each cut where the partition says; nothing out of range (range is
  unlimited between drones); nothing delivered past its lifetime.
* NOMINAL IS PHASE 9: nominal's flights are Phase 9's, both ways -- every
  delivery, every drone's record: the condition Phases 7-9 flew, now by the
  model.
* KNOWN EXACTLY: Phase 6's knowledge log passes every decision, under every
  condition -- the agent's knowledge still only what it sensed and what
  arrived, its base link the judge's in a partition.

How the team fared under each condition is recorded beside the exit, as
findings, not pass conditions (`findings`): met, when, sectors searched
twice, leases run out, alarms raised about drones that were not stopped, a
stopped drone detected and its task taken, the drones' own loss estimate,
stale-message decisions, every delivery's fate.
"""

from __future__ import annotations

import dataclasses
import statistics
from collections import Counter
from typing import Any

from ..coordination.bids import AllocationConfig
from ..coordination.health import HealthConfig
from ..core.scenario import Scenario
from ..simulator.message_bus import (
    DELIVERED,
    EXPIRED,
    LOST,
    OUT_OF_RANGE,
    PARTITIONED,
    PENDING,
    RATE_LIMITED,
)
from ..simulator.network import NetworkModel
from .message_log import late, stale_decisions
from .messaging import decisions
from .network_check import departures, partition_check, rate_check
from .recovery import RecoveryRun, fly_recovery_on_mock
from .recovery_exit import detected, known_exactly, no_false_alarm, reassigned

STOP_AT_S = 60.0
VARIANTS = (("no stop", None), ("Drone1 stopped", {"Drone1": STOP_AT_S}))
CHECKS = ("reproducible", "as_configured", "nominal_is_phase_9", "known_exactly")
STATUSES = (DELIVERED, LOST, RATE_LIMITED, PARTITIONED, EXPIRED, OUT_OF_RANGE, PENDING)
SCHEDULE_TOL_S = 1e-9


def network_flights(scenario: Scenario, seed: int, config: AllocationConfig, health: HealthConfig,
                    models: dict[str, NetworkModel]) -> dict[str, Any]:
    """The seed under each condition, both variants, each flown twice; and on Phase 9's network, both, once."""
    sc = dataclasses.replace(scenario, random_seed=seed)
    flown: dict[tuple[str, str], tuple[RecoveryRun, RecoveryRun]] = {}
    for name, model in models.items():
        for label, stop in VARIANTS:
            flown[(name, label)] = tuple(fly_recovery_on_mock(sc, config, health, label, stop, network=model)
                                         for _ in range(2))
    phase9 = {label: fly_recovery_on_mock(sc, config, health, label, stop) for label, stop in VARIANTS}
    return {"flown": flown, "phase9": phase9}


def canonical(run: RecoveryRun) -> list[tuple]:
    return sorted((d.sent_at, d.message.sender_id, d.message.sequence_number, d.recipient, d.scheduled_at, d.status,
                   d.delivered_at) for d in run.team.deliveries)


def reproducible(a: RecoveryRun, b: RecoveryRun) -> list[str]:
    problems = []
    if canonical(a) != canonical(b):
        first = next((x, y) for x, y in zip(canonical(a) + [None], canonical(b) + [None]) if x != y)
        problems.append(f"the deliveries differ, first at {first}")
    if a.policies != b.policies:
        problems.append("the drones' records differ")
    if decisions(a.team) != decisions(b.team):
        problems.append("the decisions differ")
    return problems


def as_configured(run: RecoveryRun) -> list[str]:
    """Message by message, what the network did against what its condition says."""
    m, start, ds = run.network, run.team.start, run.team.deliveries
    stream = {"model": m, "start": start, "deliveries": ds}
    problems = [f"rate limit: {p}" for p in rate_check(stream)["problems"]]
    problems += [f"partition: {p}" for p in partition_check(stream)["problems"]]
    problems += [f"{d.message.message_id} to {d.recipient} delivered past its lifetime" for d in late(ds)]
    left = departures(ds, m)
    for d in ds:
        where = f"{d.message.message_id} to {d.recipient}"
        if d.status == OUT_OF_RANGE:
            if m.range_m is None:
                problems.append(f"{where}: out of range, on a network without a range")
            continue
        if d.status in (RATE_LIMITED, PARTITIONED):
            continue
        lost, latency = m.draw(d.message.sender_id, d.recipient, d.message.sequence_number)
        if lost != (d.status == LOST):
            problems.append(f"{where}: {d.status}, the model's draw says {'lost' if lost else 'not lost'}")
        elif not lost:
            expect = left[(d.message.sender_id, d.message.sequence_number)] + latency
            if abs(d.scheduled_at - expect) > SCHEDULE_TOL_S:
                problems.append(f"{where}: scheduled {d.scheduled_at - start:.6f} s, the model says {expect - start:.6f} s")
        if d.scheduled_at is not None and d.message.expired(d.scheduled_at) and d.status not in (EXPIRED, PENDING):
            problems.append(f"{where}: arrived past its lifetime, yet {d.status}")
    return problems[:50]


def nominal_is_phase_9(nominal: RecoveryRun, phase9: RecoveryRun) -> list[str]:
    problems = []
    if canonical(nominal) != canonical(phase9):
        problems.append(f"{nominal.team.label}: the deliveries differ from Phase 9's")
    if nominal.policies != phase9.policies:
        problems.append(f"{nominal.team.label}: the drones' records differ from Phase 9's")
    if [(e.at, e.action) for t in nominal.team.traces.values() for e in t] != \
            [(e.at, e.action) for t in phase9.team.traces.values() for e in t]:
        problems.append(f"{nominal.team.label}: the decisions differ from Phase 9's")
    return problems


def exit_checks(flights: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    flown = flights["flown"]
    rep = [f"{c}, {v}: {p}" for (c, v), (a, b) in flown.items() for p in reproducible(a, b)]
    cfg = [f"{c}, {v}: {p}" for (c, v), (a, _) in flown.items() for p in as_configured(a)]
    nom = [p for label, run in flights["phase9"].items() for p in nominal_is_phase_9(flown[("nominal", label)][0], run)]
    known = [known_exactly(a, scenario) for a, _ in flown.values()]
    checks = {
        "reproducible": {"ok": not rep, "problems": rep[:20]},
        "as_configured": {"ok": not cfg, "problems": cfg[:20]},
        "nominal_is_phase_9": {"ok": not nom, "problems": nom},
        "known_exactly": {"ok": all(k["ok"] for k in known), "decisions": sum(k["decisions"] for k in known),
                          "passed": sum(k["passed"] for k in known),
                          "problems": [p for k in known for p in k["problems"]][:20]},
    }
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


# ------------------------------------------------------------------ findings

def lease_expiries(run: RecoveryRun) -> int:
    """Leases run out, each counted once however many books logged it."""
    seen = set()
    for p in run.policies.values():
        for e in p["net"]["book_log"]:
            if "lease ran out" in e["why"]:
                seen.add((e["task_id"], e["after"]["version"]))
    return len(seen)


def searched_twice(run: RecoveryRun) -> int:
    """Sector searches beyond the first: a task completed by more than one drone."""
    counts = Counter(t for ts in run.searched.values() for t in ts)
    return sum(n - 1 for n in counts.values())


def false_alarms(run: RecoveryRun) -> dict[str, int]:
    """Rungs climbed for a drone that was not stopped, by rung."""
    return dict(Counter(t["after"] for d in run.survivors for t in run.policies[d]["health"]["log"]
                        if t["teammate"] not in run.stopped))


def estimated_loss(run: RecoveryRun) -> float | None:
    """The drones' own loss estimates, averaged over every decision and teammate after the first 15 s."""
    xs = [link["loss_rate"] for t in run.team.traces.values() for e in t if e.at - run.team.start > 15.0
          for link in e.as_json()["belief"]["communication"].get("links", {}).values()
          if isinstance(link, dict) and isinstance(link["loss_rate"], (int, float))]
    return round(statistics.mean(xs), 4) if xs else None


def findings(run: RecoveryRun) -> dict[str, Any]:
    out = {"met": run.met, "completion_s": None if run.team.report.completion_s is None
           else round(run.team.report.completion_s, 1),
           "searched_twice": searched_twice(run), "lease_expiries": lease_expiries(run),
           "false_alarms": false_alarms(run), "estimated_loss": estimated_loss(run),
           "stale_decisions": len(stale_decisions(run.team.traces, run.team.start)),
           "deliveries": {s: sum(d.status == s for d in run.team.deliveries) for s in STATUSES},
           "searched": run.searched}
    if run.stopped:
        taken, problems = reassigned(run)
        out.update(detected=not detected(run), reassigned=not problems,
                   taken_by=sorted({x["taken_by"] for x in taken}))
    return out
