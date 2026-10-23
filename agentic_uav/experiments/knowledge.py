"""Phase 6's exit: for each decision, exactly what the agent knew and what it did not know.

    truth = Truth(scenario, trajectories, start, end)            # the flight's ground truth
    entry = knowledge_entry(trace_entry, "Drone1", truth)         # one decision
    entry.ok, entry.problems                                      # the three checks

AUV-06's exit criterion: "the experiment logger can show, for each decision,
EXACTLY WHAT THE AGENT KNEW AND WHAT IT DID NOT KNOW." This module is that
logger. It sits on the experiments side of the boundary: it reads the
flight's ground truth, which the agent never could, and joins it to the
belief the agent decided on (the snapshot each `TraceEntry` keeps, taken
BEFORE the decision). Nothing here flows back to an agent.

FOR EACH DECISION, THREE LISTS:

* KNOWN: every field of the belief snapshot, with where it came from
  (sensing now, an estimate, the brief, the agent's own executor or
  decisions, a teammate report, an assumption) and, where it has one, its
  age. Built by walking the snapshot, so nothing in it is left out.
* UNKNOWN, AS THE AGENT RECORDS IT: fields it holds as "unknown",
  teammates "never heard", teammate records that have expired, where the
  targets it has not found are (it knows how many to find, from the brief),
  and sectors it has not searched.
* THE TRUTH GAP, computed from ground truth at that instant: each target
  it has not seen -- where it is, in which sector, and when this drone will
  first see it, if ever -- and each teammate's true position against what it
  believed.

AND THREE CHECKS, each of which can fail:

* COMPLETE: the snapshot has the six blocks and every field has a known
  source. A field this logger does not know how to source fails it: the log
  must not silently drop anything the agent held.
* CORRECT: what it claims to know is true. Its position, battery and base
  link match the truth at that instant -- within TOLERANCE on the mock,
  where both sides come from one analytic trajectory, and within
  `poll_tolerance` live, where the belief is the last poll before the
  decision and the truth is interpolated between the polls around it, so the
  two stand up to one poll of flight apart; its sightings are exactly the
  targets this drone had detected by then.
* NO LEAK: nothing in the truth gap appears in what it knew -- no unseen
  target's id or position, no teammate's true position. An agent that knew
  these would have crossed the boundary.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..core.scenario import Scenario
from ..simulator.mission_world import Connectivity, battery, detections, place_targets
from ..simulator.trajectory import Trajectory

BLOCKS = ("self", "mission", "local_map", "team", "communication", "assumptions")
TOLERANCE = {"position_m": 0.01, "battery": 0.01}          # the snapshot rounds to 3 places
UNKNOWN_WHY = {
    "self.velocity": "not estimable yet: fewer than two readings",
    "self.heading_deg": "no heading: hovering or slower than 0.2 m/s",
    "communication.estimated_latency_s": "not measured until Phase 7",
    "communication.recent_loss_rate": "not measured until Phase 7",
    "communication.connected_peers": "not measured until Phase 7",
}

# Where each field of the belief comes from, by path prefix (longest first).
SOURCES = (
    ("schema", "the belief's own version"),
    ("self.vehicle_id", "the brief"),
    ("self.position", "sensing, now"),
    ("self.airborne", "sensing, now"),
    ("self.battery", "sensing, now"),
    ("self.base_link", "sensing, now"),
    ("self.updated_at", "sensing, now"),
    ("self.velocity", "estimated from own positions"),
    ("self.heading_deg", "estimated from own positions"),
    ("self.motion_source", "estimated from own positions"),
    ("self.home", "its first reading"),
    ("self.current_skill", "its own executor"),
    ("self.health", "its own executor"),
    ("self.current_task", "its own decisions"),
    ("mission.mission_id", "the brief"),
    ("mission.constraints", "the brief"),
    ("mission.reserve", "the brief"),
    ("mission.deadline_in_s", "the brief, against its own clock"),
    ("mission.objective", "its own decisions"),
    ("mission.progress", "its own decisions"),
    ("local_map.restricted_zones", "the brief"),
    ("local_map.observed_targets", "its own sensing"),
    ("local_map.reported_targets", "its own reckoning: seen while linked to the base"),
    ("local_map.searched_regions", "its own decisions"),
    ("local_map.known_hazards", "its own sensing"),
    ("communication.base_reachable", "sensing, now"),
    ("communication.base_reachable_for_s", "sensing, over time"),
    ("communication.estimated_latency_s", "a measurement of the link, from Phase 7"),
    ("communication.recent_loss_rate", "a measurement of the link, from Phase 7"),
    ("communication.connected_peers", "a measurement of the link, from Phase 7"),
    ("team", "the brief's roster"),
    ("team.", "a teammate report"),
    ("assumptions.", "assumed"),
)


def source_of(path: str) -> str | None:
    for prefix, source in SOURCES:
        if path == prefix or path.startswith(prefix + ".") or (prefix.endswith(".") and path.startswith(prefix)):
            return source
    return None


class Truth:
    """A flight's ground truth, asked at any instant. Never handed to an agent."""

    def __init__(self, scenario: Scenario, trajectories: dict[str, Trajectory], start: float, end: float) -> None:
        # `end` is the flight's end by the clock, as the evaluator takes it: a trajectory's last
        # knot can fall a rounding short of it (187.49999999999963 against 187.5).
        self.scenario = scenario
        self.trajectories = trajectories
        self.start = start
        self.targets = place_targets(scenario)
        self.end = end
        self.links = Connectivity(list(trajectories.values()), (scenario.base.x, scenario.base.y),
                                  scenario.network.communication_range_m, start, end)
        self._first_seen = {d: {x.target: x.detected_at for x in detections([t], self.targets, scenario.detection,
                                                                             start, end)}
                            for d, t in trajectories.items()}

    def position(self, drone: str, t: float) -> tuple[float, float, float]:
        return self.trajectories[drone].position_at(t)

    def battery(self, drone: str, t: float) -> float:
        return battery(self.trajectories[drone], self.scenario.battery, self.start, t).remaining

    def base_link(self, drone: str, t: float) -> bool:
        return self.links.connected_at(drone, t)

    def seen_by(self, drone: str, t: float) -> set[str]:
        """The targets `drone` had itself detected by `t`."""
        return {k for k, at in self._first_seen[drone].items() if at <= t + 1e-9}

    def first_seen(self, drone: str, target: str) -> float | None:
        return self._first_seen[drone].get(target)


