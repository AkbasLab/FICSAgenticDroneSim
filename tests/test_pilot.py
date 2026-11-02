"""Phase 17: pilot experiments, timelines, calibration and the freeze.

Two kinds of test live here. The first checks the Phase 17 machinery - the
matrix, the timelines, the log audit, the calibration rules, the freeze. The
second pins the four coordination defects the pilot found, each of which was
invisible in aggregate numbers and obvious in a timeline:

  1. a dead drone's stale bid out-bid the survivor forever, so a sector was
     never flown (2 drones, nominal comms - 75% coverage)
  2. a fault was applied one skill late, because it was compared with the
     belief clock; an LLM drone flew a whole sweep after it was "dead"
  3. a grounded drone whose rivals' bids were lost quit the mission
  4. an airborne drone that lost a claim conflict landed at t = 3 s, because
     idle rounds on a simulated clock took no time

Run: python tests/test_pilot.py
"""

import copy
import dataclasses
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.experiments import calibration as cal
from agentic_uav.experiments import freeze as fz
from agentic_uav.experiments import pilot
from agentic_uav.experiments import timeline as T
from agentic_uav.experiments.experiment_config import ExperimentConfig
from agentic_uav.experiments.experiment_runner import ROOT, run_experiment

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))


def _cfg(**kw):
    base = dict(experiment_id="p17", architecture="C", team_size=4,
                network_profile="nominal", failure_profile="drone_failure_early",
                random_seed=7, planner="scripted")
    base.update(kw)
    return ExperimentConfig(**base)


def _run(**kw):
    out = tempfile.mkdtemp(prefix="phase17_")
    res = run_experiment(_cfg(**kw), out_root=out)
    return res, out


# --- 17.1 the matrix -----------------------------------------------------------

def test_matrix_expands_to_every_cell_and_seed():
    m = pilot.load_matrix(os.path.join(ROOT, "configs", "experiments", "pilot_matrix.yaml"))
    cfgs = pilot.expand(m)
    check("2 archs x 2 sizes x 2 networks x 5 seeds = 40 runs", len(cfgs) == 40, len(cfgs))
    check("every experiment id is unique", len({c.experiment_id for c in cfgs}) == 40)
    check("ids name the cell and the seed",
          "pilot_v1_C_n2_nominal_s101" in {c.experiment_id for c in cfgs})
    check("the pilot uses deterministic and agentic decentralized only",
          {c.architecture_key for c in cfgs} == {"C", "D"})
    held = fz.heldout_seeds()
    if held:
        bad = dict(m, seeds=[held[0]])
        try:
            pilot.expand(bad)
            check("a pilot refuses held-out seeds", False)
        except ValueError:
            check("a pilot refuses held-out seeds", True)


def test_team_size_is_applied_not_just_warned():
    res, out = _run(team_size=2)
    try:
        r = res.result
        check("a 2-drone config flies 2 drones", res.manifest.team == ["Drone1", "Drone2"],
              res.manifest.team)
        check("with every sector still to search", r.sectors_total == 4)
        check("no team-size warning", not any("team_size" in w for w in res.manifest.warnings))
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_a_fault_on_a_drone_outside_the_team_is_skipped_and_said_so():
    res, out = _run(team_size=1, failure_profile="drone_failure_early")
    try:
        check("the run still completes", res.ok, res.manifest.error_message)
        check("the skipped fault is recorded",
              any("Drone2" in w and "not injected" in w for w in res.manifest.warnings),
              res.manifest.warnings)
        check("nothing was stopped", res.result.stopped == [])
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- 17.2 timelines ---------------------------------------------------------------

