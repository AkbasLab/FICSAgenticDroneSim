"""Tests for the Phase 15 metric definitions.

These are definition tests. They do not check that the system performs well;
they check that the numbers mean what the specification says they mean, which
is the only thing that can be established before the experiments are run.

The three that matter most are the ones encoding the exit criterion:
  - every primary metric has a written definition (and vice versa),
  - a failed run has no completion time,
  - an unmeasured quantity is None and is named, never silently zero.

Run: python tests/test_evaluation.py
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.core.models import Position3D
from agentic_uav.experiments.evaluation import (
    COLLISION_RADIUS_M, DERIVED_METRIC_DEFINITIONS, DEFAULT_WEIGHTS,
    PRIMARY_METRIC_DEFINITIONS, CommsOverhead, DiagnosticMetrics,
    MissionScoreWeights, PrimaryMetrics, SafetyCounts, continuity_retention,
    coordination_efficiency, distance_travelled, evaluate, metric_definition,
    mission_score, recovery_time, restricted_zone_entries, separation_report,
    strict_success)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append((name, detail))


def raises(name, exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        PASS.append((name, ""))
        return
    except Exception as e:                                       # noqa: BLE001
        FAIL.append((name, f"raised {type(e).__name__}, expected {exc.__name__}"))
        return
    FAIL.append((name, f"did not raise {exc.__name__}"))


# --- stubs -----------------------------------------------------------------


@dataclass
class Ev:
    """Minimal event stand-in: the real log is duck-typed the same way."""
    event_type: str
    t_s: float
    vehicle_id: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Zone:
    polygon: List[tuple]


@dataclass
class FakeResult:
    """Stands in for architectures.RunResult, with only the fields used."""
    coverage: float = 1.0
    targets_found: int = 2
    targets_total: int = 2
    drones_home: int = 4
    sectors_searched: int = 4
    duplicated_sectors: int = 0
    mission_time_s: float = 112.0
    messages_sent: int = 300
    messages_delivered: int = 290
    hit_step_cap: bool = False
    step_cap: int = 600
    stopped: List[str] = field(default_factory=list)
    llm: Optional[Dict[str, Any]] = None
    tracks: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def full_raw(**over):
    raw = {
        "bus": {"sent": 300, "delivered": 290, "bytes": 12000,
                "dropped_expired": 4, "dropped_link": 6},
        "guardian": {"evaluated": 40, "approved": 40, "interventions": 0,
                     "by_fallback": {}},
        "role_history": [],
        "conflicts": 0,
        "tasks_completed": 4,
        "reported_detections": {"D1": ["T1"], "D2": ["T2"], "D3": [], "D4": []},
        "reports_sent": {f"D{i}": 1 for i in range(1, 5)},
        "detections_by": {"D1": ["T1"], "D2": ["T2"], "D3": [], "D4": []},
        "battery_frac_end": {f"D{i}": 0.7 for i in range(1, 5)},
        "min_separation_m": 5.0,
        "restricted_zones": [],
        "survivors": [f"D{i}" for i in range(1, 5)],
    }
    raw.update(over)
    return raw


def straight_track(x0, y, n=20, dx=5.0, t0=0.0, dt=1.0):
    return [(Position3D(x=x0 + i * dx, y=y, z=-8.0), t0 + i * dt)
            for i in range(n)]


# --- 1. the exit criterion: definitions exist, both ways -------------------

def test_every_primary_metric_has_a_definition():
    fields = set(PrimaryMetrics.__dataclass_fields__)
    defined = set(PRIMARY_METRIC_DEFINITIONS)
    check("every reported primary metric has a written definition",
          fields <= defined, f"undefined: {sorted(fields - defined)}")
    check("no definition without a matching field",
          defined <= fields, f"orphaned: {sorted(defined - fields)}")
    check("definitions are non-empty prose",
          all(len(v.split()) >= 8 for v in PRIMARY_METRIC_DEFINITIONS.values()))
    check("derived metrics are defined too",
          set(DERIVED_METRIC_DEFINITIONS) == {"continuity_retention",
                                              "coordination_efficiency"})
    raises("an undefined metric name cannot be looked up",
           KeyError, metric_definition, "win_rate")
    check("a defined metric can be looked up",
          "Coverage" in metric_definition("mission_score"))


# --- 2. mission score ------------------------------------------------------

def test_mission_score():
    check("weights are fixed in advance and sum to 1",
          abs(DEFAULT_WEIGHTS.coverage + DEFAULT_WEIGHTS.target_detection
              + DEFAULT_WEIGHTS.safe_return - 1.0) < 1e-9)
    raises("unnormalised weights are rejected", ValueError,
           MissionScoreWeights, 0.5, 0.5, 0.5)
    raises("negative weights are rejected", ValueError,
           MissionScoreWeights, -0.1, 0.6, 0.5)

    check("a perfect mission scores 1.0",
          abs(mission_score(1.0, 1.0, 1.0) - 1.0) < 1e-9)
    check("a total failure scores 0.0", mission_score(0.0, 0.0, 0.0) == 0.0)
    # The weighting is the claim being made: full coverage with no safe return
    # must not outscore a partial mission that brought everything home.
    check("losing the fleet costs more than it saves",
          mission_score(1.0, 1.0, 0.0) < 1.0)
    check("components are weighted as declared",
          abs(mission_score(1.0, 0.0, 0.0) - DEFAULT_WEIGHTS.coverage) < 1e-9)
    raises("an out-of-range component is a bug, not a low score",
           ValueError, mission_score, 1.4, 0.0, 0.0)

    check("strict success needs every criterion",
          strict_success({"a": True, "b": True})
          and not strict_success({"a": True, "b": False}))
    check("strict success on an empty criteria set is False",
          not strict_success({}))


# --- 3. the timeout convention ---------------------------------------------

def test_failed_runs_have_no_completion_time():
    ok, _ = evaluate(FakeResult(raw=full_raw()))
    check("a completed run reports its time", ok.completion_time_s == 112.0)
    check("a completed run is not flagged as timed out", not ok.timed_out)

    # The important case: the clock still reads 112 s, but the run did not end.
    out, _ = evaluate(FakeResult(hit_step_cap=True, raw=full_raw()))
    check("a timed-out run reports no completion time",
          out.completion_time_s is None, f"got {out.completion_time_s}")
    check("a timed-out run is flagged", out.timed_out and not out.completed)
    check("the cap that applied is recorded", out.time_cap_s == 600)
    check("a timed-out run cannot be a strict success", not out.strict_success)

    # And the consequence that motivates the rule: a mean over completions
    # must not improve when runs fail.
    times = [r.completion_time_s for r in
             (evaluate(FakeResult(raw=full_raw()))[0],
              evaluate(FakeResult(hit_step_cap=True, raw=full_raw()))[0])]
    check("failed runs are excluded from timing, not counted as fast",
          times.count(None) == 1 and None not in [t for t in times if t])


# --- 4. unmeasured is None, never zero -------------------------------------

def test_unmeasured_metrics_are_none_and_named():
    bare, _ = evaluate(FakeResult(raw={}, tracks={}))
    s = bare.safety
    check("collisions unmeasured is None, not 0", s.collisions is None)
    check("separation violations unmeasured is None", s.separation_violations is None)
    check("restricted entries unmeasured is None", s.restricted_zone_entries is None)
    check("guardian counts unmeasured are None", s.guardian_interventions is None)
    check("unmeasured metrics are named in the result",
          {"collisions", "separation_violations", "restricted_zone_entries"}
          <= set(bare.not_measured), f"not_measured={bare.not_measured}")
    check("safety cannot be claimed clean without measurement",
          s.clean() is None)
    check("an uninstrumented run is not a strict success",
          not bare.strict_success)

    full, _ = evaluate(FakeResult(raw=full_raw(), tracks={
        "D1": straight_track(0, 0), "D2": straight_track(0, 400)}))
    check("a measured clean run reports zeros", full.safety.collisions == 0)
    check("a measured clean run can be called clean",
          full.safety.clean() is True)
    check("duplicate messages stay unmeasured until implemented",
          "duplicate_messages" in full.not_measured)
    check("SafetyCounts can list its own gaps",
          SafetyCounts(collisions=0).unmeasured()
          == sorted(["separation_violations", "restricted_zone_entries",
                     "emergency_fallbacks", "unsafe_proposals",
                     "guardian_interventions", "min_separation_m"]))


# --- 5. continuity retention ----------------------------------------------

def test_continuity_retention():
    r = continuity_retention({"nominal": 0.8, "severe": 0.4, "partitioned": 0.2})
    check("retention is a ratio to nominal", abs(r["severe"] - 0.5) < 1e-9)
    check("nominal retains itself", abs(r["nominal"] - 1.0) < 1e-9)
    check("a worse condition retains less", r["partitioned"] < r["severe"])

    # 0/0 is the trap: an architecture that failed under nominal conditions has
    # no capability to retain, and must not score 1.0 for retaining nothing.
    z = continuity_retention({"nominal": 0.0, "severe": 0.0})
    check("zero over zero is undefined, not perfect retention",
          z["severe"] is None)
    raises("retention needs a baseline run", KeyError,
           continuity_retention, {"severe": 0.4})

    # Retention above 1 is possible and must not be clamped: degradation can
    # suppress duplicated work. Hiding it would hide a real finding.
    up = continuity_retention({"nominal": 0.5, "moderate": 0.6})
    check("retention above 1 is reported, not clipped", up["moderate"] > 1.0)


# --- 6. recovery time -----------------------------------------------------

def test_recovery_time():
    events = [
        Ev("MISSION_STARTED", 0.0),
        Ev("FAULT_INJECTED", 30.0, "D2", {"task_id": "S2"}),
        Ev("TASK_ASSIGNED", 55.0, "D2", {"task_id": "S2"}),   # the dead one
        Ev("TASK_ASSIGNED", 70.0, "D4", {"task_id": "S2"}),
        Ev("SKILL_STARTED", 95.0, "D4", {"task_id": "S2"}),
    ]
    rec, prod = recovery_time(events, "D2")
    check("recovery is measured from the fault", rec == 40.0, f"got {rec}")
    check("the lost vehicle re-accepting is not recovery", rec != 25.0)
    check("resumption is measured separately", prod == 65.0, f"got {prod}")
    check("resumption is later than acceptance", prod > rec)

    check("no fault means no recovery number",
          recovery_time([Ev("MISSION_STARTED", 0.0)]) == (None, None))

    # Never recovered must stay None. Substituting the run length here would
    # turn "it never recovered" into a finite, averageable recovery time.
    never = [Ev("FAULT_INJECTED", 30.0, "D2", {"task_id": "S2"})]
    check("a run that never recovered reports None, not the run length",
          recovery_time(never, "D2") == (None, None))

    # Accepted but never flown: the coordination worked, the capability did not.
    accepted_only = [Ev("FAULT_INJECTED", 10.0, "D2", {"task_id": "S2"}),
                     Ev("TASK_ASSIGNED", 20.0, "D3", {"task_id": "S2"})]
    r2, p2 = recovery_time(accepted_only, "D2")
    check("acceptance without work gives a recovery time but no resumption",
          r2 == 10.0 and p2 is None)

    # A reassignment of a different task is not recovery of the orphaned one.
    wrong_task = [Ev("FAULT_INJECTED", 10.0, "D2", {"task_id": "S2"}),
                  Ev("TASK_ASSIGNED", 20.0, "D3", {"task_id": "S7"})]
    check("only the orphaned task counts",
          recovery_time(wrong_task, "D2") == (None, None))


# --- 7. coordination efficiency -------------------------------------------

def test_coordination_efficiency():
    check("perfect division scores 1.0", coordination_efficiency(4, 4) == 1.0)
    check("searching everything twice scores 0.5",
          coordination_efficiency(4, 8) == 0.5)
    check("an idle team is undefined, not perfect",
          coordination_efficiency(0, 0) is None)
    raises("unique work cannot exceed total work", ValueError,
           coordination_efficiency, 5, 4)
    check("zero productive work out of real work scores 0",
          coordination_efficiency(0, 4) == 0.0)


# --- 8. geometric safety from tracks --------------------------------------

def test_separation_and_zones():
    apart = {"D1": straight_track(0, 0), "D2": straight_track(0, 500)}
    rep = separation_report(apart, 5.0)
    check("well-separated tracks report no violations",
          rep["separation_violations"] == 0 and rep["collisions"] == 0)
    check("the closest approach is reported for context",
          abs(rep["min_separation_m"] - 500.0) < 1e-6)

    # Two drones on the same line, 2 m apart: inside a 5 m minimum throughout,
    # but one episode, not one per sample.
    close = {"D1": straight_track(0, 0), "D2": straight_track(0, 2)}
    rep = separation_report(close, 5.0)
    check("a sustained close approach is one violation, not one per sample",
          rep["separation_violations"] == 1, f"got {rep}")
    check("2 m apart is not a collision at a 1 m radius",
          rep["collisions"] == 0 and COLLISION_RADIUS_M == 1.0)

    touching = {"D1": straight_track(0, 0), "D2": straight_track(0, 0.2)}
    check("overlapping tracks are a collision",
          separation_report(touching, 5.0)["collisions"] == 1)

    # Sampling rate must not change the count, which is what episode-counting
    # buys: the same encounter at twice the resolution is still one violation.
    coarse = separation_report(close, 5.0, dt=1.0)["separation_violations"]
    fine = separation_report(close, 5.0, dt=0.25)["separation_violations"]
    check("violation count is independent of sampling rate", coarse == fine)

    check("a single vehicle cannot violate separation",
          separation_report({"D1": straight_track(0, 0)}, 5.0)[
              "separation_violations"] == 0)

    zone = Zone(polygon=[(20.0, -10.0), (40.0, -10.0), (40.0, 10.0),
                         (20.0, 10.0)])
    through = {"D1": straight_track(0, 0, n=20, dx=5.0)}   # crosses x=20..40
    check("flying through a restricted zone is counted",
          restricted_zone_entries(through, [zone]) == 1)
    check("staying out of it is not",
          restricted_zone_entries({"D1": straight_track(0, 400)}, [zone]) == 0)
    check("no zones means no entries",
          restricted_zone_entries(through, []) == 0)

    check("distance travelled is the path length",
          abs(distance_travelled({"D1": straight_track(0, 0, n=5, dx=5.0)})
              - 20.0) < 1e-6)


# --- 9. detection requires reporting --------------------------------------

def test_detection_requires_reporting():
    # Both targets found, but the finder never got its report to base.
    # Drone1 found T1 but never got a report out: nothing was transmitted.
    raw = full_raw(reported_detections={"D1": [], "D2": [], "D3": [], "D4": []},
                   detections_by={"D1": ["T1"], "D2": [], "D3": [], "D4": []})
    m, _ = evaluate(FakeResult(targets_found=1, raw=raw))
    check("an unreported detection does not count",
          m.target_detection == 0.0, f"got {m.target_detection}")

    raw2 = full_raw(reported_detections={"D1": ["T1"], "D2": ["T2"],
                                        "D3": [], "D4": []})
    m2, _ = evaluate(FakeResult(raw=raw2))
    check("reported detections count", m2.target_detection == 1.0)

    # Without the reporting instrumentation the metric is still produced, but
    # the gap is declared, because it overstates the result.
    bare = {k: v for k, v in full_raw().items() if k != "reported_detections"}
    m3, _ = evaluate(FakeResult(raw=bare))
    check("missing reporting data is declared",
          "target_detection_reporting" in m3.not_measured)


# --- 10. comms ratios ------------------------------------------------------

def test_comms_overhead():
    c = CommsOverhead(messages_sent=300, bytes_transmitted=12000,
                      tasks_completed=4)
    check("messages per completed task", c.messages_per_completed_task == 75.0)
    check("bytes per completed task", c.bytes_per_completed_task == 3000.0)

    idle = CommsOverhead(messages_sent=744, tasks_completed=0)
    check("no completed work makes the ratio undefined, not zero or infinite",
          idle.messages_per_completed_task is None)


# --- 11. diagnostics are not primary --------------------------------------

def test_diagnostics_separate_from_primary():
    overlap = set(DiagnosticMetrics.__dataclass_fields__) & set(
        PRIMARY_METRIC_DEFINITIONS)
    check("no field is both primary and diagnostic", not overlap,
          f"overlap: {sorted(overlap)}")

    _, d = evaluate(FakeResult(
        duplicated_sectors=2, sectors_searched=4,
        llm={"turns": 31, "fallbacks": 14, "fallback_rate": 0.45,
             "mean_latency_s": 0.8, "corrections": 0},
        tracks={"D1": straight_track(0, 0)},
        raw=full_raw(role_history=[(10.0, "scout", "relay", "lost relay"),
                                   (20.0, "relay", "scout", "relay returned")])))
    check("duplicated work lowers coordination efficiency",
          abs(d.coordination_efficiency - 4 / 6) < 1e-9,
          f"got {d.coordination_efficiency}")
    check("role changes are counted", d.role_changes == 2)
    check("a return to the previous role is an oscillation",
          d.role_oscillations == 1)
    check("the fallback rate is carried through", d.fallback_rate == 0.45)
    check("tokens stay unmeasured until the backends report them",
          d.tokens_consumed is None)
    check("as_row drops unmeasured diagnostics rather than zeroing them",
          "tokens_consumed" not in d.as_row())


# --- 12. the results row ---------------------------------------------------

def test_as_row_is_flat_and_honest():
    m, _ = evaluate(FakeResult(hit_step_cap=True, raw=full_raw()))
    row = m.as_row()
    check("the row is flat", all(not isinstance(v, (dict, list))
                                 for v in row.values()))
    check("a timeout appears as a null time, not a number",
          row["completion_time_s"] is None and row["timed_out"] is True)
    check("gaps are visible in the row", "not_measured" in row)


# --- 13. the tracks the safety metrics are computed from -------------------

def test_track_resolution_is_faithful():
    """The separation metric is only as good as the track it reads.

    Sampling positions from the agent loop produced two samples 70 s apart
    across an area sweep, and interpolating between them drew a straight line
    through a lawnmower pattern - which placed two drones on the same invented
    point and reported ten collisions in a run that had none. The adapter
    records one sample per leg endpoint instead, which is faithful because the
    mock moves in a straight line at constant speed between endpoints.
    """
    from agentic_uav.control import skills as sk
    from agentic_uav.control.skill_executor import SkillExecutor

    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter

    ad = MockVehicleAdapter(0.0)
    ad.place("D1", Position3D(0.0, 0.0, 0.0))
    ex = SkillExecutor(ad)
    ex.execute("D1", sk.TakeOffCommand(target_altitude=-8.0, timeout_s=60.0))
    ex.execute("D1", sk.SearchRegionCommand(
        min_x=0.0, min_y=0.0, max_x=40.0, max_y=40.0, altitude=-8.0,
        lane_spacing_m=10.0, speed_mps=4.0, tolerance_m=2.0, timeout_s=600.0))

    track = ad.track["D1"]
    check("the adapter records a track", len(track) > 2, f"{len(track)} samples")
    # The decisive property: a single sweep must contribute many samples, not
    # the two the agent loop would have seen.
    check("an area sweep contributes one sample per leg, not two overall",
          len(track) >= 8, f"{len(track)} samples for a 4-lane sweep")
    times = [t for (_p, t) in track]
    check("track timestamps are non-decreasing",
          all(b >= a for a, b in zip(times, times[1:])))

    # Within a leg, interpolation must land on the real straight line.
    from agentic_uav.experiments.evaluation import _interp
    series = sorted(((t, p) for (p, t) in track), key=lambda tp: tp[0])
    for i in range(len(series) - 1):
        (ta, pa), (tb, pb) = series[i], series[i + 1]
        if tb <= ta:
            continue
        mid = _interp(series, (ta + tb) / 2.0)
        expect_x, expect_y = (pa.x + pb.x) / 2.0, (pa.y + pb.y) / 2.0
        if abs(mid.x - expect_x) > 1e-6 or abs(mid.y - expect_y) > 1e-6:
            check("interpolation inside a leg follows the flown line", False,
                  f"leg {i}: got ({mid.x:.2f},{mid.y:.2f}) "
                  f"expected ({expect_x:.2f},{expect_y:.2f})")
            break
    else:
        check("interpolation inside a leg follows the flown line", True)

    # A hold passes time without moving; interpolation must not drift.
    before = ad.get_position("D1")
    ad.hold("D1", 30.0)
    series = sorted(((t, p) for (p, t) in ad.track["D1"]), key=lambda tp: tp[0])
    held = _interp(series, series[-1][0] - 15.0)
    check("a hold does not slide the vehicle",
          abs(held.x - before.x) < 1e-6 and abs(held.y - before.y) < 1e-6)


# --- 14. a known limitation, pinned so it cannot change silently -----------

def test_separation_check_is_endpoint_and_belief_based():
    """Documents what the guardian's separation check can and cannot catch.

    This is not an assertion that the behaviour is correct. It pins two
    properties found while building these metrics, so that they stay visible
    and cannot be altered without a test changing:

      1. the check compares the *destination waypoint* against believed peer
         positions, so two crossing paths with distant endpoints both pass;
      2. with no fresh peer positions it returns passed=True, so the check
         weakens precisely when communication is worst.

    Fleet-level separation assurance therefore does not follow from
    per-command, per-agent separation checking.
    """
    from agentic_uav.agents.safety_guardian import SafetyGuardian, SafetyLimits

    limits = SafetyLimits(min_separation_m=3.0, home=Position3D(0.0, 0.0, 0.0))
    g = SafetyGuardian(limits)

    class Rec:
        def __init__(self, pos, stale=False):
            self.last_position = pos
            self._stale = stale

        def is_stale(self, now):
            return self._stale

    class Team:
        def __init__(self, mates):
            self.teammates = mates

    class B:
        def __init__(self, mates):
            self.now = 10.0
            self.team = Team(mates)
            self.position = Position3D(0.0, 0.0, -8.0)

    near = g._check_separation(Position3D(1.0, 0.0, -8.0),
                               B({"D2": Rec(Position3D(0.0, 0.0, -8.0))}))
    check("a destination inside the minimum is caught", not near.passed)

    # Endpoints far apart, paths crossing at the midpoint: both pass.
    far = g._check_separation(Position3D(100.0, 100.0, -8.0),
                              B({"D2": Rec(Position3D(0.0, 0.0, -8.0))}))
    check("only the endpoint is checked, so crossing paths pass", far.passed)

    stale = g._check_separation(
        Position3D(1.0, 0.0, -8.0),
        B({"D2": Rec(Position3D(0.0, 0.0, -8.0), stale=True)}))
    check("a stale peer position is ignored", stale.passed)
    check("and the pass is vacuous, not evidence of separation",
          "no fresh teammate positions" in stale.detail)

    blind = g._check_separation(Position3D(1.0, 0.0, -8.0), B({}))
    check("with no peers known at all the check still passes",
          blind.passed and "no fresh" in blind.detail)


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("Phase 15 metric definitions\n")
    for name, _ in PASS:
        print(f"  ok    {name}")
    for name, detail in FAIL:
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