def poll_tolerance(scenario: Scenario, poll_hz: float, speed_mps: float) -> dict[str, Any]:
    """What "correct" can mean when the belief and the truth come from one poller.

    On the mock both sides come from the same analytic trajectory, so
    TOLERANCE's 0.01 m holds: a disagreement is the logger's fault. Live it
    cannot hold, and not because anything is wrong. `polled_sensors` builds
    the belief from the samples taken BEFORE a decision -- the last poll --
    while `Truth` interpolates between the polls that bracket it. The two are
    therefore up to one poll of flight apart however right the logger is: at
    5 m/s and 10 Hz, 0.5 m, some fifty times the mock's allowance.

    So the live run is checked against one poll of motion, and the battery
    that motion spends. The alternative -- comparing the belief against the
    very sample it was built from -- would keep 0.01 m by making the check
    nearly unable to fail.

    This is the measurement's resolution, not a tuned constant: it is derived
    from the poll rate and the speed, and both are recorded with the result.
    """
    if poll_hz <= 0 or speed_mps <= 0:
        raise ValueError(f"poll_hz and speed_mps must both be positive: {poll_hz}, {speed_mps}")
    period = 1.0 / poll_hz
    reach = speed_mps * period
    spent = reach * scenario.battery.move_drain_per_m + scenario.battery.hover_drain_per_s * period
    return {"position_m": round(reach, 4), "battery": round(spent, 4),
            "why": f"one poll of flight: {speed_mps:g} m/s across {period:.4g} s ({poll_hz:.4g} Hz)"}