def test_result_directory_is_enough_to_draw_the_run():
    res, out = _run(network_profile="severe")
    try:
        d = res.directory
        check("tracks.json is written", os.path.exists(os.path.join(d, "tracks.json")))
        tl = T.build_timeline(T.load_run(d))
        check("every drone has a trajectory",
              set(tl["tracks"]["tracks"]) == {"Drone1", "Drone2", "Drone3", "Drone4"})
        check("sectors and the no-fly zone are in the map",
              len(tl["tracks"]["sectors"]) == 4 and tl["tracks"]["restricted_zones"])
        check("active task by drone", any(tl["tasks"][v] for v in tl["vehicles"]))
        check("role by drone", all(tl["roles"][v] for v in tl["vehicles"]))
        check("messages over time", sum(tl["messages"]["sent"]) > 0)
        check("drop reasons are counted", sum(tl["drop_reasons"].values()) > 0)
        check("delivery per window is computed", any(tl["delivery_by_window"].values()))
        check("mission progress reaches every sector",
              tl["progress"] and tl["progress"][-1]["distinct"] == 4)
        check("the fault is on the timeline", tl["faults"] == {"Drone2": 1.0})
        check("the stopped drone works no task after its fault",
              all(a <= 1.0 + 1e-6 for a, b, _ in tl["tasks"]["Drone2"]))
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_progress_is_stamped_when_a_sweep_ends_not_when_it_starts():
    res, out = _run()
    try:
        ev = T.load_run(res.directory)["events"]
        sweeps = [e for e in ev if e["data"].get("skill") == "sector_sweep"]
        check("each sweep records when it started and when it ended",
              sweeps and all(e["t"] > e["data"]["started_at"] for e in sweeps))
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_concurrent_claims_and_reallocations_are_told_apart():
    tasks = {"A": [(0, 10, "S1")], "B": [(5, 20, "S1")], "C": [(30, 40, "S1")]}
    run = {"directory": "x", "manifest": {"team": list(tasks)}, "result": {},
           "tracks": {}, "events": []}
    for v, ivs in tasks.items():
        for a, b, task in ivs:
            for t in (a, b):
                run["events"].append({"t": t, "type": "BELIEF_UPDATED", "vehicle": v,
                                      "data": {"step": t, "task": task if t == a else None,
                                               "role": "scout"}})
                run["events"].append({"t": t, "type": "DECISION_PROPOSED", "vehicle": v,
                                      "data": {"step": t, "objective": "search_sector"}})
    run["events"].sort(key=lambda e: e["t"])
    tl = T.build_timeline(run)
    check("starting a task someone else is working is a concurrent claim",
          [c["vehicle"] for c in tl["concurrent_claims"]] == ["B"], tl["concurrent_claims"])
    check("taking it up after they stopped is a reallocation",
          [(r["from"], r["to"]) for r in tl["reallocations"]] == [("B", "C")],
          tl["reallocations"])


def test_a_timeline_png_is_drawn():
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        check("timeline drawn (matplotlib not installed - skipped)", True)
        return
    res, out = _run(architecture="D")
    try:
        path = T.plot(T.build_timeline(T.load_run(res.directory)),
                      os.path.join(out, "t.png"))
        check("the timeline PNG exists and is not empty",
              os.path.getsize(path) > 10_000, os.path.getsize(path))
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- exit criterion: the log audit ------------------------------------------------------

def test_a_complete_run_passes_the_audit():
    for arch in ("C", "D"):
        res, out = _run(architecture=arch, network_profile="final_moderate")
        try:
            a = pilot.audit_run(res.directory)
            check(f"{arch}: a normal run's logs are complete", not a["problems"], a["problems"])
        finally:
            shutil.rmtree(out, ignore_errors=True)


def test_the_audit_catches_a_log_that_disagrees_with_its_result():
    res, out = _run()
    try:
        path = os.path.join(res.directory, "events.jsonl")
        lines = open(path, encoding="utf-8").read().splitlines()
        kept = [l for l in lines if '"sector_sweep"' not in l or '"S3"' not in l]
        open(path, "w", encoding="utf-8").write("\n".join(kept) + "\n")
        a = pilot.audit_run(res.directory)
        check("a missing sweep is caught",
              any("sectors swept" in p for p in a["problems"]), a["problems"])
        os.remove(os.path.join(res.directory, "tracks.json"))
        a = pilot.audit_run(res.directory)
        check("a missing file is caught", any("tracks.json" in p for p in a["problems"]))
    finally:
        shutil.rmtree(out, ignore_errors=True)


# --- 17.3 calibration ---------------------------------------------------------------

def _level(name, axis, x, loss, lat=150.0, **per_arch):
    from agentic_uav.coordination.network_model import NetworkProfile
    lv = cal.Level(name, NetworkProfile(name=name, latency_ms_mean=lat,
                                        latency_ms_jitter=10, packet_loss_probability=loss),
                   axis, x)
    r = cal.LevelResult(lv)
    for a, (dup, time, deliv, clean, flat) in per_arch.items():
        r.by_arch[a] = {"dup_mean": dup, "dup_sd": 0.5, "time_mean": time, "time_sd": 10,
                        "delivery_mean": deliv, "coverage_mean": 1.0, "clean_rate": clean,
                        "mission_ok_rate": 1.0, "flat": flat}
    return r


