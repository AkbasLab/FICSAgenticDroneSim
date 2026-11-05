"""Phase 9's exit: a drone stopped mid-mission, and the rest carry on with no new human command.

    flights = recovery_flights(scenario, seed, config, health)   # no stop; each drone stopped, each twice
    checks = exit_checks(flights, scenario)                       # each part of the criterion, with what it found

AUV-09's exit criterion: "During a four-drone mission, one agent can be
INTENTIONALLY STOPPED. The remaining agents DETECT the disruption, REASSIGN
its task, and CONTINUE WITHOUT A NEW HUMAN COMMAND." Each seed is flown with
no stop, and with each of the four drones stopped in turn at STOP_AT_S
(mid-search), each stopped flight flown twice. Every message is delivered
(Phase 8's network): a stopped drone's silence is the only silence.

THE CHECKS, each of which can fail (tests/test_recovery_exit.py):

* DETECTED: every survivor's ladder for the stopped drone climbs SUSPECTED,
  UNREACHABLE, FAILED in that order, each at its threshold's silence and
  within a tick of it.
* NO FALSE ALARM: no survivor's ladder moves for a drone that was not
  stopped -- in the stopped flights or the flight with no stop.
* REASSIGNED: the task the stopped drone held returns to the pool one
  version on (its lease run out) and is completed by a survivor, in every
  survivor's book.
* CONTINUED: the mission met by the survivors, each ending its part itself.
* NO NEW HUMAN COMMAND: every drone told the team mission and nothing else,
  ever.
* ROLES FROM INTERACTIONS: every role change a survivor made follows from its
  own protocol and detector -- a scout from a claim it made; a reserve from a
  task it finished or lost, or a relay's teammate failed or heard again; a
  relay from a teammate found unreachable while free, or coming free while
  one is -- and was announced.
* DETERMINISTIC: each stopped flight flown twice gives the same records.
* KNOWN EXACTLY: Phase 6's knowledge log passes every decision.

BESIDE IT: a reprioritization flight (a drone stopped and the deadline cut so
its task cannot be redone) and the 9.4 report -- the five conditions of
controlled emergence, and two of AUV-19's proxies, reported, not claimed.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..coordination.bids import AllocationConfig
from ..coordination.health import HealthConfig
from ..core.scenario import Scenario
from .knowledge import Truth, knowledge_log
from .knowledge import summary as knowledge_summary
from .messaging import decisions
from .recovery import RecoveryRun, fly_recovery_on_mock

STOP_AT_S = 60.0                 # mid-search for every drone on the canonical mission
TICK_S = 0.5
EPS = 1e-6
CHECKS = ("detected", "no_false_alarm", "reassigned", "continued", "no_new_command", "roles_from_interactions",
          "deterministic", "known_exactly")
TEAM_MISSION = {"task": "team mission", "team": True}
TROUBLE_DEADLINE_S = 250.0       # too short for a returned far sector to be redone


def recovery_flights(scenario: Scenario, seed: int, config: AllocationConfig, health: HealthConfig,
                     stop_at: float = STOP_AT_S, **fly: Any) -> dict[str, RecoveryRun]:
    """The seed flown with no stop, and with each drone stopped at `stop_at` -- each stopped flight twice.
    `fly` passes on to every flight (after Phase 9's live collision: `guardian=`, `keep_out=`)."""
    sc = dataclasses.replace(scenario, random_seed=seed)
    out = {"no stop": fly_recovery_on_mock(sc, config, health, "no stop", **fly)}
    for v in scenario.vehicles:
        label = f"{v.id} stopped"
        out[label] = fly_recovery_on_mock(sc, config, health, label, {v.id: stop_at}, **fly)
        out[f"{label} again"] = fly_recovery_on_mock(sc, config, health, label, {v.id: stop_at}, **fly)
    return out


def _sent(run: RecoveryRun) -> list[Any]:
    seen, out = set(), []
    for d in run.team.deliveries:
        if d.message.message_id not in seen:
            seen.add(d.message.message_id)
            out.append(d.message)
    return sorted(out, key=lambda m: (m.timestamp, m.sender_id, m.sequence_number))


def detected(run: RecoveryRun, slack_s: float = TICK_S) -> list[str]:
    # A flight meant to stop a drone in which none was stopped -- the stop came after the mission ended --
    # shows nothing detected; it must not pass for one that does.
    problems = [] if run.stopped else [f"{run.team.label}: nobody was stopped, so nothing was there to detect"]
    h = run.health
    thresholds = {"suspected": h.suspected_s, "unreachable": h.unreachable_s, "failed": h.failed_s}
    for victim in run.stopped:
        for d in run.survivors:
            climbs = [t for t in run.policies[d]["health"]["log"] if t["teammate"] == victim]
            if [t["after"] for t in climbs] != ["suspected", "unreachable", "failed"]:
                problems.append(f"{d}'s ladder for {victim}: {[t['after'] for t in climbs]}, not the three rungs in order")
                continue
            for t in climbs:
                need = thresholds[t["after"]]
                if not need - EPS <= t["silence_s"] <= need + slack_s + EPS:
                    problems.append(f"{d} called {victim} {t['after']} after {t['silence_s']} s of silence, not {need:g}")
    return problems


def no_false_alarm(run: RecoveryRun) -> list[str]:
    return [f"{d}'s ladder moved for {t['teammate']}, which was not stopped: {t['after']} at {t['at']} s"
            for d in run.survivors for t in run.policies[d]["health"]["log"] if t["teammate"] not in run.stopped]


def reassigned(run: RecoveryRun) -> tuple[list[dict[str, Any]], list[str]]:
    found, problems = [], []
    for victim in run.stopped:
        made = run.policies[victim]["net"]["claims_made"]
        held = made[-1]["task_id"] if made and not run.searched.get(victim) else None
        if held is None:
            problems.append(f"{victim} held no unfinished task when it was stopped")
            continue
        taker = next((d for d in run.survivors if held in run.searched.get(d, [])), None)
        if taker is None:
            problems.append(f"{held}, {victim}'s, was searched by no survivor")
        for d in run.survivors:
            t = next(t for t in run.policies[d]["net"]["book"]["tasks"] if t["task_id"] == held)
            if (t["status"], t["assigned_agent"]) != ("complete", taker) or t["version"] < 2:
                problems.append(f"{d}'s book ends with {held} as {t['status']} v{t['version']} by {t['assigned_agent']}")
            if not any(e["task_id"] == held and f"{victim}'s lease ran out" in e["why"]
                       for e in run.policies[d]["net"]["book_log"]):
                problems.append(f"{d}'s book never saw {victim}'s lease on {held} run out")
        claim = next((c for c in run.policies[taker]["net"]["claims_made"] if c["task_id"] == held), None) if taker else None
        found.append({"stopped": victim, "task": held, "taken_by": taker,
                      "claimed_at": None if claim is None else claim["at"],
                      "version": None if claim is None else claim["version"]})
    return found, problems


def continued(run: RecoveryRun) -> list[str]:
    problems = [] if run.team.report.success else [f"the mission was not met: {run.team.report.summary()}"]
    problems += [f"{d} did not end its part itself" for d in run.survivors if not run.team.finished.get(d)]
    return problems


def no_new_command(run: RecoveryRun) -> list[str]:
    problems = []
    for d, trace in run.team.traces.items():
        told = [e.detail for entry in trace for e in entry.events if e.trigger.value == "task_assigned"]
        if told != [TEAM_MISSION]:
            problems.append(f"{d} was told {told}")
    return problems


def roles_from_interactions(run: RecoveryRun, slack_s: float = TICK_S) -> list[str]:
    problems = []
    announced = {(m.sender_id, round(m.timestamp, 3), m.payload["role"]) for m in _sent(run)
                 if m.message_type.value == "role_change"}
    for d in run.survivors:
        p = run.policies[d]
        claims = [c["at"] for c in p["net"]["claims_made"]]
        # Its own claimed task ending: completed (it stays the assignee) or lost (another is).
        own_ends = [e["at"] for e in p["net"]["book_log"]
                    if e["before"].get("assigned_agent") == d and e["before"].get("status") == "claimed"
                    and (e["after"].get("status") != "claimed" or e["after"].get("assigned_agent") != d)]
        unreachable = [t["at"] for t in p["health"]["log"] if t["after"] == "unreachable"]
        settled = [t["at"] for t in p["health"]["log"] if t["after"] in ("failed", "recovered")]
        # A relay begins when a teammate becomes unreachable while it is free, or when it comes
        # free while one is; it ends -- back to reserve -- when that teammate fails or is heard again.
        causes = {"scout": claims, "reserve": own_ends + settled, "relay": unreachable + own_ends}
        for c in p["roles"]["log"]:
            near = causes[c["after"]]
            if not any(abs(c["at"] - t) <= slack_s + EPS for t in near):
                problems.append(f"{d} became a {c['after']} at {c['at']} s with nothing of its own to cause it")
            if (d, c["at"], c["after"]) not in announced:
                problems.append(f"{d}'s change to {c['after']} at {c['at']} s was not announced")
    return problems


def deterministic(a: RecoveryRun, b: RecoveryRun) -> list[str]:
    problems = []
    if a.policies != b.policies:
        problems.append(f"{a.team.label}: the records differ between two flights")
    if a.searched != b.searched:
        problems.append(f"{a.team.label}: the division differs")
    if decisions(a.team) != decisions(b.team):
        problems.append(f"{a.team.label}: the decisions differ")
    return problems


def known_exactly(run: RecoveryRun, scenario: Scenario, tolerance: dict[str, Any] | None = None) -> dict[str, Any]:
    sc = dataclasses.replace(scenario, random_seed=run.team.seed)
    s = knowledge_summary(knowledge_log(run.team.traces, Truth(sc, run.team.trajectories, run.team.start,
                                                              run.team.report.until, run.network), tolerance))
    return {"ok": s["decisions"] > 0 and s["ok"] == s["decisions"], "decisions": s["decisions"], "passed": s["ok"],
            "problems": s["problems"][:20]}


def exit_checks(flights: dict[str, RecoveryRun], scenario: Scenario) -> dict[str, Any]:
    stopped = [k for k in flights if k.endswith("stopped")]
    flown = ["no stop"] + stopped
    det = [p for k in stopped for p in detected(flights[k])]
    false = [p for k in flown for p in no_false_alarm(flights[k])]
    taken, re_problems = [], []
    for k in stopped:
        f, p = reassigned(flights[k])
        taken += f
        re_problems += p
    cont = [f"{k}: {p}" for k in flown for p in continued(flights[k])]
    told = [f"{k}: {p}" for k in flown for p in no_new_command(flights[k])]
    roles = [f"{k}: {p}" for k in flown for p in roles_from_interactions(flights[k])]
    same = [p for k in stopped for p in deterministic(flights[k], flights[f"{k} again"])]
    known = [known_exactly(flights[k], scenario) for k in flown]
    checks = {
        "detected": {"ok": not det, "problems": det},
        "no_false_alarm": {"ok": not false, "problems": false},
        "reassigned": {"ok": not re_problems, "reassignments": taken, "problems": re_problems},
        "continued": {"ok": not cont, "problems": cont},
        "no_new_command": {"ok": not told, "problems": told},
        "roles_from_interactions": {"ok": not roles, "problems": roles},
        "deterministic": {"ok": not same, "problems": same},
        "known_exactly": {"ok": all(k["ok"] for k in known), "decisions": sum(k["decisions"] for k in known),
                          "passed": sum(k["passed"] for k in known),
                          "problems": [p for k in known for p in k["problems"]][:20]},
    }
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


LIVE_CHECKS = ("detected", "no_false_alarm", "reassigned", "continued", "no_new_command", "roles_from_interactions",
               "known_exactly")
LIVE_STOP_AT_S = 17.0           # mid-search on the live variant, on the mock and in CarlaAir
LIVE_SLACK_S = 2 * TICK_S       # live, a tick is the real clock's


def live_checks(run: RecoveryRun, scenario: Scenario, tolerance: dict[str, Any]) -> dict[str, Any]:
    """The checks one stopped flight can be held to on its own (determinism needs a second flight)."""
    taken, re_problems = reassigned(run)
    parts = {"detected": detected(run, LIVE_SLACK_S), "no_false_alarm": no_false_alarm(run),
             "reassigned": re_problems, "continued": continued(run), "no_new_command": no_new_command(run),
             "roles_from_interactions": roles_from_interactions(run, LIVE_SLACK_S)}
    checks = {k: {"ok": not v, "problems": v} for k, v in parts.items()}
    checks["reassigned"]["reassignments"] = taken
    checks["known_exactly"] = known_exactly(run, scenario, tolerance)
    checks["all"] = all(checks[k]["ok"] for k in LIVE_CHECKS)
    return checks


def reprioritization(scenario: Scenario, config: AllocationConfig, health: HealthConfig,
                     victim: str = "Drone1", deadline_s: float = TROUBLE_DEADLINE_S) -> dict[str, Any]:
    """A drone stopped and the deadline cut so its task cannot be redone: the team lowers its ambition."""
    short = dataclasses.replace(scenario, mission=dataclasses.replace(scenario.mission, deadline_s=deadline_s))
    run = fly_recovery_on_mock(short, config, health, f"{victim} stopped, deadline {deadline_s:g} s",
                               {victim: STOP_AT_S})
    return judge_reprioritization(run, victim, deadline_s)


def judge_reprioritization(run: RecoveryRun, victim: str, deadline_s: float) -> dict[str, Any]:
    """Was the stopped drone's task abandoned by every survivor, not chased, the team home in time?"""
    held = run.policies[victim]["net"]["claims_made"][-1]["task_id"]
    abandoned = {d: run.policies[d]["net"].get("abandoned", []) for d in run.survivors}
    problems = []
    for d, a in abandoned.items():
        if [x["task_id"] for x in a] != [held]:
            problems.append(f"{d} abandoned {[x['task_id'] for x in a]}, not {held} alone")
    if any(held in run.searched.get(d, []) for d in run.survivors):
        problems.append(f"{held} was chased after it was abandoned")
    problems += [f"{d} did not end its part" for d in run.survivors if not run.team.finished.get(d)]
    if run.team.report.until - run.team.start > deadline_s + EPS:
        problems.append("the team flew past the deadline")
    c1 = next(c for c in run.team.report.criteria if c.id == "C1")
    return {"ok": not problems, "problems": problems, "stopped": victim, "task": held, "deadline_s": deadline_s,
            "abandoned": {d: [(x["at"], x["task_id"]) for x in a] for d, a in abandoned.items()},
            "searched": run.searched, "ended_s": round(run.team.report.until - run.team.start, 3),
            "mission_met": run.team.report.success, "coverage": c1.detail}


def emergence_report(seed_rows: list[dict[str, Any]], scenario: Scenario) -> dict[str, Any]:
    """9.4's five conditions, as the record shows them, and two of AUV-19's proxies -- reported, not claimed."""
    def held(check):
        return all(r["checks"][check]["ok"] for r in seed_rows)
    naive = {v.id: f"search {s.id}" for v, s in zip(scenario.vehicles, scenario.sectors)}
    divisions = {tuple(sorted((d, ", ".join(t)) for d, t in r["division"].items())) for r in seed_rows}
    first = seed_rows[0]["division"] if seed_rows else {}
    differ = sorted(d for d, t in first.items() if t[:1] != [naive[d]])
    return {
        "conditions": {
            "a team-level objective": {"held": held("no_new_command"),
                                       "how": "every drone told only the team mission, in every flight"},
            "no central controller": {"held": held("no_new_command"),
                                      "how": "no task given to any drone, by anyone, after the start; the flight code "
                                             "calls only assign_team (tests/test_recovery_exit.py)"},
            "only local beliefs and delivered messages": {
                "held": held("known_exactly"),
                "how": "the boundary checks over agents/ and coordination/; every decision known exactly"},
            "allocation and roles from interactions": {"held": held("roles_from_interactions"),
                                                       "how": "every role change traced to the drone's own claim, "
                                                              "completion or detector; every claim to its bids"},
            "deterministic constraints": {"held": all(r.get("validated", True) for r in seed_rows),
                                          "how": "every executed decision passed the validation step"},
        },
        "proxies": {
            "assignment distance from one drone per sector": {
                "drones_off_the_naive_assignment": differ, "of": len(naive),
                "naive": naive, "flown": first},
            "allocation divergence across seeds": {
                "distinct_divisions": len(divisions), "seeds": len(seed_rows),
                "note": "these agents are deterministic and the bids depend on geometry, not targets: "
                        "one division on every seed is expected, and is not emergence measured"},
        },
    }


def validated(run: RecoveryRun) -> bool:
    """Every decision that acted passed the validation step (9.4's fifth condition)."""
    return all(e.verdict.ok for t in run.team.traces.values() for e in t if e.action != "refused")
