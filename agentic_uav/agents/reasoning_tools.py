"""Deterministic calculators the LLM may call instead of guessing (Phase 12.5).

Language models are poor at precise spatial and numerical reasoning from
coordinates written out as text, and — worse for a research instrument — they
are *plausibly* poor at it: the answer looks reasonable and is wrong by 30%. So
the model is never asked how far away something is, whether the battery will
last, or which task is cheapest. It asks, and Python answers.

The division of labour this creates is the actual research claim of Phase 12:

    the model chooses **what to do and why**
    the code computes **whether it is possible**

Every function here is pure, deterministic, and reads only the agent's own
belief — never ground truth, never the network model. They are the same
computations the deterministic Phase 5-9 policy uses, so an LLM agent and a
rule agent facing identical beliefs get identical numbers, and any behavioural
difference between them is a difference in judgement rather than arithmetic.

Results are returned as plain dicts: they go into a prompt, so they have to
survive JSON serialisation and be readable by a model.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..control.navigation import ALTITUDE
from ..core.models import Position3D

#: Speeds and margins used for feasibility answers. These match the
#: deterministic policy's constants on purpose - see module docstring.
CRUISE_SPEED_MPS = 4.0
TURN_OVERHEAD_S = 2.0          # per waypoint, for acceleration and turning
BATTERY_SAFETY_MARGIN = 1.25   # require 25% more than the nominal estimate
SWEEP_LANE_SPACING_M = 8.0


def _pos(p) -> Position3D:
    if isinstance(p, Position3D):
        return p
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return Position3D(float(p[0]), float(p[1]),
                          float(p[2]) if len(p) > 2 else ALTITUDE)
    if isinstance(p, dict):
        return Position3D(float(p["x"]), float(p["y"]),
                          float(p.get("z", ALTITUDE)))
    raise TypeError(f"cannot read a position from {p!r}")


def _round(x, n=2):
    return round(float(x), n)


# --- distance and time ---


def distance(belief, to) -> Dict[str, Any]:
    """Horizontal and 3-D distance from the agent's believed position."""
    target = _pos(to)
    here = belief.position
    horizontal = here.horizontal_distance_to(target)
    dz = target.z - here.z
    return {"tool": "distance",
            "from": [_round(here.x), _round(here.y), _round(here.z)],
            "to": [_round(target.x), _round(target.y), _round(target.z)],
            "horizontal_m": _round(horizontal),
            "vertical_m": _round(abs(dz)),
            "slant_m": _round(math.hypot(horizontal, dz))}


def travel_time(belief, to, speed_mps=CRUISE_SPEED_MPS) -> Dict[str, Any]:
    """How long flying there would take, including turn overhead."""
    speed = max(float(speed_mps), 0.1)
    d = distance(belief, to)
    seconds = d["slant_m"] / speed + TURN_OVERHEAD_S
    return {"tool": "travel_time", "distance_m": d["slant_m"],
            "speed_mps": _round(speed), "seconds": _round(seconds)}


def sweep_time(sector, speed_mps=CRUISE_SPEED_MPS,
               lane_spacing_m=SWEEP_LANE_SPACING_M) -> Dict[str, Any]:
    """How long a boustrophedon sweep of a sector would take.

    This is the number that matters most for planning, and the one a model is
    least able to guess: it is a function of area *and* lane spacing, and it is
    what the task lease has to exceed.
    """
    r = sector.footprint
    width = abs(r.max_x - r.min_x)
    height = abs(r.max_y - r.min_y)
    lanes = max(1, int(math.ceil(height / max(lane_spacing_m, 0.1))))
    path_m = lanes * width + max(0, lanes - 1) * lane_spacing_m
    speed = max(float(speed_mps), 0.1)
    return {"tool": "sweep_time", "sector": getattr(sector, "sector_id", "?"),
            "width_m": _round(width), "height_m": _round(height),
            "lanes": lanes, "path_m": _round(path_m),
            "seconds": _round(path_m / speed + lanes * TURN_OVERHEAD_S)}


# --- battery ---


