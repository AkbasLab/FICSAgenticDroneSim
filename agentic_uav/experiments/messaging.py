"""Phase 7's exit: four agents talk, and their team beliefs update only when messages are delivered.

    flights = messaging_flights(scenario, seed)          # talking, blocked, silent: the same seed three ways
    checks = exit_checks(flights)                        # each part of the criterion, with what it found

AUV-07's exit criterion: "Four deterministic agents exchange heartbeats and
status messages while flying. Their LOCAL TEAM BELIEFS UPDATE ONLY WHEN
MESSAGES ARE DELIVERED." The same seed is flown three ways:

* TALKING: the four canonical agents (S1-S4) on Phase 7's perfect network --
  a direct link within the scenario's 100 m, read at the next tick.
* BLOCKED: the same, with the radio's range cut to 1 m, so messages are sent
  and none is delivered. Beliefs must not move.
* SILENT: no messaging at all -- the reference the other two are held to.

THE CHECKS, each of which can fail (tests/test_messaging_exit.py):

* MET: the talking flight completes its tasks.
* EXCHANGED: every agent sent heartbeats and status updates, and received
  both kinds from its teammates.
* ONLY ON DELIVERY: every teammate record in every decision of every agent
  came in a message from that teammate, delivered to that drone at or before
  the decision; it carries that teammate's task and is aged from when the
  message was sent. Nothing never delivered is ever in a belief.
* KNOWN EXACTLY: Phase 6's knowledge log passes every decision -- complete,
  correct (a heard teammate's record says where it truly was when it spoke)
  and without a leak.
* BLOCKED MOVES NOTHING: in the blocked flight messages were sent, none was
  delivered, and every teammate stays "never heard" at every decision.
* STEERS NOTHING: talking and blocked flights make exactly the silent
  flight's decisions (plan, recommendation 4).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..core.scenario import Scenario
from .knowledge import Truth, knowledge_log
from .knowledge import summary as knowledge_summary
from .message_log import message_log
from .message_log import summary as log_summary
from .single_agent import TEAM_TASKS, TeamAgentRun, fly_agents_on_mock

BLOCKED_RANGE_M = 1.0          # the four pads are 4 m apart: nothing is ever within 1 m of another drone
MODES = ("talking", "blocked", "silent")
# A record's age, its belief's time and the message's sending are each written
# to the millisecond, so they can disagree by half a millisecond apiece.
AGE_ROUNDING_S = 1.5e-3


def messaging_flights(scenario: Scenario, seed: int, tasks: dict[str, str] | None = None) -> dict[str, TeamAgentRun]:
    """The same seed flown talking, blocked and silent."""
    tasks = dict(TEAM_TASKS if tasks is None else tasks)
    sc = dataclasses.replace(scenario, random_seed=seed)
    return {"talking": fly_agents_on_mock(sc, tasks, "talking", messaging=True),
            "blocked": fly_agents_on_mock(sc, tasks, "blocked", messaging=True, range_m=BLOCKED_RANGE_M),
            "silent": fly_agents_on_mock(sc, tasks, "silent")}


def decisions(run: TeamAgentRun) -> dict[str, list[tuple]]:
    return {d: [(round(e.at, 6), e.decision.as_json(), e.verdict.ok, e.action) for e in t] for d, t in run.traces.items()}


def team_beliefs(run: TeamAgentRun) -> list[dict[str, Any]]:
    """Every decision's team block, compactly: who each agent believed about, from which message, how old."""
    out = []
    for drone, trace in run.traces.items():
        for e in trace:
            team = {m: (r if r == "never heard" else {k: r[k] for k in ("message_id", "task", "age_s", "current")})
                    for m, r in e.belief["team"].items()}
            out.append({"drone": drone, "at_s": round(e.at - run.start, 3), "team": team, "read": list(e.read)})
    return sorted(out, key=lambda r: (r["at_s"], r["drone"]))


