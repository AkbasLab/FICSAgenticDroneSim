"""The evaluation metrics, defined before the main experiments are run (Phase 15).

This module is the single authority on what every reported number means. The
reason it exists as code rather than as a convention is the exit criterion: a
metric defined after the results are in is not a measurement, it is a choice
about which story the results tell. Fixing the definitions in advance - with
weights, units, and the handling of failed runs all declared up front - removes
that freedom.

Three rules are enforced structurally rather than by discipline:

  1. **A metric that was not measured is `None`, never zero.** Reporting zero
     collisions for a run that never tracked positions is a false claim, and it
     is the most dangerous kind, because zero is exactly the number a safe
     system would produce. Anything unmeasured is named in `not_measured`.

  2. **A failed mission has no completion time.** Timing out at the step cap
     produces `completed=False` and `completion_time_s=None`, not the elapsed
     clock. A failure recorded as a fast finish would make the worst runs look
     like the best ones, and the mean completion time of a set of runs would
     improve as more of them failed.

  3. **Every primary metric is registered with a written definition.** The
     registry at the bottom of this file is checked against the dataclass
     fields by `test_evaluation.py`, so a metric cannot be added to the results
     without a definition, and a definition cannot drift away from its
     implementation without a test failing.

Units: distances in metres, times in simulated seconds, data in bytes. Scores
and rates are fractions in [0, 1], never percentages.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.geometry import point_in_polygon

#: Below this horizontal separation two vehicles are counted as having
#: collided, as distinct from having violated the (much larger) commanded
#: separation minimum. Kept deliberately small: the simulated vehicles are
#: points, so this is a modelling threshold, not an airframe dimension.
COLLISION_RADIUS_M = 1.0

#: Resampling interval for the pairwise separation check. The vehicles move in
#: straight lines between samples, so positions are interpolated rather than
#: snapped to the nearest sample - nearest-sample sampling can step over a
#: close approach entirely and report a clean run.
SEPARATION_SAMPLE_DT_S = 1.0


# --- primary metric 1: mission completion ----------------------------------


@dataclass(frozen=True)
class MissionScoreWeights:
    """Weights for the composite mission score.

    Declared here, once, before any experiment runs. The three components are
    also reported separately, because a composite score can conceal a run that
    searched everything and lost an aircraft.
    """
    coverage: float = 0.5
    target_detection: float = 0.3
    safe_return: float = 0.2

    def __post_init__(self):
        total = self.coverage + self.target_detection + self.safe_return
        if abs(total - 1.0) > 1e-9:
            # Unnormalised weights would make scores from two runs
            # incomparable, which defeats the purpose of a composite.
            raise ValueError(f"weights must sum to 1.0, got {total}")
        if min(self.coverage, self.target_detection, self.safe_return) < 0.0:
            raise ValueError("weights must be non-negative")


DEFAULT_WEIGHTS = MissionScoreWeights()


def mission_score(coverage, target_detection, safe_return,
                  weights: MissionScoreWeights = DEFAULT_WEIGHTS) -> float:
    """w1*Coverage + w2*TargetDetection + w3*SafeReturn, each in [0, 1].

    Inputs outside [0, 1] are a bug in the caller rather than a low score, so
    they raise instead of clamping.
    """
    for name, value in (("coverage", coverage),
                        ("target_detection", target_detection),
                        ("safe_return", safe_return)):
        if not (0.0 - 1e-9 <= value <= 1.0 + 1e-9):
            raise ValueError(f"{name}={value} is outside [0, 1]")
    return (weights.coverage * coverage
            + weights.target_detection * target_detection
            + weights.safe_return * safe_return)


def strict_success(criteria: Dict[str, bool]) -> bool:
    """The binary alternative: every criterion must hold.

    Reported alongside the composite rather than instead of it. The composite
    distinguishes a near miss from a total failure; the binary is what a
    mission operator would actually care about.
    """
    return bool(criteria) and all(criteria.values())


# --- primary metric 5: safety ----------------------------------------------


@dataclass
class SafetyCounts:
    """Safety events. Any field left `None` was not instrumented in this run."""
    collisions: Optional[int] = None
    separation_violations: Optional[int] = None
    restricted_zone_entries: Optional[int] = None
    emergency_fallbacks: Optional[int] = None
    unsafe_proposals: Optional[int] = None
    guardian_interventions: Optional[int] = None

    #: Smallest horizontal separation observed, for context. A run with no
    #: violations at a 5 m minimum reads very differently at 5.1 m than at 40 m.
    min_separation_m: Optional[float] = None

    def unmeasured(self) -> List[str]:
        return sorted(k for k, v in asdict(self).items() if v is None)

    def clean(self) -> Optional[bool]:
        """True if nothing unsafe happened, None if that cannot be determined."""
        hard = (self.collisions, self.separation_violations,
                self.restricted_zone_entries)
        if any(v is None for v in hard):
            return None            # absence of evidence, not evidence of safety
        return all(v == 0 for v in hard)


# --- primary metric 6: communication overhead ------------------------------


@dataclass
class CommsOverhead:
    messages_sent: int = 0
    messages_delivered: int = 0
    bytes_transmitted: int = 0
    duplicate_messages: Optional[int] = None
    expired_messages: int = 0
    dropped_link: int = 0

    #: Tasks completed, used as the denominator below. Kept explicit so the
    #: ratio can be recomputed and audited.
    tasks_completed: int = 0

    @property
    def messages_per_completed_task(self) -> Optional[float]:
        """Messages per unit of work delivered.

        `None` when nothing was completed. Zero completed tasks with hundreds
        of messages sent is not "efficient", and dividing by zero to get
        infinity would sort it as the worst run rather than the undefined one.
        """
        if self.tasks_completed <= 0:
            return None
        return self.messages_sent / self.tasks_completed

    @property
    def bytes_per_completed_task(self) -> Optional[float]:
        if self.tasks_completed <= 0:
            return None
        return self.bytes_transmitted / self.tasks_completed


# --- the primary metric block ----------------------------------------------


@dataclass
class PrimaryMetrics:
    """The small set of numbers a comparison is argued from."""
    # 1: mission completion
    mission_score: float
    coverage: float
    target_detection: float
    safe_return: float
    strict_success: bool

    # 2: completion time
    completed: bool
    completion_time_s: Optional[float]
    timed_out: bool
    time_cap_s: Optional[float]

    # 4: recovery (None when no fault was injected)
    recovery_time_s: Optional[float] = None
    productive_resumption_s: Optional[float] = None

    # 5, 6
    safety: SafetyCounts = field(default_factory=SafetyCounts)
    comms: CommsOverhead = field(default_factory=CommsOverhead)

    #: Metric names that could not be computed from this run's instrumentation.
    not_measured: List[str] = field(default_factory=list)

    def as_row(self) -> Dict[str, Any]:
        row = {
            "mission_score": round(self.mission_score, 4),
            "coverage": round(self.coverage, 4),
            "target_detection": round(self.target_detection, 4),
            "safe_return": round(self.safe_return, 4),
            "strict_success": self.strict_success,
            "completed": self.completed,
            "completion_time_s": (None if self.completion_time_s is None
                                  else round(self.completion_time_s, 1)),
            "timed_out": self.timed_out,
            "recovery_time_s": (None if self.recovery_time_s is None
                                else round(self.recovery_time_s, 1)),
            "collisions": self.safety.collisions,
            "separation_violations": self.safety.separation_violations,
            "restricted_zone_entries": self.safety.restricted_zone_entries,
            "emergency_fallbacks": self.safety.emergency_fallbacks,
            "unsafe_proposals": self.safety.unsafe_proposals,
            "guardian_interventions": self.safety.guardian_interventions,
            "min_separation_m": (None if self.safety.min_separation_m is None
                                 else round(self.safety.min_separation_m, 2)),
            "messages_sent": self.comms.messages_sent,
            "bytes_transmitted": self.comms.bytes_transmitted,
            "messages_per_completed_task": (
                None if self.comms.messages_per_completed_task is None
                else round(self.comms.messages_per_completed_task, 2)),
            "expired_messages": self.comms.expired_messages,
        }
        if self.not_measured:
            row["not_measured"] = ",".join(self.not_measured)
        return row


# --- diagnostics -----------------------------------------------------------


@dataclass
class DiagnosticMetrics:
    """The wider set, for explaining a primary result rather than claiming one.

    Diagnostics are never used to decide which architecture won. They exist to
    answer "why" once the primary metrics have said "which".
    """
    area_searched_frac: Optional[float] = None
    duplicate_search: Optional[int] = None
    task_reassignments: Optional[int] = None
    orphaned_tasks: Optional[int] = None
    role_changes: Optional[int] = None
    role_oscillations: Optional[int] = None
    stale_message_decisions: Optional[int] = None
    invalid_llm_outputs: Optional[int] = None
    llm_latency_mean_s: Optional[float] = None
    llm_latency_max_s: Optional[float] = None
    llm_calls: Optional[int] = None
    fallback_policy_uses: Optional[int] = None
    fallback_rate: Optional[float] = None
    tokens_consumed: Optional[int] = None
    energy_used_frac: Optional[float] = None
    distance_travelled_m: Optional[float] = None
    conflicting_task_claims: Optional[int] = None
    coordination_efficiency: Optional[float] = None

    def as_row(self) -> Dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items() if v is not None}


# --- primary metric 3: continuity retention --------------------------------


def continuity_retention(score_by_condition: Dict[str, float],
                         baseline: str = "nominal") -> Dict[str, Optional[float]]:
    """MissionScore(c) / MissionScore(baseline), per degraded condition.

    Retention answers "how much capability survives", which is the question the
    comparison is about; raw score under degradation conflates that with how
    good the architecture was to begin with.

    Returns `None` for a condition when the baseline score is zero: an
    architecture that failed under nominal conditions has no capability to
    retain, and 0/0 is not 1.0.
    """
    if baseline not in score_by_condition:
        raise KeyError(f"no {baseline!r} run to normalise against; "
                       f"have {sorted(score_by_condition)}")
    base = score_by_condition[baseline]
    out: Dict[str, Optional[float]] = {}
    for condition, score in score_by_condition.items():
        out[condition] = None if base <= 0.0 else score / base
    return out


# --- primary metric 4: recovery time ---------------------------------------

#: Event types used by the recovery calculation. Named here so a rename in
#: `events.py` breaks a test rather than silently returning None forever.
FAULT_EVENT = "FAULT_INJECTED"
ASSIGNMENT_EVENTS = ("TASK_ASSIGNED",)
WORK_EVENTS = ("SKILL_STARTED",)


def recovery_time(events: Sequence[Any],
                  lost_vehicle: Optional[str] = None) -> Tuple[Optional[float],
                                                               Optional[float]]:
    """Time from a fault to the orphaned work being picked up, and to work resuming.

    Returns `(recovery_time_s, productive_resumption_s)`.

    Two numbers rather than one because they answer different questions.
    Acceptance of a replacement task shows the coordination mechanism noticed
    and reacted; the first skill actually flown against that task shows the
    team regained capability. A system can do the first quickly and the second
    never, and reporting only acceptance would score that as a fast recovery.

    Both are `None` when no fault was injected, or when recovery did not happen
    within the run - which is a result, not a missing value, and must not be
    filled in with the run duration.

    Events are duck-typed: anything with `.event_type`, `.t_s` and `.vehicle_id`
    works, so this runs against the live event log and against a list of stubs
    in a test.
    """
    fault = None
    for e in events:
        if _etype(e) == FAULT_EVENT:
            if lost_vehicle is None or _vehicle(e) == lost_vehicle:
                fault = e
                break
    if fault is None:
        return None, None

    t_fault = _time(fault)
    lost = lost_vehicle or _vehicle(fault)

    # The task the lost vehicle was holding, if the fault event recorded it.
    orphaned = _detail(fault, "task_id")

    accepted = None
    for e in events:
        if _etype(e) not in ASSIGNMENT_EVENTS or _time(e) < t_fault:
            continue
        if _vehicle(e) == lost:
            continue                      # the dead vehicle re-accepting is not recovery
        if orphaned and _detail(e, "task_id") not in (None, orphaned):
            continue
        accepted = e
        break
    if accepted is None:
        return None, None

    resumed = None
    for e in events:
        if _etype(e) in WORK_EVENTS and _time(e) >= _time(accepted) \
                and _vehicle(e) == _vehicle(accepted):
            resumed = e
            break

    return (_time(accepted) - t_fault,
            None if resumed is None else _time(resumed) - t_fault)


def _etype(e):
    t = getattr(e, "event_type", None)
    return getattr(t, "value", t)


def _time(e):
    for name in ("t_s", "time_s", "timestamp", "now"):
        v = getattr(e, name, None)
        if v is not None:
            return float(v)
    return 0.0


def _vehicle(e):
    return getattr(e, "vehicle_id", None) or _detail(e, "vehicle_id")


def _detail(e, key):
    d = getattr(e, "detail", None) or getattr(e, "payload", None) or {}
    return d.get(key) if isinstance(d, dict) else None


# --- coordination efficiency -----------------------------------------------


def coordination_efficiency(unique_productive_work: float,
                            total_work: float) -> Optional[float]:
    """UniqueProductiveWork / TotalWork, in [0, 1].

    For area search, unique productive work is newly searched cells and total
    work includes repeated coverage, so a team that searches the same sector
    twice scores 0.5 even though its coverage is perfect. This is the measure
    that separates "the work got done" from "the work got divided".

    `None` when no work was performed: 0/0 is undefined, and returning 1.0
    would rank an idle team as perfectly coordinated.
    """
    if total_work <= 0:
        return None
    if unique_productive_work < 0 or unique_productive_work > total_work:
        raise ValueError(f"unique ({unique_productive_work}) must be within "
                         f"[0, total={total_work}]")
    return unique_productive_work / total_work


# --- geometric safety from recorded tracks ---------------------------------


def separation_report(tracks: Dict[str, Sequence[Tuple[Any, float]]],
                      min_separation_m: float,
                      dt: float = SEPARATION_SAMPLE_DT_S) -> Dict[str, Any]:
    """Pairwise separation over time from recorded tracks.

    `tracks` maps vehicle id to a sequence of `(position, t_s)` samples.
    Positions are interpolated between samples, and a violation is counted once
    per contiguous episode rather than once per sample, so a single long close
    approach is one violation and not forty.
    """
    if len(tracks) < 2:
        return {"separation_violations": 0, "collisions": 0,
                "min_separation_m": None, "samples": 0}

    series = {vid: sorted(((float(t), p) for (p, t) in samples),
                          key=lambda tp: tp[0])
              for vid, samples in tracks.items() if samples}
    if len(series) < 2:
        return {"separation_violations": 0, "collisions": 0,
                "min_separation_m": None, "samples": 0}

    t0 = max(s[0][0] for s in series.values())     # all airborne
    t1 = min(s[-1][0] for s in series.values())
    if t1 < t0:
        return {"separation_violations": 0, "collisions": 0,
                "min_separation_m": None, "samples": 0}

    vids = sorted(series)
    pairs = [(vids[i], vids[j])
             for i in range(len(vids)) for j in range(i + 1, len(vids))]
    in_violation = {p: False for p in pairs}
    in_collision = {p: False for p in pairs}
    violations = collisions = samples = 0
    closest = None

    t = t0
    while t <= t1 + 1e-9:
        samples += 1
        for pair in pairs:
            a = _interp(series[pair[0]], t)
            b = _interp(series[pair[1]], t)
            if a is None or b is None:
                continue
            d = a.horizontal_distance_to(b)
            closest = d if closest is None else min(closest, d)
            # Edge-triggered: count the start of an episode, not its duration.
            if d < min_separation_m:
                if not in_violation[pair]:
                    violations += 1
                    in_violation[pair] = True
            else:
                in_violation[pair] = False
            if d < COLLISION_RADIUS_M:
                if not in_collision[pair]:
                    collisions += 1
                    in_collision[pair] = True
            else:
                in_collision[pair] = False
        t += dt

    return {"separation_violations": violations, "collisions": collisions,
            "min_separation_m": closest, "samples": samples}


def restricted_zone_entries(tracks, zones) -> int:
    """Entries into a restricted region, counted once per entry.

    Counted per episode for the same reason as separation: a drone that sits
    inside a no-fly zone has committed one violation, not one per sample, and
    per-sample counting would make the number depend on the sampling rate.
    """
    total = 0
    for samples in tracks.values():
        inside_prev = False
        for (p, _t) in samples:
            inside = any(point_in_polygon(p.x, p.y, z.polygon) for z in zones)
            if inside and not inside_prev:
                total += 1
            inside_prev = inside
    return total


def distance_travelled(tracks) -> float:
    """Total horizontal path length over all vehicles, in metres."""
    total = 0.0
    for samples in tracks.values():
        for i in range(len(samples) - 1):
            total += samples[i][0].horizontal_distance_to(samples[i + 1][0])
    return total


def _interp(series, t):
    """Position at time t by linear interpolation between bracketing samples."""
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1]
    if t >= series[-1][0]:
        return series[-1][1]
    lo, hi = 0, len(series) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    (ta, pa), (tb, pb) = series[lo], series[hi]
    if tb == ta:
        return pa
    f = (t - ta) / (tb - ta)
    return _lerp(pa, pb, f)


def _lerp(a, b, f):
    return type(a)(x=a.x + (b.x - a.x) * f,
                   y=a.y + (b.y - a.y) * f,
                   z=a.z + (b.z - a.z) * f)


# --- from a run to the metric block ----------------------------------------


def evaluate(result, events=None, lost_vehicle=None,
             weights: MissionScoreWeights = DEFAULT_WEIGHTS
             ) -> Tuple[PrimaryMetrics, DiagnosticMetrics]:
    """Compute both metric blocks from one `architectures.RunResult`.

    All derivation happens here rather than in the runner, so that two
    architectures cannot be scored by two slightly different procedures. The
    runner's job is to record what happened; this function's job is to decide
    what it means, and it has no access to which architecture produced the run.
    """
    raw = getattr(result, "raw", {}) or {}
    tracks = getattr(result, "tracks", {}) or {}
    not_measured: List[str] = []

    # --- component 1: coverage. Sectors actually flown, from the runner.
    coverage = float(result.coverage)

    # --- component 2: detection. A target counts only if it was also reported,
    # so a drone that found a target and then crashed scores zero for it.
    reported_detections = raw.get("reported_detections")
    targets_total = max(1, int(getattr(result, "targets_total", 0) or 0))
    if reported_detections is not None:
        reported_targets = {t for dets in reported_detections.values()
                            for t in dets}
        target_detection = min(1.0, len(reported_targets) / targets_total)
    else:
        # Fall back to raw detections, and say so: this overstates the metric,
        # because it credits detections that never reached base.
        target_detection = min(1.0, (result.targets_found or 0) / targets_total)
        not_measured.append("target_detection_reporting")

    # --- component 3: safe return, over vehicles not deliberately stopped.
    survivors = raw.get("survivors")
    n_survivors = len(survivors) if survivors else max(
        1, len(tracks) - len(getattr(result, "stopped", []) or []))
    safe_return = min(1.0, (result.drones_home or 0) / max(1, n_survivors))

    score = mission_score(coverage, target_detection, safe_return, weights)

    # --- metric 2: completion time, with the timeout convention.
    #
    # "Completed" is a statement about the mission, not about the run loop.
    # Defining it as "the loop drained" was wrong in both directions: a team
    # that stalls in a repeating objective drains nothing and would be a
    # timeout even if it had finished the work, and a team whose agents all
    # exit mid-air drains cleanly while having completed nothing. The terminal
    # condition is: every sector searched, and every surviving vehicle landed.
    timed_out = bool(getattr(result, "hit_step_cap", False))
    completed = (not timed_out
                 and coverage >= 1.0 - 1e-9
                 and safe_return >= 1.0 - 1e-9)
    completion_time_s = float(result.mission_time_s) if completed else None

    # --- metric 5: safety.
    safety = SafetyCounts()
    min_sep = raw.get("min_separation_m")
    if tracks and min_sep:
        rep = separation_report(tracks, float(min_sep))
        safety.separation_violations = rep["separation_violations"]
        safety.collisions = rep["collisions"]
        safety.min_separation_m = rep["min_separation_m"]
    else:
        not_measured += ["separation_violations", "collisions"]

    zones = raw.get("restricted_zones")
    if tracks and zones is not None:
        safety.restricted_zone_entries = restricted_zone_entries(tracks, zones)
    else:
        not_measured.append("restricted_zone_entries")

    guardian = raw.get("guardian")
    if guardian:
        safety.guardian_interventions = guardian.get("interventions", 0)
        safety.emergency_fallbacks = sum(guardian.get("by_fallback", {}).values())
        # A proposal is unsafe if any named check fired on it, which is not the
        # same as an intervention: a clamped speed is one check on one command,
        # whereas a command failing three checks is still one proposal.
        safety.unsafe_proposals = guardian.get("interventions", 0)
    else:
        not_measured += ["guardian_interventions", "emergency_fallbacks",
                         "unsafe_proposals"]

    # --- metric 6: communication overhead.
    bus = raw.get("bus") or {}
    comms = CommsOverhead(
        messages_sent=bus.get("sent", result.messages_sent or 0),
        messages_delivered=bus.get("delivered", result.messages_delivered or 0),
        bytes_transmitted=bus.get("bytes", 0),
        expired_messages=bus.get("dropped_expired", 0),
        dropped_link=bus.get("dropped_link", 0),
        tasks_completed=raw.get("tasks_completed", 0) or 0)
    if "bytes" not in bus:
        not_measured.append("bytes_transmitted")
    # Duplicate detection is not implemented in the bus; counting zero would
    # assert that the protocol never retransmits, which has not been checked.
    not_measured.append("duplicate_messages")

    # --- metric 4: recovery, only meaningful when something was lost.
    recovery = resumption = None
    if events:
        recovery, resumption = recovery_time(
            events, lost_vehicle or _first_stopped(result))

    primary = PrimaryMetrics(
        mission_score=score, coverage=coverage,
        target_detection=target_detection, safe_return=safe_return,
        strict_success=strict_success({
            "coverage": coverage >= 1.0 - 1e-9,
            "targets": target_detection >= 1.0 - 1e-9,
            "safe_return": safe_return >= 1.0 - 1e-9,
            "completed": completed,
            "safe": safety.clean() is True,
        }),
        completed=completed, completion_time_s=completion_time_s,
        timed_out=timed_out, time_cap_s=getattr(result, "step_cap", None),
        recovery_time_s=recovery, productive_resumption_s=resumption,
        safety=safety, comms=comms,
        not_measured=sorted(set(not_measured)))

    diagnostics = _diagnostics(result, raw, tracks)
    return primary, diagnostics


def _first_stopped(result):
    stopped = getattr(result, "stopped", None) or []
    return stopped[0] if stopped else None


def _diagnostics(result, raw, tracks) -> DiagnosticMetrics:
    d = DiagnosticMetrics()
    d.duplicate_search = getattr(result, "duplicated_sectors", None)
    d.conflicting_task_claims = raw.get("conflicts")

    history = raw.get("role_history") or []
    if history:
        d.role_changes = len(history)
        # An oscillation is a return to a role the vehicle just left. Counted
        # because a team that thrashes between roles can look identical to a
        # stable one on any end-of-run metric.
        d.role_oscillations = _oscillations(history)

    if result.llm:
        d.llm_calls = result.llm.get("turns")
        d.fallback_policy_uses = result.llm.get("fallbacks")
        d.fallback_rate = result.llm.get("fallback_rate")
        d.llm_latency_mean_s = result.llm.get("mean_latency_s")
        d.invalid_llm_outputs = result.llm.get("corrections")
        # Token accounting is not plumbed through the backends, so it stays
        # None rather than 0.

    if tracks:
        d.distance_travelled_m = distance_travelled(tracks)

    battery = raw.get("battery_frac_end") or {}
    if battery:
        d.energy_used_frac = 1.0 - (sum(battery.values()) / len(battery))

    searched = getattr(result, "sectors_searched", 0) or 0
    dup = getattr(result, "duplicated_sectors", 0) or 0
    d.coordination_efficiency = coordination_efficiency(searched, searched + dup)
    return d


def _oscillations(history):
    """Count A -> B -> A transitions in a role history of (t, from, to, why)."""
    count = 0
    for i in range(1, len(history)):
        prev_from = history[i - 1][1]
        if history[i][2] == prev_from:
            count += 1
    return count


# --- the metric registry (the exit criterion) ------------------------------

#: Every primary metric, with the written definition it is reported under.
#: `test_evaluation.py` asserts that this registry and `PrimaryMetrics` agree in
#: both directions, so a number cannot enter the results without a definition
#: and a definition cannot be left behind by a renamed field.
PRIMARY_METRIC_DEFINITIONS: Dict[str, str] = {
    "mission_score":
        "w1*Coverage + w2*TargetDetection + w3*SafeReturn with weights "
        "(0.5, 0.3, 0.2) fixed before any experiment. Each component is a "
        "fraction in [0, 1]. Reported with its components, never alone.",
    "coverage":
        "Fraction of required search sectors whose area was covered to the "
        "scenario's required_coverage threshold by a vehicle that actually "
        "flew it. Sectors learned about from a peer's report do not count.",
    "target_detection":
        "Fraction of the scenario's targets that were both detected and "
        "reported to base. Detection without a delivered report is not a "
        "completed mission objective.",
    "safe_return":
        "Fraction of vehicles that were not deliberately stopped by fault "
        "injection and that landed at their own home pad.",
    "strict_success":
        "Binary: every criterion in the Phase 4 success list holds. Reported "
        "alongside the composite score, not instead of it.",
    "completed":
        "The mission reached its terminal condition before the step cap.",
    "completion_time_s":
        "t_mission_complete - t_mission_start in simulated seconds. None for a "
        "run that did not complete; a timeout is never recorded as a time.",
    "timed_out":
        "The run hit the step cap with work outstanding.",
    "time_cap_s":
        "The cap that applied, so a timeout can be interpreted and compared.",
    "recovery_time_s":
        "t_replacement_task_accepted - t_failure, where acceptance is by a "
        "vehicle other than the lost one. None if no fault was injected or "
        "recovery did not occur within the run.",
    "productive_resumption_s":
        "t_first_skill_flown_against_the_replacement_task - t_failure. "
        "Separate from recovery_time_s because accepting work and doing it are "
        "different capabilities.",
    "safety":
        "Counts of collisions, separation violations, restricted-zone entries, "
        "emergency fallbacks, unsafe proposals and guardian interventions, "
        "plus the minimum observed separation. Episode-counted, not "
        "sample-counted. An uninstrumented count is None, never 0.",
    "comms":
        "Messages sent and delivered, bytes transmitted, duplicates, expired "
        "messages, and messages per completed task. The per-task ratios are "
        "None when nothing completed.",
    "not_measured":
        "Names of metrics this run could not produce. Present so that a gap in "
        "instrumentation is visible in the results table rather than appearing "
        "as a favourable value.",
}

DERIVED_METRIC_DEFINITIONS: Dict[str, str] = {
    "continuity_retention":
        "MissionScore(c) / MissionScore(nominal) for each degraded condition "
        "c. None when the nominal score is zero.",
    "coordination_efficiency":
        "UniqueProductiveWork / TotalWork. For area search, newly searched "
        "cells over all cells searched including repeats. None when no work "
        "was done.",
}


def metric_definition(name: str) -> str:
    """The written definition of a reported metric, by name."""
    for table in (PRIMARY_METRIC_DEFINITIONS, DERIVED_METRIC_DEFINITIONS):
        if name in table:
            return table[name]
    raise KeyError(f"{name!r} has no written definition; metrics may not be "
                   f"reported without one (Phase 15 exit criterion)")