def observed_poll_hz(samples: dict[str, Any], nominal_hz: float) -> dict[str, Any]:
    """The rate the poller actually kept, which is the one that bounds the lag.

    `PollingObserver` sleeps its period and THEN queries, so it runs a little
    slower than asked: a nominal 10 Hz measured 9.2 Hz over a 30 s flight,
    median gap 0.109 s and worst 0.125 s. One INTENDED poll of flight is
    therefore not a bound -- a decision was seen 0.550 m from the truth
    against the 0.5 m that 10 Hz allows -- while one OBSERVED poll is: the
    worst gap times the speed came to 0.625 m.

    So the live allowance is taken from the samples the flight actually took.
    The median goes in beside it, because a single stalled poll would widen
    the worst gap and ought to be visible rather than silently generous.

    A flight too short to have two samples falls back to the nominal rate.
    """
    gaps = sorted(b[0] - a[0] for rows in samples.values() for a, b in zip(rows, rows[1:]))
    if not gaps:
        return {"hz": nominal_hz, "asked_hz": nominal_hz, "worst_gap_s": None,
                "median_gap_s": None, "samples": 0}
    worst = gaps[-1]
    return {"hz": 1.0 / worst, "asked_hz": nominal_hz, "worst_gap_s": round(worst, 4),
            "median_gap_s": round(gaps[len(gaps) // 2], 4), "samples": len(gaps) + 1}


@dataclass
class KnowledgeEntry:
    drone: str
    at_s: float                                   # from the flight's start
    events: list[str]
    decision: dict[str, Any]
    known: list[dict[str, Any]] = field(default_factory=list)
    unknown: list[dict[str, Any]] = field(default_factory=list)
    gap: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_json(self) -> dict[str, Any]:
        return {"drone": self.drone, "at_s": self.at_s, "events": self.events, "decision": self.decision,
                "known": self.known, "unknown": self.unknown, "gap": self.gap,
                "checks": {"ok": self.ok, "problems": self.problems}}


def knowledge_entry(entry: Any, drone: str, truth: Truth,
                    tolerance: dict[str, Any] | None = None) -> KnowledgeEntry:
    """What `drone` knew and did not know at one decision (a `TraceEntry`, or its JSON).

    `tolerance` defaults to TOLERANCE, which is the mock's; a live flight
    passes `poll_tolerance(...)`.
    """
    data = entry if isinstance(entry, dict) else entry_json(entry)
    t = data["at"]
    belief = data["belief"]
    d = data["decision"]
    out = KnowledgeEntry(drone, round(t - truth.start, 3), [e["trigger"] for e in data["events"]],
                         {"kind": d["kind"], "skill": d.get("skill"), "reason": d.get("reason", "")})
    _classify(belief, out)
    _gap(belief, drone, t, truth, out)
    _check(belief, drone, t, truth, out, tolerance)
    return out


def entry_json(entry: Any) -> dict[str, Any]:
    return json.loads(json.dumps(entry.as_json(), default=str))


# --------------------------------------------------------------- the lists

def _leaves(value: Any, path: str):
    """(path, value) for every field of the snapshot; assumptions keyed by their key."""
    if isinstance(value, dict) and value:
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif path == "assumptions" and isinstance(value, list):
        for a in value:
            yield f"assumptions.{a['key']}", a
    else:
        yield path, value


def _classify(belief: dict[str, Any], out: KnowledgeEntry) -> None:
    now = belief.get("self", {}).get("updated_at", 0.0)
    for path, value in _leaves(belief, ""):
        source = source_of(path)
        if source is None:
            out.problems.append(f"incomplete: no known source for {path}")
            continue
        if path.startswith("team."):
            _team_item(path, value, out)
            continue
        if value == "unknown":
            out.unknown.append({"what": path, "why": UNKNOWN_WHY.get(path, "held as unknown")})
            continue
        item: dict[str, Any] = {"what": path, "value": value, "source": source}
        if path.startswith("assumptions."):
            item.update(value=value["statement"], evidence=value["evidence"], age_s=value["age_s"],
                        confidence=value["confidence"])
        elif path.startswith("local_map.observed_targets.") and isinstance(value, list) and len(value) == 3:
            item["age_s"] = round(now - value[2], 3)
        out.known.append(item)
    for missing in [b for b in BLOCKS if b not in belief]:
        out.problems.append(f"incomplete: the {missing} block is missing")
    # What it knows it does not know, beyond the fields it holds as unknown.
    lm, mission = belief.get("local_map", {}), belief.get("mission", {})
    found = len(lm.get("observed_targets", {}))
    wanted = mission.get("constraints", {}).get("targets_to_find")
    if wanted is None:
        out.unknown.append({"what": "targets", "why": f"where any target it has not seen is; it has seen {found}"})
    elif wanted > found:
        out.unknown.append({"what": "targets", "why": f"where {wanted - found} more target(s) are; it has seen {found}"})
    searched = {tuple(r) for r in lm.get("searched_regions", [])}
    for sector in mission.get("constraints", {}).get("sectors", []):
        if tuple(sector["bounds"]) not in searched:
            out.unknown.append({"what": f"sector {sector['id']}", "why": "not searched by this drone"})


def _team_item(path: str, value: Any, out: KnowledgeEntry) -> None:
    parts = path.split(".")
    member = parts[1]
    if value == "never heard":
        out.unknown.append({"what": f"teammate {member}", "why": "never heard from"})
    elif len(parts) == 3 and parts[2] == "current" and value is False:
        out.unknown.append({"what": f"teammate {member} now", "why": "its last report has expired"})
    elif value == "unknown":
        out.unknown.append({"what": path, "why": "not in its last report"})
    else:
        out.known.append({"what": path, "value": value, "source": "a teammate report"})


def _gap(belief: dict[str, Any], drone: str, t: float, truth: Truth, out: KnowledgeEntry) -> None:
    seen = set(belief.get("local_map", {}).get("observed_targets", {}))
    for target in truth.targets:
        if target.id in seen:
            continue
        later = truth.first_seen(drone, target.id)
        out.gap.append({"what": f"target {target.id}", "believed": "not seen",
                        "truth": {"position": [round(target.x, 3), round(target.y, 3)], "sector": target.sector,
                                  "first_seen_by_this_drone_s": None if later is None else round(later - truth.start, 3)}})
    for member, record in sorted(belief.get("team", {}).items()):
        x, y, alt = truth.position(member, t)
        believed = record if record == "never heard" else {k: record.get(k) for k in ("position", "age_s", "current")}
        out.gap.append({"what": f"teammate {member}", "believed": believed,
                        "truth": {"position": [round(x, 3), round(y, 3), round(alt, 3)]}})


def _check(belief: dict[str, Any], drone: str, t: float, truth: Truth, out: KnowledgeEntry,
           tolerance: dict[str, Any] | None = None) -> None:
    tol = TOLERANCE if tolerance is None else tolerance
    me = belief.get("self", {})
    if "position" in me:
        x, y, alt = truth.position(drone, t)
        off = math.dist(me["position"], (x, y, alt))
        if off > tol["position_m"]:
            out.problems.append(f"incorrect: believed position {me['position']} is {off:.3f} m from the truth, "
                                f"past the {tol['position_m']:g} m allowed")
    if "battery" in me:
        real = truth.battery(drone, t)
        if abs(me["battery"] - real) > tol["battery"]:
            out.problems.append(f"incorrect: believed battery {me['battery']} against {real:.3f}, "
                                f"past the {tol['battery']:g} allowed")
    if "base_link" in me and me["base_link"] != truth.base_link(drone, t):
        out.problems.append(f"incorrect: believed base link {me['base_link']}, truth {not me['base_link']}")
    seen = set(belief.get("local_map", {}).get("observed_targets", {}))
    real_seen = truth.seen_by(drone, t)
    if seen != real_seen:
        out.problems.append(f"incorrect: believed sightings {sorted(seen)}, truly detected {sorted(real_seen)}")
    # No leak: nothing of the truth gap anywhere in what it knew.
    # Its own velocity is a speed, not a place: descending, [0.0, 0.0, -1.0] read as a teammate at [0.0, 0.0].
    text = json.dumps([k for k in out.known if k["what"] != "self.velocity"])
    for item in out.gap:
        truth_pos = item["truth"]["position"]
        name = item["what"].split()[-1]
        if item["what"].startswith("target") and (f'"{name}"' in text or _mentions(text, truth_pos[:2])):
            out.problems.append(f"leak: it knew something of {item['what']}, which it had not seen")
        if item["what"].startswith("teammate") and _mentions(text, truth_pos[:2]):
            out.problems.append(f"leak: it knew where {name} really was, never having heard it")


def _mentions(text: str, xy: list[float]) -> bool:
    """Whether the point appears as an x, y pair, as the snapshot would round and write it."""
    return f"[{json.dumps(round(xy[0], 3))}, {json.dumps(round(xy[1], 3))}" in text


# --------------------------------------------------------------- a whole run

def knowledge_log(traces: dict[str, Any], truth: Truth,
                 tolerance: dict[str, Any] | None = None) -> list[KnowledgeEntry]:
    """Every decision of every agent in a flight, in time order."""
    entries = [knowledge_entry(e, drone, truth, tolerance)
               for drone, trace in traces.items() for e in trace]
    return sorted(entries, key=lambda k: (k.at_s, k.drone))


def summary(entries: list[KnowledgeEntry]) -> dict[str, Any]:
    return {"decisions": len(entries), "ok": sum(e.ok for e in entries),
            "known": sum(len(e.known) for e in entries), "unknown": sum(len(e.unknown) for e in entries),
            "gap": sum(len(e.gap) for e in entries),
            "problems": [f"{e.drone} at {e.at_s} s: {p}" for e in entries for p in e.problems]}