def battery_sufficient(belief, to=None, extra_seconds=0.0,
                       include_return=True) -> Dict[str, Any]:
    """Whether the battery covers a proposed piece of work *and the way home*.

    `include_return` defaults to True because the question an agent actually
    needs answered is never "can I get there" — it is "can I get there and
    still get back". Answering the first question and acting on it is how a
    drone ends up on the far side of a search area with 8% remaining.
    """
    remaining = float(belief.battery_remaining_s)
    legs = []
    needed = float(extra_seconds)

    if to is not None:
        out = travel_time(belief, to)["seconds"]
        legs.append({"leg": "outbound", "seconds": out})
        needed += out

    if include_return:
        origin = _pos(to) if to is not None else belief.position
        home = belief.home
        d = math.hypot(origin.x - home.x, origin.y - home.y)
        back = d / CRUISE_SPEED_MPS + TURN_OVERHEAD_S
        legs.append({"leg": "return_home", "seconds": _round(back)})
        needed += back

    required = needed * BATTERY_SAFETY_MARGIN
    return {"tool": "battery_sufficient",
            "remaining_s": _round(remaining),
            "needed_s": _round(needed),
            "required_with_margin_s": _round(required),
            "margin_factor": BATTERY_SAFETY_MARGIN,
            "legs": legs,
            "sufficient": bool(remaining >= required),
            "surplus_s": _round(remaining - required)}


# --- communication ---


def comms_reachable(belief, peer_id=None) -> Dict[str, Any]:
    """What the agent believes about its links. Estimates only, never truth.

    Note the deliberate absence of a "will this message arrive" answer. The
    agent cannot know that, and a tool that implied it could would be smuggling
    the network model into the agent's reasoning — the exact leak Phase 10 tests
    for.
    """
    c = belief.communication
    out = {"tool": "comms_reachable",
           "base_reachable": bool(c.base_reachable),
           "estimated_loss_rate": _round(c.recent_loss_rate, 3),
           "estimated_message_age_s": _round(c.estimated_latency_s),
           "connected_peers": list(c.connected_peers),
           "degraded": bool(c.degraded)}
    if peer_id is not None:
        rec = belief.team.teammates.get(peer_id)
        out["peer"] = peer_id
        out["peer_known"] = rec is not None
        if rec is not None:
            out["peer_last_heard_s_ago"] = _round(rec.age(belief.now))
            out["peer_stale"] = bool(rec.is_stale(belief.now))
            out["peer_status"] = rec.status
            out["peer_confidence"] = _round(rec.status_confidence(belief.now), 3)
        else:
            out["note"] = "never heard from this drone"
    return out


# --- task cost ---


def task_cost(belief, task, capabilities=None) -> Dict[str, Any]:
    """The deterministic bid value for a task.

    The model is allowed to decide *whether to bid*. It is never allowed to
    choose the number: a model that can pick its own bid can win every task by
    bidding zero, and the contract-net protocol's guarantees evaporate.
    """
    from ..coordination.bidding import BidWeights, compute_bid, explain
    bid = compute_bid(task, belief, capabilities=capabilities)
    return {"tool": "task_cost", "task_id": task.task_id,
            "cost": _round(bid.value, 3), "eligible": bool(bid.eligible),
            "breakdown": {k: _round(v, 3) for k, v in bid.breakdown.items()},
            "weights": BidWeights().as_dict(),
            "explanation": explain(bid),
            "note": "lower cost is better; this value is computed, not chosen"}


def compare_task_costs(belief, tasks, capabilities=None) -> Dict[str, Any]:
    """Rank several tasks by cost, cheapest first."""
    rows = [task_cost(belief, t, capabilities) for t in tasks]
    rows.sort(key=lambda r: r["cost"])
    return {"tool": "compare_task_costs",
            "ranked": [{"task_id": r["task_id"], "cost": r["cost"],
                        "eligible": r["eligible"]} for r in rows],
            "cheapest": rows[0]["task_id"] if rows else None}


# --- feasibility and risk ---