def test_calibration_rules():
    ladder = cal.load_ladder(os.path.join(ROOT, "configs", "networks", "calibration_ladder.yaml"))
    base = _level("loss00", "loss", 0.0, 0.0, C=(0, 200, 0.98, 1.0, True), D=(0, 200, 0.98, 1.0, True))
    weak = _level("loss05", "loss", 0.05, 0.05, C=(0.1, 205, 0.92, 0.9, False), D=(0.2, 210, 0.92, 0.8, False))
    good = _level("loss20", "loss", 0.2, 0.2, C=(1.0, 260, 0.75, 0.4, False), D=(1.4, 280, 0.75, 0.3, False))
    sat = _level("loss70", "loss", 0.7, 0.7, C=(3.4, 390, 0.30, 0.0, False), D=(3.6, 370, 0.3, 0.0, False))
    dead = _level("loss90", "loss", 0.9, 0.9, C=(3.8, 380, 0.09, 0.0, False), D=(4.0, 380, 0.1, 0.0, False))
    slow = _level("lat60", "latency", 60000, 0.05, lat=60000, C=(3, 300, 0.7, 0.0, False), D=(2.5, 300, 0.7, 0.0, False))
    flat = _level("ref", "reference", float("nan"), 0.3, C=(4, 354, 0.5, 0.0, True), D=(2, 356, 0.5, 0.1, True))
    rs = [base, weak, good, sat, dead, slow, flat]
    cal.classify(rs, ladder)
    check("the loss-free level is the reference, not 'too weak'", base.usable, base.flags)
    check("a level that changes nothing is too weak", "too_weak" in weak.flags, weak.flags)
    check("a level with room to tell architectures apart is usable", good.usable, good.flags)
    check("saturated duplication with no clean success is trivial failure",
          "trivial_failure" in sat.flags, sat.flags)
    check("under a quarter delivered is useless", "useless" in dead.flags, dead.flags)
    check("latency past the presumed-lost threshold is useless",
          "useless" in slow.flags and any("presumed lost" in x for x in slow.reasons))
    check("a level where every seed agrees is flat", "flat" in flat.flags, flat.flags)
    good2 = _level("loss40", "loss", 0.4, 0.4, C=(2.0, 300, 0.6, 0.2, False), D=(2.2, 310, 0.6, 0.1, False))
    cal.classify([base, good2], ladder)
    choice = cal.select([base, weak, good, good2, sat, dead])
    check("moderate is the mildest usable level", choice["moderate"] is good)
    check("severe is the harshest usable level", choice["severe"] is good2)
    check("each choice is explained", len(cal.explain(choice, rs)) == 3)


def test_final_profiles_are_registered():
    from agentic_uav.coordination import comms_conditions as cc
    check("the calibrated profiles load by name",
          set(cc.FINAL) == {"final_nominal", "final_moderate", "final_severe"}, cc.FINAL)
    if cc.FINAL:
        check("moderate is milder than severe",
              cc.condition("final_moderate").packet_loss_probability
              < cc.condition("final_severe").packet_loss_probability)
        check("the final profiles carry no rate limit (the artefact the "
              "calibration found)", all(not cc.condition(n).message_rate_limit for n in cc.FINAL))


# --- 17.4 freeze ---------------------------------------------------------------

def test_held_out_seeds():
    a = fz.generate_heldout(count=20, exclude=fz.development_seeds())
    b = fz.generate_heldout(count=20, exclude=fz.development_seeds())
    check("held-out seeds are reproducible", a == b)
    check("held-out seeds never overlap development seeds",
          not set(a) & set(fz.development_seeds()))
    stored = fz.heldout_seeds()
    if stored:
        check("the stored held-out seeds are the generated ones",
              stored == fz.generate_heldout(count=len(stored), exclude=fz.development_seeds()))


def test_freeze_detects_a_change_and_says_what():
    groups = fz.snapshot()
    changed = copy.deepcopy(groups)
    changed["task_rules"]["lease_s"] = 999.0
    changed["prompts"]["llm_system_prompt"] = "different"
    d = fz.diff(groups, changed)
    check("a changed lease is reported by name", any("task_rules.lease_s" in x for x in d), d)
    check("a changed prompt is reported", any("prompts.llm_system_prompt" in x for x in d), d)
    check("an unchanged snapshot has no diff", fz.diff(groups, fz.snapshot()) == [])
    check("source hashes ignore Windows line endings",
          _crlf_hash_matches())


