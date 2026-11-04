"""Phase 8's exit: four drones, one team mission, the sectors divided with no central assignment.

    flights = allocation_flights(scenario, seed, config)   # deliberating and contested, each flown twice
    checks = exit_checks(flights, scenario)                 # each part of the criterion, with what it found

AUV-08's exit criterion: "Four drones receive ONE TEAM MISSION, divide the
sectors WITHOUT A CENTRAL ASSIGNMENT, complete the work, and RESOLVE
SIMULTANEOUS CLAIMS DETERMINISTICALLY." Each seed is flown two ways, and each
way twice:

* DELIBERATING: the manifest's bid window, long enough to hear every bid
  before claiming -- the protocol as it runs.
* CONTESTED: no bid window: every drone claims at once on its own bids,
  before any other can arrive, so simultaneous claims happen on every seed
  (plan, recommendation 5).

THE NETWORK delivers every message (decided 2026-11-04): the exit is the
protocol under perfect communication. On the canonical 100 m radio a drone
searching a far sector goes silent, its lease runs out mid-search and the
sector is searched twice; that is recorded beside the exit as a finding, and
is Phase 10's subject.

THE CHECKS, each of which can fail (tests/test_allocation_exit.py):

* MET: both flights complete the mission (AUV-05's criteria), every drone
  ending its part itself.
* NO CENTRAL ASSIGNMENT: every drone was told the team mission and nothing
  more; every claim it made rested on its own bid and the bids it had heard
  (deliberating: every drone's); and the task it flew is the last it claimed.
* ONE HOLDER EACH: every sector searched, each by exactly one drone; every
  book agrees at the end, each task complete by the drone that searched it.
* CONFLICTS RESOLVED BY THE RULES: contested -- at least one simultaneous
  claim; each settled for the lowest bid (the lower id on a tie); every book
  logs the same corrections; every loser released. Deliberating -- none.
* LEASES RENEWED: no lease ran out in any book; every holder reported from
  its claim to its completion with no gap longer than a progress period
  and a tick.
* DETERMINISTIC: each way flown twice gives the same books, the same
  division and the same decisions.
* KNOWN EXACTLY: Phase 6's knowledge log passes every decision.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..coordination.bids import AllocationConfig
from ..core.scenario import Scenario
from .allocation import AllocationRun, contested, fly_team_on_mock
from .knowledge import Truth, knowledge_log
from .knowledge import summary as knowledge_summary
from .messaging import decisions

MODES = ("deliberating", "contested")
CHECKS = ("met", "no_central_assignment", "one_holder_each", "conflicts_resolved", "leases_renewed",
          "deterministic", "known_exactly")
TICK_S = 0.5
EPS = 1e-6
TEAM_MISSION = {"task": "team mission", "team": True}


def allocation_flights(scenario: Scenario, seed: int, config: AllocationConfig,
                       range_m: float | None | str = None) -> dict[str, AllocationRun]:
    """The seed flown deliberating and contested, each twice; every message delivered unless told otherwise."""
    sc = dataclasses.replace(scenario, random_seed=seed)
    out: dict[str, AllocationRun] = {}
    for mode in MODES:
        c = config if mode == "deliberating" else contested(config)
        out[mode] = fly_team_on_mock(sc, c, mode, range_m=range_m)
        out[f"{mode} again"] = fly_team_on_mock(sc, c, mode, range_m=range_m)
    return out


def _sent(run: AllocationRun) -> list[Any]:
    """Every message sent in the flight, once each, in the order sent."""
    seen, out = set(), []
    for d in run.team.deliveries:
        if d.message.message_id not in seen:
            seen.add(d.message.message_id)
            out.append(d.message)
    return sorted(out, key=lambda m: (m.timestamp, m.sender_id, m.sequence_number))


def _rank(value: float, who: str) -> tuple[float, str]:
    return (round(value, 6), who)


def no_central_assignment(run: AllocationRun, everyone_heard: bool) -> list[str]:
    problems = []
    drones = sorted(run.nets)
    for d, trace in run.team.traces.items():
        told = [e.detail for entry in trace for e in entry.events if e.trigger.value == "task_assigned"]
        if told != [TEAM_MISSION]:
            problems.append(f"{d} was told {told}, not the team mission alone")
    for d, net in run.nets.items():
        made = net["claims_made"]
        for c in made:
            if round(c["heard"].get(d, float("nan")), 3) != round(c["value"], 3):
                problems.append(f"{d}'s claim of {c['task_id']} at {c['at']} s did not rest on its own bid")
            if everyone_heard and sorted(c["heard"]) != drones:
                problems.append(f"{d} claimed {c['task_id']} at {c['at']} s having heard only {sorted(c['heard'])}")
        flown = run.searched.get(d, [])
        if flown and (not made or made[-1]["task_id"] != flown[-1]):
            problems.append(f"{d} searched {flown[-1]}, which was not its last claim")
    return problems


def one_holder_each(run: AllocationRun, tasks: list[str]) -> list[str]:
    problems = []
    flown = sorted(t for ts in run.searched.values() for t in ts)
    if flown != sorted(tasks):
        problems.append(f"searched {flown}, not each of {sorted(tasks)} once")
    by = {t: d for d, ts in run.searched.items() for t in ts}
    for d, net in run.nets.items():
        view = {t["task_id"]: (t["status"], t["assigned_agent"]) for t in net["book"]["tasks"]}
        for t in tasks:
            if view.get(t) != ("complete", by.get(t)):
                problems.append(f"{d}'s book ends with {t} as {view.get(t)}, not complete by {by.get(t)}")
    return problems


def conflicts(run: AllocationRun) -> list[dict[str, Any]]:
    """Simultaneous claims: two or more drones claiming one task, one version, at one instant."""
    groups: dict[tuple, dict[str, float]] = {}
    for d, net in run.nets.items():
        for c in net["claims_made"]:
            groups.setdefault((c["task_id"], c["version"], c["at"]), {})[d] = c["value"]
    out = []
    for (task, version, at), claims in sorted(groups.items()):
        if len(claims) > 1:
            winner = min(claims, key=lambda w: _rank(claims[w], w))
            out.append({"task_id": task, "version": version, "at": at, "claims": dict(sorted(claims.items())),
                        "winner": winner})
    return out


def conflicts_resolved(run: AllocationRun, contested_flight: bool) -> tuple[list[dict[str, Any]], list[str]]:
    found = conflicts(run)
    problems = []
    logged = {d: sorted((c["task_id"], c["version"], c["kept"], c["displaced"], c["rule"]) for c in net["corrections"])
              for d, net in run.nets.items()}
    if not contested_flight:
        if found or any(logged.values()):
            problems.append(f"a deliberating flight had conflicts: {found or logged}")
        return found, problems
    if not found:
        problems.append("no simultaneous claim: the contested flight contested nothing")
    expected = []
    for c in found:
        best = c["claims"][c["winner"]]
        for loser, value in c["claims"].items():
            if loser != c["winner"]:
                rule = "lower agent id" if _rank(value, "") == _rank(best, "") else "lowest valid bid"
                expected.append((c["task_id"], c["version"], c["winner"], loser, rule))
    for d, got in logged.items():
        if got != sorted(expected):
            problems.append(f"{d}'s book logged {got}, not the rules' {sorted(expected)}")
    released = {(m.sender_id, m.payload["task_id"], m.payload["version"]) for m in _sent(run)
                if m.message_type.value == "task_release"}
    for task, version, _, loser, _ in expected:
        if (loser, task, version) not in released:
            problems.append(f"{loser} lost {task} v{version} and never released it")
    return found, problems


def leases_renewed(run: AllocationRun) -> list[str]:
    problems = []
    for d, net in run.nets.items():
        problems += [f"{d}'s book: {e['task_id']} {e['why']}" for e in net["book_log"] if "lease ran out" in e["why"]]
    period = run.config.progress_period_s
    sent = _sent(run)
    for d, tasks in run.searched.items():
        for task in tasks:
            claimed = [c["at"] for c in run.nets[d]["claims_made"] if c["task_id"] == task]
            times = [m.timestamp for m in sent if m.sender_id == d and m.payload.get("task_id") == task
                     and m.message_type.value in ("task_award", "status_update", "task_complete")
                     and m.timestamp >= (claimed[-1] if claimed else 0.0) - EPS]
            gaps = [b - a for a, b in zip(times, times[1:])]
            if not times or (gaps and max(gaps) > period + TICK_S + EPS):
                problems.append(f"{d}'s reports on {task} left a gap of {max(gaps or [0]):.3f} s")
    return problems


def deterministic(a: AllocationRun, b: AllocationRun) -> list[str]:
    problems = []
    if a.nets != b.nets:
        problems.append(f"{a.team.label}: the books differ between two flights")
    if a.searched != b.searched:
        problems.append(f"{a.team.label}: the division differs: {a.searched} / {b.searched}")
    if decisions(a.team) != decisions(b.team):
        problems.append(f"{a.team.label}: the decisions differ between two flights")
    return problems


def known_exactly(run: AllocationRun, scenario: Scenario) -> dict[str, Any]:
    sc = dataclasses.replace(scenario, random_seed=run.team.seed)
    s = knowledge_summary(knowledge_log(run.team.traces, Truth(sc, run.team.trajectories, run.team.start,
                                                              run.team.report.until)))
    return {"ok": s["ok"] == s["decisions"] and s["decisions"] > 0, "decisions": s["decisions"], "passed": s["ok"],
            "problems": s["problems"][:20]}


def exit_checks(flights: dict[str, AllocationRun], scenario: Scenario) -> dict[str, Any]:
    """Each part of the exit criterion on one seed's flights, with what it found."""
    tasks = [f"search {s.id}" for s in scenario.sectors]
    deliberating, contested_run = flights["deliberating"], flights["contested"]
    met = [f"the {m} flight did not meet the mission" for m in MODES if not flights[m].met]
    central = (no_central_assignment(deliberating, everyone_heard=True)
               + no_central_assignment(contested_run, everyone_heard=False))
    holders = [f"{m}: {p}" for m in MODES for p in one_holder_each(flights[m], tasks)]
    quiet, quiet_problems = conflicts_resolved(deliberating, contested_flight=False)
    found, found_problems = conflicts_resolved(contested_run, contested_flight=True)
    leases = [f"{m}: {p}" for m in MODES for p in leases_renewed(flights[m])]
    same = [p for m in MODES for p in deterministic(flights[m], flights[f"{m} again"])]
    known = {m: known_exactly(flights[m], scenario) for m in MODES}
    checks = {
        "met": {"ok": not met, "problems": met},
        "no_central_assignment": {"ok": not central, "problems": central},
        "one_holder_each": {"ok": not holders, "problems": holders},
        "conflicts_resolved": {"ok": not (quiet_problems or found_problems), "conflicts": found,
                               "problems": quiet_problems + found_problems},
        "leases_renewed": {"ok": not leases, "problems": leases},
        "deterministic": {"ok": not same, "problems": same},
        "known_exactly": {"ok": all(k["ok"] for k in known.values()),
                          "decisions": sum(k["decisions"] for k in known.values()),
                          "passed": sum(k["passed"] for k in known.values()),
                          "problems": [p for k in known.values() for p in k["problems"]][:20]},
    }
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


def hundred_metre_finding(scenario: Scenario, config: AllocationConfig) -> dict[str, Any]:
    """The scenario's own radio, flown once, for the record: what the exit's network spares it."""
    run = fly_team_on_mock(scenario, config, "deliberating, 100 m radio", range_m="scenario")
    flown = [t for ts in run.searched.values() for t in ts]
    expiries = [{"by": d, "at": e["at"], "task_id": e["task_id"], "why": e["why"]}
                for d, n in run.nets.items() for e in n["book_log"] if "lease ran out" in e["why"]]
    return {"range_m": scenario.network.communication_range_m, "met": run.met, "searched": run.searched,
            "searches": len(flown), "sectors": len(set(flown)), "lease_expiries": len(expiries),
            "first_expiries": expiries[:6], "completion_s": run.team.report.completion_s}
