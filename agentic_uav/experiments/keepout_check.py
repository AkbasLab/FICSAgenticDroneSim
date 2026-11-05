"""Phase 9's stop flights again, with the keep-out: does every survivor keep clear of a silent teammate?

    flights = keepout_flights(scenario, seed, config, health, limits, keep_out)
    checks = keepout_checks(flights, scenario, keep_out)

The fix for Phase 9's live collision (2026-11-04): teammates silent in the air
are kept out of, by every policy and by the guardian (`coordination.keepout`).
This shows it on the mock, on Phase 9's own flights, every message delivered:

THE FLIGHTS, each seed:

    phase 9            no stop, no keep-out, no guardian: Phase 9's own flight
    no stop            keep-out and guardian on, nothing stopped
    <drone> stopped    each of the canonical four stopped at 60 s, keep-out and guardian on -- twice each
    twin               the live variant's pair, Drone2 stopped at 17 s -- the live flight's mock twin

THE CHECKS, each on every seed:

    phase_9_checks     Phase 9's eight exit checks, on the four-drone flights as they stand (detected, no false
                       alarm, reassigned, continued, no new command, roles, deterministic, known exactly)
    twin_checks        the same eight on the twin
    kept_out           no survivor's flown path, from the moment the stopped drone had been silent `after_s`,
                       enters the square round the position it was last heard at -- the rule's own geometry
    no_interventions   the guardian -- now with its keep_out check -- intervened not once: the policies did it
    no_stop_unchanged  with nothing stopped, the flight with keep-out and guardian is Phase 9's, knot for knot

Beside them, as findings: each survivor's closest pass to where the stopped
drone TRULY hovers (it can differ from where it was last heard by the
distance flown since its last heartbeat), and how the mission's end moved.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

from ..coordination.bids import AllocationConfig
from ..coordination.health import HealthConfig
from ..coordination.keepout import KeepOutConfig, square
from ..core.messages import MessageType
from ..core.scenario import Scenario
from ..safety.guardian import GuardianLimits, segment_distance
from .guardian_exit import interventions, same_flight
from .recovery import RecoveryRun, fly_recovery_on_mock
from .recovery_exit import LIVE_STOP_AT_S, STOP_AT_S, exit_checks

CHECKS = ("phase_9_checks", "twin_checks", "kept_out", "no_interventions", "no_stop_unchanged")
TWIN_SCENARIO = "search_relay_live_small"
TWIN_VICTIM = "Drone2"
_HEARD = (MessageType.HEARTBEAT, MessageType.STATUS_UPDATE)


def keepout_flights(scenario: Scenario, twin: Scenario, seed: int, config: AllocationConfig, health: HealthConfig,
                    limits: GuardianLimits, keep_out: KeepOutConfig) -> dict[str, Any]:
    sc = dataclasses.replace(scenario, random_seed=seed)
    on = {"guardian": limits, "keep_out": keep_out}
    four: dict[str, RecoveryRun] = {"no stop": fly_recovery_on_mock(sc, config, health, "no stop", **on)}
    for v in sc.vehicles:
        label = f"{v.id} stopped"
        four[label] = fly_recovery_on_mock(sc, config, health, label, {v.id: STOP_AT_S}, **on)
        four[f"{label} again"] = fly_recovery_on_mock(sc, config, health, label, {v.id: STOP_AT_S}, **on)
    tw = dataclasses.replace(twin, random_seed=seed)
    pair = {"no stop": fly_recovery_on_mock(tw, config, health, "no stop", **on)}
    for again in ("", " again"):
        pair[f"{TWIN_VICTIM} stopped{again}"] = fly_recovery_on_mock(tw, config, health, f"{TWIN_VICTIM} stopped",
                                                                     {TWIN_VICTIM: LIVE_STOP_AT_S}, **on)
    return {"seed": seed, "phase9": fly_recovery_on_mock(sc, config, health, "no stop"), "four": four, "pair": pair,
            "scenario": sc, "twin": tw}


def last_heard(run: RecoveryRun, victim: str) -> tuple[float, float, float, float] | None:
    """Where the stopped drone was last heard to be: (x, y, altitude, when), from its last delivered report."""
    sent = [d.message for d in run.team.deliveries
            if d.message.sender_id == victim and d.message.message_type in _HEARD and d.status == "delivered"]
    if not sent:
        return None
    m = max(sent, key=lambda m: (m.timestamp, m.sequence_number))
    p = m.payload["position"]
    return (p[0], p[1], p[2], m.timestamp)


def passes(run: RecoveryRun, victim: str, keep_out: KeepOutConfig) -> list[dict[str, Any]]:
    """Each survivor's flown path from when the keep-out stands: does it enter it; how close to the truth."""
    heard = last_heard(run, victim)
    if heard is None or victim not in run.stopped:
        return []
    x, y, alt, at = heard
    from_t = at + keep_out.after_s
    zone = square(x, y, keep_out.half_width_m)
    hover = run.team.trajectories[victim].knots[-1]
    out = []
    for d in run.survivors:
        ks = [k for k in run.team.trajectories[d].knots if k.t >= from_t - 1e-9]
        segs = list(zip(ks, ks[1:]))
        entered = any(zone.crosses((a.x, a.y), (b.x, b.y)) or zone.contains(b.x, b.y) for a, b in segs)
        near_heard = min((segment_distance((a.x, a.y), (b.x, b.y), (x, y)) for a, b in segs), default=math.inf)
        near_true = min((segment_distance((a.x, a.y), (b.x, b.y), (hover.x, hover.y)) for a, b in segs),
                        default=math.inf)
        out.append({"survivor": d, "entered": entered, "closest_to_heard_m": round(near_heard, 2),
                    "closest_to_true_m": round(near_true, 2),
                    "heard_vs_true_m": round(math.dist((x, y), (hover.x, hover.y)), 2)})
    return out