def route_feasible(belief, to, limits=None) -> Dict[str, Any]:
    """Whether flying to a point is possible *and* permitted.

    Deliberately consults the same `SafetyLimits` the Phase 11 guardian uses, so
    the model can find out that a waypoint is illegal *before* proposing it. An
    agent that learns the answer only by being rejected wastes a decision cycle
    every time, and under degraded comms decision cycles are the scarce resource.
    """
    target = _pos(to)
    reasons = []

    if not all(math.isfinite(v) for v in (target.x, target.y, target.z)):
        return {"tool": "route_feasible", "feasible": False,
                "reasons": ["waypoint contains a non-finite coordinate"]}

    if limits is not None:
        if not limits.inside_geofence(target):
            reasons.append("outside the geofence")
        if not (limits.min_altitude <= target.z <= limits.max_altitude):
            reasons.append(
                f"altitude {target.z} outside the permitted "
                f"{limits.min_altitude}..{limits.max_altitude}")
        for zone in limits.restricted_zones:
            if _in_zone(target, zone):
                reasons.append(f"inside restricted zone "
                               f"{getattr(zone, 'zone_id', '?')}")

    battery = battery_sufficient(belief, to=target)
    if not battery["sufficient"]:
        reasons.append(f"battery insufficient (needs "
                       f"{battery['required_with_margin_s']}s, has "
                       f"{battery['remaining_s']}s)")

    return {"tool": "route_feasible",
            "to": [_round(target.x), _round(target.y), _round(target.z)],
            "feasible": not reasons,
            "reasons": reasons,
            "travel_time_s": travel_time(belief, target)["seconds"],
            "battery": battery}


def _in_zone(p, zone):
    from ..core.geometry import point_in_polygon
    poly = getattr(zone, "polygon", None) or getattr(zone, "footprint", None)
    if poly is None:
        return False
    try:
        return point_in_polygon(p.x, p.y, poly)
    except (TypeError, ValueError):
        return False


def separation_risk(belief, to=None, min_separation_m=3.0) -> Dict[str, Any]:
    """Closest believed teammate to a point, and whether that is too close.

    The staleness of each teammate's position is reported alongside the
    distance, because under degraded comms "3 metres away" and "3 metres away as
    of 90 seconds ago" are very different facts, and only one of them is a
    reason not to fly there. The tool reports both and lets the decision be made
    with that uncertainty visible, rather than hiding it behind a single number.
    """
    target = _pos(to) if to is not None else belief.position
    nearest, rows = None, []
    for vid, rec in belief.team.teammates.items():
        if rec.last_position is None:
            continue
        d = math.hypot(rec.last_position.x - target.x,
                       rec.last_position.y - target.y)
        age = rec.age(belief.now)
        rows.append({"vehicle_id": vid, "distance_m": _round(d),
                     "position_age_s": _round(age) if age != float("inf") else None,
                     "stale": bool(rec.is_stale(belief.now))})
        if nearest is None or d < nearest["distance_m"]:
            nearest = rows[-1]
    rows.sort(key=lambda r: r["distance_m"])
    too_close = nearest is not None and nearest["distance_m"] < min_separation_m
    return {"tool": "separation_risk",
            "at": [_round(target.x), _round(target.y)],
            "min_separation_m": min_separation_m,
            "nearest": nearest,
            "teammates": rows[:4],
            "conflict": bool(too_close),
            "note": ("positions are believed, not observed; a stale position is "
                     "weak evidence of where a drone is now")}


# --- the bundle the prompt actually carries ---


def brief(belief, task=None, limits=None, capabilities=None) -> Dict[str, Any]:
    """Pre-compute the answers an agent almost always needs.

    Rather than a multi-turn tool-calling loop — which costs a model round-trip
    per question, and an airborne drone cannot afford several of those per
    decision — the handful of computations that are relevant every single turn
    are done up front and handed to the model with its context. The model can
    still call for more, but in the common case it already has the numbers.
    """
    out = {"battery": battery_sufficient(belief),
           "comms": comms_reachable(belief),
           "separation": separation_risk(belief)}
    if task is not None and getattr(task, "sector", None) is not None:
        out["current_task"] = {
            "task_id": getattr(task, "task_id", None),
            "sweep": sweep_time(task.sector),
            "distance_to_sector": distance(belief, _sector_entry(task.sector)),
        }
        out["can_finish_and_return"] = battery_sufficient(
            belief, to=_sector_entry(task.sector),
            extra_seconds=sweep_time(task.sector)["seconds"])
    out["home"] = distance(belief, belief.home)
    return out


def _sector_entry(sector):
    r = sector.footprint
    return Position3D(r.min_x, r.min_y, sector.altitude)