def only_on_delivery(run: TeamAgentRun, rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """How many teammate records were checked, and every one that did not come in a delivered message."""
    delivered = {(r["recipient"], r["message_id"]): r["delivered_s"] for r in rows if r["status"] == "delivered"}
    created = {r["message_id"]: r["created_s"] for r in rows}
    problems, checked = [], 0
    for drone, trace in run.traces.items():
        for e in trace:
            at = round(e.at - run.start, 3)
            # Ages are taken when the belief was (its own time), which live is a
            # little before the decision is stamped; on the mock the two are one.
            seen = e.belief["self"]["updated_at"] - run.start
            for member, record in e.belief["team"].items():
                if record == "never heard":
                    continue
                checked += 1
                mid = record.get("message_id")
                where = f"{drone} at {at} s, its record of {member}"
                if (drone, mid) not in delivered:
                    problems.append(f"{where}: {mid} was never delivered to it")
                    continue
                if delivered[(drone, mid)] > at + 1e-9:
                    problems.append(f"{where}: {mid} was delivered after the decision")
                if mid.split("#")[0] != member:
                    problems.append(f"{where}: {mid} is not {member}'s")
                if record["task"] != run.tasks.get(member):
                    problems.append(f"{where}: task {record['task']!r}, but {member} was told {run.tasks.get(member)!r}")
                if abs(record["age_s"] - (seen - created[mid])) > AGE_ROUNDING_S + 1e-9:
                    problems.append(f"{where}: aged {record['age_s']} s, but {mid} was sent "
                                    f"{seen - created[mid]:.3f} s before the belief")
    for r in rows:
        if r["status"] != "delivered" and (r["in_belief_at_s"] is not None or r["read_by_policy_at_s"] is not None):
            problems.append(f"{r['recipient']} believed or read {r['message_id']}, which was {r['status']}")
    return checked, problems


def exchanged(rows: list[dict[str, Any]], drones: list[str]) -> list[str]:
    """Problems if any agent did not send, or did not receive, both heartbeats and status updates."""
    problems = []
    for d in drones:
        for kind in ("heartbeat", "status_update"):
            if not any(r["sender"] == d and r["type"] == kind for r in rows):
                problems.append(f"{d} sent no {kind}")
            if not any(r["recipient"] == d and r["type"] == kind and r["status"] == "delivered" for r in rows):
                problems.append(f"{d} received no {kind}")
    return problems


def talking_checks(talk: TeamAgentRun, scenario: Scenario | None = None,
                   tolerance: dict[str, Any] | None = None) -> dict[str, Any]:
    """The checks a talking flight can be held to on its own: met, exchanged, only on delivery, known exactly.

    These are the ones a live flight is held to (it cannot also be flown
    blocked and silent). `tolerance` is the knowledge log's: the mock's
    default, or a live flight's `poll_tolerance`.
    """
    rows = message_log(talk.deliveries, talk.traces, talk.start)
    drones = sorted(talk.tasks)
    checked, delivery_problems = only_on_delivery(talk, rows)
    checks = {
        "met": {"ok": talk.met, "problems": [] if talk.met else ["the talking flight did not meet its tasks"]},
        "exchanged": {"ok": not exchanged(rows, drones), "problems": exchanged(rows, drones)},
        "only_on_delivery": {"ok": checked > 0 and not delivery_problems, "records_checked": checked,
                             "problems": delivery_problems if checked else ["no teammate record was ever held"]},
    }
    if scenario is not None:
        sc = dataclasses.replace(scenario, random_seed=talk.seed)
        knowledge = knowledge_summary(knowledge_log(talk.traces, Truth(sc, talk.trajectories, talk.start,
                                                                      talk.report.until), tolerance))
        checks["known_exactly"] = {"ok": knowledge["ok"] == knowledge["decisions"], "decisions": knowledge["decisions"],
                                   "passed": knowledge["ok"], "problems": knowledge["problems"][:20]}
    return checks


def exit_checks(flights: dict[str, TeamAgentRun], scenario: Scenario | None = None) -> dict[str, Any]:
    """Each part of the exit criterion on one seed's three flights, with what it found."""
    talk, blocked, silent = flights["talking"], flights["blocked"], flights["silent"]
    rows = message_log(talk.deliveries, talk.traces, talk.start)
    brows = message_log(blocked.deliveries, blocked.traces, blocked.start)
    heard_blocked = [f"{b['drone']} at {b['at_s']} s believed {m}" for b in team_beliefs(blocked)
                     for m, r in b["team"].items() if r != "never heard"]
    checks = {
        **talking_checks(talk, scenario),
        "blocked_moves_nothing": {
            "ok": bool(brows) and all(r["status"] == "out_of_range" for r in brows) and not heard_blocked,
            "sent": len(brows), "delivered": sum(r["status"] == "delivered" for r in brows),
            "problems": heard_blocked + ([] if brows else ["the blocked flight sent nothing"])
                        + [f"{r['message_id']} reached {r['recipient']}" for r in brows if r["status"] != "out_of_range"]},
        "steers_nothing": {"ok": decisions(talk) == decisions(silent) == decisions(blocked),
                           "problems": [f"{name}'s decisions differ from the silent flight's"
                                        for name, run in (("talking", talk), ("blocked", blocked))
                                        if decisions(run) != decisions(silent)]},
    }
    checks["all"] = all(c["ok"] for c in checks.values())
    checks["messages"] = log_summary(rows)
    return checks
