"""Phase 14: a flight's structured event log, the 19 types of AUV-14 (14.3).

    events = flight_events(flight, run_config, scenario, failure)    # a list of dicts, in time order
    write_events(events, "events.jsonl.gz")

DERIVED, NOT INSTRUMENTED. Every event is read after the flight from what the
flight already records -- the bus's deliveries, each agent's trace of
decisions, the skills each drone started, the guardians' and models' logs, the
base controller's log, the judge's facts. No agent, policy or harness code
writes an event, so nothing the agents do changes, every earlier run of record
stays as it was, and the log of any old flight can be rebuilt from its record.

Each event is one JSON object: `t` (seconds from the flight's start, the
simulated clock), `type`, `drone` (or null), and what that type carries.

    MISSION_STARTED       t 0: scenario, architecture, roster, network, failure, seed
    OBSERVATION_RECEIVED  at each decision: what the drone's own sensing said (position, battery, airborne)
    BELIEF_UPDATED        at each decision: the belief it decided on (a digest; teammates known; link state)
    DECISION_PROPOSED     each decision: kind, objective, reason, what triggered it
    MESSAGE_SENT          each message, once: id, type, recipients, bytes, lifetime, and a digest of its payload
                          (Phase 15, log version 2: so a message repeating another can be told apart)
    MESSAGE_RECEIVED      each delivery read: id, recipient, delay
    MESSAGE_DROPPED       each delivery not read: id, recipient, why (lost, rate_limited, partitioned,
                          out_of_range, expired; or never_read -- still waiting when its recipient stopped)
    TASK_ANNOUNCED        each task announcement: task, version, why
    TASK_BID              each bid: task, version, value
    TASK_ASSIGNED         a drone takes a task: claimed itself (C, D), awarded by the base (A), its share of
                          the first division (B)
    TASK_RELEASED         a drone loses or gives up a task: lost, abandoned (C, D); reassigned or given back (A)
    ROLE_CHANGED          each role change announced: role, previous, why
    LLM_CALLED            each decision a model was asked for: tool, agreed with the rule, latency, prompt digest
                          (none where the model is replaced by its fallback: no model was there to ask)
    GUARDIAN_INTERVENED   each guardian outcome other than approval: outcome, checks, reasons
    SKILL_STARTED         each skill a drone started: skill, command
    SKILL_COMPLETED       each skill's end, the executor's status: when the drone heard it, or as the next began
    TARGET_FOUND          each detection the judge saw: target, when detected, when reported
    FAULT_INJECTED        each stop, injection and network partition
    MISSION_COMPLETED     the judge's verdict: success, met, completion time, each criterion

Observations and beliefs are logged once per DECISION, not per tick: a tick
is a tenth of a second, so a flight would log tens of thousands; the ones that
matter are those a decision was made on.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from typing import Any, Iterable

from ..core.messages import MessageType

LOG_VERSION = 2            # 1: Phase 14; 2: MESSAGE_SENT carries payload_digest, and its bytes as a number (Phase 15;
                           # version 1 wrote the method's name where the byte count belonged)
EVENT_TYPES = (
    "MISSION_STARTED", "OBSERVATION_RECEIVED", "BELIEF_UPDATED",
    "MESSAGE_SENT", "MESSAGE_DROPPED", "MESSAGE_RECEIVED",
    "TASK_ANNOUNCED", "TASK_BID", "TASK_ASSIGNED",
    "TASK_RELEASED", "ROLE_CHANGED", "LLM_CALLED",
    "DECISION_PROPOSED", "GUARDIAN_INTERVENED", "SKILL_STARTED",
    "SKILL_COMPLETED", "TARGET_FOUND", "FAULT_INJECTED",
    "MISSION_COMPLETED",
)
ORDER = {t: i for i, t in enumerate(EVENT_TYPES)}
SKILL_ENDS = {"skill_succeeded": "succeeded", "skill_failed": "failed", "skill_aborted": "aborted"}
NEVER_READ = "never_read"


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 3)


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _ev(t: float, etype: str, drone: str | None, /, **fields: Any) -> dict[str, Any]:
    return {"t": _r(t), "type": etype, "drone": drone, **fields}


def flight_events(flight: Any, run: Any, scenario: Any, failure: Any, injection_record: dict | None = None
                  ) -> list[dict[str, Any]]:
    """Every event of one flight (a Phase 13 `Flight`), in time order."""
    r = flight.run
    team = getattr(r, "team", None)
    start = team.start if team is not None else 0.0
    roster = [v.id for v in scenario.vehicles]
    out: list[dict[str, Any]] = [_ev(0.0, "MISSION_STARTED", None, scenario=scenario.scenario_id,
                                     architecture=run.architecture, roster=roster, network=run.network,
                                     failure=run.failure, seed=run.seed, planner=run.planner)]
    if team is None:                                   # E: Phase 4's preflight plan, no agents
        out += _scripted(r, start)
    else:
        out += _decisions(team, start)
        out += _messages(team, start)
        out += _tasks(r, team, start)
        if flight.architecture.decider == "llm":              # D-fallback has no model: nothing was asked
            out += _models(flight.llm, start)
        out += _guardians(r, start)
        out += _skills(r, team, start)
        out += _faults(r, failure, injection_record, start)
    out += _targets(r.report if team is None else team.report)
    out.append(_completed(flight, r))
    # A total order: drones act in threads, so events at one instant are recorded in whatever order the threads
    # ran -- the same flight, listed differently. Time, then type, then drone, then the event itself.
    out.sort(key=lambda e: (e["t"], ORDER[e["type"]], e["drone"] or "", json.dumps(e, sort_keys=True, default=str)))
    return out


def _decisions(team: Any, start: float) -> list[dict[str, Any]]:
    out = []
    for d, trace in sorted(team.traces.items()):
        for e in trace:
            t = e.at - start
            me = e.belief.get("self", {})
            comm = e.belief.get("communication", {})
            out.append(_ev(t, "OBSERVATION_RECEIVED", d, position=me.get("position"), battery=me.get("battery"),
                           airborne=me.get("airborne"), skill=me.get("current_skill")))
            out.append(_ev(t, "BELIEF_UPDATED", d, belief_digest=_digest(e.belief),
                           teammates_known=len(e.belief.get("team", {})), task=me.get("current_task"),
                           base_reachable=comm.get("base_reachable"), connected_peers=comm.get("connected_peers")))
            out.append(_ev(t, "DECISION_PROPOSED", d, kind=e.decision.kind.value, objective=e.decision.objective,
                           reason=e.decision.reason, triggers=[ev.trigger.value for ev in e.events]))
    return out


def _skills(r: Any, team: Any, start: float) -> list[dict[str, Any]]:
    """Every skill started, and its end: the executor's own status for each (`team.skills`, one per start). When
    the drone heard it end, then; a skill it replaced by starting the next ended as the next began; the last
    skill of a stopped drone, at its stop; otherwise at the end of the record."""
    out = []
    end = team.report.until - start
    for d, started in sorted(r.executed.items()):
        statuses = team.skills.get(d, ())
        heard = {(ev.detail or {}).get("serial"): ev.at - start for e in team.traces.get(d, ()) for ev in e.events
                 if ev.trigger.value in SKILL_ENDS}
        for i, e in enumerate(started):
            out.append(_ev(e["started_at"] - start, "SKILL_STARTED", d, serial=e["serial"], skill=e["skill"],
                           command=e["command"]))
            status = statuses[i][1] if i < len(statuses) else "unknown"
            if e["serial"] in heard:
                at, how = heard[e["serial"]], "heard"
            elif i + 1 < len(started):
                at, how = started[i + 1]["started_at"] - start, "replaced"
            elif d in r.stopped:
                at, how = r.stopped[d], "stopped"
            else:
                at, how = end, "end of record"
            out.append(_ev(at, "SKILL_COMPLETED", d, serial=e["serial"], skill=e["skill"], status=status,
                           ended=how))
    return out


def _messages(team: Any, start: float) -> list[dict[str, Any]]:
    out, seen = [], set()
    for dl in team.deliveries:
        m = dl.message
        if m.message_id not in seen:
            seen.add(m.message_id)
            out.append(_ev(dl.sent_at - start, "MESSAGE_SENT", m.sender_id, message_id=m.message_id,
                           message_type=m.message_type.value, recipients=list(m.recipient_ids),
                           bytes=m.size_bytes(), ttl_s=m.time_to_live_s, payload_digest=_digest(m.payload)))
            p = m.payload
            if m.message_type is MessageType.TASK_ANNOUNCEMENT:
                out.append(_ev(dl.sent_at - start, "TASK_ANNOUNCED", m.sender_id, task=p["task_id"],
                               version=p["version"], why=p["why"]))
            elif m.message_type is MessageType.TASK_BID:
                out.append(_ev(dl.sent_at - start, "TASK_BID", m.sender_id, task=p["task_id"], version=p["version"],
                               value=_r(p["value"])))
            elif m.message_type is MessageType.ROLE_CHANGE:
                out.append(_ev(dl.sent_at - start, "ROLE_CHANGED", m.sender_id, role=p["role"],
                               previous=p["previous"], why=p["why"]))
        if dl.status == "delivered":
            out.append(_ev(dl.delivered_at - start, "MESSAGE_RECEIVED", dl.recipient, message_id=m.message_id,
                           message_type=m.message_type.value, sender=m.sender_id,
                           delay_s=_r(dl.delivered_at - dl.sent_at)))
        else:
            why = NEVER_READ if dl.status == "pending" else dl.status
            out.append(_ev(dl.sent_at - start, "MESSAGE_DROPPED", dl.recipient, message_id=m.message_id,
                           message_type=m.message_type.value, sender=m.sender_id, why=why))
    return out


def _tasks(r: Any, team: Any, start: float) -> list[dict[str, Any]]:
    out = []
    if r.team_kind == "central" and r.controller is not None:
        for e in r.controller["log"]:
            if e["what"] == "assigned":
                out.append(_ev(e["at"], "TASK_ASSIGNED", e["to"], task=e["task"], by="base", value=_r(e["value"])))
            elif e["what"] in ("reassigned", "given back"):
                out.append(_ev(e["at"], "TASK_RELEASED", e.get("from", e.get("by")), task=e["task"], by="base",
                               why=e["what"]))
        return out
    if r.team_kind == "independent":
        for d, rec in sorted(r.policies.items()):
            first = rec.get("task") or (rec.get("completed") or [None])[0]
            if first:
                out.append(_ev(0.0, "TASK_ASSIGNED", d, task=first, by="division"))
    for d, trace in sorted(team.traces.items()):
        for e in trace:
            for ev in e.events:
                a = (ev.detail or {}).get("allocation")
                if a == "claimed":
                    out.append(_ev(ev.at - start, "TASK_ASSIGNED", d, task=ev.detail["task"], by="self",
                                   value=_r(ev.detail.get("value"))))
                elif a in ("lost", "abandoned"):
                    out.append(_ev(ev.at - start, "TASK_RELEASED", d, task=ev.detail["task"], by="self",
                                   why=f"{a}: {ev.detail.get('why', '')}"))
    return out


def _models(llm: dict[str, Any], start: float) -> list[dict[str, Any]]:
    out = []
    for d, rec in sorted(llm.items()):
        for e in rec["log"]:
            if e["kind"] == "procedural":
                continue
            lat = e.get("latency_s") or []
            out.append(_ev(e["at"] - start, "LLM_CALLED", d, kind=e["kind"], tool=e.get("tool"),
                           agreed=e.get("agreed"), calls=len(lat), latency_s=[_r(x) for x in lat],
                           prompt_digest=e.get("prompt_digest"), problems=e.get("problems", [])))
    return out


def _guardians(r: Any, start: float) -> list[dict[str, Any]]:
    return [_ev(e["at"] - start, "GUARDIAN_INTERVENED", d, outcome=e["outcome"], checks=e.get("checks", []),
                reasons=e.get("reasons", []), source=e.get("source"), fallback=e.get("fallback"))
            for d, g in sorted(r.guardians.items()) for e in g["log"]]


def _faults(r: Any, failure: Any, injection_record: dict | None, start: float) -> list[dict[str, Any]]:
    out = [_ev(at, "FAULT_INJECTED", d, fault="stop", planned_s=failure.stop.get(d)) for d, at in
           sorted(r.stopped.items())]
    if failure.injection is not None:
        at = None if injection_record is None else injection_record.get("fired_at")
        from .experiment import injection_named
        inj = injection_named(failure.injection)
        out.append(_ev(at if at is not None else inj.at_s, "FAULT_INJECTED", inj.drone, fault="injection",
                       injection=inj.name, fired=at is not None, what=inj.what, expected=inj.outcome,
                       check=inj.check))
    net = getattr(r, "network", None)
    for part in (net.partitions if net is not None else ()):
        out.append(_ev(part.start_s, "FAULT_INJECTED", None, fault="partition",
                       groups=[sorted(g) for g in part.groups], until_s=part.end_s))
    return out


def _targets(report: Any) -> list[dict[str, Any]]:
    facts = report.facts.as_json()
    reported = {(x["target"], x["drone"]): x["reported_s"] for x in facts.get("reports", [])}
    return [_ev(x["detected_s"], "TARGET_FOUND", x["drone"], target=x["target"], detected_s=_r(x["detected_s"]),
                reported_s=_r(reported.get((x["target"], x["drone"]))))
            for x in facts.get("detections", [])]


def _completed(flight: Any, r: Any) -> dict[str, Any]:
    rep = r.report if getattr(r, "team", None) is None else r.team.report
    t = rep.completion_s if rep.completion_s is not None else rep.until - rep.start
    return _ev(t, "MISSION_COMPLETED", None, success=rep.success, met=bool(r.met), completion_s=_r(rep.completion_s),
               criteria={c.id: c.passed for c in rep.criteria})


def _scripted(r: Any, start: float) -> list[dict[str, Any]]:
    out = []
    for d, recs in sorted(r.records.items()):
        for rec in recs:
            j = rec.as_json()
            if rec.result is None:
                continue
            out.append(_ev(rec.result.started_at - start, "SKILL_STARTED", d, serial=rec.index + 1,
                           skill=j["skill"], command=j["command"]))
            out.append(_ev(rec.result.ended_at - start, "SKILL_COMPLETED", d, serial=rec.index + 1, skill=j["skill"],
                           status=rec.result.status.value, ended="executor"))
    return out


WALL_CLOCK = ("latency_s",)     # measured on the wall clock (a model call's time): the run's, never the seed's


def without_wall_clock(obj: Any) -> Any:
    """`obj` with every wall-clock measurement left out: what a flight must repeat exactly (16.4)."""
    if isinstance(obj, dict):
        return {k: without_wall_clock(v) for k, v in obj.items() if k not in WALL_CLOCK}
    if isinstance(obj, list):
        return [without_wall_clock(v) for v in obj]
    return obj


def write_events(events: Iterable[dict[str, Any]], path: str) -> int:
    """JSON Lines, gzip-compressed, written byte-for-byte the same for the same events (mtime fixed)."""
    n = 0
    with io.open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            for e in events:
                gz.write((json.dumps(e, sort_keys=True, default=str) + "\n").encode("utf-8"))
                n += 1
    return n


def read_events(path: str) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as h:
        return [json.loads(line) for line in h]