def _crlf_hash_matches():
    d = tempfile.mkdtemp()
    try:
        a, b = os.path.join(d, "a.py"), os.path.join(d, "b.py")
        open(a, "wb").write(b"x = 1\ny = 2\n")
        open(b, "wb").write(b"x = 1\r\ny = 2\r\n")
        old = fz.ROOT
        fz.ROOT = d
        try:
            return fz.file_hash("a.py") == fz.file_hash("b.py")
        finally:
            fz.ROOT = old
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_repository_matches_its_freeze():
    if os.environ.get("AGENTIC_UAV_SKIP_FREEZE_CHECK") == "1":
        check("repository freeze (skipped for defect injection)", True)
        return
    if fz.load() is None:
        check("repository freeze (not frozen yet - skipped)", True)
        return
    r = fz.check()
    check("nothing frozen has changed since the freeze "
          "(if intended: scripts/freeze.py --refreeze --reason ...)", r["ok"], r["changes"][:5])


# --- the four defects the pilot found ------------------------------------------------

def _team(key, n, condition, seed=1, faults=None):
    from agentic_uav.experiments import architectures as arch
    from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
    from agentic_uav.simulator.scenario_manager import load_scenario
    sc = load_scenario(os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml"))
    sc = dataclasses.replace(sc, vehicles=list(sc.vehicles[:n]))
    backend = None
    if key == "D":
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from run_llm_agents import sensible_model
        from agentic_uav.agents.llm_backends import ScriptedBackend
        backend = ScriptedBackend(default=sensible_model)
    b = arch.build(key, sc, lambda v: MockVehicleAdapter(0.0), condition=condition,
                   seed=seed, backend=backend, heartbeat_interval_s=8.0)
    return b, arch.run(b, stop_at=faults or {"Drone2": 1.0})


def test_defect_1_a_dead_drones_bid_does_not_block_the_survivor():
    b, r = _team("C", 2, "nominal")
    check("the lone survivor searches every sector", r.coverage == 1.0,
          f"coverage {r.coverage}")


def test_defect_2_a_fault_lands_on_the_adapter_clock():
    b, r = _team("D", 2, "nominal")
    d2 = next(a for a in b.agents if a.vehicle_id == "Drone2")
    swept = [x for x in d2.belief.local_map.searched_regions if x.by_vehicle == "Drone2"]
    check("a drone stopped at t = 1 s sweeps nothing", not swept,
          [x.region_id for x in swept])
    check("so nothing is duplicated", r.duplicated_sectors == 0, r.duplicated_sectors)


def test_defect_3_a_grounded_drone_waits_for_its_bids():
    from agentic_uav.coordination import comms_conditions as cc
    from agentic_uav.coordination.network_model import NetworkProfile
    cc.CONDITIONS["_t_loss10"] = NetworkProfile(name="_t_loss10", latency_ms_mean=150,
                                                latency_ms_jitter=50, packet_loss_probability=0.1)
    b, r = _team("D", 4, "_t_loss10", seed=0)
    landed = [a.vehicle_id for a in b.agents if a.vehicle_id != "Drone2"
              and a.report().landed]
    check("every survivor flies and lands under 10% loss", len(landed) == 3, landed)
    check("and the mission is complete", r.coverage == 1.0, r.coverage)


def test_defect_4_an_idle_drone_waits_in_simulated_time():
    from agentic_uav.coordination import comms_conditions as cc
    from agentic_uav.coordination.network_model import NetworkProfile
    cc.CONDITIONS["_t_loss30"] = NetworkProfile(name="_t_loss30", latency_ms_mean=150,
                                                latency_ms_jitter=50, packet_loss_probability=0.3)
    covered = []
    for seed in range(5):
        b, r = _team("C", 4, "_t_loss30", seed=seed)
        covered.append(r.coverage)
    check("no sector is abandoned under 30% loss", all(c == 1.0 for c in covered), covered)


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")
    print("Phase 17 pilots, timelines, calibration, freeze\n")
    for n, _ in PASS:
        print(f"  ok    {n}")
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f"  [{str(d)[:200]}]" if d != "" else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