def keepout_checks(flights: dict[str, Any], keep_out: KeepOutConfig) -> dict[str, Any]:
    four, pair = flights["four"], flights["pair"]
    p9 = exit_checks(four, flights["scenario"])
    tw = exit_checks(pair, flights["twin"])
    stopped = [(f"four, {k}", r) for k, r in four.items() if r.stopped] + \
              [(f"twin, {k}", r) for k, r in pair.items() if r.stopped]
    entered = [f"{label}: {p['survivor']} entered the keep-out round {v}" for label, r in stopped
               for v in r.stopped for p in passes(r, v, keep_out) if p["entered"]]
    quiet = [f"{label}: {e['drone']} {e['outcome']} at {e['at']}: {e['checks']}"
             for label, r in [(f"four, {k}", r) for k, r in four.items()] + [(f"twin, {k}", r) for k, r in pair.items()]
             for e in interventions(r)]
    same = same_flight(four["no stop"], flights["phase9"])
    checks = {
        "phase_9_checks": {"ok": p9["all"], "failed": [k for k in p9 if k != "all" and not p9[k]["ok"]],
                           "problems": [p for k in p9 if k != "all" for p in p9[k]["problems"]][:20]},
        "twin_checks": {"ok": tw["all"], "failed": [k for k in tw if k != "all" and not tw[k]["ok"]],
                        "problems": [p for k in tw if k != "all" for p in tw[k]["problems"]][:20]},
        "kept_out": {"ok": not entered, "problems": entered},
        "no_interventions": {"ok": not quiet, "problems": quiet[:20]},
        "no_stop_unchanged": {"ok": not same, "problems": same},
    }
    checks["all"] = all(checks[k]["ok"] for k in CHECKS)
    return checks


def keepout_findings(flights: dict[str, Any], keep_out: KeepOutConfig) -> dict[str, Any]:
    out = {}
    for group in ("four", "pair"):
        for label, run in flights[group].items():
            if not run.stopped or label.endswith("again"):
                continue
            (victim,) = run.stopped
            out[f"{'twin' if group == 'pair' else 'four'}, {label}"] = {
                "met": run.met, "completion_s": None if run.team.report.completion_s is None
                else round(run.team.report.completion_s, 1),
                "searched": run.searched, "passes": passes(run, victim, keep_out)}
    return out
